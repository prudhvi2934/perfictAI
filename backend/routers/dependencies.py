import sqlite3
from typing import Generator

from fastapi import Depends, HTTPException, Query

from db.queries import User, get_user_by_id
from db.schema import get_connection


def get_db() -> Generator[sqlite3.Connection, None, None]:
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


def get_user(
    user_id: int = Query(..., description="User ID"),
    conn: sqlite3.Connection = Depends(get_db),
) -> User:
    user = get_user_by_id(conn, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found")
    return user
