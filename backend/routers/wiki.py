import sqlite3
from pathlib import Path

from fastapi import APIRouter, Depends

from db.queries import User
from llm.client import LLMClient
from wiki.wiki_manager import WikiManager
from routers.dependencies import get_db, get_user

router = APIRouter(prefix="/wiki", tags=["wiki"])

_DATA_DIR = Path(__file__).parent.parent.parent / "data"


def get_wiki_manager(user: User = Depends(get_user)) -> WikiManager:
    llm = LLMClient()
    current_path = _DATA_DIR / user.name / "finance_current_month.md"
    archive_path = _DATA_DIR / user.name / "finance_archive.md"
    return WikiManager(llm, current_path, archive_path)


@router.post("/refresh")
def refresh_wiki(
    user: User = Depends(get_user),
    conn: sqlite3.Connection = Depends(get_db),
    wiki: WikiManager = Depends(get_wiki_manager),
) -> dict[str, str]:
    """Regenerate finance_current_month.md from approved DB transactions.

    Call manually or via nightly cron:
      0 2 * * * curl -s -X POST "http://localhost:8000/wiki/refresh?user_id=1"
    """
    wiki.refresh_current_month(conn, user.id)
    return {"status": "ok"}

