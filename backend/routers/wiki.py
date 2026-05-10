import sqlite3
from pathlib import Path
from typing import Generator

from fastapi import APIRouter, Depends

from db.schema import get_connection
from llm.client import LLMClient
from wiki.wiki_manager import WikiManager

router = APIRouter(prefix="/wiki", tags=["wiki"])

_DATA_DIR = Path(__file__).parent.parent.parent / "data"
_CURRENT_WIKI_PATH = _DATA_DIR / "finance_current_month.md"
_ARCHIVE_WIKI_PATH = _DATA_DIR / "finance_archive.md"


def get_db() -> Generator[sqlite3.Connection, None, None]:
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


def get_wiki_manager() -> WikiManager:
    llm = LLMClient()
    return WikiManager(llm, _CURRENT_WIKI_PATH, _ARCHIVE_WIKI_PATH)


@router.post("/refresh")
def refresh_wiki(
    conn: sqlite3.Connection = Depends(get_db),
    wiki: WikiManager = Depends(get_wiki_manager),
) -> dict[str, str]:
    """Regenerate finance_current_month.md from approved DB transactions.

    Call manually or via nightly cron:
      0 2 * * * curl -s -X POST http://localhost:8000/wiki/refresh
    """
    wiki.refresh_current_month(conn)
    return {"status": "ok"}
