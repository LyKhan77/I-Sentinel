from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request, Response
from app.core.config import settings
from app.core.db import get_db
from app.core.security import create_access_token, decode_token
from app.models.user import User

COOKIE = "isentinel_token"

def _token_from(request: Request) -> str | None:
    # cookie first (httpOnly), Authorization Bearer fallback
    if request.cookies.get(COOKIE): return request.cookies[COOKIE]
    h = request.headers.get("Authorization", "")
    return h[7:] if h.startswith("Bearer ") else None

def set_auth_cookie(response: Response, token: str) -> None:
    """Cookie sesi httpOnly (dipakai login dan perpanjangan sesi)."""
    response.set_cookie(COOKIE, token, httponly=True, samesite="lax", secure=settings.cookie_secure)

def get_current_user(request: Request, response: Response, db=Depends(get_db)) -> User:
    tok = _token_from(request)
    payload = decode_token(tok) if tok else None
    if not payload: raise HTTPException(401, "not authenticated")
    user = db.get(User, int(payload["sub"]))
    if not user: raise HTTPException(401, "user gone")
    if not user.is_active: raise HTTPException(401, "account disabled")
    # token tanpa klaim tv (terbit sebelum 0018) = versi 0 → tidak ada logout massal saat deploy
    if payload.get("tv", 0) != user.token_version: raise HTTPException(401, "session revoked")
    # Sesi bergulir: token cookie yang lewat separuh umurnya diganti baru, jadi layar TV yang
    # terus me-refresh tidak pernah logout. Bearer (skrip/API) tidak diubah.
    remaining_s = payload["exp"] - datetime.now(timezone.utc).timestamp()
    if request.cookies.get(COOKIE) == tok and remaining_s < settings.access_token_expire_min * 30:
        set_auth_cookie(response, create_access_token(user.id, user.role, user.token_version))
    return user

def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin": raise HTTPException(403, "admin only")
    return user
