import sqlite3
from dataclasses import dataclass
from typing import Optional


@dataclass
class Transaction:
    id: int
    user_id: str
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


@dataclass
class NewTransaction:
    user_id: str
    email_message_id: str
    amount: float
    date: str
    transaction_type: str
    merchant: Optional[str] = None
    category: Optional[str] = None
    bucket: Optional[str] = None
    description: Optional[str] = None
    review_status: str = "approved"


def _row_to_transaction(row: sqlite3.Row) -> Transaction:
    return Transaction(
        id=row["id"],
        user_id=row["user_id"],
        email_message_id=row["email_message_id"],
        amount=row["amount"],
        merchant=row["merchant"],
        date=row["date"],
        transaction_type=row["transaction_type"],
        category=row["category"],
        bucket=row["bucket"],
        description=row["description"],
        review_status=row["review_status"],
        created_at=row["created_at"],
    )


def insert_transaction(conn: sqlite3.Connection, txn: NewTransaction) -> int:
    cursor = conn.execute(
        """
        INSERT INTO transactions
            (user_id, email_message_id, amount, merchant, date, transaction_type,
             category, bucket, description, review_status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            txn.user_id,
            txn.email_message_id,
            txn.amount,
            txn.merchant,
            txn.date,
            txn.transaction_type,
            txn.category,
            txn.bucket,
            txn.description,
            txn.review_status,
        ),
    )
    conn.commit()
    return cursor.lastrowid  # type: ignore[return-value]


def get_all_transactions(conn: sqlite3.Connection, user_id: str) -> list[Transaction]:
    rows = conn.execute(
        "SELECT * FROM transactions WHERE user_id = ? ORDER BY date DESC",
        (user_id,),
    ).fetchall()
    return [_row_to_transaction(r) for r in rows]


def get_transactions_by_type(
    conn: sqlite3.Connection, user_id: str, transaction_type: str
) -> list[Transaction]:
    rows = conn.execute(
        "SELECT * FROM transactions WHERE user_id = ? AND transaction_type = ? ORDER BY date DESC",
        (user_id, transaction_type),
    ).fetchall()
    return [_row_to_transaction(r) for r in rows]


def get_transactions_by_date_range(
    conn: sqlite3.Connection, user_id: str, start_date: str, end_date: str
) -> list[Transaction]:
    rows = conn.execute(
        "SELECT * FROM transactions WHERE user_id = ? AND date BETWEEN ? AND ? ORDER BY date DESC",
        (user_id, start_date, end_date),
    ).fetchall()
    return [_row_to_transaction(r) for r in rows]


def get_monthly_totals_by_type(
    conn: sqlite3.Connection, user_id: str, year: int, month: int
) -> dict[str, float]:
    month_prefix = f"{year:04d}-{month:02d}-%"
    rows = conn.execute(
        """
        SELECT transaction_type, SUM(amount) AS total
        FROM transactions
        WHERE user_id = ? AND date LIKE ?
        GROUP BY transaction_type
        """,
        (user_id, month_prefix),
    ).fetchall()
    return {r["transaction_type"]: r["total"] for r in rows}


def get_transaction_by_id(
    conn: sqlite3.Connection, user_id: str, txn_id: int
) -> Optional[Transaction]:
    row = conn.execute(
        "SELECT * FROM transactions WHERE user_id = ? AND id = ?",
        (user_id, txn_id),
    ).fetchone()
    return _row_to_transaction(row) if row else None


def get_pending_transactions(conn: sqlite3.Connection, user_id: str) -> list[Transaction]:
    rows = conn.execute(
        "SELECT * FROM transactions WHERE user_id = ? AND review_status = 'pending_review' ORDER BY created_at DESC",
        (user_id,),
    ).fetchall()
    return [_row_to_transaction(r) for r in rows]


def approve_transaction(
    conn: sqlite3.Connection,
    user_id: str,
    txn_id: int,
    transaction_type: str,
    bucket: str,
    category: Optional[str],
) -> bool:
    """Update transaction with human-confirmed classification and mark as approved.

    Returns True if the transaction was found and updated, False if not found.
    """
    cursor = conn.execute(
        """
        UPDATE transactions
        SET transaction_type = ?,
            bucket           = ?,
            category         = ?,
            review_status    = 'approved'
        WHERE user_id = ? AND id = ?
        """,
        (transaction_type, bucket, category, user_id, txn_id),
    )
    conn.commit()
    return cursor.rowcount > 0


def get_approved_transactions_for_month(
    conn: sqlite3.Connection, user_id: str, year: int, month: int
) -> list[Transaction]:
    month_str = f"{year:04d}-{month:02d}"
    rows = conn.execute(
        """
        SELECT * FROM transactions
        WHERE user_id = ?
          AND review_status = 'approved'
          AND strftime('%Y-%m', date) = ?
        ORDER BY date ASC
        """,
        (user_id, month_str),
    ).fetchall()
    return [_row_to_transaction(r) for r in rows]


def is_email_processed(conn: sqlite3.Connection, user_id: str, message_id: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM processed_emails WHERE user_id = ? AND message_id = ?",
        (user_id, message_id),
    ).fetchone()
    return row is not None


def mark_email_processed(conn: sqlite3.Connection, user_id: str, message_id: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO processed_emails (user_id, message_id) VALUES (?, ?)",
        (user_id, message_id),
    )
    conn.commit()
