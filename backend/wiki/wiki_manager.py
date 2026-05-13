import logging
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from db.queries import Transaction, get_approved_transactions_for_month
from llm.client import LLMClient

logger = logging.getLogger(__name__)

_ROUNDING = 1000  # round bucket/category totals to nearest ₹1,000


def _round_to_bracket(amount: float) -> int:
    return round(amount / _ROUNDING) * _ROUNDING


def _week_number(day: int) -> int:
    """Map day-of-month (1-31) to week 1-4."""
    return min((day - 1) // 7 + 1, 4)


def _build_stats_for_prompt(txns: list[Transaction], year: int, month: int) -> str:
    """Aggregate transactions into rounded, anonymised stats for the LLM prompt."""
    bucket_totals: dict[str, float] = defaultdict(float)
    category_totals: dict[str, float] = defaultdict(float)
    week_totals: dict[int, float] = defaultdict(float)
    income_total = 0.0
    pending_count = 0

    for txn in txns:
        if txn.transaction_type == "credit":
            income_total += txn.amount
        else:
            if txn.bucket:
                bucket_totals[txn.bucket] += txn.amount
            if txn.category:
                category_totals[txn.category] += txn.amount
        try:
            day = int(txn.date.split("-")[2])
            week_totals[_week_number(day)] += txn.amount
        except (IndexError, ValueError):
            pass
        if txn.review_status == "pending_review":
            pending_count += 1

    lines = [f"Month: {year:04d}-{month:02d}", f"Income (approx): ₹{_round_to_bracket(income_total):,}"]

    lines.append("\nBucket breakdown:")
    for bucket, total in sorted(bucket_totals.items()):
        lines.append(f"  {bucket}: ₹{_round_to_bracket(total):,}")

    lines.append("\nCategory breakdown:")
    for cat, total in sorted(category_totals.items()):
        lines.append(f"  {cat}: ₹{_round_to_bracket(total):,}")

    lines.append("\nWeekly spending:")
    for week in sorted(week_totals):
        lines.append(f"  Week {week}: ₹{_round_to_bracket(week_totals[week]):,}")

    if pending_count:
        lines.append(f"\nTransactions awaiting review: {pending_count}")

    return "\n".join(lines)


_CURRENT_MONTH_PROMPT = """\
You are the AI finance assistant for a personal finance app.
Using only the anonymised stats below, write a concise, human-friendly
markdown summary for the current month. Include:
- A one-paragraph overview of income vs spending
- A brief weekly spending narrative (Week 1 to Week 4)
- Key observations about bucket distribution against the 50/30/20 target
  (Fundamentals 50%, Fun 30%, Future You 20%)
- A note if any transactions are still awaiting review

Keep the tone conversational. No tables of raw numbers. No exact rupee figures —
use approximate brackets. Keep the total under 400 words.

Stats:
{stats}
"""

_ARCHIVE_PROMPT = """\
Summarise the following month's finance summary in one line, under 120 characters.
Include: approximate spend, approximate income or investment if notable, and one key highlight.
Example format: "₹85k spent, ₹20k invested — Fun budget 8% over; big grocery spike week 3"

Summary:
{summary}
"""


class WikiManager:
    def __init__(
        self,
        llm_client: LLMClient,
        current_path: Path,
        archive_path: Path,
    ) -> None:
        self._llm = llm_client
        self._current_path = current_path
        self._archive_path = archive_path
        current_path.parent.mkdir(parents=True, exist_ok=True)
        archive_path.parent.mkdir(parents=True, exist_ok=True)

    def refresh_current_month(self, conn: sqlite3.Connection, user_id: str) -> None:
        """Regenerate finance_current_month.md from approved DB transactions.

        If the stored file belongs to a previous month, rolls it up to the
        archive first, then writes the new month.
        """
        now = datetime.now()
        year, month = now.year, now.month
        month_label = now.strftime("%B %Y")  # e.g. "May 2026"

        self._maybe_rollup(conn, user_id, year, month)

        txns = get_approved_transactions_for_month(conn, user_id, year, month)
        if not txns:
            content = f"# Finance — {month_label}\n\nNo approved transactions yet this month.\n"
            self._current_path.write_text(content, encoding="utf-8")
            logger.info("Wiki: no transactions for %s, wrote placeholder.", month_label)
            return

        stats = _build_stats_for_prompt(txns, year, month)
        prompt = _CURRENT_MONTH_PROMPT.format(stats=stats)
        narrative = self._llm.generate(prompt)
        content = f"# Finance — {month_label}\n\n{narrative.strip()}\n"
        self._current_path.write_text(content, encoding="utf-8")
        logger.info("Wiki: regenerated current month for %s.", month_label)

    def _maybe_rollup(self, conn: sqlite3.Connection, user_id: str, current_year: int, current_month: int) -> None:
        """If finance_current_month.md belongs to a past month, roll it up to archive."""
        if not self._current_path.exists():
            return
        first_line = self._current_path.read_text(encoding="utf-8").splitlines()[0] if self._current_path.stat().st_size > 0 else ""

        # Parse "# Finance — Month YYYY" from the header
        stored_month = _parse_month_header(first_line)
        if stored_month is None:
            return

        stored_year, stored_mon = stored_month
        if (stored_year, stored_mon) >= (current_year, current_month):
            return  # already current month or future, nothing to roll up

        # Roll up the old month
        old_label = datetime(stored_year, stored_mon, 1).strftime("%B %Y")
        logger.info("Wiki: rolling up %s to archive.", old_label)
        old_summary = self._current_path.read_text(encoding="utf-8")
        one_liner = self._generate_archive_line(old_summary)
        self._append_to_archive(old_label, one_liner)

    def _generate_archive_line(self, summary: str) -> str:
        prompt = _ARCHIVE_PROMPT.format(summary=summary[:2000])
        try:
            return self._llm.generate(prompt).strip()
        except RuntimeError:
            return "(summary unavailable)"

    def _append_to_archive(self, month_label: str, one_liner: str) -> None:
        if not self._archive_path.exists():
            self._archive_path.write_text(
                "# Finance Archive\n\n<!-- One-liner per past month is appended here at month end -->\n",
                encoding="utf-8",
            )
        with self._archive_path.open("a", encoding="utf-8") as f:
            f.write(f"- {month_label}: {one_liner}\n")
        logger.info("Archive: appended entry for %s.", month_label)


def _parse_month_header(first_line: str) -> Optional[tuple[int, int]]:
    """Extract (year, month) from a header like '# Finance — May 2026'."""
    import re
    m = re.match(r"#\s*Finance\s*[—–-]\s*(\w+)\s+(\d{4})", first_line)
    if not m:
        return None
    month_name, year_str = m.group(1), m.group(2)
    try:
        dt = datetime.strptime(f"{month_name} {year_str}", "%B %Y")
        return dt.year, dt.month
    except ValueError:
        return None
