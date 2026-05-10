# PerfictAI — Personal Finance AI

A local-first, AI-powered personal finance assistant. Ingests bank alert emails,
classifies transactions, and visualises spending patterns.
All data stays on your machine.

## Project structure

```
/
├── backend/        Python / FastAPI — email parsing, DB, LLM, API
├── frontend/       React / Vite — transaction review UI
└── data/           Runtime artifacts (finance.db, finance.md wiki)
```

## Running the project

You need two terminals running at the same time.

### Terminal 1 — Backend

```bash
cd backend
source .venv/bin/activate   # activate the Python virtual environment
uvicorn main:app --reload   # starts FastAPI on http://localhost:8000
```

> First time setup — create the virtual environment and install dependencies:
> ```bash
> cd backend
> uv sync
> ```

### Terminal 2 — Frontend

```bash
cd frontend
npm install    # only needed the first time
npm run dev    # starts Vite dev server on http://localhost:5173
```

Then open **http://localhost:5173** in your browser.

The backend must be running before you open the frontend — the UI calls the API
on every page load.

## API docs

FastAPI generates interactive docs automatically. With the backend running, visit:

- **http://localhost:8000/docs** — Swagger UI (try endpoints in the browser)
- **http://localhost:8000/redoc** — ReDoc (cleaner read-only view)

## Tech stack

| Layer | Technology |
|---|---|
| Backend | Python, FastAPI, SQLite |
| Frontend | React, Vite |
| LLM | Gemini (via model-agnostic `LLMClient`) |
| Email source | Gmail API |
