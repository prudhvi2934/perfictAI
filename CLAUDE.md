# CLAUDE.md — Backend

> Root `CLAUDE.md` covers project scope and architecture. This file covers backend development standards only.

---

## Environment

- **Python 3.11+** managed with **uv**
- **FastAPI** + **Uvicorn**

---

## Folder layout

```
backend/
├── main.py
├── pyproject.toml
├── llm/
│   └── client.py
├── guardrails/
│   └── sanitiser.py
├── email_parser/
│   └── parser.py
├── db/
│   ├── schema.py
│   └── queries.py
├── wiki/
│   └── manager.py
└── routers/
    ├── transactions.py
    ├── dashboard.py
    └── chat.py
```

---

## Code style

- Follow **PEP 8**. Use **Ruff** for linting and formatting (`uv add --dev ruff`).
- Type-hint every function — arguments and return types.
- Prefer explicit over implicit. No clever one-liners that sacrifice readability.
- Keep functions small and single-purpose. If it needs a comment to explain what it does, split it.
- Use `dataclasses` or **Pydantic models** for structured data — no raw dicts passed between layers.

---

## Project conventions

**Routers**
- One file per domain in `routers/`. Register all routers in `main.py`.
- Routers handle HTTP only — no business logic inside them. Delegate to a service or module.

**Database**
- No ORM. Use the stdlib `sqlite3` module directly.
- All SQL statements live in `db/queries.py`. No inline SQL anywhere else.
- Schema defined in `db/schema.py`. Use `IF NOT EXISTS` on all `CREATE TABLE` statements.

**Dependencies**
- Inject shared resources (DB connection, `LLMClient`) via FastAPI `Depends()`.
- Never instantiate shared resources inside a route handler.

**Error handling**
- Raise `HTTPException` at the router layer only.
- Use Python built-in exceptions (`ValueError`, `RuntimeError`, etc.) inside service/module code.
- Never silently swallow exceptions. Log and re-raise or convert.

**Logging**
- Use the stdlib `logging` module. Configure once in `main.py`.
- No `print()` statements in production code paths.

---

## Testing

- Use **pytest**. One test file per module: `test_<module>.py`.
- Test pure logic with unit tests. Test endpoints with FastAPI `TestClient`.
- Aim for behaviour coverage, not line coverage — test what the function is supposed to do.

---

## Dependencies

- Keep `pyproject.toml` clean. Add a dependency only when stdlib cannot do the job.
- Pin versions in `pyproject.toml`. Lock file (`uv.lock`) is committed to version control.
