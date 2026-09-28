from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.db import get_db
from app.core.security import hash_password
from app.api.deps import require_admin
from app.models.user import User
from app.schemas.user import UserOut, UserIn, UserPatch

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

def _active_admins(db: Session) -> int:
    return db.query(User).filter_by(role="admin", is_active=True).count()

def _is_last_active_admin(db: Session, user: User) -> bool:
    return user.role == "admin" and user.is_active and _active_admins(db) == 1

@router.patch("/{user_id}", response_model=UserOut)
def update_user(user_id: int, body: UserPatch, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if not user: raise HTTPException(404, "user not found")
    is_self = user.id == admin.id
    if body.role is not None and body.role != user.role:
        if is_self: raise HTTPException(409, "cannot change your own role")
        if _is_last_active_admin(db, user): raise HTTPException(409, "cannot demote last admin")
        user.role = body.role
    if body.is_active is not None and body.is_active != user.is_active:
        if not body.is_active:
            if is_self: raise HTTPException(409, "cannot deactivate yourself")
            if _is_last_active_admin(db, user): raise HTTPException(409, "cannot deactivate last admin")
            user.token_version += 1  # sesi yang sedang aktif langsung ditolak
        user.is_active = body.is_active
    if body.locale is not None:
        user.locale = body.locale
    if body.password is not None:
        user.password_hash = hash_password(body.password)
        user.token_version += 1  # reset password mengeluarkan semua sesi user ini
    db.commit(); db.refresh(user)
    return user

@router.delete("/{user_id}")
def delete_user(user_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if not user: raise HTTPException(404, "user not found")
    if user.id == admin.id: raise HTTPException(409, "cannot delete yourself")
    if _is_last_active_admin(db, user): raise HTTPException(409, "cannot delete last admin")
    db.delete(user); db.commit()
    return {"ok": True}
