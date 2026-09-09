from fastapi import Depends, HTTPException, Request
from app.core.db import get_db
from app.core.security import decode_token
from app.models.user import User

COOKIE = "isentinel_token"

def _token_from(request: Request) -> str | None:
    # cookie first (httpOnly), Authorization Bearer fallback
    if request.cookies.get(COOKIE): return request.cookies[COOKIE]
    h = request.headers.get("Authorization", "")
    return h[7:] if h.startswith("Bearer ") else None

def get_current_user(request: Request, db=Depends(get_db)) -> User:
    tok = _token_from(request)
    payload = decode_token(tok) if tok else None
    if not payload: raise HTTPException(401, "not authenticated")
    user = db.get(User, int(payload["sub"]))
    if not user: raise HTTPException(401, "user gone")
    return user

def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin": raise HTTPException(403, "admin only")
    return user
