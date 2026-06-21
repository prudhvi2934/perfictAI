import logging
import sqlite3

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from db.queries import NewTransaction, User, insert_transaction_if_new
from llm.client import LLMClient
from routers.dependencies import get_db, get_rules_manager, get_user
from statement_parser.parser import StatementParser
from wiki.rules_manager import RulesManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/statements", tags=["statements"])


class UploadResponse(BaseModel):
    parsed: int       # transactions the LLM extracted from the file
    imported: int     # new transactions written to the DB
    duplicates: int   # rows already ingested before, skipped
    pending_review: int  # imported transactions awaiting human review


@router.post("/upload", response_model=UploadResponse)
async def upload_statement(
    file: UploadFile = File(...),
    user: User = Depends(get_user),
    conn: sqlite3.Connection = Depends(get_db),
    rules: RulesManager = Depends(get_rules_manager),
) -> UploadResponse:
    """Parse an uploaded bank statement CSV into transactions for review.

    Alternative to email ingestion: rows are sanitised, classified by the LLM,
    and stored with review_status='pending_review' (unless a confirmed rule
    matches). Re-uploading the same statement is safe — already-seen rows are
    skipped via a per-row content hash.
    """
    filename = file.filename or ""
    if not filename.lower().endswith(".csv"):
        raise HTTPException(
            status_code=400, detail="Only .csv statement files are supported"
        )

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    parser = StatementParser(LLMClient(), rules)
    try:
        parsed = parser.parse_csv(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        logger.error("Statement parsing failed for user %s: %s", user.id, exc)
        raise HTTPException(
            status_code=502, detail="Failed to parse statement"
        ) from exc

    imported = 0
    duplicates = 0
    pending_review = 0
    for txn in parsed:
        row_id = insert_transaction_if_new(
            conn,
            NewTransaction(
                user_id=user.id,
                email_message_id=txn.dedup_id,
                amount=txn.amount,
                date=txn.date,
                transaction_type=txn.transaction_type,
                merchant=txn.merchant,
                category=txn.category,
                bucket=txn.bucket,
                description=txn.description,
                review_status=txn.review_status,
                source="csv",
                direction=txn.direction,
            ),
        )
        if row_id is None:
            duplicates += 1
            continue
        imported += 1
        if txn.review_status == "pending_review":
            pending_review += 1

    logger.info(
        "Statement upload by user %s: parsed=%d imported=%d duplicates=%d",
        user.id,
        len(parsed),
        imported,
        duplicates,
    )
    return UploadResponse(
        parsed=len(parsed),
        imported=imported,
        duplicates=duplicates,
        pending_review=pending_review,
    )
