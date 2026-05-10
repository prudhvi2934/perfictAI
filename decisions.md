# Design Decisions

## 2026-04-26 — Add `credit` transaction type

**Decision:** Added `credit` as a first-class `transaction_type` value alongside `expense`, `investment`, `loan_repayment`, and `others`.

**Why:** All incoming money (salary credits, refunds, cashback, incoming transfers) was previously lumped into `others`, making it impossible to distinguish real inflows from genuinely unknown transactions in analytics and the finance wiki.

**Impact:** `others` is now reserved for transactions that truly cannot be classified. The `CHECK` constraint in `schema.py`, the LLM JSON schema enum, and the system prompt in `parser.py` all updated consistently. If `data/finance.db` already exists, delete it so `init_db()` recreates the schema with the new constraint.
