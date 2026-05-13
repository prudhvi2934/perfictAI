import sqlite3
from pathlib import Path
from typing import Generator

from fastapi import APIRouter, Depends

from db.schema import get_connection
from llm.client import LLMClient
from wiki.wiki_manager import WikiManager
from routers.dependencies import get_user_id

router = APIRouter(prefix="/wiki", tags=["wiki"])

_DATA_DIR = Path(__file__).parent.parent.parent / "data"


def get_db() -> Generator[sqlite3.Connection, None, None]:
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


def get_wiki_manager(user_id: str = Depends(get_user_id)) -> WikiManager:
    llm = LLMClient()
    current_path = _DATA_DIR / user_id / "finance_current_month.md"
    archive_path = _DATA_DIR / user_id / "finance_archive.md"
    return WikiManager(llm, current_path, archive_path)


@router.post("/refresh")
def refresh_wiki(
    user_id: str = Depends(get_user_id),
    conn: sqlite3.Connection = Depends(get_db),
    wiki: WikiManager = Depends(get_wiki_manager),
) -> dict[str, str]:
    """Regenerate finance_current_month.md from approved DB transactions.

    Call manually or via nightly cron:
      0 2 * * * curl -s -H "X-User-ID: alice" -X POST http://localhost:8000/wiki/refresh
    """
    wiki.refresh_current_month(conn, user_id)
    return {"status": "ok"}

