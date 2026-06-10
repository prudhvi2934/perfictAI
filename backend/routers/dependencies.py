from fastapi import Depends, HTTPException, Query

from db.queries import User, get_user_by_id
from db.schema import get_connection


def get_user(user_id: int = Query(..., description="User ID")) -> User:
    conn = get_connection()
    user = get_user_by_id(conn, user_id)
    conn.close()
    if user is None:
        raise HTTPException(status_code=404, detail=f"User {user_id} not found")
    return user
