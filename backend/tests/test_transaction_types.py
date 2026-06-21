"""Schema, seeding and query tests for the two-tier categorization system."""

from __future__ import annotations

import sqlite3

import pytest

from db.queries import (
    create_transaction_type,
    create_user,
    get_transaction_type_by_id,
    get_transaction_type_by_name,
    list_transaction_types,
)
from db.schema import (
    _SYSTEM_TRANSACTION_TYPES,
    get_connection,
    init_db,
    migrate_db,
    seed_system_transaction_types,
)


@pytest.fixture
def conn(tmp_path):
    db_path = tmp_path / "finance.db"
    init_db(db_path)
    migrate_db(db_path)
    connection = get_connection(db_path)
    yield connection
    connection.close()


def test_init_seeds_all_system_types(conn):
    rows = conn.execute(
        "SELECT name, kind, bucket FROM transaction_types WHERE user_id IS NULL"
    ).fetchall()
    seeded = {(r["name"], r["kind"], r["bucket"]) for r in rows}
    assert seeded == set(_SYSTEM_TRANSACTION_TYPES)


def test_income_and_transfer_have_null_bucket(conn):
    salary = get_transaction_type_by_name(conn, user_id=1, name="salary")
    friend = get_transaction_type_by_name(conn, user_id=1, name="friend_lending")
    assert salary is not None and salary.kind == "income" and salary.bucket is None
    assert friend is not None and friend.kind == "transfer" and friend.bucket is None


def test_expense_type_maps_to_bucket(conn):
    rent = get_transaction_type_by_name(conn, user_id=1, name="rent")
    assert rent is not None
    assert rent.kind == "expense"
    assert rent.bucket == "fundamentals"
    assert rent.is_system_default is True


def test_seeding_is_idempotent(conn, tmp_path):
    before = conn.execute("SELECT COUNT(*) AS n FROM transaction_types").fetchone()["n"]
    seed_system_transaction_types(tmp_path / "finance.db")
    seed_system_transaction_types(tmp_path / "finance.db")
    after = conn.execute("SELECT COUNT(*) AS n FROM transaction_types").fetchone()["n"]
    assert before == after == len(_SYSTEM_TRANSACTION_TYPES)


def test_user_type_listed_alongside_system_defaults(conn):
    user = create_user(conn, "alice")
    create_transaction_type(conn, user.id, "pet_care", "expense", "fun")

    names = {t.name for t in list_transaction_types(conn, user.id)}
    assert "pet_care" in names
    assert "rent" in names  # system default still visible

    # A different user does not see alice's custom type.
    other = create_user(conn, "bob")
    other_names = {t.name for t in list_transaction_types(conn, other.id)}
    assert "pet_care" not in other_names
    assert "rent" in other_names


def test_user_type_overrides_system_default_by_name(conn):
    user = create_user(conn, "alice")
    # alice reclassifies "food" as a fundamental for her household.
    custom = create_transaction_type(conn, user.id, "food", "expense", "fundamentals")

    resolved = get_transaction_type_by_name(conn, user.id, "food")
    assert resolved is not None
    assert resolved.id == custom.id
    assert resolved.user_id == user.id
    assert resolved.bucket == "fundamentals"
    assert resolved.is_system_default is False


def test_duplicate_user_type_name_rejected(conn):
    user = create_user(conn, "alice")
    create_transaction_type(conn, user.id, "pet_care", "expense", "fun")
    with pytest.raises(sqlite3.IntegrityError):
        create_transaction_type(conn, user.id, "pet_care", "expense", "fundamentals")


def test_get_transaction_type_by_id(conn):
    rent = get_transaction_type_by_name(conn, user_id=1, name="rent")
    fetched = get_transaction_type_by_id(conn, rent.id)
    assert fetched is not None
    assert fetched.name == "rent"
    assert get_transaction_type_by_id(conn, 999999) is None


def test_invalid_kind_rejected(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO transaction_types (user_id, name, kind, bucket) "
            "VALUES (NULL, 'bogus', 'nonsense', 'fun')"
        )


def test_transactions_have_two_tier_columns(conn):
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(transactions)")}
    assert "direction" in cols
    assert "type_id" in cols
