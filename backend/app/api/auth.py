from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.db import get_db
from app.core.security import verify_password, create_access_token
from app.api.deps import COOKIE, get_current_user
from app.models.user import User
from app.schemas.user import UserOut, LoginIn

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

def _login(user: User, response: Response) -> dict:
    token = create_access_token(user.id, user.role)
    # secure=True: browser only sends over HTTPS; also keeps httpx test client from
    # auto-replaying the cookie on unauthenticated requests
    response.set_cookie(COOKIE, token, httponly=True, samesite="lax", secure=settings.cookie_secure)
    return {"token": token, "user": UserOut.model_validate(user)}

@router.post("/login")
def login(body: LoginIn, response: Response, db: Session = Depends(get_db)):
    user = db.query(User).filter_by(username=body.username).first()
    # bcrypt raises on >72-byte passwords; 401 (not 422) here — client sent wrong creds
    if not user or len(body.password.encode()) > 72 or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "invalid credentials")
    return _login(user, response)

@router.post("/logout")
def logout(response: Response, user: User = Depends(get_current_user)):
    response.delete_cookie(COOKIE)
    return {}

@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user

@router.patch("/me", response_model=UserOut)
def update_me(body: dict, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    locale = body.get("locale")
    if locale is not None: user.locale = locale
    db.commit(); db.refresh(user)
    return user
