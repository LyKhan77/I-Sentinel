import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.db import get_db
from app.api.deps import get_current_user, require_admin
from app.models.attendance import AttendanceEvent, AttendanceDay
from app.models.employee import Employee
from app.models.face_embedding import FaceEmbedding
from app.models.shift import Shift
from app.schemas.employee import EmployeeIn, EmployeePatch, EmployeeOut
from app.services import face

router = APIRouter(prefix="/api/v1/employees", tags=["employees"])


def _dup_code(db: Session, code: str, exclude_id: int | None = None) -> bool:
    q = db.query(Employee).filter(Employee.employee_code == code)
    if exclude_id is not None:
        q = q.filter(Employee.id != exclude_id)
    return db.query(q.exists()).scalar()


def _check_shift(db: Session, shift_id: int | None) -> None:
    if shift_id is not None and not db.get(Shift, shift_id):
        raise HTTPException(404, "shift not found")


@router.get("", response_model=list[EmployeeOut])
def list_employees(active: bool | None = None, user=Depends(get_current_user), db: Session = Depends(get_db)):
    q = db.query(Employee)
    if active is not None:
        q = q.filter(Employee.active == active)
    return q.all()


@router.post("", response_model=EmployeeOut)
def create_employee(body: EmployeeIn, admin=Depends(require_admin), db: Session = Depends(get_db)):
    if _dup_code(db, body.employee_code):
        raise HTTPException(409, "employee_code already exists")
    _check_shift(db, body.shift_id)
    emp = Employee(**body.model_dump())
    db.add(emp); db.commit(); db.refresh(emp)
    return emp


@router.get("/{employee_id}", response_model=EmployeeOut)
def get_employee(employee_id: int, user=Depends(get_current_user), db: Session = Depends(get_db)):
    emp = db.get(Employee, employee_id)
    if not emp: raise HTTPException(404, "employee not found")
    return emp


@router.patch("/{employee_id}", response_model=EmployeeOut)
def update_employee(employee_id: int, body: EmployeePatch, admin=Depends(require_admin), db: Session = Depends(get_db)):
    emp = db.get(Employee, employee_id)
    if not emp: raise HTTPException(404, "employee not found")
    # shift_id boleh null (lepas shift); kolom lain NOT NULL → null eksplisit diabaikan
    changes = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None or k == "shift_id"}
    if "employee_code" in changes and _dup_code(db, changes["employee_code"], exclude_id=employee_id):
        raise HTTPException(409, "employee_code already exists")
    if "shift_id" in changes:
        _check_shift(db, changes["shift_id"])
    for k, v in changes.items():
        setattr(emp, k, v)
    db.commit(); db.refresh(emp)
    return emp


@router.delete("/{employee_id}")
def delete_employee(employee_id: int, admin=Depends(require_admin), db: Session = Depends(get_db)):
    emp = db.get(Employee, employee_id)
    if not emp: raise HTTPException(404, "employee not found")
    if (db.query(AttendanceEvent).filter(AttendanceEvent.employee_id == employee_id).first()
            or db.query(AttendanceDay).filter(AttendanceDay.employee_id == employee_id).first()):
        raise HTTPException(409, "employee has attendance records; deactivate instead")
    db.query(FaceEmbedding).filter(FaceEmbedding.employee_id == employee_id).delete(synchronize_session=False)
    db.delete(emp); db.commit()
    shutil.rmtree(Path(settings.storage_root) / "faces" / str(employee_id), ignore_errors=True)
    face.refresh_gallery(db)
    return {"ok": True}
