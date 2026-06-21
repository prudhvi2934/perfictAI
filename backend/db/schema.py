import sqlite3
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).parent.parent.parent / "data" / "finance.db"

_CREATE_USERS = """
CREATE TABLE IF NOT EXISTS users (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT    NOT NULL UNIQUE
);
"""

# Two-tier categorization: a granular, user-editable `transaction_type` (food,
# rent, salary, …) carries a coarse `kind` and the privacy-safe `bucket` that
# maps to the 50/30/20 framework. user_id IS NULL marks a system default shared
# across all users; a per-user row with the same name overrides it.
_CREATE_TRANSACTION_TYPES = """
CREATE TABLE IF NOT EXISTS transaction_types (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id           INTEGER REFERENCES users(id),
    name              TEXT    NOT NULL,
    kind              TEXT    NOT NULL
        CHECK(kind IN ('income', 'expense', 'investment', 'loan', 'transfer')),
    bucket            TEXT
        CHECK(bucket IN ('fundamentals', 'fun', 'future')),
    is_system_default INTEGER NOT NULL DEFAULT 0
);
"""

# A plain UNIQUE(user_id, name) would NOT constrain system rows, because SQLite
# treats every NULL as distinct — two system "food" rows would both insert.
# Indexing on IFNULL(user_id, 0) folds NULL into a single bucket (user ids start
# at 1, so 0 never collides), making seeding idempotent and per-user names unique.
_CREATE_TRANSACTION_TYPES_INDEX = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_transaction_types_user_name
ON transaction_types(IFNULL(user_id, 0), name);
"""

# System defaults: (name, kind, bucket). bucket is NULL for income/transfer
# kinds, which sit outside the 50/30/20 spend buckets.
_SYSTEM_TRANSACTION_TYPES: tuple[tuple[str, str, Optional[str]], ...] = (
    ("food", "expense", "fun"),
    ("groceries", "expense", "fundamentals"),
    ("rent", "expense", "fundamentals"),
    ("transport", "expense", "fundamentals"),
    ("shopping", "expense", "fun"),
    ("subscriptions", "expense", "fun"),
    ("sip", "investment", "future"),
    ("emergency_fund", "investment", "future"),
    ("loan_emi", "loan", "fundamentals"),
    ("loan_interest", "loan", "fundamentals"),
    ("salary", "income", None),
    ("friend_lending", "transfer", None),
)

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
        CHECK(bucket IN ('fundamentals', 'fun', 'future', 'unknown')),
    -- Two-tier categorization: direction is parsed from the source (email/CSV);
    -- type_id points at the resolved transaction_types row, from which kind and
    -- bucket are derived (type-only for now — no per-transaction bucket override).
    direction         TEXT
        CHECK(direction IN ('debit', 'credit')),
    type_id           INTEGER REFERENCES transaction_types(id),
    description       TEXT,
    source            TEXT    NOT NULL DEFAULT 'email'
        CHECK(source IN ('email', 'csv')),
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
    # check_same_thread=False: FastAPI may create the connection (dependency)
    # and use it (endpoint) on different threadpool threads. Each request gets
    # its own connection and uses it sequentially, so this is safe.
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: Path = DB_PATH) -> None:
    with get_connection(db_path) as conn:
        conn.execute(_CREATE_USERS)
        conn.execute(_CREATE_TRANSACTION_TYPES)
        conn.execute(_CREATE_TRANSACTION_TYPES_INDEX)
        conn.execute(_CREATE_TRANSACTIONS)
        conn.execute(_CREATE_PROCESSED_EMAILS)
        conn.commit()
    seed_system_transaction_types(db_path)


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row["name"] == column for row in rows)


def seed_system_transaction_types(db_path: Path = DB_PATH) -> None:
    """Insert the built-in system transaction types if they are not present.

    Idempotent: the unique index on (IFNULL(user_id, 0), name) makes the
    INSERT OR IGNORE skip system types that already exist, so this is safe to
    run on every startup. New entries in _SYSTEM_TRANSACTION_TYPES are picked up
    automatically without touching existing rows or user customisations.
    """
    with get_connection(db_path) as conn:
        for name, kind, bucket in _SYSTEM_TRANSACTION_TYPES:
            conn.execute(
                """
                INSERT OR IGNORE INTO transaction_types
                    (user_id, name, kind, bucket, is_system_default)
                VALUES (NULL, ?, ?, ?, 1)
                """,
                (name, kind, bucket),
            )
        conn.commit()


def migrate_db(db_path: Path = DB_PATH) -> None:
    """Ensure tables exist and columns are up to date.

    Safe to call on both fresh and existing databases.
    """
    with get_connection(db_path) as conn:
        conn.execute(_CREATE_USERS)
        conn.execute(_CREATE_TRANSACTION_TYPES)
        conn.execute(_CREATE_TRANSACTION_TYPES_INDEX)
        # Provenance column added when CSV statement ingestion landed. Existing
        # rows were all email-sourced, so the backfill default is 'email'.
        if not _column_exists(conn, "transactions", "source"):
            conn.execute(
                "ALTER TABLE transactions "
                "ADD COLUMN source TEXT NOT NULL DEFAULT 'email'"
            )
        # Two-tier categorization columns. Both nullable, so existing rows keep
        # their flat transaction_type/bucket until reclassified.
        if not _column_exists(conn, "transactions", "direction"):
            conn.execute(
                "ALTER TABLE transactions ADD COLUMN direction TEXT "
                "CHECK(direction IN ('debit', 'credit'))"
            )
        if not _column_exists(conn, "transactions", "type_id"):
            conn.execute(
                "ALTER TABLE transactions ADD COLUMN type_id INTEGER "
                "REFERENCES transaction_types(id)"
            )
        conn.commit()
    seed_system_transaction_types(db_path)


