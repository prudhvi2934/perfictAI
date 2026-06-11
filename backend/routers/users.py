import sqlite3

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from db.queries import get_all_users
from routers.dependencies import get_db

router = APIRouter(prefix="/users", tags=["users"])


class UserOut(BaseModel):
    id: int
    name: str


@router.get("", response_model=list[UserOut])
def list_users(conn: sqlite3.Connection = Depends(get_db)) -> list[UserOut]:
    return [UserOut(id=u.id, name=u.name) for u in get_all_users(conn)]
