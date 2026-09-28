import time
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.db import get_db
from app.core.security import verify_password, create_access_token, hash_password
from app.api.deps import COOKIE, get_current_user, set_auth_cookie
from app.models.user import User
from app.schemas.user import UserOut, LoginIn, PasswordChange

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

# ponytail: penghitung in-memory per proses. Cukup karena deployment ini satu
# worker uvicorn. Kalau nanti dijalankan multi-worker, pindah ke tabel DB atau
# Redis (sudah ada di host) — jangan pakai dict lagi.
_FAILURES: dict[tuple[str, str], list[float]] = {}


def _client_key(username: str, request: Request) -> tuple[str, str]:
    ip = request.client.host if request.client else "?"
    return (username.strip().lower(), ip)


def _check_lock(key: tuple[str, str]) -> None:
    window = settings.login_lockout_min * 60
    now = time.monotonic()
    hits = [t for t in _FAILURES.get(key, []) if now - t < window]
    _FAILURES[key] = hits
    if len(hits) >= settings.login_max_attempts:
        retry = int(window - (now - hits[0])) + 1
        raise HTTPException(
            status_code=429,
            detail="too many failed login attempts",
            headers={"Retry-After": str(retry)},
        )

def _login(user: User, response: Response) -> dict:
    token = create_access_token(user.id, user.role, user.token_version)
    # secure=True: browser only sends over HTTPS; also keeps httpx test client from
    # auto-replaying the cookie on unauthenticated requests
    set_auth_cookie(response, token)
    return {"token": token, "user": UserOut.model_validate(user)}

@router.post("/login")
def login(body: LoginIn, response: Response, request: Request, db: Session = Depends(get_db)):
    key = _client_key(body.username, request)
    _check_lock(key)
    user = db.query(User).filter_by(username=body.username).first()
    # bcrypt raises on >72-byte passwords; 401 (not 422) here — client sent wrong creds
    if not user or len(body.password.encode()) > 72 or not verify_password(body.password, user.password_hash):
        _FAILURES.setdefault(key, []).append(time.monotonic())
        raise HTTPException(401, "invalid credentials")
    if not user.is_active:
        # hanya pemegang password benar yang tahu akunnya nonaktif
        raise HTTPException(403, "account disabled")
    _FAILURES.pop(key, None)
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    return _login(user, response)

@router.post("/logout")
def logout(response: Response, user: User = Depends(get_current_user)):
    response.delete_cookie(COOKIE)
    return {}

@router.post("/change-password")
def change_password(body: PasswordChange, request: Request, response: Response,
                    user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    key = _client_key(user.username, request)
    _check_lock(key)  # tebakan password lama ikut batas percobaan login
    if len(body.current_password.encode()) > 72 or not verify_password(body.current_password, user.password_hash):
        _FAILURES.setdefault(key, []).append(time.monotonic())
        raise HTTPException(400, "current password is incorrect")  # bukan 401: jangan lempar ke /login
    user.password_hash = hash_password(body.new_password)
    user.token_version += 1  # perangkat lain keluar
    db.commit()
    # ditulis setelah cookie perpanjangan dari get_current_user (bila ada) → yang terakhir menang
    set_auth_cookie(response, create_access_token(user.id, user.role, user.token_version))
    return {"ok": True}

@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user

@router.patch("/me", response_model=UserOut)
def update_me(body: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    locale = body.get("locale")
    if locale is not None: user.locale = locale
    db.commit(); db.refresh(user)
    return user
