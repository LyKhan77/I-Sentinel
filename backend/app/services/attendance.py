"""Absensi: face event → match → AttendanceEvent, lalu agregasi harian.

Waktu disimpan tz-aware. Semua perbandingan dilakukan di timezone server
(WIB +07): ts_event dinormalisasi lewat _local() — SQLite mengembalikan naive
(zona lokal saat insert), Postgres mengembalikan aware UTC.
"""
import logging
import threading
from datetime import datetime, timedelta
from pathlib import Path

from app.core.config import settings
from app.core.db import SessionLocal
from app.models.attendance import AttendanceDay, AttendanceEvent
from app.models.employee import Employee
from app.models.event import Event
from app.models.zone import Zone
from app.services import face
from app.services.annotate import ORANGE, annotate_face_crop, annotate_snapshot

logger = logging.getLogger(__name__)

LOCAL_TZ = datetime.now().astimezone().tzinfo  # tz server (WIB +07)
VALID_DIRECTIONS = {"entry", "exit"}
CLOSE_INTERVAL_S = 900
CLOSE_DAYS_BACK = 7
EXIT_EARLY_MIN = 60


def _local(dt: datetime | None) -> datetime | None:
    """Normalisasi ke tz lokal server. Naive (SQLite) dianggap sudah lokal."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=LOCAL_TZ)
    return dt.astimezone(LOCAL_TZ)


def _shift_dt(shift, day, hhmm: str) -> datetime:
    return datetime(day.year, day.month, day.day, int(hhmm[:2]), int(hhmm[3:]), tzinfo=LOCAL_TZ)


def deadline(shift, day) -> datetime:
    """Batas penutupan hari: jam shift selesai + toleransi no_exit (tz lokal)."""
    return _shift_dt(shift, day, shift.end_time) + timedelta(minutes=settings.no_exit_grace_min)


def compute_status(shift, first_entry, last_exit, now: datetime | None = None):
    """(status, late_minutes, duration_min). Pure — input sudah tz lokal."""
    now = _local(now) or datetime.now(LOCAL_TZ)
    if first_entry is None:
        # hanya exit terdeteksi: orangnya hadir tapi entry terlewat → perlu koreksi, bukan absent
        return ("no_entry" if last_exit is not None else "absent"), None, None

    if last_exit is not None:
        duration = round((last_exit - first_entry).total_seconds() / 60)
        if shift is None:
            return "ontime", None, duration
        start = _shift_dt(shift, first_entry.date(), shift.start_time)
        late = max(0, int((first_entry - start).total_seconds() // 60) - shift.tolerance_min)
        return ("late" if late > 0 else "ontime"), late, duration

    if shift is None:
        return "waiting", None, None
    return ("waiting" if now < deadline(shift, first_entry.date()) else "no_exit"), None, None


def effective_status(row, shift, now: datetime | None = None) -> str:
    """Status untuk ditampilkan: `waiting` yang sudah lewat batas → `no_exit` walau job belum jalan.
    Baris yang dikoreksi manual (override_note) dan karyawan tanpa shift tidak diubah."""
    if row.status != "waiting" or (row.override_note or "").strip() or shift is None:
        return row.status
    now = _local(now) or datetime.now(LOCAL_TZ)
    return "no_exit" if now >= deadline(shift, row.date) else "waiting"


def exit_early_min(row, shift, now: datetime | None = None) -> int | None:
    """Menit antara exit terakhir dan jam shift selesai pada baris `ontime`/`late` yang pulangnya
    lebih dari `EXIT_EARLY_MIN` menit awal; selain itu None.

    Dihitung saat baca seperti `effective_status` — status tersimpan tidak pernah diubah. None untuk
    baris ber-`override_note` (sudah diputuskan manusia, termasuk hasil impor), karyawan tanpa shift,
    dan hari yang jam shift-nya belum lewat (exit makan siang di hari berjalan bukan anomali).
    Exit terakhir bisa saja sore yang tidak terlintas kamera, bukan pulang awal.
    """
    if shift is None or row.last_exit is None or row.status not in ("ontime", "late"):
        return None
    if (row.override_note or "").strip():
        return None
    end = _shift_dt(shift, row.date, shift.end_time)
    if (_local(now) or datetime.now(LOCAL_TZ)) < end:
        return None
    gap = round((end - _local(row.last_exit)).total_seconds() / 60)
    return gap if gap > EXIT_EARLY_MIN else None


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


def _first_entry_today(db, employee_id: int, ts: datetime) -> datetime | None:
    """Return the first local-day entry at or before this event; late earlier entries remain recordable."""
    ts_local = _local(ts)
    rows = db.query(AttendanceEvent).filter(
        AttendanceEvent.employee_id == employee_id, AttendanceEvent.direction == "entry")
    # ponytail: normalize in Python for SQLite naive and Postgres aware timestamps.
    entries = [_local(r.ts_event) for r in rows]
    return min((t for t in entries if t.date() == ts_local.date() and t <= ts_local), default=None)


def _exit_between(db, employee_id: int, start: datetime, end: datetime) -> datetime | None:
    """Return the latest exit strictly after the first entry and no later than this event."""
    start, end = _local(start), _local(end)
    rows = db.query(AttendanceEvent).filter(
        AttendanceEvent.employee_id == employee_id, AttendanceEvent.direction == "exit")
    # ponytail: use local Python comparisons across database datetime dialects.
    exits = [_local(r.ts_event) for r in rows]
    return max((t for t in exits if start < t <= end), default=None)


def _record_on(db, zone_id: int | None) -> bool:
    """Default to recording attendance when zone data or the record flag is absent."""
    zone = db.get(Zone, zone_id) if zone_id is not None else None
    return zone.behavior_flag("attendance", "record") if zone is not None else True


def _seen_recently(db, event, employee_id: int, *, same_zone: bool, reason: str | None = None) -> bool:
    """Another attendance event of this employee within the cooldown window, in both time directions.

    `same_zone` limits the search to this event's zone; `reason` limits it to one `match_reason`.
    """
    ts = _local(event.ts_event)
    window = timedelta(minutes=settings.attendance_cooldown_min)
    rows = db.query(Event).filter(
        Event.id != event.id, Event.type == "attendance",
        Event.ts_event >= ts - timedelta(days=1), Event.ts_event <= ts + timedelta(days=1))
    if same_zone:
        rows = rows.filter(Event.zone_id == event.zone_id)
    # ponytail: a broad DB prefilter tolerates SQLite naive and Postgres aware times;
    # compare the exact window and the small payload set in Python.
    return any(
        (row.payload or {}).get("employee_id") == employee_id
        and (reason is None or (row.payload or {}).get("match_reason") == reason)
        and abs(_local(row.ts_event) - ts) <= window
        for row in rows)


def _label_snapshot(event, payload: dict, label: str, color=None) -> None:
    """Snapshot absensi diberi nama/Unknown setelah pencocokan (vision belum tahu identitas)."""
    if event.snapshot_path:
        kwargs = {"color": color} if color is not None else {}
        annotate_snapshot(str(Path(settings.storage_root) / event.snapshot_path), label,
                          payload.get("bbox_norm"), **kwargs)


def annotate_event_snapshot(event) -> None:
    """Label ulang snapshot absensi yang datang belakangan (topik media).

    handle_face_event jalan saat snapshot mungkin masih None (label no-op);
    label diambil dari payload yang ia simpan (employee_name / match_reason).
    """
    payload = event.payload or {}
    if payload.get("match_reason") == "no_match":
        _label_snapshot(event, payload, "Unknown", ORANGE)
    elif payload.get("employee_id") is not None:
        _label_snapshot(event, payload, payload.get("employee_name") or "Unknown")


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
        if res.reason == "no_match":
            _label_snapshot(event, payload, "Unknown", ORANGE)
        logger.info("attendance: event %s tidak cocok (%s)", event.event_id, res.reason)
        return _save(db, event, payload, None)

    emp = db.get(Employee, res.employee_id)
    payload["employee_id"] = res.employee_id
    payload["employee_name"] = emp.name if emp is not None else None
    payload["face_score"] = res.score
    _label_snapshot(event, payload, emp.name if emp is not None else "Unknown")
    if emp is not None and crop:
        annotate_face_crop(str(Path(settings.storage_root) / crop),
                           emp.name, res.score or 0.0, payload.get("face_bbox"))

    if not _record_on(db, event.zone_id):
        seen = _seen_recently(db, event, res.employee_id, same_zone=True, reason="detected")
        payload["match_reason"] = "cooldown" if seen else "detected"
        return _save(db, event, payload, None)

    if _in_cooldown(db, res.employee_id, direction, event.ts_event):
        payload["match_reason"] = "cooldown"
        return _save(db, event, payload, None)

    first_entry = _first_entry_today(db, res.employee_id, event.ts_event) if direction == "entry" else None
    if first_entry is not None:
        if _seen_recently(db, event, res.employee_id, same_zone=False):
            payload["match_reason"] = "cooldown"  # masih terlihat terus: bukan masuk ulang, tanpa evidence
            return _save(db, event, payload, None)
        payload["match_reason"] = "already_in"  # entry sekali per hari; exit boleh berulang
        payload["first_entry_ts"] = _local(first_entry).isoformat()
        exit_ts = _exit_between(db, res.employee_id, first_entry, event.ts_event)
        if exit_ts is not None:
            payload["exit_ts"] = _local(exit_ts).isoformat()
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
    """Recompute semua karyawan aktif dengan shift pada hari kerja `day`. Tanpa event → absent.
    Baris yang sudah dikoreksi manual (override_note) dilewati."""
    n = 0
    for emp in db.query(Employee).filter(Employee.active.is_(True)).all():
        shift = emp.shift
        if shift is None or day.isoweekday() not in (shift.workdays or []):
            continue
        row = db.query(AttendanceDay).filter_by(employee_id=emp.id, date=day).first()
        registered = _registered_on(emp)
        if (row is not None and _has_override(row)) or (row is None and registered and day < registered):
            continue
        recompute_day(db, emp.id, day, now=now)
        n += 1
    return n


def _has_override(row) -> bool:
    return bool((row.override_note or "").strip())


def _registered_on(emp) -> "date | None":
    """Tanggal lokal karyawan didaftarkan; hari sebelumnya tidak boleh dicatat "Tidak hadir"."""
    return _local(emp.created_at).date() if emp.created_at is not None else None


def close_due(db, now: datetime | None = None, days_back: int = CLOSE_DAYS_BACK) -> dict:
    """Tutup hari yang sudah lewat batas untuk karyawan aktif ber-shift di hari kerjanya:
    buat baris (absent / dari event) bila belum ada; hitung ulang `waiting`. Baris dikoreksi dilewati."""
    now = _local(now) or datetime.now(LOCAL_TZ)
    created = updated = 0
    emps = [e for e in db.query(Employee).filter(Employee.active.is_(True)).all() if e.shift is not None]
    for back in range(days_back, -1, -1):
        day = (now - timedelta(days=back)).date()
        for emp in emps:
            if day.isoweekday() not in (emp.shift.workdays or []) or now < deadline(emp.shift, day):
                continue
            row = db.query(AttendanceDay).filter_by(employee_id=emp.id, date=day).first()
            if row is None:
                registered = _registered_on(emp)
                if registered and day < registered:
                    continue  # belum terdaftar hari itu → bukan "Tidak hadir"
                recompute_day(db, emp.id, day, now=now)
                created += 1
            elif row.status == "waiting" and not _has_override(row):
                recompute_day(db, emp.id, day, now=now)
                updated += 1
    return {"created": created, "updated": updated}


class AttendanceCloser:
    """Thread latar: close_due tiap interval_s; run pertama saat start (catch-up setelah API restart)."""

    def __init__(self, interval_s: float = CLOSE_INTERVAL_S, session_factory=SessionLocal,
                 run_on_start: bool = True):
        self.interval_s = interval_s
        self.run_on_start = run_on_start
        self._session_factory = session_factory
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def run_once(self, now: datetime | None = None) -> dict:
        db = self._session_factory()
        try:
            return close_due(db, now=now)
        finally:
            db.close()

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="attendance-closer")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def _loop(self) -> None:
        first = self.run_on_start
        while first or not self._stop.wait(self.interval_s):
            first = False
            if self._stop.is_set():
                break
            try:
                self.run_once()
            except Exception:
                logger.warning("attendance close failed", exc_info=True)


closer = AttendanceCloser()
