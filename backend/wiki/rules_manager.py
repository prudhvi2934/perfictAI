import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_HEADER = """\
# Finance Rules

Rules are auto-generated from human corrections and applied before LLM
classification is stored. Each rule matches case-insensitively against the
extracted merchant name. Rules take precedence over LLM output.

---
"""

_KV_RE = re.compile(r"^- (\w+):\s*(.+)$", re.MULTILINE)


@dataclass
class FinanceRule:
    pattern: str            # lowercase — case-insensitive match key
    transaction_type: str
    bucket: str
    category: Optional[str]


def _rule_to_block(rule: FinanceRule) -> str:
    category_line = rule.category if rule.category else ""
    return (
        f"## Rule: {rule.pattern}\n\n"
        f"- pattern: {rule.pattern}\n"
        f"- transaction_type: {rule.transaction_type}\n"
        f"- bucket: {rule.bucket}\n"
        f"- category: {category_line}\n\n"
        "---\n"
    )


class RulesManager:
    def __init__(self, rules_path: Path) -> None:
        self._path = rules_path
        if not rules_path.exists():
            rules_path.parent.mkdir(parents=True, exist_ok=True)
            rules_path.write_text(_HEADER, encoding="utf-8")

    def load_rules(self) -> list[FinanceRule]:
        content = self._path.read_text(encoding="utf-8")
        # Split on section headers; first chunk is the file header, skip it
        chunks = re.split(r"\n## Rule:", content)
        rules: list[FinanceRule] = []
        for chunk in chunks[1:]:
            kv = dict(_KV_RE.findall(chunk))
            if "pattern" not in kv or "transaction_type" not in kv or "bucket" not in kv:
                logger.warning("Skipping malformed rule block: %r", chunk[:80])
                continue
            rules.append(
                FinanceRule(
                    pattern=kv["pattern"].strip().lower(),
                    transaction_type=kv["transaction_type"].strip(),
                    bucket=kv["bucket"].strip(),
                    category=kv.get("category", "").strip() or None,
                )
            )
        return rules

    def match(self, merchant: Optional[str]) -> Optional[FinanceRule]:
        """Return the first rule whose pattern is a substring of merchant (case-insensitive)."""
        if not merchant:
            return None
        merchant_lower = merchant.lower()
        for rule in self.load_rules():
            if rule.pattern in merchant_lower:
                return rule
        return None

    def upsert_rule(self, rule: FinanceRule) -> None:
        """Add or replace the rule for rule.pattern, then rewrite the file."""
        existing = {r.pattern: r for r in self.load_rules()}
        existing[rule.pattern] = rule
        content = _HEADER + "".join(_rule_to_block(r) for r in existing.values())
        self._path.write_text(content, encoding="utf-8")
        logger.info("Rule upserted for pattern %r", rule.pattern)
