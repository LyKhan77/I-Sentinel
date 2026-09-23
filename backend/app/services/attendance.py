"""Absensi: face event → match → AttendanceEvent, lalu agregasi harian.

Waktu disimpan tz-aware. Semua perbandingan dilakukan di timezone server
(WIB +07): ts_event dinormalisasi lewat _local() — SQLite mengembalikan naive
(zona lokal saat insert), Postgres mengembalikan aware UTC.
"""
import logging
from datetime import datetime, timedelta
from pathlib import Path

from app.core.config import settings
from app.models.attendance import AttendanceDay, AttendanceEvent
from app.models.employee import Employee
from app.services import face
from app.services.annotate import annotate_face_crop

logger = logging.getLogger(__name__)

LOCAL_TZ = datetime.now().astimezone().tzinfo  # tz server (WIB +07)
VALID_DIRECTIONS = {"entry", "exit"}


def _local(dt: datetime | None) -> datetime | None:
    """Normalisasi ke tz lokal server. Naive (SQLite) dianggap sudah lokal."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=LOCAL_TZ)
    return dt.astimezone(LOCAL_TZ)


def _shift_dt(shift, day, hhmm: str) -> datetime:
    return datetime(day.year, day.month, day.day, int(hhmm[:2]), int(hhmm[3:]), tzinfo=LOCAL_TZ)


def compute_status(shift, first_entry, last_exit, now: datetime | None = None):
    """(status, late_minutes, duration_min). Pure — input sudah tz lokal."""
    now = _local(now) or datetime.now(LOCAL_TZ)
    if first_entry is None:
        return "absent", None, None

    if last_exit is not None:
        duration = round((last_exit - first_entry).total_seconds() / 60)
        if shift is None:
            return "ontime", None, duration
        start = _shift_dt(shift, first_entry.date(), shift.start_time)
        late = max(0, int((first_entry - start).total_seconds() // 60) - shift.tolerance_min)
        return ("late" if late > 0 else "ontime"), late, duration

    if shift is None:
        return "waiting", None, None
    end_grace = _shift_dt(shift, first_entry.date(), shift.end_time) + timedelta(
        minutes=settings.no_exit_grace_min
    )
    return ("waiting" if now < end_grace else "no_exit"), None, None


def recompute_day(db, employee_id: int, day, now: datetime | None = None) -> AttendanceDay:
    """Hitung ulang AttendanceDay dari AttendanceEvent hari itu. Upsert; override_note dipertahankan."""
    emp = db.get(Employee, employee_id)
    # ponytail: filter tanggal di Python, bukan SQL — SQLite menyimpan datetime tanpa
    # tz sehingga range query lintas-dialect rapuh. Event per karyawan kecil; 
    # pindahkan ke WHERE employee_id+ts_event kalau volume absensi membesar.
    entries: list[datetime] = []
    exits: list[datetime] = []
    for r in db.query(AttendanceEvent).filter(AttendanceEvent.employee_id == employee_id).all():
        ts = _local(r.ts_event)
        if ts.date() != day:
            continue
        if r.direction == "entry":
            entries.append(ts)
        elif r.direction == "exit":
            exits.append(ts)
    first_entry = min(entries) if entries else None
    last_exit = max(exits) if exits else None

    status, late, duration = compute_status(emp.shift if emp else None, first_entry, last_exit, now)

    row = db.query(AttendanceDay).filter_by(employee_id=employee_id, date=day).first()
    if row is None:
        row = AttendanceDay(employee_id=employee_id, date=day)
        db.add(row)
    row.first_entry = first_entry
    row.last_exit = last_exit
    row.duration_min = duration
    row.status = status
    row.late_minutes = late
    db.commit()
    db.refresh(row)
    return row


def _save(db, event, payload: dict, result):
    """Reassign JSON payload for SQLAlchemy change tracking, then commit."""
    event.payload = payload
    db.commit()
    return result


def _in_cooldown(db, employee_id: int, direction: str, ts: datetime) -> bool:
    """Check both directions in time: node media can delay newer events."""
    window = timedelta(minutes=settings.attendance_cooldown_min)
    ts_local = _local(ts)
    rows = db.query(AttendanceEvent).filter(
        AttendanceEvent.employee_id == employee_id, AttendanceEvent.direction == direction)
    # ponytail: Python time comparison handles SQLite naive and Postgres aware timestamps;
    # add a DB time window only if per-employee attendance history grows large.
    return any(abs(_local(row.ts_event) - ts_local) <= window for row in rows)


def _entered_earlier_today(db, employee_id: int, ts: datetime) -> bool:
    """Sudah ada entry karyawan ini lebih awal di hari lokal yang sama. Entry yang lebih awal
    tapi tiba belakangan (antrean disk node) tetap dicatat supaya jam masuk benar."""
    ts_local = _local(ts)
    rows = db.query(AttendanceEvent).filter(
        AttendanceEvent.employee_id == employee_id, AttendanceEvent.direction == "entry")
    return any(_local(r.ts_event).date() == ts_local.date() and _local(r.ts_event) <= ts_local
               for r in rows)


def handle_face_event(db, event, embedding: list[float] | None = None) -> AttendanceEvent | None:
    """Match attendance event, discard embedding, then update attendance day.

    Exceptions propagate to events_consumer for rollback.
    """
    if event.type != "attendance":
        return None

    payload = dict(event.payload or {})
    # consumer memisahkan embedding sebelum ingest; pop tetap membersihkan payload lama
    embedding = payload.pop("embedding", None) or embedding
    crop = payload.get("crop_path")
    direction = payload.get("direction")
    if direction not in VALID_DIRECTIONS:
        logger.warning("attendance: direction %r tidak valid pada event %s — skip", direction, event.event_id)
        return _save(db, event, payload, None)

    if embedding:
        res = face.match_vector(embedding, payload.get("face_quality"))
    elif crop:
        res = face.match_crop(db, str(Path(settings.storage_root) / crop))
    else:
        logger.info("attendance: event %s tanpa embedding dan crop — skip", event.event_id)
        return _save(db, event, payload, None)

    if res.employee_id is None:
        payload["employee_id"] = None
        payload["match_reason"] = res.reason
        logger.info("attendance: event %s tidak cocok (%s)", event.event_id, res.reason)
        return _save(db, event, payload, None)

    emp = db.get(Employee, res.employee_id)
    payload["employee_id"] = res.employee_id
    payload["employee_name"] = emp.name if emp is not None else None
    payload["face_score"] = res.score
    if emp is not None and crop:
        annotate_face_crop(str(Path(settings.storage_root) / crop),
                           emp.name, res.score or 0.0, payload.get("face_bbox"))

    if _in_cooldown(db, res.employee_id, direction, event.ts_event):
        payload["match_reason"] = "cooldown"
        return _save(db, event, payload, None)

    if direction == "entry" and _entered_earlier_today(db, res.employee_id, event.ts_event):
        payload["match_reason"] = "already_in"  # entry sekali per hari; exit boleh berulang
        return _save(db, event, payload, None)

    payload["match_reason"] = "matched"
    row = AttendanceEvent(
        employee_id=res.employee_id,
        camera_id=event.camera_id,
        zone_id=event.zone_id,
        direction=direction,
        ts_event=event.ts_event,
        match_score=res.score,
        snapshot_path=crop,
        event_id=event.event_id,
    )
    db.add(row)
    _save(db, event, payload, None)
    db.refresh(row)
    recompute_day(db, res.employee_id, _local(event.ts_event).date())
    return row


def close_days(db, day, now: datetime | None = None) -> int:
    """Recompute semua karyawan aktif dengan shift pada hari kerja `day`. Tanpa event → absent."""
    n = 0
    for emp in db.query(Employee).filter(Employee.active.is_(True)).all():
        shift = emp.shift
        if shift is None or day.isoweekday() not in (shift.workdays or []):
            continue
        recompute_day(db, emp.id, day, now=now)
        n += 1
    return n
