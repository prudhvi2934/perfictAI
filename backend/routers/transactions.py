import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from db.queries import (
    Transaction,
    User,
    approve_transaction,
    get_monthly_summaries,
    get_pending_transactions,
    get_reviewed_transactions,
    get_transaction_by_id,
)
from wiki.rules_manager import FinanceRule, RulesManager
from routers.dependencies import get_db, get_rules_manager, get_user

router = APIRouter(prefix="/transactions", tags=["transactions"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class ApproveRequest(BaseModel):
    transaction_type: str
    bucket: str
    category: Optional[str] = None


class TransactionOut(BaseModel):
    id: int
    email_message_id: str
    amount: float
    merchant: Optional[str]
    date: str
    transaction_type: str
    category: Optional[str]
    bucket: Optional[str]
    description: Optional[str]
    review_status: str
    created_at: str


class PendingListResponse(BaseModel):
    count: int
    transactions: list[TransactionOut]


class HistoryListResponse(BaseModel):
    count: int
    transactions: list[TransactionOut]


class MonthlySummaryOut(BaseModel):
    month: str
    credit: float
    debit: float
    net: float
    by_type: dict[str, float]


class MonthlySummaryResponse(BaseModel):
    months: list[MonthlySummaryOut]


class ApproveResponse(BaseModel):
    id: int
    review_status: str
    rule_written: bool
    merchant: Optional[str]


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------


def _txn_to_out(txn: Transaction) -> TransactionOut:
    return TransactionOut(
        id=txn.id,
        email_message_id=txn.email_message_id,
        amount=txn.amount,
        merchant=txn.merchant,
        date=txn.date,
        transaction_type=txn.transaction_type,
        category=txn.category,
        bucket=txn.bucket,
        description=txn.description,
        review_status=txn.review_status,
        created_at=txn.created_at,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/pending", response_model=PendingListResponse)
def list_pending(
    user: User = Depends(get_user),
    conn: sqlite3.Connection = Depends(get_db),
) -> PendingListResponse:
    """Return all transactions awaiting human review for the current user."""
    txns = get_pending_transactions(conn, user.id)
    return PendingListResponse(
        count=len(txns),
        transactions=[_txn_to_out(t) for t in txns],
    )


@router.get("/history", response_model=HistoryListResponse)
def list_history(
    user: User = Depends(get_user),
    conn: sqlite3.Connection = Depends(get_db),
) -> HistoryListResponse:
    """Return all reviewed (approved) transactions for the current user, newest first."""
    txns = get_reviewed_transactions(conn, user.id)
    return HistoryListResponse(
        count=len(txns),
        transactions=[_txn_to_out(t) for t in txns],
    )


@router.get("/summary/monthly", response_model=MonthlySummaryResponse)
def monthly_summary(
    user: User = Depends(get_user),
    conn: sqlite3.Connection = Depends(get_db),
) -> MonthlySummaryResponse:
    """Per-month credit/debit/net totals over reviewed transactions, newest month first."""
    summaries = get_monthly_summaries(conn, user.id)
    return MonthlySummaryResponse(
        months=[
            MonthlySummaryOut(
                month=s.month,
                credit=s.credit,
                debit=s.debit,
                net=s.net,
                by_type=s.by_type,
            )
            for s in summaries
        ]
    )


@router.post("/{txn_id}/approve", response_model=ApproveResponse)
def approve(
    txn_id: int,
    body: ApproveRequest,
    user: User = Depends(get_user),
    conn: sqlite3.Connection = Depends(get_db),
    rules: RulesManager = Depends(get_rules_manager),
) -> ApproveResponse:
    """Human confirms correct classification for a transaction.

    Saves the correction to the DB. Only writes a rule when the user changed
    the LLM's original bucket or transaction_type — rules are corrections, not
    confirmations.
    """
    _VALID_TYPES = {"expense", "investment", "loan_repayment", "credit", "others"}
    _VALID_BUCKETS = {"fundamentals", "fun", "future", "unknown"}

    if body.transaction_type not in _VALID_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid transaction_type. Must be one of: {sorted(_VALID_TYPES)}",
        )
    if body.bucket not in _VALID_BUCKETS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid bucket. Must be one of: {sorted(_VALID_BUCKETS)}",
        )

    txn = get_transaction_by_id(conn, user.id, txn_id)
    if txn is None:
        raise HTTPException(status_code=404, detail="Transaction not found")

    approve_transaction(conn, user.id, txn_id, body.transaction_type, body.bucket, body.category)

    user_corrected = (
        body.transaction_type != txn.transaction_type
        or body.bucket != txn.bucket
    )
    rule_written = False
    if txn.merchant and user_corrected:
        rules.upsert_rule(
            FinanceRule(
                pattern=txn.merchant.lower(),
                transaction_type=body.transaction_type,
                bucket=body.bucket,
                category=body.category,
            )
        )
        rule_written = True

    return ApproveResponse(
        id=txn_id,
        review_status="approved",
        rule_written=rule_written,
        merchant=txn.merchant,
    )

