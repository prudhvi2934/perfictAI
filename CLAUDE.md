# CLAUDE.md — Personal Finance AI

> This file is the source of truth for Claude Code when working on this project.
> Read this before touching any file. Sub-folders (`/backend`, `/frontend`) have
> their own `CLAUDE.md` files with layer-specific rules. This root file governs
> the entire project — those files extend it, never override it.

---

## What is this project?

A **local-first, AI-powered personal finance assistant** built for a single user.

It ingests bank alert emails from Gmail, classifies every transaction, stores
everything in a local SQLite database, and maintains a living `finance.md`
markdown wiki that an LLM reads and writes to build up financial memory over
time. A React/Vue dashboard visualises spending through the 50/30/20 framework.
An AI chat interface lets the user query their finances in natural language.

**The one-line rule:** All data stays on the machine. Nothing personal ever
reaches an external service in raw form.

---

## Project structure

```
/
├── CLAUDE.md                  ← you are here (universal rules)
├── decisions.md
├── data/ 
│   ├── finance.md                 ← AI-maintained financial wiki (runtime artifact)
│   ├── finance.db                 ← SQLite database (runtime artifact)
│
├── backend/                   ← Python / FastAPI
│   ├── CLAUDE.md              ← backend-specific rules
│   ├── main.py
│   ├── llm/                   ← model-agnostic LLM abstraction layer
│   │   └── client.py          ← LLMClient — the ONLY place that calls any LLM API
│   ├── email_parser/          ← Gmail ingestion + transaction extraction
│   ├── db/                    ← SQLite models and queries
│   ├── wiki/                  ← finance.md read/write logic
│   ├── guardrails/            ← data sanitisation before any LLM call
│   └── routers/               ← FastAPI route handlers
│
└── frontend/                  ← React or Vue (TBD)
    ├── CLAUDE.md              ← frontend-specific rules
    └── src/
        ├── components/
        │   ├── Dashboard/     ← 50/30/20 visual breakdown
        │   ├── LoanTracker/
        │   └── ChatInterface/
        └── api/               ← all calls go to local FastAPI, never external
```

---

## Core philosophy — never negotiate these

| Principle | What it means in practice |
|---|---|
| **Local-first** | SQLite + `finance.md` on disk. No cloud DB, no cloud sync, no remote backups. |
| **Privacy by design** | Raw transaction data never leaves the machine. Guardrails are mandatory, not optional. |
| **Model-agnostic** | Feature code never imports or calls Gemini, Claude, OpenAI, or Ollama directly. Always go through `LLMClient`. |
| **Wiki as memory** | `finance.md` is the AI's long-term memory. It is human-readable and user-editable. The AI treats user-written notes as ground truth. |
| **Simplicity first** | If a simpler approach works for the current phase, use it. Avoid over-engineering for future phases. |

---

## Current phase — Phase 1 (MVP)

Stay focused on Phase 1 unless explicitly told otherwise.

**MVP build order — follow this sequence:**

1. **Email parser** — Gmail API → extract amount, merchant, date, type per email
2. **Local database** — SQLite storage + expense / investment / loan repayment classification
3. **Finance wiki** — AI generates and updates `finance.md` after each transaction batch
4. **Dashboard** — 50/30/20 visual breakdown against actual spending
5. **AI chat interface** — user asks questions; AI reads wiki + DB to answer

**Phase 2** (not in scope yet): goal-based investment planning, Indian tax
optimisation.

**Phase 3** (not in scope yet): bank API integration, multi-account, mobile app.

> If asked to build something from Phase 2 or 3, flag it and confirm before proceeding.

---

## The 50/30/20 framework

This is the core budgeting model. Every dashboard view, insight, and
recommendation anchors to it.

| Bucket | Target | Covers |
|---|---|---|
| **Fundamentals** | 50% | Rent, loans, phone, insurance, transport, etc |
| **Fun** | 30% | Gym, dining, subscriptions, shopping, etc |
| **Future You** | 20% | Emergency fund, pension, house/car savings, short-term goals, etc |

---

## Transaction taxonomy

Every transaction belongs to exactly one of:

- `expense` — day-to-day spending
- `investment` — money going toward growth or savings
- `loan_repayment` — clearing existing debt
- `credit` — any money coming IN: salary, refunds, cashback, incoming transfers
- `others` — unknown / cannot classify

Use these exact snake_case strings as the canonical values everywhere — in the
DB schema, API responses, and frontend.

---

## The `finance.md` wiki — rules

- The wiki is **not** a data dump. It is a narrative summary written by the AI.
- It is updated by the AI after every new batch of transactions.
- **User-written annotations are ground truth.** The AI must preserve and respect them.
- The AI reads the wiki before every chat interaction — this replaces repeated raw DB queries.
- Format: plain markdown. No JSON blocks, no tables of raw numbers.
- Location: always at the project root as `finance.md`

---

## Guardrail rules — enforce in every LLM-touching code path

These rules apply to **every** prompt sent to any LLM, including local models
(Ollama). They are not optional.

| Rule | Detail |
|---|---|
| No account or card numbers | Strip or never include in any prompt |
| No exact merchant names | Map to a category (food, transport, shopping, …) before sending |
| Bucket amounts | Round to nearest ₹500 or ₹1,000 bracket — never send exact rupee figures |
| Wiki only | Only the `finance.md` summary goes to the LLM — never raw SQLite rows |
| No PII | No name, phone number, email address, or UPI ID in any prompt |

The `backend/guardrails/` module must sanitise all data before it reaches
`LLMClient`. Guardrail failures must raise an exception — never silently pass
through.

---

## Tech stack decisions (locked)

| Layer | Decision | Reason |
|---|---|---|
| Backend language | Python | FastAPI ecosystem, LLM library support |
| API framework | FastAPI | Async, typed, auto-docs |
| Database | SQLite (local file) | Zero-infrastructure, single-user, local-first |
| AI memory | `finance.md` markdown wiki | Human-readable, Git-friendly, cheap LLM context |
| LLM provider | Gemini free API (via `LLMClient`) | Free tier, swappable via abstraction |
| Email source | Gmail API | Only supported ingestion method in Phase 1 |
| Frontend | React or Vue (TBD) | Local web app served by FastAPI or standalone dev server |
| Hosting | Local machine only | Privacy is non-negotiable |

> Do not suggest alternatives to these unless the user explicitly opens the
> decision for reconsideration.

---

## What to never suggest

- Cloud storage or syncing of any financial data to any external service
- Calling a specific LLM provider directly outside of `llm/client.py`
- Sending raw transaction rows, exact amounts, or merchant names to any LLM
- Paid APIs or services when a free alternative fits the current phase
- Skipping or weakening the guardrail layer for convenience
- Adding complexity that belongs to Phase 2 or 3 while Phase 1 is incomplete

---

## Design decisions log

Record significant decisions in decisions.md file so context is never lost between sessions.

---

## How to work with this codebase

- **Default language:** Python for all backend work unless specified otherwise.
- **Default to Phase 1 scope.** If a feature spans phases, build only what Phase 1 needs.
- **When in doubt about scope or architecture**, re-read this file.
- **Sub-folder `CLAUDE.md` files** cover layer-specific conventions (file layout, dependencies, test patterns). Read the relevant one before touching that layer.
- **If a request conflicts with a locked decision**, flag it explicitly and ask before proceeding. Do not silently comply.
