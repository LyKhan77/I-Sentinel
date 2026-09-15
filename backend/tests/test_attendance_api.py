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
    e = Employee(name=name, employee_code=code, shift_id=sh.id)
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
