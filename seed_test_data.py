"""Seed script: parse test_user_data.json through the LLM pipeline and store in DB.

Usage:
    GEMINI_API_KEY=<key> python seed_test_data.py
"""

import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "backend"))

from db.queries import NewTransaction, insert_transaction
from db.schema import get_connection, init_db
from email_parser.parser import EmailParser
from llm.client import LLMClient

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

USER_ID = 1  # test_user


def main() -> None:
    data_file = Path(__file__).parent / "test_user_data.json"
    emails: list[dict] = json.loads(data_file.read_text())

    init_db()
    conn = get_connection()

    llm = LLMClient()
    parser = EmailParser(llm)

    inserted = skipped = failed = 0

    for idx, email in enumerate(emails):
        message_id = f"seed-{idx:04d}"
        subject: str = email["subject"]
        body: str = email["body"]
        date: str = email["date"]

        try:
            parsed = parser.parse(message_id, subject, body, email_header_date=date)
            time.sleep(4)  # stay under 15 req/min free-tier limit
        except Exception as exc:
            logger.error("[FAIL] seed-%04d — LLM error: %s", idx, exc)
            failed += 1
            continue

        if parsed is None:
            logger.info("[SKIP] seed-%04d — not a transaction email", idx)
            skipped += 1
            continue

        txn = NewTransaction(
            user_id=USER_ID,
            email_message_id=message_id,
            amount=parsed.amount,
            date=parsed.date,
            transaction_type=parsed.transaction_type,
            merchant=parsed.merchant,
            category=parsed.category,
            bucket=parsed.bucket,
            description=parsed.description,
            review_status=parsed.review_status,
        )

        try:
            row_id = insert_transaction(conn, txn)
            logger.info(
                "[OK]   id=%-4d  %s  %-16s  ₹%9.2f  %s",
                row_id,
                parsed.date,
                parsed.transaction_type,
                parsed.amount,
                parsed.merchant or "—",
            )
            inserted += 1
        except Exception as exc:
            if "UNIQUE constraint failed" in str(exc):
                logger.info("[DUP]  seed-%04d already exists — skipping", idx)
                skipped += 1
            else:
                logger.error("[FAIL] seed-%04d — DB error: %s", idx, exc)
                failed += 1

    conn.close()
    print(f"\nDone: {inserted} inserted, {skipped} skipped, {failed} failed.")


if __name__ == "__main__":
    main()
