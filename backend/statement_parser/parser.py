"""Bank statement (CSV) ingestion and transaction extraction.

An alternative to email ingestion: instead of pulling bank alert emails from
Gmail, the user uploads a bank statement export. Each statement row becomes a
transaction awaiting human review.

Design:
  - Date, amount and direction (debit/credit) are extracted DETERMINISTICALLY
    from the CSV. They are facts already stated in the file, so we never ask the
    LLM for them — that avoids hallucinated dates/amounts.
  - Direction is derived from the running-balance column, not the DR/CR labels.
    Some banks (e.g. Axis) export columns whose DR/CR headers are inverted
    relative to the customer's view; the balance delta is the ground truth.
  - The LLM is used ONLY to classify debits (transaction_type, bucket, category)
    and to produce a clean merchant name. Credits are money-in, so their type is
    fixed to "credit" without an LLM call.

Flow:
  StatementParser.parse_csv(raw)  ->  list[ParsedStatementTransaction]
"""

from __future__ import annotations

import csv
import hashlib
import io
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from guardrails.sanitiser import sanitise_text
from llm.client import LLMClient
from wiki.rules_manager import RulesManager

logger = logging.getLogger(__name__)

# How many debit rows to classify per LLM request.
_CHUNK_SIZE = 20

# Guards against an accidental huge / non-statement upload.
_MAX_ROWS = 5000

# Accepted date layouts, day-first (Indian bank convention) before month-first.
_DATE_FORMATS = (
    "%d-%m-%Y",
    "%d/%m/%Y",
    "%d-%m-%y",
    "%d/%m/%y",
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%d-%b-%Y",
    "%d %b %Y",
    "%d-%b-%y",
    "%m/%d/%Y",
)

# Header keyword -> logical role. First matching cell wins a role.
_DATE_KEYS = ("date",)
_DESC_KEYS = (
    "particular",
    "description",
    "narration",
    "naration",
    "details",
    "remarks",
)
_DEBIT_KEYS = ("debit", "withdrawal", "withdraw")
_CREDIT_KEYS = ("credit", "deposit")
_BALANCE_KEYS = ("balance", "bal")
_AMOUNT_KEYS = ("amount", "amt")


# ---------------------------------------------------------------------------
# Output model
# ---------------------------------------------------------------------------


@dataclass
class ParsedStatementTransaction:
    dedup_id: str           # stable content hash of the source row
    amount: float
    merchant: Optional[str]
    date: str               # ISO 8601: YYYY-MM-DD
    transaction_type: str   # expense | investment | loan_repayment | credit | others
    description: str        # cleaned statement narration, kept for audit trail
    direction: str = "debit"         # debit (money out) | credit (money in)
    category: Optional[str] = None   # food, transport, shopping, …
    bucket: Optional[str] = None     # fundamentals | fun | future | unknown
    review_status: str = "pending_review"


@dataclass
class _RawRow:
    """A deterministically-parsed statement row, before LLM classification."""

    index: int
    date: str
    amount: float
    description: str
    direction: str          # "debit" (money out) | "credit" (money in)
    dedup_id: str
    merchant: Optional[str] = None
    transaction_type: Optional[str] = None
    bucket: Optional[str] = None
    category: Optional[str] = None


# ---------------------------------------------------------------------------
# LLM schema + prompt (debits only — classification, not extraction)
# ---------------------------------------------------------------------------

_CLASSIFY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "transactions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "row_index": {"type": "integer"},
                    "merchant": {"type": "string"},
                    "transaction_type": {
                        "type": "string",
                        "enum": ["expense", "investment", "loan_repayment", "others"],
                    },
                    "category": {"type": "string"},
                    "bucket": {
                        "type": "string",
                        "enum": ["fundamentals", "fun", "future", "unknown"],
                    },
                },
                "required": ["row_index", "transaction_type", "bucket"],
            },
        }
    },
    "required": ["transactions"],
}

_SYSTEM_PROMPT = """\
You are a financial transaction classifier for a personal finance app.
Below are debit (money-out) rows from a bank statement, each tagged with a
row_index. The amount and date are already known — only classify each row.

For every row return:
- row_index: copy the row_index of the row you are describing — required.
- merchant: a short, clean merchant or payee name pulled from the narration
  (e.g. "bigbasket", "Swiggy", "Razorpay"). Omit if it cannot be identified.
- transaction_type:
    "expense"        — day-to-day spending (food, transport, shopping, bills, subscriptions)
    "investment"     — SIP, mutual fund, FD, RD, NPS, PPF, ELSS
    "loan_repayment" — EMI, mortgage payment, credit-card bill, loan repayment
    "others"         — a debit that does not fit the above
- category: a short lowercase label such as food, transport, shopping, utilities,
  emi, sip, entertainment, health. Omit if unclear.
- bucket:
    "fundamentals" — rent, EMI, utilities, insurance, essential transport
    "fun"          — dining, gym, entertainment, subscriptions, shopping
    "future"       — SIP, FD, investments, savings transfers
    "unknown"      — when you cannot determine the bucket

Rules:
- Never invent data. Omit a field you cannot determine (except the required ones).
- Some values are redacted (e.g. [ACCOUNT], [PHONE], [UPI_ID]); do not guess them.
- Return exactly one object per input row_index.
"""


def _build_prompt(header: str, indexed_rows: list[tuple[int, str]]) -> str:
    lines = [f"Statement columns: {header}", "", "Debit rows:"]
    for index, desc in indexed_rows:
        lines.append(f"[{index}] {desc}")
    return f"{_SYSTEM_PROMPT}\n" + "\n".join(lines)


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

_AMOUNT_CLEAN_RE = re.compile(r"[^\d.\-]")
_WHITESPACE_RE = re.compile(r"\s+")


def _decode(raw: bytes) -> str:
    """Decode uploaded bytes, tolerating a UTF-8 BOM and stray bytes."""
    return raw.decode("utf-8-sig", errors="replace")


def _cell(cells: list[str], idx: Optional[int]) -> str:
    if idx is None or idx >= len(cells):
        return ""
    return cells[idx].strip()


def _parse_amount(value: str) -> Optional[float]:
    """Parse a money string (Indian grouping, parentheses negatives) to float.

    Returns None for blank/zero cells so an unused DR or CR column reads as empty.
    """
    raw = value.strip()
    if not raw:
        return None
    negative = raw.startswith("(") and raw.endswith(")")
    cleaned = _AMOUNT_CLEAN_RE.sub("", raw)
    if cleaned in ("", "-", "."):
        return None
    try:
        amount = float(cleaned)
    except ValueError:
        return None
    if amount == 0:
        return None
    return -amount if negative else amount


def _parse_date(value: str) -> Optional[str]:
    """Parse a statement date in any accepted format to ISO YYYY-MM-DD."""
    raw = value.strip()
    if not raw:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _clean_text(value: str) -> str:
    return _WHITESPACE_RE.sub(" ", value).strip()


def _dedup_id(cells: list[str]) -> str:
    digest = hashlib.sha256("\x1f".join(cells).encode("utf-8")).hexdigest()
    return f"csv:{digest[:16]}"


def _map_columns(header: list[str]) -> dict[str, int]:
    """Map header cells to logical roles by keyword, first match wins per role.

    Each cell resolves to at most one role; specific roles (date, debit, credit,
    balance, amount) are checked before the generic description role so a column
    like "Debit Amount" is treated as debit, not description.
    """
    roles: dict[str, int] = {}

    def assign(role: str, idx: int) -> None:
        roles.setdefault(role, idx)

    for idx, cell in enumerate(header):
        c = cell.strip().lower()
        if not c:
            continue
        if any(k in c for k in _DATE_KEYS):
            assign("date", idx)
        elif c == "dr" or any(k in c for k in _DEBIT_KEYS):
            assign("debit", idx)
        elif c == "cr" or any(k in c for k in _CREDIT_KEYS):
            assign("credit", idx)
        elif any(k in c for k in _BALANCE_KEYS):
            assign("balance", idx)
        elif any(k in c for k in _AMOUNT_KEYS):
            assign("amount", idx)
        elif any(k in c for k in _DESC_KEYS):
            assign("description", idx)
    return roles


def _find_header(rows: list[list[str]]) -> tuple[int, dict[str, int]]:
    """Locate the transaction header row and its column map.

    Skips the account-info preamble many statements carry. A header qualifies if
    it has a date column, a description column, and either a debit+credit pair or
    a single amount column.
    """
    for idx, row in enumerate(rows):
        cols = _map_columns(row)
        has_amount = ("debit" in cols and "credit" in cols) or "amount" in cols
        if "date" in cols and "description" in cols and has_amount:
            return idx, cols
    raise ValueError(
        "Could not find a transaction header row (need date, description and "
        "debit/credit or amount columns)"
    )


def _labels_swapped(data_rows: list[list[str]], cols: dict[str, int]) -> bool:
    """Decide whether DR/CR labels are inverted, using running-balance deltas.

    Returns True when a value in the debit-labelled column actually corresponds
    to money coming IN (balance rising) — i.e. the labels are reversed.
    """
    bal_idx = cols.get("balance")
    if bal_idx is None or "debit" not in cols or "credit" not in cols:
        return False  # no balance evidence — trust the labels

    score = 0  # >=0 keeps labels as-is; <0 means swapped
    prev_bal: Optional[float] = None
    for cells in data_rows:
        bal = _parse_amount(_cell(cells, bal_idx))
        dr = _parse_amount(_cell(cells, cols["debit"]))
        cr = _parse_amount(_cell(cells, cols["credit"]))
        if bal is not None and prev_bal is not None:
            delta = bal - prev_bal
            if dr and not cr:
                score += 1 if delta < 0 else -1
            elif cr and not dr:
                score += 1 if delta > 0 else -1
        if bal is not None:
            prev_bal = bal
    return score < 0


def _direction_and_amount(
    cells: list[str], cols: dict[str, int], swapped: bool
) -> Optional[tuple[str, float]]:
    """Return (direction, positive_amount) for a row, or None if not a txn row."""
    if "amount" in cols and "debit" not in cols and "credit" not in cols:
        amount = _parse_amount(_cell(cells, cols["amount"]))
        if amount is None:
            return None
        direction = "debit" if amount < 0 else "credit"
        return direction, abs(amount)

    dr = _parse_amount(_cell(cells, cols.get("debit")))
    cr = _parse_amount(_cell(cells, cols.get("credit")))
    # Resolve the labelled columns into real money-in / money-out values.
    money_out, money_in = (cr, dr) if swapped else (dr, cr)
    if money_out and not money_in:
        return "debit", abs(money_out)
    if money_in and not money_out:
        return "credit", abs(money_in)
    if money_out and money_in:
        # Both populated — fall back to the larger as the transaction amount.
        return ("debit", abs(money_out)) if money_out >= money_in else (
            "credit",
            abs(money_in),
        )
    return None


# ---------------------------------------------------------------------------
# StatementParser
# ---------------------------------------------------------------------------


class StatementParser:
    """Parses bank statement CSVs into transactions."""

    def __init__(
        self,
        llm_client: LLMClient,
        rules_manager: Optional[RulesManager] = None,
    ) -> None:
        self._llm = llm_client
        self._rules = rules_manager

    def parse_csv(self, raw: bytes) -> list[ParsedStatementTransaction]:
        """Extract transactions from raw CSV bytes.

        Date/amount/direction come from the CSV; debit classification comes from
        the LLM. Preamble, summary and legend rows are skipped automatically
        (they have no parseable date + amount).

        Raises:
            ValueError: if no transaction header/rows can be found, or too large.
            RuntimeError: if the LLM API fails or returns unusable output.
        """
        rows = [
            r
            for r in csv.reader(io.StringIO(_decode(raw)))
            if any(cell.strip() for cell in r)
        ]
        if not rows:
            raise ValueError("CSV file is empty")

        header_idx, cols = _find_header(rows)
        data_rows = rows[header_idx + 1 :]
        if not data_rows:
            raise ValueError("CSV has a transaction header but no data rows")
        if len(data_rows) > _MAX_ROWS:
            raise ValueError(
                f"CSV has {len(data_rows)} rows, exceeding the {_MAX_ROWS}-row limit"
            )

        header_text = ", ".join(c.strip() for c in rows[header_idx] if c.strip())
        swapped = _labels_swapped(data_rows, cols)
        if swapped:
            logger.info("Detected inverted DR/CR columns — using balance direction")

        raw_txns = self._extract_rows(data_rows, cols, swapped)
        self._classify_debits(raw_txns, header_text)

        results = [self._finalise(r) for r in raw_txns]
        logger.info(
            "Parsed %d transactions (%d debit, %d credit) from %d statement rows",
            len(results),
            sum(1 for r in raw_txns if r.direction == "debit"),
            sum(1 for r in raw_txns if r.direction == "credit"),
            len(data_rows),
        )
        return results

    def _extract_rows(
        self, data_rows: list[list[str]], cols: dict[str, int], swapped: bool
    ) -> list[_RawRow]:
        extracted: list[_RawRow] = []
        for index, cells in enumerate(data_rows):
            date = _parse_date(_cell(cells, cols["date"]))
            if date is None:
                continue  # preamble / summary / legend line — not a transaction
            dir_amount = _direction_and_amount(cells, cols, swapped)
            if dir_amount is None:
                continue
            direction, amount = dir_amount
            description = _clean_text(_cell(cells, cols["description"]))
            extracted.append(
                _RawRow(
                    index=index,
                    date=date,
                    amount=amount,
                    description=description,
                    direction=direction,
                    dedup_id=_dedup_id(cells),
                )
            )
        return extracted

    def _classify_debits(self, rows: list[_RawRow], header_text: str) -> None:
        debits = [r for r in rows if r.direction == "debit"]
        for chunk in (
            debits[i : i + _CHUNK_SIZE] for i in range(0, len(debits), _CHUNK_SIZE)
        ):
            by_index = {r.index: r for r in chunk}
            indexed = [
                (r.index, sanitise_text(r.description) or "(no description)")
                for r in chunk
            ]
            data = self._llm.generate_json(
                _build_prompt(header_text, indexed), _CLASSIFY_SCHEMA
            )
            for item in data.get("transactions", []):
                row = by_index.get(item.get("row_index"))
                if row is None:
                    continue
                row.transaction_type = item.get("transaction_type")
                row.bucket = item.get("bucket")
                row.category = item.get("category")
                merchant = item.get("merchant")
                if merchant:
                    row.merchant = merchant.strip()

    def _finalise(self, row: _RawRow) -> ParsedStatementTransaction:
        if row.direction == "credit":
            transaction_type = "credit"
            bucket = "unknown"
            merchant = row.merchant or row.description or None
            category = row.category
        else:
            transaction_type = row.transaction_type or "others"
            bucket = row.bucket or "unknown"
            merchant = row.merchant or row.description or None
            category = row.category

        txn = ParsedStatementTransaction(
            dedup_id=row.dedup_id,
            amount=row.amount,
            merchant=merchant,
            date=row.date,
            transaction_type=transaction_type,
            description=row.description,
            direction=row.direction,
            category=category,
            bucket=bucket,
        )
        self._apply_rule(txn)
        return txn

    def _apply_rule(self, txn: ParsedStatementTransaction) -> None:
        """Override classification with a human-confirmed rule, if one matches."""
        if self._rules is None:
            return
        rule = self._rules.match(txn.merchant)
        if rule is None:
            return
        logger.info(
            "Rule match for merchant %r — overriding type=%s bucket=%s",
            txn.merchant,
            rule.transaction_type,
            rule.bucket,
        )
        txn.transaction_type = rule.transaction_type
        txn.bucket = rule.bucket
        if rule.category:
            txn.category = rule.category
        txn.review_status = "approved"
