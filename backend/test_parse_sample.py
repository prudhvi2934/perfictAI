"""One-shot script to test the parser pipeline on a sample Axis Bank email."""
import json
import logging
import sys
from pathlib import Path

# Make sure backend/ is on the path when run from the backend/ directory
sys.path.insert(0, str(Path(__file__).parent))

# Load .env from project root so GEMINI_API_KEY etc. are available without
# manually exporting them before each run.
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

logging.basicConfig(level=logging.DEBUG, format="%(levelname)s  %(message)s")

SUBJECT = "Transaction Alert - Amount Debited INR 32.00"

BODY = """\

07-05-2026

Dear rama krishna,

Here's the summary of your transaction:
	
Amount Debited:
INR 32.00
	
Account Number:
XX9999
	
Date & Time:
07-05-26, 02:07:52 IST
	
Transaction Info:
UPI/P2M/64990099759884/NOOKALA PRAHALAD

"""

# ------------------------------------------------------------------
# Step 1 — Sanitiser
# ------------------------------------------------------------------
from guardrails.sanitiser import sanitise_email

sanitised = sanitise_email(SUBJECT, BODY)
print("\n" + "="*60)
print("SANITISED OUTPUT (what goes to the LLM)")
print("="*60)
print(sanitised)

# ------------------------------------------------------------------
# Step 2 — Full parse (needs GEMINI_API_KEY in env)
# ------------------------------------------------------------------
import os
if not os.environ.get("GEMINI_API_KEY"):
    print("\n[SKIPPED] Set GEMINI_API_KEY to also test the full LLM parse step.")
    sys.exit(0)

from llm.client import LLMClient
from email_parser.parser import EmailParser

llm = LLMClient()
parser = EmailParser(llm)

result = parser.parse(
    message_id="test-axis-001",
    subject=SUBJECT,
    body=BODY,
    email_header_date=None,
)

print("\n" + "="*60)
print("PARSED TRANSACTION")
print("="*60)
if result is None:
    print("LLM decided this is NOT a transaction email.")
else:
    import dataclasses
    print(json.dumps(dataclasses.asdict(result), indent=2))
