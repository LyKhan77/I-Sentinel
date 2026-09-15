"""Absensi API: list harian, export/import CSV, override manual, close-days (internal).

Catatan: `date`/`from`/`to` di query diberi alias karena `date` menutupi tipe bawaan.
"""
import csv
import io
from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin
from app.core.config import settings
from app.core.db import get_db
from app.models.attendance import AttendanceDay
from app.models.employee import Employee
from app.services import attendance
from app.services.attendance import LOCAL_TZ

router = APIRouter(tags=["attendance"])

CSV_COLUMNS = ["employee_code", "name", "date", "shift", "first_entry", "last_exit",
               "duration_min", "status", "late_minutes", "override_note"]
VALID_STATUSES = {"ontime", "late", "waiting", "no_exit", "absent"}


class AttendancePatch(BaseModel):
    first_entry: datetime | None = None
    last_exit: datetime | None = None
    status: str | None = None
    override_note: str | None = None


class CloseDaysIn(BaseModel):
    # field bernama `date` menutupi tipe `date` di body class → pakai alias
    day: date | None = Field(None, alias="date")


def _hhmmss(dt) -> str:
    local = attendance._local(dt)
    return local.strftime("%H:%M:%S") if local else ""


def _parse_time(day: date, raw: str | None):
    """Combine tanggal + 'HH:MM[:SS]' lokal. None/kosong → None; invalid → ValueError."""
    if raw is None or not raw.strip():
        return None
    t = time.fromisoformat(raw.strip())
    return datetime.combine(day, t, tzinfo=LOCAL_TZ)


def _csv_safe(value):
    """Prefix apostrof kalau cell mulai =,+,-,@ (formula injection)."""
    s = value if isinstance(value, str) else ("" if value is None else str(value))
    return f"'{s}" if s[:1] in ("=", "+", "-", "@") else s


def _row_dict(day: AttendanceDay, emp: Employee) -> dict:
    return {
        "id": day.id,
        "employee_id": day.employee_id,
        "employee_code": emp.employee_code if emp else None,
        "name": emp.name if emp else None,
        "date": day.date.isoformat(),
        "first_entry": _hhmmss(day.first_entry),
        "last_exit": _hhmmss(day.last_exit),
        "duration_min": day.duration_min,
        "status": day.status,
        "late_minutes": day.late_minutes,
        "override_note": day.override_note,
        "shift_name": emp.shift_name if emp else None,
    }


def _query_days(db: Session, date_: date | None, from_: date | None, to: date | None, employee_id: int | None):
    q = (db.query(AttendanceDay, Employee)
         .join(Employee, Employee.id == AttendanceDay.employee_id))
    if date_ is not None:
        q = q.filter(AttendanceDay.date == date_)
    if from_ is not None:
        q = q.filter(AttendanceDay.date >= from_)
    if to is not None:
        q = q.filter(AttendanceDay.date <= to)
    if employee_id is not None:
        q = q.filter(AttendanceDay.employee_id == employee_id)
    return q.order_by(AttendanceDay.date, Employee.employee_code).all()


@router.get("/api/v1/attendance")
def list_attendance(
    date_: date | None = Query(None, alias="date"),
    from_: date | None = Query(None, alias="from"),
    to: date | None = Query(None, alias="to"),
    employee_id: int | None = None,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if date_ is None and from_ is None and to is None:
        date_ = datetime.now(LOCAL_TZ).date()
    return [_row_dict(day, emp) for day, emp in _query_days(db, date_, from_, to, employee_id)]


@router.get("/api/v1/attendance/rekap.csv")
def export_csv(
    from_: date | None = Query(None, alias="from"),
    to: date | None = Query(None, alias="to"),
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    today = datetime.now(LOCAL_TZ).date()
    from_, to = from_ or today, to or today
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(CSV_COLUMNS)
    for day, emp in _query_days(db, None, from_, to, None):
        w.writerow([
            emp.employee_code, _csv_safe(emp.name), day.date.isoformat(), emp.shift_name or "",
            _hhmmss(day.first_entry), _hhmmss(day.last_exit),
            day.duration_min if day.duration_min is not None else "",
            day.status,
            day.late_minutes if day.late_minutes is not None else "",
            _csv_safe(day.override_note or ""),
        ])
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="rekap_absensi_{from_}_{to}.csv"'},
    )


@router.post("/api/v1/attendance/import")
def import_csv(
    file: UploadFile = File(...),
    admin=Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Upsert AttendanceDay dari CSV (kolom sama dengan export). Set override_note='import'."""
    text = file.file.read().decode("utf-8-sig")
    updated = created = skipped = 0
    for rec in csv.DictReader(io.StringIO(text)):
        code = (rec.get("employee_code") or "").strip()
        raw_date = (rec.get("date") or "").strip()
        try:
            day = date.fromisoformat(raw_date)
        except ValueError:
            skipped += 1
            continue
        emp = db.query(Employee).filter(Employee.employee_code == code).first()
        if emp is None:
            skipped += 1
            continue

        try:
            first_entry = _parse_time(day, rec.get("first_entry"))
            last_exit = _parse_time(day, rec.get("last_exit"))
        except ValueError:
            # non-kosong tapi tak terparse: jangan sentuh DB, jangan timpa row valid
            skipped += 1
            continue
        status, late, duration = attendance.compute_status(emp.shift, first_entry, last_exit)

        row = db.query(AttendanceDay).filter_by(employee_id=emp.id, date=day).first()
        if row is None:
            row = AttendanceDay(employee_id=emp.id, date=day)
            db.add(row)
            created += 1
        else:
            updated += 1
        row.first_entry = first_entry
        row.last_exit = last_exit
        row.duration_min = duration
        row.status = status
        row.late_minutes = late
        row.override_note = "import"
    db.commit()
    return {"updated": updated, "created": created, "skipped": skipped}


@router.patch("/api/v1/attendance/{day_id}")
def patch_day(
    day_id: int,
    body: AttendancePatch,
    admin=Depends(require_admin),
    db: Session = Depends(get_db),
):
    row = db.get(AttendanceDay, day_id)
    if row is None:
        raise HTTPException(404, "attendance day not found")

    changes = body.model_dump(exclude_unset=True)
    note = changes.pop("override_note", None)
    if changes and not note:
        raise HTTPException(422, "override_note required when changing attendance fields")
    if "status" in changes and changes["status"] not in VALID_STATUSES:
        raise HTTPException(422, f"status must be one of {sorted(VALID_STATUSES)}")
    if note is not None:
        row.override_note = note
    for k, v in changes.items():
        setattr(row, k, v)
    emp = db.get(Employee, row.employee_id)
    if "first_entry" in changes or "last_exit" in changes:
        # waktu override berubah → duration_min / late_minutes jangan stale (status tetap manual)
        _, late, duration = attendance.compute_status(
            emp.shift if emp else None,
            attendance._local(row.first_entry), attendance._local(row.last_exit),
        )
        row.late_minutes = late
        row.duration_min = duration
    db.commit()
    db.refresh(row)
    return _row_dict(row, emp)


@router.post("/internal/maintenance/close-days")
def close_days_endpoint(
    body: CloseDaysIn | None = None,
    authorization: str = Header(""),
    db: Session = Depends(get_db),
):
    if authorization != f"Bearer {settings.node_api_key}":
        raise HTTPException(401, "invalid node api key")
    day = (body.day if body and body.day else datetime.now(LOCAL_TZ).date() - timedelta(days=1))
    return {"closed": attendance.close_days(db, day)}
