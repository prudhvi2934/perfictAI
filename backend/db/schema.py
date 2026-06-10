import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent.parent / "data" / "finance.db"

_CREATE_USERS = """
CREATE TABLE IF NOT EXISTS users (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT    NOT NULL UNIQUE
);
"""

_CREATE_TRANSACTIONS = """
CREATE TABLE IF NOT EXISTS transactions (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id           INTEGER NOT NULL REFERENCES users(id),
    email_message_id  TEXT    NOT NULL,
    amount            REAL    NOT NULL,
    merchant          TEXT,
    date              TEXT    NOT NULL,
    transaction_type  TEXT    NOT NULL
        CHECK(transaction_type IN ('expense', 'investment', 'loan_repayment', 'credit', 'others')),
    category          TEXT,
    bucket            TEXT
        CHECK(bucket IN ('fundamentals', 'fun', 'future_you', 'unknown')),
    description       TEXT,
    review_status     TEXT    NOT NULL DEFAULT 'approved'
        CHECK(review_status IN ('pending_review', 'approved')),
    created_at        TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE(user_id, email_message_id)
);
"""

_CREATE_PROCESSED_EMAILS = """
CREATE TABLE IF NOT EXISTS processed_emails (
    user_id      INTEGER NOT NULL REFERENCES users(id),
    message_id   TEXT    NOT NULL,
    processed_at TEXT    NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, message_id)
);
"""


def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: Path = DB_PATH) -> None:
    with get_connection(db_path) as conn:
        conn.execute(_CREATE_USERS)
        conn.execute(_CREATE_TRANSACTIONS)
        conn.execute(_CREATE_PROCESSED_EMAILS)
        conn.commit()


def migrate_db(db_path: Path = DB_PATH) -> None:
    """Ensure the users table exists and columns are up to date.

    Safe to call on both fresh and existing databases.
    """
    with get_connection(db_path) as conn:
        conn.execute(_CREATE_USERS)
        conn.commit()


