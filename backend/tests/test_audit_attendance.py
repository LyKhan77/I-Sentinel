import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.db import get_db
from app.models.audit_log import AuditLog
from app.models.employee import Employee
from app.models.shift import Shift
from tests.conftest import admin_headers  # noqa


@pytest.fixture
def client(db, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "admin_password", "boot123")
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _actions(db):
    return {r[0] for r in db.query(AuditLog.action).all()}


def test_employee_crud_recorded(client, db):
    h = admin_headers(client)
    r = client.post("/api/v1/employees", json={"name": "Budi", "employee_code": "E001"}, headers=h)
    assert r.status_code == 200, r.text
    eid = r.json()["id"]
    r = client.patch(f"/api/v1/employees/{eid}", json={"name": "Budi Santoso"}, headers=h)
    assert r.status_code == 200
    row = db.query(AuditLog).filter_by(action="employee.update").one()
    assert row.changes == {"name": "Budi Santoso"}
    assert row.target_label == "Budi Santoso"
    assert row.target_type == "employee"
    assert row.target_id == str(eid)
    r = client.delete(f"/api/v1/employees/{eid}", headers=h)
    assert r.status_code == 200
    assert {"employee.create", "employee.delete"} <= _actions(db)


def test_shift_crud_recorded(client, db):
    h = admin_headers(client)
    r = client.post("/api/v1/shifts", json={"name": "Pagi", "start_time": "07:00",
                                            "end_time": "15:00"}, headers=h)
    assert r.status_code == 200, r.text
    sid = r.json()["id"]
    client.patch(f"/api/v1/shifts/{sid}", json={"tolerance_min": 20}, headers=h)
    client.delete(f"/api/v1/shifts/{sid}", headers=h)
    assert {"shift.create", "shift.update", "shift.delete"} <= _actions(db)
    row = db.query(AuditLog).filter_by(action="shift.update").one()
    assert row.changes == {"tolerance_min": 20}


def test_attendance_correct_and_import_recorded(client, db):
    h = admin_headers(client)
    db.add(Shift(id=1, name="Pagi", start_time="07:00", end_time="15:00"))
    db.add(Employee(id=1, name="Budi", employee_code="E001", shift_id=1))
    db.commit()

    # koreksi manual butuh baris AttendanceDay → impor dulu (sekaligus menguji import)
    csv_text = "employee_code,date,first_entry,last_exit\nE001,2026-10-01,07:05:00,15:02:00\n"
    r = client.post("/api/v1/attendance/import",
                    files={"file": ("rekap.csv", csv_text, "text/csv")}, headers=h)
    assert r.status_code == 200, r.text
    row = db.query(AuditLog).filter_by(action="attendance.import").one()
    assert row.changes == {"created": 1, "updated": 0, "skipped": 0}

    from app.models.attendance import AttendanceDay
    day = db.query(AttendanceDay).one()
    r = client.patch(f"/api/v1/attendance/{day.id}",
                     json={"override_note": "dinas luar"}, headers=h)
    assert r.status_code == 200, r.text
    row = db.query(AuditLog).filter_by(action="attendance.correct").one()
    assert row.changes == {"override_note": "dinas luar"}
    assert row.category == "attendance"
    assert row.target_type == "attendance_day"


def test_enrollment_can_join_caller_transaction(db):
    from app.services import face
    from app.models.face_embedding import FaceEmbedding
    emp = Employee(name="Budi", employee_code="E001")
    db.add(emp)
    db.commit()
    best = face.FaceResult(vector=[1.0, 0.0], det_score=0.9, bbox=[0, 0, 10, 10], quality=0.9)
    face._save_embedding(db, emp.id, best, "faces/test.jpg", commit=False)
    db.rollback()
    assert db.query(FaceEmbedding).count() == 0
