"""Attendance logic — agregasi harian, handle_face_event, close_days. Tanpa insightface."""
import uuid
from datetime import datetime

from app.models.attendance import AttendanceDay, AttendanceEvent
from app.models.camera import Camera
from app.models.employee import Employee
from app.models.event import Event
from app.models.shift import Shift
from app.services import attendance
from app.services.attendance import LOCAL_TZ
from app.core.config import settings
from app.services.face import MatchResult

MON = (2025, 1, 6)  # Senin — masuk workdays default


def _at(y, m, d, hh, mm):
    return datetime(y, m, d, hh, mm, tzinfo=LOCAL_TZ)


def _shift(db, start="07:00", end="16:00", tol=15):
    s = Shift(name=f"Pagi-{uuid.uuid4().hex[:6]}", start_time=start, end_time=end,
              tolerance_min=tol, workdays=[1, 2, 3, 4, 5])
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


def _emp(db, shift=None, code="E1"):
    e = Employee(name="Budi", employee_code=code, shift_id=shift.id if shift else None)
    db.add(e)
    db.commit()
    db.refresh(e)
    return e


def _camera(db):
    c = Camera(name="Gate", host="127.0.0.1")
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def _att_event(db, employee_id, direction, ts, camera_id=1):
    db.add(AttendanceEvent(employee_id=employee_id, camera_id=camera_id, direction=direction, ts_event=ts))
    db.commit()


def _raw_event(db, direction, ts, payload_over=None):
    payload = {"crop_path": "crops/x.jpg", "direction": direction}
    payload.update(payload_over or {})
    ev = Event(event_id=str(uuid.uuid4()), type="attendance", camera_id=1, severity="info",
               ts_event=ts, payload=payload)
    db.add(ev)
    db.commit()
    db.refresh(ev)
    return ev


def _matched(eid=1, score=0.8):
    return lambda db, path: MatchResult(eid, score, 0.9, "matched")


def _no_match():
    return lambda db, path: MatchResult(None, None, 0.9, "no_match")


# --- (a) ontime, durasi 535 -------------------------------------------------

def test_ontime_duration(db):
    sh = _shift(db)
    e = _emp(db, sh)
    _camera(db)
    _att_event(db, e.id, "entry", _at(*MON, 7, 10))
    _att_event(db, e.id, "exit", _at(*MON, 16, 5))

    row = attendance.recompute_day(db, e.id, _at(*MON, 18, 0).date())
    assert row.status == "ontime"
    assert row.duration_min == 535
    assert row.late_minutes == 0
    assert row.first_entry is not None


# --- (b) late 5 menit -------------------------------------------------------

def test_late_minutes(db):
    sh = _shift(db)
    e = _emp(db, sh)
    _camera(db)
    _att_event(db, e.id, "entry", _at(*MON, 7, 20))
    _att_event(db, e.id, "exit", _at(*MON, 16, 0))

    row = attendance.recompute_day(db, e.id, _at(*MON, 18, 0).date())
    assert row.status == "late"
    assert row.late_minutes == 5


# --- (c) belum lewat grace -> waiting ---------------------------------------

def test_waiting_before_grace(db):
    sh = _shift(db)
    e = _emp(db, sh)
    _camera(db)
    _att_event(db, e.id, "entry", _at(*MON, 7, 10))

    day = _at(*MON, 7, 10).date()
    row = attendance.recompute_day(db, e.id, day, now=_at(*MON, 16, 30))
    assert row.status == "waiting"
    assert row.duration_min is None and row.late_minutes is None


# --- (d) lewat grace tanpa exit -> no_exit ----------------------------------

def test_no_exit_after_grace(db):
    sh = _shift(db)
    e = _emp(db, sh)
    _camera(db)
    _att_event(db, e.id, "entry", _at(*MON, 7, 10))

    day = _at(*MON, 7, 10).date()
    row = attendance.recompute_day(db, e.id, day, now=_at(*MON, 17, 30))
    assert row.status == "no_exit"


# --- (e) tidak ada event + close_days -> absent -----------------------------

def test_close_days_marks_absent(db):
    sh = _shift(db)
    e = _emp(db, sh)

    n = attendance.close_days(db, _at(*MON, 23, 0).date(), now=_at(*MON, 23, 0))
    assert n == 1
    row = db.query(AttendanceDay).filter_by(employee_id=e.id).one()
    assert row.status == "absent"
    assert row.first_entry is None and row.duration_min is None and row.late_minutes is None


def test_close_days_skips_non_workday_and_shiftless(db):
    sh = _shift(db)  # workdays 1-5
    _emp(db, sh, code="E1")
    _emp(db, None, code="E2")  # tanpa shift
    n = attendance.close_days(db, _at(2025, 1, 11, 23, 0).date())  # Sabtu
    assert n == 0
    assert db.query(AttendanceDay).count() == 0


# --- (f) shift None -> ontime tanpa late ------------------------------------

def test_no_shift_ontime_no_late(db):
    e = _emp(db, None)
    _camera(db)
    _att_event(db, e.id, "entry", _at(*MON, 7, 10))
    _att_event(db, e.id, "exit", _at(*MON, 16, 5))

    row = attendance.recompute_day(db, e.id, _at(*MON, 7, 10).date())
    assert row.status == "ontime"
    assert row.late_minutes is None
    assert row.duration_min == 535


# --- (g) handle_face_event match -> AttendanceEvent + day recompute ---------

def test_handle_face_event_matched(db, monkeypatch):
    sh = _shift(db)
    e = _emp(db, sh)
    _camera(db)
    monkeypatch.setattr(attendance.face, "match_crop", _matched(e.id))

    ev = _raw_event(db, "entry", _at(*MON, 7, 10))
    row = attendance.handle_face_event(db, ev)
    assert row is not None
    assert row.employee_id == e.id
    assert row.direction == "entry"
    assert row.snapshot_path == "crops/x.jpg"
    assert row.event_id == ev.event_id
    assert db.query(AttendanceEvent).count() == 1

    ev2 = _raw_event(db, "exit", _at(*MON, 16, 5))
    attendance.handle_face_event(db, ev2)

    day = db.query(AttendanceDay).filter_by(employee_id=e.id).one()
    assert day.first_entry is not None
    assert day.status == "ontime"
    assert day.duration_min == 535


# --- (h) unknown face -> tidak ada AttendanceEvent, payload ada match_reason -

def test_handle_face_event_unknown(db, monkeypatch):
    _shift(db)
    _emp(db, _shift(db))
    _camera(db)
    monkeypatch.setattr(attendance.face, "match_crop", _no_match())

    ev = _raw_event(db, "entry", _at(*MON, 7, 10))
    assert attendance.handle_face_event(db, ev) is None
    assert db.query(AttendanceEvent).count() == 0
    db.refresh(ev)
    assert ev.payload["employee_id"] is None
    assert ev.payload["match_reason"] == "no_match"


# --- (i) direction invalid -> skip ------------------------------------------

def test_handle_face_event_invalid_direction(db, monkeypatch):
    _shift(db)
    e = _emp(db, _shift(db))
    _camera(db)
    monkeypatch.setattr(attendance.face, "match_crop", _matched(e.id))

    ev = _raw_event(db, "sideways", _at(*MON, 7, 10))
    assert attendance.handle_face_event(db, ev) is None
    assert db.query(AttendanceEvent).count() == 0


# --- crop_path kosong -> skip -----------------------------------------------

def test_handle_face_event_missing_crop(db, monkeypatch):
    _shift(db)
    _emp(db, _shift(db))
    _camera(db)
    monkeypatch.setattr(attendance.face, "match_crop", _matched())

    ev = _raw_event(db, "entry", _at(*MON, 7, 10), {"crop_path": None})
    assert attendance.handle_face_event(db, ev) is None
    assert db.query(AttendanceEvent).count() == 0


# --- bukan tipe attendance -> None ------------------------------------------

def test_handle_face_event_other_type(db):
    _shift(db)
    _emp(db, _shift(db))
    _camera(db)
    ev = Event(event_id=str(uuid.uuid4()), type="intrusion", camera_id=1, severity="info",
               ts_event=_at(*MON, 7, 10), payload={"crop_path": "x.jpg", "direction": "entry"})
    db.add(ev)
    db.commit()
    assert attendance.handle_face_event(db, ev) is None


# --- override_note dipertahankan saat recompute -----------------------------

def test_recompute_keeps_override_note(db):
    sh = _shift(db)
    e = _emp(db, sh)
    _camera(db)
    _att_event(db, e.id, "entry", _at(*MON, 7, 10))
    row = attendance.recompute_day(db, e.id, _at(*MON, 7, 10).date())
    row.override_note = "izin telat"
    db.commit()

    attendance.recompute_day(db, e.id, _at(*MON, 7, 10).date())
    db.refresh(row)
    assert row.override_note == "izin telat"


# --- Opsi B: payload embedding dari node -> match gallery langsung -----------

def test_handle_face_event_with_node_embedding(db, monkeypatch):
    """Payload bawa embedding -> match gallery langsung, tanpa engine backend."""
    sh = _shift(db)
    e = _emp(db, sh)
    _camera(db)
    called = {"embed": 0}

    def _spy_match_crop(db_, path):
        called["embed"] += 1
        return MatchResult(None, None, None, "not_configured")

    monkeypatch.setattr(attendance.face, "match_crop", _spy_match_crop)
    monkeypatch.setattr(attendance.face, "match_vector",
                        lambda vec, q=None: MatchResult(e.id, 0.83, q, "matched"))

    ev = _raw_event(db, "entry", _at(*MON, 7, 10),
                    {"embedding": [0.1] * 512, "face_quality": 0.9})
    row = attendance.handle_face_event(db, ev)
    assert row is not None
    assert row.employee_id == e.id
    assert called["embed"] == 0  # backend TIDAK embed ulang


def test_handle_face_event_low_quality_rejected(db, monkeypatch):
    _shift(db)
    _emp(db, _shift(db))
    _camera(db)
    monkeypatch.setattr(attendance.face, "match_vector",
                        lambda vec, q=None: MatchResult(None, None, q, "low_quality"))

    ev = _raw_event(db, "entry", _at(*MON, 7, 10),
                    {"embedding": [0.1] * 512, "face_quality": 0.1})
    assert attendance.handle_face_event(db, ev) is None
    db.refresh(ev)
    assert ev.payload["match_reason"] == "low_quality"


def test_handle_face_event_fallback_crop_without_embedding(db, monkeypatch):
    """Tanpa embedding -> jalur lama (match_crop) — status quo terjaga."""
    sh = _shift(db)
    e = _emp(db, sh)
    _camera(db)
    monkeypatch.setattr(attendance.face, "match_crop",
                        lambda db_, path: MatchResult(e.id, 0.8, 0.9, "matched"))

    ev = _raw_event(db, "entry", _at(*MON, 7, 10))  # tanpa embedding
    row = attendance.handle_face_event(db, ev)
    assert row is not None
    assert row.employee_id == e.id


# --- R1: anotasi identitas pada crop setelah match ---------------------------

def test_handle_face_event_annotates_crop(tmp_path, db, monkeypatch):
    """Match sukses → file crop di-overwrite dengan nama + score (best-effort)."""
    from PIL import Image
    import numpy as np

    sh = _shift(db)
    e = _emp(db, sh)
    _camera(db)
    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    monkeypatch.setattr(attendance.face, "match_vector",
                        lambda vec, q=None: MatchResult(e.id, 0.83, q, "matched"))

    p = tmp_path / "crops" / "x.jpg"
    p.parent.mkdir()
    Image.new("RGB", (120, 120), (255, 255, 255)).save(p)
    before = p.read_bytes()

    ev = _raw_event(db, "entry", _at(*MON, 7, 10),
                    {"embedding": [0.1] * 512, "face_quality": 0.9})
    row = attendance.handle_face_event(db, ev)
    assert row is not None
    after = p.read_bytes()
    assert after != before
    img = Image.open(p)
    assert img.size == (120, 120)


def test_handle_face_event_annotation_failure_not_fatal(tmp_path, db, monkeypatch):
    """Crop hilang/corrupt → attendance tetap jalan (anotasi best-effort)."""
    sh = _shift(db)
    e = _emp(db, sh)
    _camera(db)
    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    monkeypatch.setattr(attendance.face, "match_vector",
                        lambda vec, q=None: MatchResult(e.id, 0.83, q, "matched"))
    ev = _raw_event(db, "entry", _at(*MON, 7, 10),
                    {"embedding": [0.1] * 512, "face_quality": 0.9,
                     "crop_path": "crops/nope.jpg"})
    row = attendance.handle_face_event(db, ev)
    assert row is not None
