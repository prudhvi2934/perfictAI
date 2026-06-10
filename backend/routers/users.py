import sqlite3
from typing import Generator

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from db.queries import get_all_users
from db.schema import get_connection

router = APIRouter(prefix="/users", tags=["users"])


class UserOut(BaseModel):
    id: int
    name: str


def get_db() -> Generator[sqlite3.Connection, None, None]:
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


@router.get("", response_model=list[UserOut])
def list_users(conn: sqlite3.Connection = Depends(get_db)) -> list[UserOut]:
    return [UserOut(id=u.id, name=u.name) for u in get_all_users(conn)]
