from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.db import get_db
from app.api.deps import get_current_user, require_admin
from app.models.shift import Shift
from app.models.employee import Employee
from app.schemas.employee import ShiftIn, ShiftPatch, ShiftOut

router = APIRouter(prefix="/api/v1/shifts", tags=["shifts"])


def _dup_name(db: Session, name: str, exclude_id: int | None = None) -> bool:
    q = db.query(Shift).filter(Shift.name == name)
    if exclude_id is not None:
        q = q.filter(Shift.id != exclude_id)
    return db.query(q.exists()).scalar()


@router.get("", response_model=list[ShiftOut])
def list_shifts(user=Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(Shift).all()


@router.post("", response_model=ShiftOut)
def create_shift(body: ShiftIn, admin=Depends(require_admin), db: Session = Depends(get_db)):
    if _dup_name(db, body.name):
        raise HTTPException(409, "shift name already exists")
    shift = Shift(**body.model_dump())
    db.add(shift); db.commit(); db.refresh(shift)
    return shift


@router.get("/{shift_id}", response_model=ShiftOut)
def get_shift(shift_id: int, user=Depends(get_current_user), db: Session = Depends(get_db)):
    shift = db.get(Shift, shift_id)
    if not shift: raise HTTPException(404, "shift not found")
    return shift


@router.patch("/{shift_id}", response_model=ShiftOut)
def update_shift(shift_id: int, body: ShiftPatch, admin=Depends(require_admin), db: Session = Depends(get_db)):
    shift = db.get(Shift, shift_id)
    if not shift: raise HTTPException(404, "shift not found")
    changes = body.model_dump(exclude_unset=True)
    if "name" in changes and _dup_name(db, changes["name"], exclude_id=shift_id):
        raise HTTPException(409, "shift name already exists")
    for k, v in changes.items():
        setattr(shift, k, v)
    db.commit(); db.refresh(shift)
    return shift


@router.delete("/{shift_id}")
def delete_shift(shift_id: int, admin=Depends(require_admin), db: Session = Depends(get_db)):
    shift = db.get(Shift, shift_id)
    if not shift: raise HTTPException(404, "shift not found")
    if db.query(Employee).filter(Employee.shift_id == shift_id).first():
        raise HTTPException(409, "shift in use by employees")
    db.delete(shift); db.commit()
    return {"ok": True}
