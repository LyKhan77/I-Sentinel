"""Attendance logic — agregasi harian, handle_face_event, close_days. Tanpa insightface."""
import uuid
from datetime import datetime, timedelta

from app.models.attendance import AttendanceDay, AttendanceEvent
from app.models.camera import Camera
from app.models.employee import Employee
from app.models.event import Event
from app.models.shift import Shift
from app.models.zone import Zone
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


def _emp(db, shift=None, code="E1", created_at=None):
    # default jauh di masa lalu: tanggal uji (MON, 2025) harus setelah karyawan terdaftar
    e = Employee(name="Budi", employee_code=code, shift_id=shift.id if shift else None,
                 created_at=created_at or datetime(2020, 1, 1, tzinfo=LOCAL_TZ))
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


def _raw_event(db, direction, ts, payload_over=None, zone_id=None):
    payload = {"crop_path": "crops/x.jpg", "direction": direction}
    payload.update(payload_over or {})
    ev = Event(event_id=str(uuid.uuid4()), type="attendance", camera_id=1, severity="info",
               ts_event=ts, payload=payload, zone_id=zone_id)
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


# --- R5b: cooldown dan sanitasi embedding -----------------------------------


def _matched_vec(eid, score=0.8):
    return lambda vector, quality=None: MatchResult(eid, score, quality, "matched")


def _no_match_vec():
    return lambda vector, quality=None: MatchResult(None, None, quality, "no_match")


VEC = {"embedding": [0.1] * 512, "face_quality": 0.8}


def test_embedding_never_stored_after_match(db, monkeypatch):
    _camera(db)
    e = _emp(db, _shift(db))
    monkeypatch.setattr(attendance.face, "match_vector", _matched_vec(e.id))
    ev = _raw_event(db, "entry", _at(*MON, 7, 10), VEC)
    assert attendance.handle_face_event(db, ev) is not None
    db.refresh(ev)
    assert "embedding" not in ev.payload
    assert (ev.payload["employee_name"], ev.payload["match_reason"]) == ("Budi", "matched")


def test_embedding_stripped_on_unmatched_and_invalid_paths(db, monkeypatch):
    _camera(db)
    _emp(db, _shift(db))
    monkeypatch.setattr(attendance.face, "match_vector", _no_match_vec())
    unmatched = _raw_event(db, "entry", _at(*MON, 7, 10), VEC)
    invalid = _raw_event(db, "sideways", _at(*MON, 7, 11), VEC)
    attendance.handle_face_event(db, unmatched)
    attendance.handle_face_event(db, invalid)
    for ev in (unmatched, invalid):
        db.refresh(ev)
        assert "embedding" not in ev.payload
    assert unmatched.payload["match_reason"] == "no_match"


def test_embedding_stripped_when_neither_vector_nor_crop_can_match(db):
    _camera(db)
    ev = _raw_event(db, "entry", _at(*MON, 7, 10),
                    {"embedding": [], "crop_path": None})
    assert attendance.handle_face_event(db, ev) is None
    db.refresh(ev)
    assert "embedding" not in ev.payload


def test_embedding_event_without_crop_is_still_matched(db, monkeypatch):
    _camera(db)
    e = _emp(db, _shift(db))
    monkeypatch.setattr(attendance.face, "match_vector", _matched_vec(e.id))
    ev = _raw_event(db, "entry", _at(*MON, 7, 10), {**VEC, "crop_path": None})
    row = attendance.handle_face_event(db, ev)
    assert row is not None and row.snapshot_path is None


def test_second_pass_within_cooldown_records_one_attendance(db, monkeypatch):
    _camera(db)
    e = _emp(db, _shift(db))
    monkeypatch.setattr(settings, "attendance_cooldown_min", 5)
    monkeypatch.setattr(attendance.face, "match_vector", _matched_vec(e.id))
    attendance.handle_face_event(db, _raw_event(db, "entry", _at(*MON, 7, 10), VEC))
    second = _raw_event(db, "entry", _at(*MON, 7, 13), VEC)
    assert attendance.handle_face_event(db, second) is None
    assert db.query(AttendanceEvent).count() == 1
    db.refresh(second)
    assert (second.payload["match_reason"], second.payload["employee_id"]) == ("cooldown", e.id)
    assert "embedding" not in second.payload


def test_pass_after_cooldown_records_again(db, monkeypatch):
    """Setelah cooldown lewat, exit dicatat lagi (entry dibatasi sekali per hari)."""
    _camera(db)
    e = _emp(db, _shift(db))
    monkeypatch.setattr(settings, "attendance_cooldown_min", 5)
    monkeypatch.setattr(attendance.face, "match_vector", _matched_vec(e.id))
    attendance.handle_face_event(db, _raw_event(db, "exit", _at(*MON, 12, 0), VEC))
    attendance.handle_face_event(db, _raw_event(db, "exit", _at(*MON, 12, 6), VEC))
    assert db.query(AttendanceEvent).count() == 2


def test_cooldown_is_per_direction(db, monkeypatch):
    _camera(db)
    e = _emp(db, _shift(db))
    monkeypatch.setattr(settings, "attendance_cooldown_min", 5)
    monkeypatch.setattr(attendance.face, "match_vector", _matched_vec(e.id))
    attendance.handle_face_event(db, _raw_event(db, "entry", _at(*MON, 7, 10), VEC))
    attendance.handle_face_event(db, _raw_event(db, "exit", _at(*MON, 7, 12), VEC))
    assert db.query(AttendanceEvent).count() == 2


def test_out_of_order_delivery_within_cooldown_records_once(db, monkeypatch):
    """Antrean disk node bisa mengirim event lama setelah yang baru."""
    _camera(db)
    e = _emp(db, _shift(db))
    monkeypatch.setattr(settings, "attendance_cooldown_min", 5)
    monkeypatch.setattr(attendance.face, "match_vector", _matched_vec(e.id))
    attendance.handle_face_event(db, _raw_event(db, "entry", _at(*MON, 7, 10), VEC))
    attendance.handle_face_event(db, _raw_event(db, "entry", _at(*MON, 7, 8), VEC))
    assert db.query(AttendanceEvent).count() == 1


def test_cooldown_across_cameras_and_exact_boundary(db, monkeypatch):
    first_camera = _camera(db)
    e = _emp(db, _shift(db))
    monkeypatch.setattr(settings, "attendance_cooldown_min", 5)
    monkeypatch.setattr(attendance.face, "match_vector", _matched_vec(e.id))
    attendance.handle_face_event(db, _raw_event(db, "entry", _at(*MON, 7, 10), VEC))
    second_camera = _camera(db)
    assert first_camera.id != second_camera.id
    at_boundary = _raw_event(db, "entry", _at(*MON, 7, 15), VEC)
    at_boundary.camera_id = second_camera.id
    db.commit()
    assert attendance.handle_face_event(db, at_boundary) is None
    assert db.query(AttendanceEvent).count() == 1


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


def test_second_entry_same_day_after_cooldown_is_not_recorded(db, monkeypatch):
    """Entry sekali per hari: lewat lagi di zona entry (> cooldown) tidak menggandakan absensi."""
    _camera(db)
    e = _emp(db, _shift(db))
    monkeypatch.setattr(settings, "attendance_cooldown_min", 5)
    monkeypatch.setattr(attendance.face, "match_vector", _matched_vec(e.id))
    attendance.handle_face_event(db, _raw_event(db, "entry", _at(*MON, 7, 10), VEC))
    again = _raw_event(db, "entry", _at(*MON, 9, 30), VEC)
    assert attendance.handle_face_event(db, again) is None
    assert db.query(AttendanceEvent).filter_by(direction="entry").count() == 1
    db.refresh(again)
    assert (again.payload["match_reason"], again.payload["employee_name"]) == ("already_in", "Budi")


def test_earlier_entry_arriving_late_is_still_recorded(db, monkeypatch):
    """Antrean disk node bisa mengirim entry pagi setelah entry siang: jam masuk harus yang pagi."""
    _camera(db)
    e = _emp(db, _shift(db))
    monkeypatch.setattr(settings, "attendance_cooldown_min", 5)
    monkeypatch.setattr(attendance.face, "match_vector", _matched_vec(e.id))
    attendance.handle_face_event(db, _raw_event(db, "entry", _at(*MON, 9, 30), VEC))
    assert attendance.handle_face_event(db, _raw_event(db, "entry", _at(*MON, 7, 10), VEC)) is not None
    day = db.query(AttendanceDay).filter_by(employee_id=e.id).one()
    assert attendance._local(day.first_entry).hour == 7


def test_entry_next_day_and_repeated_exits_are_recorded(db, monkeypatch):
    _camera(db)
    e = _emp(db, _shift(db))
    monkeypatch.setattr(settings, "attendance_cooldown_min", 5)
    monkeypatch.setattr(attendance.face, "match_vector", _matched_vec(e.id))
    attendance.handle_face_event(db, _raw_event(db, "entry", _at(*MON, 7, 10), VEC))
    attendance.handle_face_event(db, _raw_event(db, "exit", _at(*MON, 12, 0), VEC))
    attendance.handle_face_event(db, _raw_event(db, "exit", _at(*MON, 16, 5), VEC))
    attendance.handle_face_event(db, _raw_event(db, "entry", _at(2025, 1, 7, 7, 5), VEC))
    assert db.query(AttendanceEvent).filter_by(direction="entry").count() == 2
    assert db.query(AttendanceEvent).filter_by(direction="exit").count() == 2


def test_face_snapshot_labeled_with_name_or_unknown(db, monkeypatch):
    calls = []
    monkeypatch.setattr(attendance, "annotate_snapshot",
                        lambda path, label, bbox, color=None: calls.append((path.endswith("snapshots/s.jpg"), label)))
    sh = _shift(db)
    e = _emp(db, sh)
    _camera(db)
    monkeypatch.setattr(attendance.face, "match_crop", _matched(e.id))
    ev = _raw_event(db, "entry", _at(*MON, 7, 10), {"bbox_norm": [0.1, 0.1, 0.2, 0.2]})
    ev.snapshot_path = "snapshots/s.jpg"
    db.commit()
    attendance.handle_face_event(db, ev)
    monkeypatch.setattr(attendance.face, "match_crop", _no_match())
    ev2 = _raw_event(db, "entry", _at(*MON, 7, 20))
    ev2.snapshot_path = "snapshots/s.jpg"
    db.commit()
    attendance.handle_face_event(db, ev2)
    assert calls == [(True, e.name), (True, "Unknown")]


def test_exit_without_entry_is_no_entry(db):
    sh = _shift(db)
    e = _emp(db, sh)
    _camera(db)
    _att_event(db, e.id, "exit", _at(*MON, 16, 5))
    row = attendance.recompute_day(db, e.id, _at(*MON, 16, 5).date(), now=_at(*MON, 18, 0))
    assert row.status == "no_entry" and row.duration_min is None and row.late_minutes is None


def test_effective_status_waiting_past_deadline_is_no_exit(db):
    sh = _shift(db)  # 07:00-16:00, grace default 60 → batas 17:00
    e = _emp(db, sh)
    _camera(db)
    _att_event(db, e.id, "entry", _at(*MON, 7, 5))
    row = attendance.recompute_day(db, e.id, _at(*MON, 7, 5).date(), now=_at(*MON, 9, 0))
    assert row.status == "waiting"
    assert attendance.effective_status(row, sh, now=_at(*MON, 16, 59)) == "waiting"
    assert attendance.effective_status(row, sh, now=_at(*MON, 17, 0)) == "no_exit"
    row.override_note = "dikoreksi HR"
    assert attendance.effective_status(row, sh, now=_at(*MON, 18, 0)) == "waiting"  # koreksi manual tidak diubah
    assert attendance.effective_status(row, None, now=_at(*MON, 23, 0)) == "waiting"  # tanpa shift


def test_close_due_absent_only_after_deadline_and_workdays(db):
    sh = _shift(db)            # Senin-Jumat 07:00-16:00, batas 17:00
    e = _emp(db, sh, code="E1")
    _emp(db, None, code="E2")  # tanpa shift → tidak pernah absent
    off = _emp(db, sh, code="E3")
    off.active = False
    db.commit()
    day = _at(*MON, 9, 0).date()
    assert attendance.close_due(db, now=_at(*MON, 16, 59), days_back=0) == {"created": 0, "updated": 0}
    assert db.query(AttendanceDay).count() == 0  # hari ini sebelum batas: belum "tidak hadir"
    r = attendance.close_due(db, now=_at(*MON, 17, 0), days_back=0)
    assert r == {"created": 1, "updated": 0}
    row = db.query(AttendanceDay).one()
    assert row.employee_id == e.id and row.date == day and row.status == "absent"


def test_close_due_turns_waiting_into_no_exit_and_skips_override(db):
    sh = _shift(db)
    a = _emp(db, sh, code="A")
    b = _emp(db, sh, code="B")
    _camera(db)
    for emp in (a, b):
        _att_event(db, emp.id, "entry", _at(*MON, 7, 5))
        attendance.recompute_day(db, emp.id, _at(*MON, 7, 5).date(), now=_at(*MON, 8, 0))
    rb = db.query(AttendanceDay).filter_by(employee_id=b.id).one()
    rb.override_note = "koreksi HR"
    db.commit()
    r = attendance.close_due(db, now=_at(*MON, 18, 0), days_back=0)
    assert r["updated"] == 1
    assert db.query(AttendanceDay).filter_by(employee_id=a.id).one().status == "no_exit"
    assert db.query(AttendanceDay).filter_by(employee_id=b.id).one().status == "waiting"  # tidak disentuh


def test_close_due_catch_up_and_idempotent(db):
    sh = _shift(db)
    _emp(db, sh)
    now = _at(*MON, 10, 0) + timedelta(days=8)  # Selasa minggu berikutnya 10:00, hari ini belum lewat batas
    first = attendance.close_due(db, now=now)            # 7 hari ke belakang
    again = attendance.close_due(db, now=now)
    workdays = sum(1 for i in range(1, 8) if (now - timedelta(days=i)).isoweekday() <= 5)
    assert first["created"] == workdays and again == {"created": 0, "updated": 0}
    assert db.query(AttendanceDay).count() == workdays


def test_close_days_skips_override(db):
    sh = _shift(db)
    e = _emp(db, sh)
    day = _at(*MON, 9, 0).date()
    db.add(AttendanceDay(employee_id=e.id, date=day, status="ontime", override_note="manual"))
    db.commit()
    attendance.close_days(db, day, now=_at(*MON, 23, 0))
    assert db.query(AttendanceDay).one().status == "ontime"


def test_closer_runs_on_start_survives_error_and_stops(monkeypatch):
    calls = []

    def boom():
        calls.append(1)
        raise RuntimeError("db down")

    c = attendance.AttendanceCloser(interval_s=0.01, session_factory=boom, run_on_start=True)
    c.start()
    import time
    deadline = time.monotonic() + 2
    while len(calls) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    c.stop()
    assert len(calls) >= 2 and not c._thread.is_alive()


def test_close_due_no_absent_before_employee_registered(db):
    # uji lapangan: catch-up 7 hari tidak boleh membuat "Tidak hadir" untuk hari sebelum karyawan didaftarkan
    sh = _shift(db)
    now = _at(*MON, 10, 0) + timedelta(days=8)          # Selasa minggu berikutnya
    registered = now - timedelta(days=2)                 # didaftarkan hari Minggu
    e = _emp(db, sh, created_at=registered)
    attendance.close_due(db, now=now)
    days = {r.date for r in db.query(AttendanceDay).filter_by(employee_id=e.id)}
    assert days == {(now - timedelta(days=1)).date()}   # hanya Senin (hari kerja setelah terdaftar)
    assert attendance.close_days(db, (now - timedelta(days=4)).date(), now=now) == 0  # manual juga dilewati


def test_already_in_payload_carries_first_entry_without_exit(db, monkeypatch):
    _camera(db)
    e = _emp(db, _shift(db))
    monkeypatch.setattr(attendance.face, "match_vector", _matched_vec(e.id))
    attendance.handle_face_event(db, _raw_event(db, "entry", _at(*MON, 7, 10), VEC))
    day = db.query(AttendanceDay).one()
    before = (day.first_entry, day.last_exit, day.status)
    again = _raw_event(db, "entry", _at(*MON, 9, 30), VEC)
    assert attendance.handle_face_event(db, again) is None
    assert again.payload["first_entry_ts"] == _at(*MON, 7, 10).isoformat()
    assert "exit_ts" not in again.payload
    assert db.query(AttendanceEvent).count() == 1
    db.refresh(day)
    assert (day.first_entry, day.last_exit, day.status) == before


def test_already_in_payload_carries_exit_seen_between(db, monkeypatch):
    _camera(db)
    e = _emp(db, _shift(db))
    monkeypatch.setattr(attendance.face, "match_vector", _matched_vec(e.id))
    for direction, hh, mm in (("entry", 7, 10), ("exit", 8, 0)):
        attendance.handle_face_event(db, _raw_event(db, direction, _at(*MON, hh, mm), VEC))
    again = _raw_event(db, "entry", _at(*MON, 9, 30), VEC)
    attendance.handle_face_event(db, again)
    assert again.payload["first_entry_ts"] == _at(*MON, 7, 10).isoformat()
    assert again.payload["exit_ts"] == _at(*MON, 8, 0).isoformat()


def test_already_in_ignores_exit_before_first_entry(db, monkeypatch):
    _camera(db)
    e = _emp(db, _shift(db))
    monkeypatch.setattr(attendance.face, "match_vector", _matched_vec(e.id))
    _att_event(db, e.id, "exit", _at(*MON, 6, 0))
    _att_event(db, e.id, "exit", _at(2025, 1, 5, 16, 0))
    attendance.handle_face_event(db, _raw_event(db, "entry", _at(*MON, 7, 10), VEC))
    again = _raw_event(db, "entry", _at(*MON, 9, 30), VEC)
    attendance.handle_face_event(db, again)
    assert again.payload["first_entry_ts"] == _at(*MON, 7, 10).isoformat()
    assert "exit_ts" not in again.payload


def _record_zone(db, record=None):
    behavior = {"kind": "attendance", "trigger_seconds": 0}
    if record is not None:
        behavior["record"] = record
    z = Zone(camera_id=1, name="Gate", type="attendance", direction="entry",
             polygon=[[0, 0], [1, 0], [1, 1]], behaviors=[behavior], telegram=True, rate_limit_min=2)
    db.add(z)
    db.commit()
    return z


def test_record_off_detects_without_attendance_rows(db, monkeypatch):
    _camera(db)
    e = _emp(db, _shift(db))
    z = _record_zone(db, False)
    monkeypatch.setattr(attendance.face, "match_vector", _matched_vec(e.id))
    ev = _raw_event(db, "entry", _at(*MON, 7, 10), VEC, zone_id=z.id)
    assert attendance.handle_face_event(db, ev) is None
    assert db.query(AttendanceEvent).count() == 0
    assert db.query(AttendanceDay).count() == 0
    assert (ev.payload["match_reason"], ev.payload["employee_name"]) == ("detected", "Budi")
    assert "embedding" not in ev.payload


def test_record_off_dedups_per_employee_and_zone_within_window(db, monkeypatch):
    _camera(db)
    e = _emp(db, _shift(db))
    other = _emp(db, code="E2")
    z, z2 = _record_zone(db, False), _record_zone(db, False)
    monkeypatch.setattr(settings, "attendance_cooldown_min", 5)
    for employee, zone, minute, expected in (
        (e, z, 10, "detected"), (e, z, 13, "cooldown"), (e, z, 16, "detected"),
        (other, z, 16, "detected"), (e, z2, 16, "detected"),
    ):
        monkeypatch.setattr(attendance.face, "match_vector", _matched_vec(employee.id))
        ev = _raw_event(db, "entry", _at(*MON, 7, minute), VEC, zone_id=zone.id)
        assert attendance.handle_face_event(db, ev) is None
        assert ev.payload["match_reason"] == expected
    assert db.query(AttendanceEvent).count() == db.query(AttendanceDay).count() == 0


def test_record_off_unknown_face_is_not_deduped(db, monkeypatch):
    _camera(db)
    z = _record_zone(db, False)
    monkeypatch.setattr(attendance.face, "match_vector", _no_match_vec())
    for minute in (10, 11):
        ev = _raw_event(db, "entry", _at(*MON, 7, minute), VEC, zone_id=z.id)
        assert attendance.handle_face_event(db, ev) is None
        assert ev.payload["match_reason"] == "no_match"
        assert ev.payload["employee_id"] is None
    assert db.query(AttendanceEvent).count() == db.query(AttendanceDay).count() == 0


def test_record_default_true_keeps_recording(db, monkeypatch):
    _camera(db)
    e = _emp(db, _shift(db))
    z = _record_zone(db)
    monkeypatch.setattr(attendance.face, "match_vector", _matched_vec(e.id))
    ev = _raw_event(db, "entry", _at(*MON, 7, 10), VEC, zone_id=z.id)
    assert attendance.handle_face_event(db, ev) is not None
    assert db.query(AttendanceEvent).count() == db.query(AttendanceDay).count() == 1


def test_record_off_dedup_ignores_other_reasons_and_handles_late_events(db, monkeypatch):
    _camera(db)
    e = _emp(db)
    z = _record_zone(db, False)
    monkeypatch.setattr(settings, "attendance_cooldown_min", 5)
    monkeypatch.setattr(attendance.face, "match_vector", _matched_vec(e.id))
    _raw_event(db, "entry", _at(*MON, 7, 9),
               {"employee_id": e.id, "match_reason": "cooldown"}, zone_id=z.id)
    first = _raw_event(db, "entry", _at(*MON, 7, 10), VEC, zone_id=z.id)
    attendance.handle_face_event(db, first)
    assert first.payload["match_reason"] == "detected"
    late = _raw_event(db, "entry", _at(*MON, 7, 5), VEC, zone_id=z.id)
    attendance.handle_face_event(db, late)
    assert late.payload["match_reason"] == "cooldown"
    outside = _raw_event(db, "entry", _at(*MON, 7, 4), VEC, zone_id=z.id)
    attendance.handle_face_event(db, outside)
    assert outside.payload["match_reason"] == "detected"
