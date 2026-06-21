"""Gmail ingestion and transaction extraction.

Flow:
  GmailClient.fetch_bank_emails()   →  list of message IDs
  GmailClient.get_email_content()   →  raw subject / body / date
  EmailParser.parse()               →  ParsedTransaction | None
"""

from __future__ import annotations

import base64
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from guardrails.sanitiser import sanitise_email
from llm.client import LLMClient
from wiki.rules_manager import RulesManager

logger = logging.getLogger(__name__)

_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

_DATA_DIR = Path(__file__).parent.parent.parent / "data"
CREDENTIALS_PATH = Path(
    os.getenv("GMAIL_CREDENTIALS_PATH", str(_DATA_DIR / "credentials.json"))
)
TOKEN_PATH = Path(
    os.getenv("GMAIL_TOKEN_PATH", str(_DATA_DIR / "token.json"))
)

# Override via env var to filter by your bank's sender address, e.g.
#   BANK_EMAIL_QUERY="from:alerts@hdfcbank.net"
BANK_EMAIL_QUERY = os.getenv(
    "BANK_EMAIL_QUERY",
    "subject:(transaction OR debit OR credit OR alert) label:inbox",
)

# ---------------------------------------------------------------------------
# Output model
# ---------------------------------------------------------------------------


@dataclass
class ParsedTransaction:
    message_id: str
    amount: float
    merchant: Optional[str]
    date: str               # ISO 8601: YYYY-MM-DD
    transaction_type: str   # expense | investment | loan_repayment | credit | others
    description: str        # raw email subject, kept for audit trail
    category: Optional[str] = None   # food, transport, shopping, …
    bucket: Optional[str] = None     # fundamentals | fun | future | unknown
    review_status: str = "approved"  # pending_review when LLM can't classify


# ---------------------------------------------------------------------------
# LLM schema + prompt
# ---------------------------------------------------------------------------

_TRANSACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "is_transaction": {"type": "boolean"},
        "amount": {"type": "number"},
        "merchant": {"type": "string"},
        "date": {"type": "string"},
        "transaction_type": {
            "type": "string",
            "enum": ["expense", "investment", "loan_repayment", "credit", "others"],
        },
        "category": {"type": "string"},
        "bucket": {
            "type": "string",
            "enum": ["fundamentals", "fun", "future", "unknown"],
        },
    },
    "required": ["is_transaction"],
}

_SYSTEM_PROMPT = """\
You are a financial transaction extractor for an personal finance app.
Analyse the bank alert email below and extract transaction details.

Field definitions:
- is_transaction: true if this email describes a debit, credit, or financial transaction; false for statements, OTPs, promotions.
- amount: the transaction amount as a positive number (e.g. 1250.00). Omit if not found.
- merchant: the merchant or payee name. Omit if not found.
- date: the transaction date in YYYY-MM-DD format. Prefer the date in the email body over the subject. Omit if not found.
- transaction_type:
    "expense"        — day-to-day spending (food, transport, shopping, bills, subscriptions)
    "investment"     — SIP, mutual fund, FD, RD, NPS, PPF, ELSS
    "loan_repayment" — EMI, mortgage payment, loan repayment
    "credit"         — salary credited, refunds, cashback, any incoming money
    "others"         — unknown debits or credits that don't fit above
- category: a short lowercase label such as food, transport, shopping, utilities, emi, sip, salary, entertainment, health. Omit if unclear.
- bucket:
    "fundamentals" — rent, EMI, utilities, insurance, essential transport
    "fun"          — dining, gym, entertainment, subscriptions, shopping
    "future"       — SIP, FD, investments, savings transfers
    "unknown"      — when you cannot determine the bucket

Rules:
- Never invent data. If a field is absent from the email, omit it from the response.
- amount must always be positive even for debits.
- The email text has had PII redacted (e.g. [ACCOUNT], [PHONE], [UPI_ID]). Do not attempt to recover redacted values.
"""


def _build_prompt(sanitised_text: str) -> str:
    return f"{_SYSTEM_PROMPT}\nEmail:\n{sanitised_text}"


# ---------------------------------------------------------------------------
# Date fallback helper
# ---------------------------------------------------------------------------


def _parse_header_date(email_header_date: Optional[str]) -> str:
    """Parse RFC 2822 email Date header into YYYY-MM-DD, defaulting to today."""
    if email_header_date:
        for fmt in ("%a, %d %b %Y %H:%M:%S", "%d %b %Y %H:%M:%S"):
            try:
                return datetime.strptime(
                    email_header_date[:25].strip(), fmt
                ).strftime("%Y-%m-%d")
            except ValueError:
                continue
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Gmail body extractor (unchanged)
# ---------------------------------------------------------------------------


def _extract_body(payload: dict) -> str:
    """Recursively extract the first plain-text (or HTML) body part."""
    mime_type = payload.get("mimeType", "")
    if mime_type in ("text/plain", "text/html"):
        data = payload.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
    for part in payload.get("parts", []):
        text = _extract_body(part)
        if text:
            return text
    return ""


# ---------------------------------------------------------------------------
# EmailParser — LLM-backed
# ---------------------------------------------------------------------------


class EmailParser:
    """Parses bank alert emails into ParsedTransaction using an LLM."""

    def __init__(
        self,
        llm_client: LLMClient,
        rules_manager: Optional[RulesManager] = None,
    ) -> None:
        self._llm = llm_client
        self._rules = rules_manager

    def parse(
        self,
        message_id: str,
        subject: str,
        body: str,
        email_header_date: Optional[str] = None,
    ) -> Optional[ParsedTransaction]:
        """Extract a transaction from an email using the LLM.

        Returns:
            ParsedTransaction if the email describes a transaction.
            None if the LLM determines it is not a transaction email.

        Raises:
            ValueError: if sanitisation fails (bad input types).
            RuntimeError: if the LLM API fails or returns unusable output.
        """
        sanitised = sanitise_email(subject, body)
        prompt = _build_prompt(sanitised)

        logger.debug("Sending message %s to LLM for parsing", message_id)
        data = self._llm.generate_json(prompt, _TRANSACTION_SCHEMA)

        if not data.get("is_transaction"):
            logger.debug("LLM determined message %s is not a transaction — skipping", message_id)
            return None

        amount = data.get("amount")
        if not amount or float(amount) <= 0:
            raise RuntimeError(
                f"LLM flagged is_transaction=true but returned no valid amount "
                f"for message {message_id}"
            )

        date_val = data.get("date")
        if date_val:
            try:
                datetime.strptime(date_val, "%Y-%m-%d")
            except ValueError:
                logger.warning(
                    "LLM returned non-ISO date %r for %s — falling back to header date",
                    date_val,
                    message_id,
                )
                date_val = None
        date_val = date_val or _parse_header_date(email_header_date)

        txn = ParsedTransaction(
            message_id=message_id,
            amount=float(amount),
            merchant=data.get("merchant"),
            date=date_val,
            transaction_type=data.get("transaction_type", "others"),
            description=subject.strip(),
            category=data.get("category"),
            bucket=data.get("bucket", "unknown"),
        )

        # All LLM-parsed transactions require human review by default
        txn.review_status = "pending_review"

        # Apply rule override — human-confirmed rules take precedence over LLM
        # and can bypass review since the pattern was already approved by a human
        if self._rules is not None:
            rule = self._rules.match(txn.merchant)
            if rule:
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

        return txn


# ---------------------------------------------------------------------------
# GmailClient — unchanged
# ---------------------------------------------------------------------------


class GmailClient:
    """Handles OAuth 2.0 auth and Gmail API calls."""

    def __init__(self) -> None:
        self._service = None

    def _build_service(self):
        creds: Optional[Credentials] = None
        if TOKEN_PATH.exists():
            creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), _SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not CREDENTIALS_PATH.exists():
                    raise RuntimeError(
                        f"Gmail credentials not found at {CREDENTIALS_PATH}. "
                        "Download credentials.json from the Google Cloud Console "
                        "and place it in the data/ directory."
                    )
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(CREDENTIALS_PATH), _SCOPES
                )
                creds = flow.run_local_server(port=0)
            TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
            TOKEN_PATH.write_text(creds.to_json())

        return build("gmail", "v1", credentials=creds)

    @property
    def service(self):
        if self._service is None:
            self._service = self._build_service()
        return self._service

    def fetch_bank_emails(self, max_results: int = 50) -> list[dict]:
        """Return a list of {id, threadId} dicts matching BANK_EMAIL_QUERY."""
        try:
            result = (
                self.service.users()
                .messages()
                .list(userId="me", q=BANK_EMAIL_QUERY, maxResults=max_results)
                .execute()
            )
            return result.get("messages", [])
        except HttpError as exc:
            logger.error("Gmail API error listing messages: %s", exc)
            raise RuntimeError(f"Gmail API error: {exc}") from exc

    def get_email_content(self, message_id: str) -> dict:
        """Return subject, body, and Date header for a single message."""
        try:
            msg = (
                self.service.users()
                .messages()
                .get(userId="me", id=message_id, format="full")
                .execute()
            )
        except HttpError as exc:
            logger.error("Gmail API error fetching message %s: %s", message_id, exc)
            raise RuntimeError(f"Gmail API error: {exc}") from exc

        headers = {
            h["name"]: h["value"]
            for h in msg.get("payload", {}).get("headers", [])
        }
        return {
            "message_id": message_id,
            "subject": headers.get("Subject", ""),
            "body": _extract_body(msg.get("payload", {})),
            "date": headers.get("Date"),
        }
