"""Guardrail sanitiser — strips PII from email text before any LLM call.

Rules enforced (from root CLAUDE.md):
  - Account / card numbers  → [ACCOUNT]
  - UPI IDs                 → [UPI_ID]
  - Phone numbers           → [PHONE]
  - Email addresses         → [EMAIL]
  - Customer name patterns  → Dear [NAME]

Guardrail failures raise ValueError — never silently pass through.

Note: merchant names are intentionally NOT redacted here. The guardrail
"no exact merchant names" applies to wiki/chat prompts, not to structural
email parsing where the LLM must see the merchant to extract it.
See decisions.md for this distinction.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Compiled patterns — applied in order (most-specific first)
# ---------------------------------------------------------------------------

# UPI IDs: alphanumeric/dot/hyphen before @ then short bank-like word
_UPI_RE = re.compile(r"\b[\w.\-]+@[a-zA-Z]{2,20}\b", re.IGNORECASE)

# Generic email addresses (after UPI so bank@domain.com is caught above first)
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")

# Account / card numbers:
#   "A/c XX1234", "Acct no. 123456", "account ending 1234",
#   "card ending in 1234", standalone "XX1234" masked patterns
_ACCOUNT_RE = re.compile(
    r"""
    (?:
        (?:a/?c|acct|account|card)              # keyword
        (?:\s+(?:no\.?|number|ending(?:\s+in)?))?  # optional qualifier
        \s*[:\-]?\s*
        [X*\d]{2,4}[\s]?\d{3,8}                # masked prefix + trailing digits
    )
    |
    (?:XX+\d{3,6})                              # standalone XX1234 pattern
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Indian phone numbers: 10-digit starting with 6–9, optional country code.
# Negative lookahead/behind prevents matching digit runs inside longer numbers
# (e.g. 12-digit UPI transaction reference IDs).
_PHONE_RE = re.compile(
    r"""
    (?<!\d)                 # not preceded by a digit
    (?:\+91|0091|0)?        # optional country code
    [\s\-]?
    [6-9]\d{9}              # 10-digit mobile
    (?!\d)                  # not followed by a digit
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Customer name patterns: "Dear Rahul Sharma", "Dear Mr Rahul", "Dear Ms. Priya", etc.
# The title+space is grouped as an optional unit so untitled salutations like
# "Dear lskn ldmjj" are caught without requiring a double space.
_NAME_RE = re.compile(
    r"\bDear\s+(?:(?:Mr\.?|Mrs\.?|Ms\.?|Dr\.?)\s+)?[A-Za-z][a-zA-Z]{1,20}"
    r"(?:\s+[A-Za-z][a-zA-Z]{1,20}){0,2}\b"
)

_RULES: list[tuple[re.Pattern[str], str]] = [
    (_UPI_RE,     "[UPI_ID]"),
    (_EMAIL_RE,   "[EMAIL]"),
    (_ACCOUNT_RE, "[ACCOUNT]"),
    (_PHONE_RE,   "[PHONE]"),
    (_NAME_RE,    "Dear [NAME]"),
]


def sanitise_text(text: str) -> str:
    """Strip PII from arbitrary text before sending it to an LLM.

    Replaces account/card numbers, UPI IDs, phone numbers, email addresses and
    customer-name salutations with labelled placeholders so the LLM keeps
    grammatical context. Merchant names are intentionally preserved — see the
    module docstring.

    Raises:
        ValueError: if the input is not a string.
    """
    if not isinstance(text, str):
        raise ValueError(f"sanitise_text expects a str input, got {type(text)!r}")

    sanitised = text
    for pattern, replacement in _RULES:
        sanitised = pattern.sub(replacement, sanitised)

    if sanitised != text:
        logger.debug("sanitise_text: PII redacted before LLM call")
    else:
        logger.debug("sanitise_text: no PII patterns matched")

    return sanitised


def sanitise_email(subject: str, body: str) -> str:
    """Strip PII from email subject and body before sending to an LLM.

    Returns a single combined string with all PII replaced by labelled
    placeholders so the LLM retains grammatical context.

    Raises:
        ValueError: if either input is not a string.
    """
    if not isinstance(subject, str) or not isinstance(body, str):
        raise ValueError(
            f"sanitise_email expects str inputs, got "
            f"subject={type(subject)!r}, body={type(body)!r}"
        )

    return sanitise_text(f"Subject: {subject}\n\n{body}")
