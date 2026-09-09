from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.db import get_db
from app.core.security import hash_password
from app.api.deps import require_admin
from app.models.user import User
from app.schemas.user import UserOut, UserIn

router = APIRouter(prefix="/api/v1/users", tags=["users"])

@router.get("", response_model=list[UserOut])
def list_users(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return db.query(User).all()

@router.post("", response_model=UserOut)
def create_user(body: UserIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    if db.query(User).filter_by(username=body.username).first():
        raise HTTPException(409, "username taken")
    user = User(username=body.username, password_hash=hash_password(body.password), role=body.role, locale=body.locale)
    db.add(user); db.commit(); db.refresh(user)
    return user

@router.patch("/{user_id}", response_model=UserOut)
def update_user(user_id: int, body: dict, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if not user: raise HTTPException(404, "user not found")
    if "role" in body:
        if user.role == "admin" and body["role"] != "admin" and _admin_count(db) == 1:
            raise HTTPException(409, "cannot demote last admin")
        user.role = body["role"]
    if "locale" in body: user.locale = body["locale"]
    if "password" in body: user.password_hash = hash_password(body["password"])
    db.commit(); db.refresh(user)
    return user

def _admin_count(db: Session) -> int:
    return db.query(User).filter_by(role="admin").count()

@router.delete("/{user_id}")
def delete_user(user_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if not user: raise HTTPException(404, "user not found")
    if user.role == "admin" and _admin_count(db) == 1:
        raise HTTPException(409, "cannot delete last admin")
    db.delete(user); db.commit()
    return {"ok": True}
