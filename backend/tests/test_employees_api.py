import datetime as dt

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.db import get_db
from app.core.config import settings
from tests.conftest import *  # noqa


@pytest.fixture
def client(db, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "admin_username", "admin")
    monkeypatch.setattr(settings, "admin_password", "boot123")
    monkeypatch.setattr(settings, "cookie_secure", True)
    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _admin_headers(client):
    tok = client.post("/api/v1/auth/login", json={"username": "admin", "password": "boot123"}).json()["token"]
    return {"Authorization": f"Bearer {tok}"}


SHIFT = {"name": "Pagi", "start_time": "08:00", "end_time": "17:00"}


def _shift(client, h, **over):
    return client.post("/api/v1/shifts", json={**SHIFT, **over}, headers=h)


def _camera(client, h, name="cam1"):
    return client.post("/api/v1/cameras", json={"name": name, "host": "1.2.3.4"}, headers=h).json()


# --- (a) shift CRUD ---------------------------------------------------------

def test_shift_crud_happy(client):
    h = _admin_headers(client)
    r = _shift(client, h)
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Pagi" and body["start_time"] == "08:00" and body["end_time"] == "17:00"
    assert body["tolerance_min"] == 15 and body["workdays"] == [1, 2, 3, 4, 5]
    sid = body["id"]

    assert [s["id"] for s in client.get("/api/v1/shifts", headers=h).json()] == [sid]
    assert client.get(f"/api/v1/shifts/{sid}", headers=h).json()["name"] == "Pagi"

    r = client.patch(f"/api/v1/shifts/{sid}", json={"tolerance_min": 30}, headers=h)
    assert r.status_code == 200 and r.json()["tolerance_min"] == 30

    assert client.delete(f"/api/v1/shifts/{sid}", headers=h).status_code == 200
    assert client.get("/api/v1/shifts", headers=h).json() == []


def test_shift_requires_auth(client):
    assert client.post("/api/v1/shifts", json=SHIFT).status_code == 401


def test_shift_bad_time_422(client):
    h = _admin_headers(client)
    assert _shift(client, h, start_time="7:5").status_code == 422
    assert _shift(client, h, end_time="25:00").status_code == 422


def test_shift_bad_tolerance_422(client):
    h = _admin_headers(client)
    assert _shift(client, h, tolerance_min=200).status_code == 422


# --- (e) workdays validation ------------------------------------------------

def test_shift_workdays_empty_422(client):
    h = _admin_headers(client)
    assert _shift(client, h, workdays=[]).status_code == 422


def test_shift_workdays_out_of_range_422(client):
    h = _admin_headers(client)
    assert _shift(client, h, workdays=[9]).status_code == 422


# --- (b) employee CRUD ------------------------------------------------------

def test_employee_crud_happy(client):
    h = _admin_headers(client)
    r = client.post("/api/v1/employees", json={"name": "Budi", "employee_code": "E001"}, headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Budi" and body["employee_code"] == "E001"
    assert body["active"] is True and body["shift_id"] is None and body["shift_name"] is None
    eid = body["id"]

    assert [e["id"] for e in client.get("/api/v1/employees", headers=h).json()] == [eid]
    r = client.patch(f"/api/v1/employees/{eid}", json={"name": "Budi S", "active": False}, headers=h)
    assert r.status_code == 200 and r.json()["name"] == "Budi S" and r.json()["active"] is False

    assert client.get("/api/v1/employees?active=false", headers=h).json()[0]["id"] == eid
    assert client.get("/api/v1/employees?active=true", headers=h).json() == []


def test_employee_duplicate_code_409(client):
    h = _admin_headers(client)
    client.post("/api/v1/employees", json={"name": "Budi", "employee_code": "E001"}, headers=h)
    r = client.post("/api/v1/employees", json={"name": "Ani", "employee_code": "E001"}, headers=h)
    assert r.status_code == 409


def test_employee_requires_auth(client):
    assert client.post("/api/v1/employees", json={"name": "a", "employee_code": "x"}).status_code == 401


# --- (d) employee + shift ---------------------------------------------------

def test_employee_with_shift_returns_shift_name(client):
    h = _admin_headers(client)
    sid = _shift(client, h).json()["id"]
    body = client.post("/api/v1/employees", json={"name": "Budi", "employee_code": "E001", "shift_id": sid},
                       headers=h).json()
    assert body["shift_id"] == sid and body["shift_name"] == "Pagi"


def test_shift_used_by_employee_delete_409(client):
    h = _admin_headers(client)
    sid = _shift(client, h).json()["id"]
    client.post("/api/v1/employees", json={"name": "Budi", "employee_code": "E001", "shift_id": sid}, headers=h)
    assert client.delete(f"/api/v1/shifts/{sid}", headers=h).status_code == 409


# --- (c) employee delete rules ----------------------------------------------

def test_delete_employee_with_attendance_409(client, db):
    from app.models.attendance import AttendanceEvent
    h = _admin_headers(client)
    cam = _camera(client, h)
    eid = client.post("/api/v1/employees", json={"name": "Budi", "employee_code": "E001"}, headers=h).json()["id"]
    db.add(AttendanceEvent(employee_id=eid, camera_id=cam["id"], direction="entry",
                           ts_event=dt.datetime.now(dt.timezone.utc)))
    db.commit()
    assert client.delete(f"/api/v1/employees/{eid}", headers=h).status_code == 409


def test_delete_employee_clean_removes_faces_dir(client, tmp_path):
    h = _admin_headers(client)
    eid = client.post("/api/v1/employees", json={"name": "Budi", "employee_code": "E001"}, headers=h).json()["id"]
    faces = tmp_path / "faces" / str(eid)
    faces.mkdir(parents=True)
    (faces / "a.jpg").write_bytes(b"x")

    assert client.delete(f"/api/v1/employees/{eid}", headers=h).status_code == 200
    assert not faces.exists()
    assert client.get(f"/api/v1/employees/{eid}", headers=h).status_code == 404


def test_delete_employee_with_attendance_day_409(client, db):
    from app.models.attendance import AttendanceDay
    h = _admin_headers(client)
    eid = client.post("/api/v1/employees", json={"name": "Budi", "employee_code": "E001"}, headers=h).json()["id"]
    db.add(AttendanceDay(employee_id=eid, date=dt.date(2026, 1, 1)))
    db.commit()
    assert client.delete(f"/api/v1/employees/{eid}", headers=h).status_code == 409


def test_delete_employee_removes_embedding_rows(client, db):
    from app.models.face_embedding import FaceEmbedding
    h = _admin_headers(client)
    eid = client.post("/api/v1/employees", json={"name": "Budi", "employee_code": "E001"}, headers=h).json()["id"]
    db.add(FaceEmbedding(employee_id=eid, vector=[0.1, 0.2]))
    db.commit()
    assert db.query(FaceEmbedding).filter_by(employee_id=eid).count() == 1

    assert client.delete(f"/api/v1/employees/{eid}", headers=h).status_code == 200
    assert db.query(FaceEmbedding).filter_by(employee_id=eid).count() == 0


# --- (f) DB constraints -----------------------------------------------------

def test_attendance_day_unique_employee_date(client, db):
    from sqlalchemy.exc import IntegrityError
    from app.models.attendance import AttendanceDay
    h = _admin_headers(client)
    eid = client.post("/api/v1/employees", json={"name": "Budi", "employee_code": "E001"}, headers=h).json()["id"]
    d = dt.date(2026, 1, 1)
    db.add(AttendanceDay(employee_id=eid, date=d)); db.commit()
    db.add(AttendanceDay(employee_id=eid, date=d))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_attendance_event_unique_event_id(client, db):
    from sqlalchemy.exc import IntegrityError
    from app.models.attendance import AttendanceEvent
    h = _admin_headers(client)
    cam = _camera(client, h)
    eid = client.post("/api/v1/employees", json={"name": "Budi", "employee_code": "E001"}, headers=h).json()["id"]
    now = dt.datetime.now(dt.timezone.utc)
    db.add(AttendanceEvent(employee_id=eid, camera_id=cam["id"], direction="entry", ts_event=now, event_id="dup"))
    db.commit()
    db.add(AttendanceEvent(employee_id=eid, camera_id=cam["id"], direction="exit", ts_event=now, event_id="dup"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


# --- (i) validasi refining ---------------------------------------------------

def test_employee_blank_name_or_code_422(client):
    h = _admin_headers(client)
    assert client.post("/api/v1/employees", json={"name": "   ", "employee_code": "E1"}, headers=h).status_code == 422
    assert client.post("/api/v1/employees", json={"name": "Budi", "employee_code": ""}, headers=h).status_code == 422


def test_employee_fields_trimmed_and_trimmed_duplicate_409(client):
    h = _admin_headers(client)
    r = client.post("/api/v1/employees", json={"name": "  Budi ", "employee_code": " E001 "}, headers=h)
    assert r.status_code == 200
    assert r.json()["name"] == "Budi" and r.json()["employee_code"] == "E001"
    assert client.post("/api/v1/employees", json={"name": "Ani", "employee_code": "E001  "}, headers=h).status_code == 409


def test_employee_patch_code_and_blank_code_422(client):
    h = _admin_headers(client)
    eid = client.post("/api/v1/employees", json={"name": "Budi", "employee_code": "E001"}, headers=h).json()["id"]
    r = client.patch(f"/api/v1/employees/{eid}", json={"employee_code": "E002"}, headers=h)
    assert r.status_code == 200 and r.json()["employee_code"] == "E002"
    assert client.patch(f"/api/v1/employees/{eid}", json={"employee_code": "  "}, headers=h).status_code == 422


def test_employee_patch_null_ignored_but_shift_can_be_cleared(client):
    h = _admin_headers(client)
    sid = _shift(client, h).json()["id"]
    eid = client.post("/api/v1/employees", json={"name": "Budi", "employee_code": "E001", "shift_id": sid}, headers=h).json()["id"]
    r = client.patch(f"/api/v1/employees/{eid}", json={"name": None, "active": None}, headers=h)
    assert r.status_code == 200 and r.json()["name"] == "Budi" and r.json()["active"] is True
    r = client.patch(f"/api/v1/employees/{eid}", json={"shift_id": None}, headers=h)
    assert r.status_code == 200 and r.json()["shift_id"] is None and r.json()["shift_name"] is None


def test_shift_blank_name_422(client):
    h = _admin_headers(client)
    assert _shift(client, h, name="  ").status_code == 422


def test_shift_end_not_after_start_422(client):
    h = _admin_headers(client)
    assert _shift(client, h, end_time="07:00").status_code == 422
    assert _shift(client, h, end_time="08:00").status_code == 422


def test_shift_patch_validates_merged_times(client):
    h = _admin_headers(client)
    sid = _shift(client, h).json()["id"]  # 08:00–17:00
    assert client.patch(f"/api/v1/shifts/{sid}", json={"end_time": "07:00"}, headers=h).status_code == 422
    assert client.patch(f"/api/v1/shifts/{sid}", json={"start_time": "18:00"}, headers=h).status_code == 422
    r = client.patch(f"/api/v1/shifts/{sid}", json={"start_time": "06:00", "end_time": "07:00"}, headers=h)
    assert r.status_code == 200 and r.json()["end_time"] == "07:00"


def test_shift_patch_null_ignored(client):
    h = _admin_headers(client)
    sid = _shift(client, h).json()["id"]
    r = client.patch(f"/api/v1/shifts/{sid}", json={"start_time": None, "name": None}, headers=h)
    assert r.status_code == 200 and r.json()["start_time"] == "08:00" and r.json()["name"] == "Pagi"


def test_employee_out_has_photo_count_and_face_ready(client, db):
    from app.models.face_embedding import FaceEmbedding
    h = _admin_headers(client)
    e1 = client.post("/api/v1/employees", json={"name": "Budi", "employee_code": "E001"}, headers=h).json()
    e2 = client.post("/api/v1/employees", json={"name": "Ani", "employee_code": "E002"}, headers=h).json()
    assert e1["photo_count"] == 0 and e1["face_ready"] is False
    for _ in range(3):
        db.add(FaceEmbedding(employee_id=e1["id"], vector=[1.0, 0.0, 0.0, 0.0], quality=0.9))
    db.add(FaceEmbedding(employee_id=e2["id"], vector=[0.0, 1.0, 0.0, 0.0], quality=0.9))
    db.commit()
    by_id = {e["id"]: e for e in client.get("/api/v1/employees", headers=h).json()}
    assert by_id[e1["id"]]["photo_count"] == 3 and by_id[e1["id"]]["face_ready"] is True
    assert by_id[e2["id"]]["photo_count"] == 1 and by_id[e2["id"]]["face_ready"] is False
