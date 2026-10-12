"""Attendance API — list, CSV export/import, PATCH override, close-days internal."""
import csv
import io
import uuid
from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.db import get_db
from app.main import app
from app.models.attendance import AttendanceDay, AttendanceEvent
from app.models.camera import Camera
from app.models.employee import Employee
from app.models.shift import Shift
from app.services import attendance
from app.services.attendance import LOCAL_TZ

DAY = date(2025, 1, 6)  # Senin


@pytest.fixture
def client(db, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "admin_username", "admin")
    monkeypatch.setattr(settings, "admin_password", "boot123")
    monkeypatch.setattr(settings, "node_api_key", "kunci")
    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _headers(client):
    tok = client.post("/api/v1/auth/login", json={"username": "admin", "password": "boot123"}).json()["token"]
    return {"Authorization": f"Bearer {tok}"}


def _at(hh, mm, d=DAY):
    return datetime(d.year, d.month, d.day, hh, mm, tzinfo=LOCAL_TZ)


def _fixture_employee(db, code="E1", name="Budi"):
    sh = Shift(name=f"Pagi-{uuid.uuid4().hex[:6]}", start_time="07:00", end_time="16:00",
               tolerance_min=15, workdays=[1, 2, 3, 4, 5])
    db.add(sh)
    db.commit()
    db.refresh(sh)
    # terdaftar jauh sebelum DAY: penutupan hari tidak melewati hari sebelum karyawan didaftarkan
    e = Employee(name=name, employee_code=code, shift_id=sh.id, created_at=datetime(2020, 1, 1, tzinfo=LOCAL_TZ))
    db.add(e)
    db.commit()
    db.refresh(e)
    c = Camera(name="Gate", host="127.0.0.1")
    db.add(c)
    db.commit()
    db.refresh(c)
    for direction, ts in (("entry", _at(7, 10)), ("exit", _at(16, 5))):
        db.add(AttendanceEvent(employee_id=e.id, camera_id=c.id, direction=direction, ts_event=ts))
    db.commit()
    attendance.recompute_day(db, e.id, DAY, now=_at(18, 0))
    return e, sh


def _move_exit_earlier(db, employee_id, hh=12, mm=3):
    """Pindahkan `last_exit` baris rekap (fixture default 16:05 = sesudah shift selesai)."""
    row = db.query(AttendanceDay).filter_by(employee_id=employee_id, date=DAY).one()
    row.last_exit = _at(hh, mm)
    db.commit()
    return row


# --- (a) GET list -----------------------------------------------------------

def test_list_today(client, db):
    e, _ = _fixture_employee(db)
    h = _headers(client)

    r = client.get(f"/api/v1/attendance?date={DAY.isoformat()}", headers=h)
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    row = rows[0]
    assert row["employee_code"] == "E1"
    assert row["name"] == "Budi"
    assert row["date"] == DAY.isoformat()
    assert row["first_entry"] == "07:10:00"
    assert row["last_exit"] == "16:05:00"
    assert row["duration_min"] == 535
    assert row["status"] == "ontime"
    assert row["shift_name"].startswith("Pagi-")


def test_list_defaults_to_today(client, db):
    e, _ = _fixture_employee(db)
    attendance.recompute_day(db, e.id, datetime.now(LOCAL_TZ).date())
    # pindahkan row ke hari ini
    db.query(AttendanceDay).filter_by(employee_id=e.id).delete()
    db.commit()
    today = datetime.now(LOCAL_TZ).date()
    db.add(AttendanceDay(employee_id=e.id, date=today, status="ontime", first_entry=_at(7, 10, today)))
    db.commit()

    r = client.get("/api/v1/attendance", headers=_headers(client))
    assert r.status_code == 200
    assert [x["date"] for x in r.json()] == [today.isoformat()]


def test_list_filter_employee_id(client, db):
    e, _ = _fixture_employee(db)
    _fixture_employee(db, code="E2", name="Siti")
    r = client.get(f"/api/v1/attendance?date={DAY.isoformat()}&employee_id={e.id}", headers=_headers(client))
    assert [x["employee_code"] for x in r.json()] == ["E1"]


# --- (b) CSV export ---------------------------------------------------------

def _export(client, h, frm=DAY, to=DAY):
    r = client.get(f"/api/v1/attendance/rekap.csv?from={frm}&to={to}", headers=h)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert f"rekap_absensi_{frm}_{to}.csv" in r.headers["content-disposition"]
    return list(csv.DictReader(io.StringIO(r.text)))


def test_csv_export_rows(client, db):
    _fixture_employee(db)
    rows = _export(client, _headers(client))
    assert len(rows) == 1
    assert rows[0]["shift"].startswith("Pagi-")
    assert {k: v for k, v in rows[0].items() if k != "shift"} == {
        "employee_code": "E1",
        "name": "Budi",
        "date": DAY.isoformat(),
        "first_entry": "07:10:00",
        "last_exit": "16:05:00",
        "duration_min": "535",
        "status": "ontime",
        "late_minutes": "0",
        "override_note": "",
        "exit_early_min": "",
    }
    # tanpa biometrik
    assert not any("vector" in k or "biometric" in k for k in rows[0])


# --- (c) import roundtrip ---------------------------------------------------

def test_import_roundtrip(client, db):
    _fixture_employee(db)
    h = _headers(client)
    first = _export(client, h)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(first[0].keys()))
    w.writeheader()
    w.writerows(first)

    r = client.post("/api/v1/attendance/import",
                    files={"file": ("rekap.csv", buf.getvalue().encode(), "text/csv")}, headers=h)
    assert r.status_code == 200
    assert r.json() == {"updated": 1, "created": 0, "skipped": 0}

    second = _export(client, h)
    strip = lambda rows: [{k: v for k, v in row.items() if k != "override_note"} for row in rows]
    assert strip(second) == strip(first)
    assert second[0]["override_note"] == "import"


def test_import_creates_new_row(client, db):
    e, sh = _fixture_employee(db)
    h = _headers(client)
    csv_text = (f"employee_code,name,date,shift,first_entry,last_exit,duration_min,status,late_minutes,override_note\n"
                f"E1,Budi,2025-01-07,Pagi,07:20:00,16:00:00,,,\n")
    r = client.post("/api/v1/attendance/import",
                    files={"file": ("in.csv", csv_text.encode(), "text/csv")}, headers=h)
    assert r.json() == {"updated": 0, "created": 1, "skipped": 0}
    row = db.query(AttendanceDay).filter_by(employee_id=e.id, date=date(2025, 1, 7)).one()
    assert row.status == "late" and row.late_minutes == 5 and row.override_note == "import"


def test_import_skips_unknown_employee(client, db):
    _fixture_employee(db)
    csv_text = "employee_code,name,date,shift,first_entry,last_exit\nNOPE,X,2025-01-07,Pagi,07:00:00,16:00:00\n"
    r = client.post("/api/v1/attendance/import",
                    files={"file": ("in.csv", csv_text.encode(), "text/csv")}, headers=_headers(client))
    assert r.json() == {"updated": 0, "created": 0, "skipped": 1}


def test_import_skips_malformed_time_keeps_row(client, db):
    e, _ = _fixture_employee(db)
    csv_text = (f"employee_code,name,date,shift,first_entry,last_exit,duration_min,status,late_minutes,override_note\n"
                f"E1,Budi,{DAY.isoformat()},Pagi,bogus,16:05:00,,,\n")
    r = client.post("/api/v1/attendance/import",
                    files={"file": ("in.csv", csv_text.encode(), "text/csv")}, headers=_headers(client))
    assert r.json() == {"updated": 0, "created": 0, "skipped": 1}
    row = db.query(AttendanceDay).filter_by(employee_id=e.id, date=DAY).one()
    assert row.first_entry.strftime("%H:%M") == "07:10"
    assert row.last_exit.strftime("%H:%M") == "16:05"
    assert row.status == "ontime" and row.duration_min == 535


def test_import_requires_admin(client, db):
    _fixture_employee(db)
    r = client.post("/api/v1/attendance/import", files={"file": ("in.csv", b"x", "text/csv")})
    assert r.status_code == 401


# --- (d) PATCH override -----------------------------------------------------

def test_patch_requires_note(client, db):
    e, _ = _fixture_employee(db)
    day_id = db.query(AttendanceDay).filter_by(employee_id=e.id).one().id
    h = _headers(client)

    assert client.patch(f"/api/v1/attendance/{day_id}", json={"status": "late"}, headers=h).status_code == 422

    r = client.patch(f"/api/v1/attendance/{day_id}", json={"status": "late", "override_note": "manual"},
                     headers=h)
    assert r.status_code == 200
    assert r.json()["status"] == "late"
    assert r.json()["override_note"] == "manual"


def test_patch_note_only_ok(client, db):
    e, _ = _fixture_employee(db)
    day_id = db.query(AttendanceDay).filter_by(employee_id=e.id).one().id
    r = client.patch(f"/api/v1/attendance/{day_id}", json={"override_note": "cuti"}, headers=_headers(client))
    assert r.status_code == 200
    assert r.json()["override_note"] == "cuti"


def test_patch_time_recomputes_duration(client, db):
    e, _ = _fixture_employee(db)
    day_id = db.query(AttendanceDay).filter_by(employee_id=e.id).one().id
    r = client.patch(f"/api/v1/attendance/{day_id}",
                     json={"first_entry": "2025-01-06T07:00:00", "override_note": "manual"},
                     headers=_headers(client))
    assert r.status_code == 200
    assert r.json()["first_entry"] == "07:00:00"
    assert r.json()["duration_min"] == 545
    assert r.json()["late_minutes"] == 0


def test_patch_404(client, db):
    _fixture_employee(db)
    r = client.patch("/api/v1/attendance/9999", json={"override_note": "x"}, headers=_headers(client))
    assert r.status_code == 404


# --- (e) close-days internal ------------------------------------------------

def test_close_days_endpoint(client, db):
    e, _ = _fixture_employee(db)
    db.query(AttendanceDay).delete()
    db.query(AttendanceEvent).delete()
    db.commit()

    r = client.post("/internal/maintenance/close-days", json={"date": DAY.isoformat()},
                    headers={"Authorization": "Bearer kunci"})
    assert r.status_code == 200
    assert r.json() == {"closed": 1}
    assert db.query(AttendanceDay).filter_by(employee_id=e.id).one().status == "absent"


def test_close_days_bad_key(client, db):
    _fixture_employee(db)
    r = client.post("/internal/maintenance/close-days", json={"date": DAY.isoformat()},
                    headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


def test_list_orders_date_desc_then_name(client, db):
    sh = Shift(name=f"Pagi-{uuid.uuid4().hex[:6]}", start_time="07:00", end_time="16:00",
               tolerance_min=15, workdays=[1, 2, 3, 4, 5])
    db.add(sh)
    db.commit()
    rows = [
        ("A1", "Zara", date(2025, 1, 7)),
        ("Z9", "Ani", date(2025, 1, 7)),
        ("B1", "Budi", date(2025, 1, 6)),
    ]
    for code, name, day in rows:
        emp = Employee(name=name, employee_code=code, shift_id=sh.id)
        db.add(emp)
        db.commit()
        db.add(AttendanceDay(employee_id=emp.id, date=day, status="ontime"))
    db.commit()
    r = client.get("/api/v1/attendance?from=2025-01-06&to=2025-01-07", headers=_headers(client))
    assert r.status_code == 200
    assert [(x["date"], x["name"]) for x in r.json()] == [
        ("2025-01-07", "Ani"),
        ("2025-01-07", "Zara"),
        ("2025-01-06", "Budi"),
    ]


def test_list_and_csv_show_effective_no_exit_for_past_waiting(client, db):
    e, _ = _fixture_employee(db)
    db.query(AttendanceEvent).filter_by(employee_id=e.id, direction="exit").delete()
    db.commit()
    attendance.recompute_day(db, e.id, DAY, now=_at(9, 0))
    stored = db.query(AttendanceDay).filter_by(employee_id=e.id, date=DAY).one()
    assert stored.status == "waiting"
    h = _headers(client)
    listed = client.get(f"/api/v1/attendance?from={DAY.isoformat()}&to={DAY.isoformat()}", headers=h)
    assert listed.status_code == 200
    assert listed.json()[0]["status"] == "no_exit"
    assert _export(client, h)[0]["status"] == "no_exit"


def test_patch_accepts_no_entry_rejects_unknown(client, db):
    e, _ = _fixture_employee(db)
    day_id = db.query(AttendanceDay).filter_by(employee_id=e.id).one().id
    h = _headers(client)
    bad = client.patch(
        f"/api/v1/attendance/{day_id}",
        json={"status": "nope", "override_note": "x"},
        headers=h,
    )
    assert bad.status_code == 422
    ok = client.patch(
        f"/api/v1/attendance/{day_id}",
        json={"status": "no_entry", "override_note": "exit saja"},
        headers=h,
    )
    assert ok.status_code == 200
    assert ok.json()["status"] == "no_entry"
    assert ok.json()["override_note"] == "exit saja"


def test_import_exit_without_entry_is_no_entry(client, db):
    e, _ = _fixture_employee(db)
    csv_text = (
        "employee_code,name,date,shift,first_entry,last_exit,duration_min,status,late_minutes,override_note\n"
        "E1,Budi,2025-01-07,Pagi,,16:05:00,,,\n"
    )
    r = client.post(
        "/api/v1/attendance/import",
        files={"file": ("in.csv", csv_text.encode(), "text/csv")},
        headers=_headers(client),
    )
    assert r.status_code == 200
    assert r.json()["created"] == 1
    row = db.query(AttendanceDay).filter_by(employee_id=e.id, date=date(2025, 1, 7)).one()
    assert row.status == "no_entry"
    assert row.duration_min is None and row.late_minutes is None


# --- (f) peringatan exit awal: turunan saat baca, status tidak berubah ------

def test_list_exposes_exit_early_min(client, db):
    early, _ = _fixture_employee(db)
    _fixture_employee(db, code="E2", name="Siti")  # exit 16:05 = sesudah shift selesai
    _move_exit_earlier(db, early.id)
    rows = client.get(f"/api/v1/attendance?date={DAY.isoformat()}", headers=_headers(client)).json()
    assert {r["employee_code"]: r["exit_early_min"] for r in rows} == {"E1": 237, "E2": None}


def test_csv_export_has_exit_early_min_as_last_column(client, db):
    early, _ = _fixture_employee(db)
    _fixture_employee(db, code="E2", name="Siti")
    _move_exit_earlier(db, early.id)
    h = _headers(client)
    res = client.get(f"/api/v1/attendance/rekap.csv?from={DAY}&to={DAY}", headers=h)
    assert next(csv.reader(io.StringIO(res.text)))[-1] == "exit_early_min"
    assert [(r["employee_code"], r["exit_early_min"]) for r in _export(client, h)] == [
        ("E1", "237"), ("E2", ""),
    ]


def test_import_ignores_exit_early_min_column(client, db):
    """Kolom hasil ekspor dibaca sebagai kolom tak dikenal: nilai rekap tidak berubah (Review Focus 4)."""
    e, _ = _fixture_employee(db)
    _move_exit_earlier(db, e.id)
    h = _headers(client)
    rows = _export(client, h)
    assert rows[0]["exit_early_min"] == "237"
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows([{**r, "exit_early_min": "999"} for r in rows])

    r = client.post("/api/v1/attendance/import",
                    files={"file": ("rekap.csv", buf.getvalue().encode(), "text/csv")}, headers=h)
    assert r.status_code == 200
    assert r.json() == {"updated": 1, "created": 0, "skipped": 0}

    day = db.query(AttendanceDay).filter_by(employee_id=e.id, date=DAY).one()
    assert day.last_exit.strftime("%H:%M") == "12:03"
    assert day.status == "ontime"
    assert day.override_note == "import"
    assert _export(client, h)[0]["exit_early_min"] == ""  # baris terkoreksi tidak diberi peringatan


def test_patch_with_note_clears_exit_early_min(client, db):
    e, _ = _fixture_employee(db)
    day = _move_exit_earlier(db, e.id)
    h = _headers(client)
    listed = client.get(f"/api/v1/attendance?date={DAY.isoformat()}", headers=h).json()
    assert listed[0]["exit_early_min"] == 237
    r = client.patch(f"/api/v1/attendance/{day.id}", json={"override_note": "pulang cepat"}, headers=h)
    assert r.status_code == 200
    assert r.json()["exit_early_min"] is None


# --- kebijakan pencocokan dari baris detector_setting (T2) ------------------

def _policy_row(db, **over):
    """Baris id=1 lengkap supaya policy bisa dibaca tanpa default kolom yang tak pernah di-flush."""
    from app.models.detector_setting import DetectorSetting

    values = {
        "default_ai_fps": 5.0, "default_confidence": 0.4, "motion_enabled": True,
        "motion_threshold": 25.0, "motion_min_area": 0.01, "motion_force_interval_s": 2.0,
        "face_min_width_px": 80.0, "face_min_det_score": 0.6, "face_max_yaw": 0.35,
        "face_blur_min": 120.0, "face_min_frames": 3,
        "face_match_threshold": 0.40, "face_match_margin": 0.15, "face_max_pitch": 0.30,
        "face_best_k": 5, "face_ident_min_width_px": 60.0, "face_ident_window_s": 8.0,
    }
    row = db.get(DetectorSetting, 1)
    if row is None:
        row = DetectorSetting(id=1, **values)
        db.add(row)
    for key, value in over.items():
        setattr(row, key, value)
    db.commit()
    return row


def test_embedding_match_follows_db_threshold(db):
    """Ambang baris DB berlaku di jalur absensi tanpa restart; event berikutnya memakai nilai baru."""
    import math
    from app.models.event import Event
    from app.models.face_embedding import FaceEmbedding
    from app.services import face as face_mod

    cam = Camera(name="Gate", host="127.0.0.1")
    e = Employee(name="Budi", employee_code="E9")
    db.add(cam)
    db.add(e)
    db.commit()
    db.refresh(cam)
    db.refresh(e)
    db.add(FaceEmbedding(employee_id=e.id, vector=[1.0, 0.0, 0.0, 0.0], quality=0.9))
    db.commit()
    face_mod.gallery._by_employee = {e.id: [[1.0, 0.0, 0.0, 0.0]]}
    query = [0.45, math.sqrt(1 - 0.45 ** 2), 0.0, 0.0]  # cos = 0.45

    _policy_row(db, face_match_threshold=0.40)
    matched = Event(event_id=str(uuid.uuid4()), type="attendance", camera_id=cam.id, severity="info",
                    ts_event=_at(7, 10), payload={"direction": "entry", "embedding": query, "face_quality": 0.9})
    db.add(matched)
    db.commit()
    row = attendance.handle_face_event(db, matched)
    assert row is not None and row.employee_id == e.id
    db.refresh(matched)
    assert matched.payload["match_reason"] == "matched"

    _policy_row(db, face_match_threshold=0.99)
    rejected = Event(event_id=str(uuid.uuid4()), type="attendance", camera_id=cam.id, severity="info",
                     ts_event=_at(7, 12), payload={"direction": "entry", "embedding": query, "face_quality": 0.9})
    db.add(rejected)
    db.commit()
    assert attendance.handle_face_event(db, rejected) is None
    db.refresh(rejected)
    assert rejected.payload["match_reason"] == "no_match"


# --- keputusan event unified: match_strict + margin, `ambiguous` seperti tidak dikenal ---


def _attendance_event(db, camera_id, payload_over=None):
    from app.models.event import Event

    payload = {"direction": "entry", "embedding": [1.0, 0.0, 0.0, 0.0], "face_quality": 0.9}
    payload.update(payload_over or {})
    ev = Event(event_id=str(uuid.uuid4()), type="attendance", camera_id=camera_id, severity="info",
               ts_event=_at(7, 10), payload=payload)
    db.add(ev)
    db.commit()
    db.refresh(ev)
    return ev


def _two_employees(db, second_vector):
    from app.services import face as face_mod

    cam = Camera(name="Gate", host="127.0.0.1")
    db.add(cam)
    a = Employee(name="Budi", employee_code="E1")
    b = Employee(name="Siti", employee_code="E2")
    db.add_all([a, b])
    db.commit()
    db.refresh(cam)
    db.refresh(a)
    db.refresh(b)
    face_mod.gallery._by_employee = {a.id: [[1.0, 0.0, 0.0, 0.0]], b.id: [list(second_vector)]}
    return cam, a, b


def test_unified_close_second_employee_is_ambiguous_without_record(db):
    cam, _a, _b = _two_employees(db, [0.995, 0.1, 0.0, 0.0])  # cos ≈ 0,995 → margin < 0,15
    _policy_row(db)

    ev = _attendance_event(db, cam.id, {"policy": "unified"})
    assert attendance.handle_face_event(db, ev) is None
    assert db.query(AttendanceEvent).count() == 0
    db.refresh(ev)
    assert (ev.payload["employee_id"], ev.payload["match_reason"]) == (None, "ambiguous")
    assert "embedding" not in ev.payload


def test_unified_matched_event_stores_face_margin(db):
    cam, a, _b = _two_employees(db, [0.0, 1.0, 0.0, 0.0])  # ortogonal → margin 1,0
    _policy_row(db)

    ev = _attendance_event(db, cam.id, {"policy": "unified"})
    row = attendance.handle_face_event(db, ev)
    assert row is not None and row.employee_id == a.id
    db.refresh(ev)
    assert ev.payload["match_reason"] == "matched"
    assert ev.payload["face_margin"] == pytest.approx(1.0)


def test_unified_has_no_low_quality_gate(db):
    """`unified` memakai match_strict tanpa gerbang `low_quality` (kualitas kecil tetap diputuskan)."""
    cam, a, _b = _two_employees(db, [0.0, 1.0, 0.0, 0.0])
    _policy_row(db)

    ev = _attendance_event(db, cam.id, {"policy": "unified", "face_quality": 0.1})
    row = attendance.handle_face_event(db, ev)
    assert row is not None and row.employee_id == a.id
    db.refresh(ev)
    assert ev.payload["match_reason"] == "matched"


def test_event_policy_decides_not_db_row(db):
    """Payload menentukan algoritma: baris DB `legacy` + payload unified → strict; sebaliknya → match_vector."""
    cam, _a, _b = _two_employees(db, [0.98, 0.199, 0.0, 0.0])  # margin 0,02: strict ambiguous, longgar matched

    _policy_row(db, face_attendance_mode="legacy")
    unified = _attendance_event(db, cam.id, {"policy": "unified"})
    assert attendance.handle_face_event(db, unified) is None
    assert unified.payload["match_reason"] == "ambiguous"

    _policy_row(db, face_attendance_mode="unified")
    plain = _attendance_event(db, cam.id)  # tanpa policy → perilaku lama
    assert attendance.handle_face_event(db, plain) is not None
    assert plain.payload["match_reason"] == "matched"


def test_event_without_policy_keeps_low_quality_gate(db):
    cam, _a, _b = _two_employees(db, [0.0, 1.0, 0.0, 0.0])
    _policy_row(db)

    ev = _attendance_event(db, cam.id, {"face_quality": 0.1})
    assert attendance.handle_face_event(db, ev) is None
    db.refresh(ev)
    assert ev.payload["match_reason"] == "low_quality"
