"""Endpoint tests for the statement upload router.

The LLM and parser are faked so these exercise upload validation, DB insertion,
dedup, and the response shape — not real model calls.
"""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

import routers.statements as statements_module
from db.queries import create_user, get_all_transactions
from db.schema import get_connection, init_db, migrate_db
from main import app
from routers.dependencies import get_db, get_rules_manager, get_user
from statement_parser.parser import ParsedStatementTransaction
from wiki.rules_manager import RulesManager


class _FakeParser:
    """Replaces StatementParser; returns a preset transaction list."""

    returns: list[ParsedStatementTransaction] = []

    def __init__(self, *_args, **_kwargs) -> None:
        pass

    def parse_csv(self, raw: bytes) -> list[ParsedStatementTransaction]:
        return list(self.returns)


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "finance.db"
    init_db(db_path)
    migrate_db(db_path)
    conn = get_connection(db_path)
    user = create_user(conn, "tester")

    monkeypatch.setattr(statements_module, "LLMClient", lambda *a, **k: object())
    monkeypatch.setattr(statements_module, "StatementParser", _FakeParser)

    app.dependency_overrides[get_db] = lambda: conn
    app.dependency_overrides[get_user] = lambda: user
    app.dependency_overrides[get_rules_manager] = lambda: RulesManager(
        tmp_path / "finance_rules.md"
    )

    test_client = TestClient(app)
    test_client.user = user
    test_client.conn = conn
    yield test_client

    app.dependency_overrides.clear()
    conn.close()


def _upload(client, content: bytes = b"Date,Amount\n2026-06-01,100\n", name="s.csv"):
    return client.post(
        "/statements/upload?user_id=1",
        files={"file": (name, io.BytesIO(content), "text/csv")},
    )


def _txn(
    dedup_id: str, review_status: str = "pending_review"
) -> ParsedStatementTransaction:
    return ParsedStatementTransaction(
        dedup_id=dedup_id,
        amount=100.0,
        merchant="Coffee",
        date="2026-06-01",
        transaction_type="expense",
        description="2026-06-01, Coffee, 100",
        category="food",
        bucket="fun",
        review_status=review_status,
    )


def test_upload_imports_transactions(client):
    _FakeParser.returns = [_txn("csv:aaa"), _txn("csv:bbb")]

    resp = _upload(client)

    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "parsed": 2,
        "imported": 2,
        "duplicates": 0,
        "pending_review": 2,
    }
    stored = get_all_transactions(client.conn, client.user.id)
    assert len(stored) == 2
    assert all(t.source == "csv" for t in stored)


def test_reupload_skips_duplicates(client):
    _FakeParser.returns = [_txn("csv:same")]
    first = _upload(client).json()
    assert first["imported"] == 1

    second = _upload(client).json()
    assert second == {
        "parsed": 1,
        "imported": 0,
        "duplicates": 1,
        "pending_review": 0,
    }
    assert len(get_all_transactions(client.conn, client.user.id)) == 1


def test_non_csv_rejected(client):
    _FakeParser.returns = []
    resp = _upload(client, name="statement.pdf")
    assert resp.status_code == 400


def test_empty_file_rejected(client):
    _FakeParser.returns = []
    resp = _upload(client, content=b"")
    assert resp.status_code == 400
