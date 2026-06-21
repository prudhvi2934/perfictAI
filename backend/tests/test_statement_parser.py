"""Unit tests for the CSV bank-statement parser.

Date, amount and direction are extracted deterministically from the CSV; the
LLM is faked since it only classifies debits.
"""

from __future__ import annotations

import re
from typing import Any, Optional

import pytest

from statement_parser.parser import StatementParser
from wiki.rules_manager import FinanceRule, RulesManager


class FakeLLM:
    """Classifies debit rows. Echoes a per-row override or a default expense.

    Captures prompts so tests can assert sanitisation happened before the call.
    """

    def __init__(self, classifications: Optional[dict[int, dict[str, Any]]] = None):
        self.classifications = classifications or {}
        self.prompts: list[str] = []

    def generate_json(self, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        self.prompts.append(prompt)
        indices = [int(m) for m in re.findall(r"\[(\d+)\]", prompt)]
        out = []
        for i in indices:
            c = self.classifications.get(i, {})
            out.append(
                {
                    "row_index": i,
                    "merchant": c.get("merchant", "Acme"),
                    "transaction_type": c.get("transaction_type", "expense"),
                    "bucket": c.get("bucket", "fun"),
                    "category": c.get("category", "misc"),
                }
            )
        return {"transactions": out}


def _csv(*lines: str) -> bytes:
    return ("\n".join(lines) + "\n").encode("utf-8")


# A normal statement: Debit column = money out, Credit column = money in.
def _normal_statement() -> bytes:
    return _csv(
        "Account holder: TEST USER",
        "Statement period 01-05-2026 to 31-05-2026",
        "",
        "Date,Description,Debit,Credit,Balance",
        "01-05-2026,Coffee Shop,100.00,,900.00",
        "02-05-2026,Monthly Salary,,5000.00,5900.00",
        "03-05-2026,Grocery Store,200.00,,5700.00",
        "Closing balance,,,,5700.00",
    )


def test_date_and_amount_come_from_csv_not_llm() -> None:
    # LLM returns a bogus row_index only — it must not influence date/amount.
    parser = StatementParser(FakeLLM())
    txns = parser.parse_csv(_normal_statement())

    coffee = next(t for t in txns if "Coffee" in t.description)
    assert coffee.date == "2026-05-01"   # parsed from DD-MM-YYYY
    assert coffee.amount == 100.0        # straight from the CSV column


def test_credit_is_classified_without_llm() -> None:
    txns = StatementParser(FakeLLM()).parse_csv(_normal_statement())

    salary = next(t for t in txns if "Salary" in t.description)
    assert salary.transaction_type == "credit"
    assert salary.amount == 5000.0
    assert salary.bucket == "unknown"


def test_debit_classification_comes_from_llm() -> None:
    llm = FakeLLM(
        {
            0: {
                "merchant": "Coffee Shop",
                "transaction_type": "expense",
                "bucket": "fun",
                "category": "food",
            }
        }
    )
    txns = StatementParser(llm).parse_csv(_normal_statement())

    coffee = next(t for t in txns if t.merchant == "Coffee Shop")
    assert coffee.transaction_type == "expense"
    assert coffee.bucket == "fun"
    assert coffee.category == "food"


def test_inverted_dr_cr_columns_use_balance_direction() -> None:
    # Axis-style export: a value in the CR column lowers the balance (money out),
    # a value in the DR column raises it (money in). Labels are reversed.
    raw = _csv(
        "Statement of account",
        "Tran Date,PARTICULARS,DR,CR,BAL",
        "01-05-2026,Card Payment,,100.00,900.00",
        "02-05-2026,Cashback Refund,50.00,,950.00",
        "03-05-2026,Shop Payment,,30.00,920.00",
    )
    txns = StatementParser(FakeLLM()).parse_csv(raw)

    payment = next(t for t in txns if "Card Payment" in t.description)
    refund = next(t for t in txns if "Cashback Refund" in t.description)
    # CR-column payment is money out -> debit; DR-column refund is money in.
    assert payment.transaction_type != "credit"
    assert payment.amount == 100.0
    assert refund.transaction_type == "credit"
    assert refund.amount == 50.0


def test_single_signed_amount_column() -> None:
    raw = _csv(
        "Date,Narration,Amount",
        "01-05-2026,Netflix,-499.00",
        "02-05-2026,Refund,200.00",
    )
    txns = StatementParser(FakeLLM()).parse_csv(raw)

    netflix = next(t for t in txns if "Netflix" in t.description)
    refund = next(t for t in txns if "Refund" in t.description)
    assert netflix.transaction_type != "credit"  # negative -> debit
    assert netflix.amount == 499.0
    assert refund.transaction_type == "credit"    # positive -> credit


def test_preamble_and_summary_rows_are_skipped() -> None:
    # 3 data rows but only 2 are real transactions (closing-balance line dropped).
    txns = StatementParser(FakeLLM()).parse_csv(_normal_statement())
    assert len(txns) == 3
    assert all("Closing balance" not in t.description for t in txns)


def test_rule_override_marks_approved(tmp_path) -> None:
    rules = RulesManager(tmp_path / "finance_rules.md")
    rules.upsert_rule(
        FinanceRule(
            pattern="coffee",
            transaction_type="expense",
            bucket="fundamentals",
            category="essentials",
        )
    )
    llm = FakeLLM({0: {"merchant": "Coffee Shop", "bucket": "fun"}})
    txns = StatementParser(llm, rules).parse_csv(_normal_statement())

    coffee = next(t for t in txns if t.merchant == "Coffee Shop")
    assert coffee.review_status == "approved"
    assert coffee.bucket == "fundamentals"
    assert coffee.category == "essentials"


def test_dedup_id_is_stable_for_same_row() -> None:
    first = StatementParser(FakeLLM()).parse_csv(_normal_statement())
    second = StatementParser(FakeLLM()).parse_csv(_normal_statement())
    ids_first = sorted(t.dedup_id for t in first)
    ids_second = sorted(t.dedup_id for t in second)
    assert ids_first == ids_second
    assert all(i.startswith("csv:") for i in ids_first)


def test_pii_redacted_before_reaching_llm() -> None:
    raw = _csv(
        "Date,Description,Debit,Credit,Balance",
        "01-05-2026,Transfer to XX1234,500.00,,500.00",
    )
    llm = FakeLLM()
    StatementParser(llm).parse_csv(raw)

    assert llm.prompts, "expected the debit to be sent to the LLM"
    prompt = llm.prompts[0]
    assert "XX1234" not in prompt
    assert "[ACCOUNT]" in prompt


def test_empty_csv_raises() -> None:
    with pytest.raises(ValueError):
        StatementParser(FakeLLM()).parse_csv(b"")


def test_csv_without_recognisable_header_raises() -> None:
    with pytest.raises(ValueError):
        StatementParser(FakeLLM()).parse_csv(_csv("just,some,random", "a,b,c"))
