from fastapi import Request, HTTPException


def get_user_id(request: Request) -> str:
    user_id = request.headers.get("X-User-ID")
    if not user_id:
        raise HTTPException(status_code=401, detail="X-User-ID header required")
    return user_id.strip()
