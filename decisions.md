# Design Decisions

## 2026-06-21 — Two-tier transaction categorization (type → bucket, kind-gated)

**Decision:** Replaced the flat classification model (a single `transaction_type`
constrained to `expense | investment | loan_repayment | credit | others`) with a
**two-tier model**: a granular, user-editable **transaction type** carries a
coarse **kind** and rolls up to a privacy-safe **bucket**.

**The two tiers:**
- **Type** — granular, named, and user-editable: `food`, `groceries`, `rent`,
  `sip`, `salary`, `loan_interest`, … This is the rich detail kept locally.
- **Kind** — coarse class gating each type: `income | expense | investment |
  loan | transfer`.
- **Bucket** — the 50/30/20 rollup: `fundamentals | fun | future` (NULL for
  `income`/`transfer`, which sit outside spending). **The bucket is the finest
  thing ever sent to the LLM** — never the granular type or merchant. The type is
  the local-only detail; the bucket is the privacy-preserving abstraction that
  maps to `finance.md`.

**Schema (`backend/db/schema.py`):**
- New `transaction_types` table: `id, user_id, name, kind, bucket,
  is_system_default`.
  - `user_id IS NULL` ⇒ a **system default** shared across all users. A per-user
    row with the same `name` **overrides** the system default for that user.
  - Uniqueness is enforced by a unique index on `(IFNULL(user_id, 0), name)`,
    **not** a plain `UNIQUE(user_id, name)`: SQLite treats every NULL as distinct,
    so a plain constraint would let duplicate system rows through. Folding NULL to
    `0` (user ids start at 1, so no collision) keeps seeding idempotent.
- `transactions` gains two columns, both nullable and added non-destructively via
  `ALTER TABLE` in `migrate_db()`:
  - `direction` — `debit | credit`, parsed deterministically from the source.
  - `type_id` — FK → `transaction_types`. Bucket/kind are resolved **via the type**
    (type-only for now; no per-transaction bucket override).

**Seed:** `seed_system_transaction_types()` runs on every startup (idempotent via
`INSERT OR IGNORE`). System defaults: food→expense/fun, groceries→expense/fundamentals,
rent→expense/fundamentals, transport→expense/fundamentals, shopping→expense/fun,
subscriptions→expense/fun, sip→investment/future, emergency_fund→investment/future,
loan_emi→loan/fundamentals, loan_interest→loan/fundamentals, salary→income/NULL,
friend_lending→transfer/NULL.

**Resolution rule:** `get_transaction_type_by_name(conn, user_id, name)` returns a
user's override ahead of the system default (`ORDER BY user_id IS NULL`), so a user
can reclassify e.g. `food` as `fundamentals` without affecting anyone else.

**Bucket vocabulary unified:** the legacy `future_you` spelling was renamed to `future`
everywhere — `transactions.bucket`'s CHECK, both classifier prompts/enums
(`statement_parser`, `email_parser`), the approve-route validation, and the frontend
selector — so the legacy `transactions.bucket` column and the new
`transaction_types.bucket` share one vocabulary (`fundamentals | fun | future`). The
flat column additionally keeps `unknown` as the "can't determine" sentinel for the
current classification path. The stale local `finance.db` was deleted (test data) and
is recreated fresh by `init_db()`/`migrate_db()` with the unified schema.

**Type_id population:** the new columns start NULL until the classification pipeline is
updated to emit granular type names and populate `type_id`. **Follow-up (not in this
change):** wire the CSV/email classifier to emit a granular type name, resolve it to
`type_id`, and derive kind/bucket from the type instead of the LLM-supplied flat
`transaction_type`/`bucket`.

**Supersedes** the flat-model description in the *2026-04-26 — Add `credit`
transaction type* entry below; `credit`/`others` on `transactions.transaction_type`
remain only for backward compatibility with already-stored rows.

## 2026-06-14 — CSV bank statement ingestion

**Decision:** Added a second ingestion path alongside the Gmail email parser: users upload a bank statement CSV via `POST /statements/upload`, and the rows are parsed and classified by the LLM into transactions.

**How it works (hybrid — deterministic extraction + LLM classification):**
- `backend/statement_parser/parser.py` (`StatementParser`) reads the CSV with the stdlib `csv` module and extracts **date, amount, and direction deterministically** from the columns. The LLM is **not** asked for these — an early full-LLM-extraction version hallucinated a date (`2026` → `2426`), and amount/date are facts already stated in the file.
- **Column mapping** is keyword-based on the header row (`date`, `particulars/narration/description`, `dr/cr/debit/credit`, `balance`, `amount`), which also skips the account-info preamble many statements carry. Date parsing accepts day-first formats (`DD-MM-YYYY`, etc.) and normalises to ISO.
- **Direction (debit vs credit) is derived from the running-balance delta, not the DR/CR labels.** Real Axis Bank exports label the columns inverted relative to the customer's view (a value in the `CR` column *lowers* the balance). `_labels_swapped()` correlates which column is populated against the sign of the balance change and flips if needed. This is bank-agnostic and was essential to get a ₹140k salary credit and credit-card payments on the right side.
- **The LLM only classifies debits** (in chunks of 20): `transaction_type ∈ {expense, investment, loan_repayment, others}`, `bucket`, `category`, and a clean `merchant`. Credits are money-in, so type is fixed to `credit` and bucket to `unknown` with no LLM call.
- Each debit's narration is sanitised with the new `guardrails.sanitiser.sanitise_text()` before reaching the LLM (account numbers, UPI IDs, phones, emails, names redacted). `sanitise_email()` now delegates to it. Amounts are never sent to the LLM, so the "bucket amounts" guardrail is moot for this path.
- Imported transactions get `review_status='pending_review'`, unless a confirmed `finance_rules.md` rule matches the merchant, which marks them `approved`.

**Schema change:** Added a `source` column to `transactions` (`'email' | 'csv'`, default `'email'`). Existing rows backfill to `'email'`. Applied non-destructively via an `ALTER TABLE` in `migrate_db()` — no need to delete `finance.db`.

**Dedup:** CSV rows have no email message id, so dedup reuses the existing `UNIQUE(user_id, email_message_id)` key. The dedup value for a CSV row is `csv:<sha256(raw row)[:16]>`, stored in `email_message_id`. Re-uploading the same statement (or an overlapping date range) is therefore idempotent. The `email_message_id` column is now a generic per-source dedup reference despite its name; the `source` column records true provenance. Insertion uses `insert_transaction_if_new()` (`INSERT OR IGNORE`), which reports duplicates instead of raising.

**Why not delete email ingestion:** The email parser stays; CSV upload is an alternative source, not a replacement. Both feed the same review queue and DB.

**Frontend:** New `UploadPage` (Upload nav tab) posts the file as multipart form data and shows parsed/imported/duplicate counts.


## 2026-04-26 — Add `credit` transaction type

**Decision:** Added `credit` as a first-class `transaction_type` value alongside `expense`, `investment`, `loan_repayment`, and `others`.

**Why:** All incoming money (salary credits, refunds, cashback, incoming transfers) was previously lumped into `others`, making it impossible to distinguish real inflows from genuinely unknown transactions in analytics and the finance wiki.

**Impact:** `others` is now reserved for transactions that truly cannot be classified. The `CHECK` constraint in `schema.py`, the LLM JSON schema enum, and the system prompt in `parser.py` all updated consistently. If `data/finance.db` already exists, delete it so `init_db()` recreates the schema with the new constraint.
