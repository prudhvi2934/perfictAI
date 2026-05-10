import sqlite3
from pathlib import Path
from typing import Generator, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from db.queries import (
    Transaction,
    approve_transaction,
    get_pending_transactions,
    get_transaction_by_id,
)
from db.schema import get_connection
from wiki.rules_manager import FinanceRule, RulesManager
from wiki.wiki_manager import WikiManager
from llm.client import LLMClient

router = APIRouter(prefix="/transactions", tags=["transactions"])

_DATA_DIR = Path(__file__).parent.parent.parent / "data"
_RULES_PATH = _DATA_DIR / "finance_rules.md"
_CURRENT_WIKI_PATH = _DATA_DIR / "finance_current_month.md"
_ARCHIVE_WIKI_PATH = _DATA_DIR / "finance_archive.md"

_VALID_TYPES = {"expense", "investment", "loan_repayment", "credit", "others"}
_VALID_BUCKETS = {"fundamentals", "fun", "future_you", "unknown"}


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


class ApproveResponse(BaseModel):
    id: int
    review_status: str
    rule_written: bool
    merchant: Optional[str]


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------


def get_db() -> Generator[sqlite3.Connection, None, None]:
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


def get_rules_manager() -> RulesManager:
    return RulesManager(_RULES_PATH)


def get_wiki_manager() -> WikiManager:
    llm = LLMClient()
    return WikiManager(llm, _CURRENT_WIKI_PATH, _ARCHIVE_WIKI_PATH)


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
    conn: sqlite3.Connection = Depends(get_db),
) -> PendingListResponse:
    """Return all transactions awaiting human review."""
    txns = get_pending_transactions(conn)
    return PendingListResponse(
        count=len(txns),
        transactions=[_txn_to_out(t) for t in txns],
    )


@router.post("/{txn_id}/approve", response_model=ApproveResponse)
def approve(
    txn_id: int,
    body: ApproveRequest,
    conn: sqlite3.Connection = Depends(get_db),
    rules: RulesManager = Depends(get_rules_manager),
    wiki: WikiManager = Depends(get_wiki_manager),
) -> ApproveResponse:
    """Human confirms correct classification for a transaction.

    Saves the correction to the DB, records the pattern in finance_rules.md,
    and regenerates the current month wiki.
    """
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

    txn = get_transaction_by_id(conn, txn_id)
    if txn is None:
        raise HTTPException(status_code=404, detail="Transaction not found")

    approve_transaction(conn, txn_id, body.transaction_type, body.bucket, body.category)

    rule_written = False
    if txn.merchant:
        rules.upsert_rule(
            FinanceRule(
                pattern=txn.merchant.lower(),
                transaction_type=body.transaction_type,
                bucket=body.bucket,
                category=body.category,
            )
        )
        rule_written = True

    wiki.refresh_current_month(conn)

    return ApproveResponse(
        id=txn_id,
        review_status="approved",
        rule_written=rule_written,
        merchant=txn.merchant,
    )
