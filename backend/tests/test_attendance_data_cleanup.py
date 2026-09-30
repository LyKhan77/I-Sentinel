"""mode="attendance_data": hapus permanen riwayat, rekap, entri Inbox, dan media absensi
untuk karyawan terpilih (atau semua) pada rentang tanggal — tindakan admin eksplisit, tidak
bisa dipulihkan. Beda dengan attendance_media: mode ini juga menghapus attendance_event dan
attendance_day (termasuk override_note)."""
import logging
import os
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.db import get_db
from app.models.attendance import AttendanceDay, AttendanceEvent
from app.models.camera import Camera
from app.models.employee import Employee
from app.models.event import Event
from app.services import retention
from tests.conftest import *  # noqa


def _local(y, m, d, hh=12, mm=0):
    return datetime(y, m, d, hh, mm).astimezone()


def _file(root, rel, size=100):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(b"x" * size)
    return path


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(retention.settings, "storage_root", str(tmp_path))
    return str(tmp_path)


def _employee(db, name, code):
    emp = Employee(name=name, employee_code=code)
    db.add(emp); db.commit(); db.refresh(emp)
    return emp


def _att(db, emp, ts, snap=None, cam=1):
    """AttendanceEvent + Event Inbox absensi terkait."""
    ev = Event(type="attendance", ts_event=ts, camera_id=cam, snapshot_path=snap,
               payload={"direction": "entry", "employee_id": emp.id})
    db.add(ev); db.commit(); db.refresh(ev)
    row = AttendanceEvent(employee_id=emp.id, camera_id=cam, direction="entry", ts_event=ts,
                          snapshot_path=snap, event_id=ev.event_id)
    db.add(row); db.commit(); db.refresh(row)
    return ev, row


def _unknown_event(db, ts, cam=1):
    """Event absensi wajah tak dikenal: tidak punya baris AttendanceEvent."""
    ev = Event(type="attendance", ts_event=ts, camera_id=cam, payload={"direction": "entry", "employee_id": None})
    db.add(ev); db.commit(); db.refresh(ev)
    return ev


def _setup_two_employees(db):
    db.add(Camera(id=1, name="c1", host="h")); db.commit()
    return _employee(db, "Ani", "A-1"), _employee(db, "Budi", "B-1")


def test_deletes_only_selected_employee_rows_media_and_inbox(db, root):
    a, b = _setup_two_employees(db)
    snap_a = _file(root, "snapshots/a.jpg")
    snap_b = _file(root, "snapshots/b.jpg")
    ev_a, row_a = _att(db, a, _local(2026, 9, 10), snap="snapshots/a.jpg")
    day_a = AttendanceDay(employee_id=a.id, date=date(2026, 9, 10), status="ontime")
    db.add(day_a); db.commit()
    ev_b, row_b = _att(db, b, _local(2026, 9, 10), snap="snapshots/b.jpg")
    day_b = AttendanceDay(employee_id=b.id, date=date(2026, 9, 10), status="ontime")
    db.add(day_b); db.commit()
    ev_a_out, row_a_out = _att(db, a, _local(2026, 9, 20))  # di luar rentang

    r = retention.cleanup_attendance_data(db, date(2026, 9, 10), date(2026, 9, 10), [a.id], dry_run=False)
    assert (r["attendance_events"], r["days"], r["events"], r["files"]) == (1, 1, 1, 1)
    assert db.get(AttendanceEvent, row_a.id) is None and db.get(Event, ev_a.id) is None
    assert not os.path.exists(snap_a)
    assert db.get(AttendanceDay, day_a.id) is None
    assert db.get(AttendanceEvent, row_b.id) is not None and db.get(Event, ev_b.id) is not None
    assert os.path.exists(snap_b)
    assert db.get(AttendanceDay, day_b.id) is not None
    assert db.get(AttendanceEvent, row_a_out.id) is not None


def test_boundary_local_day(db, root):
    a, _b = _setup_two_employees(db)
    _late_ev, late_row = _att(db, a, _local(2026, 9, 10, 23, 59))
    _early_ev, early_row = _att(db, a, _local(2026, 9, 11, 0, 0))
    retention.cleanup_attendance_data(db, date(2026, 9, 10), date(2026, 9, 10), [a.id], dry_run=False)
    assert db.get(AttendanceEvent, late_row.id) is None
    assert db.get(AttendanceEvent, early_row.id) is not None


def test_employee_filter_keeps_unknown_face_events(db, root):
    a, _b = _setup_two_employees(db)
    unk = _unknown_event(db, _local(2026, 9, 10))
    ev_a, _row_a = _att(db, a, _local(2026, 9, 10))
    retention.cleanup_attendance_data(db, date(2026, 9, 10), date(2026, 9, 10), [a.id], dry_run=False)
    assert db.get(Event, unk.id) is not None
    assert db.get(Event, ev_a.id) is None


def test_all_employees_removes_unknown_face_events(db, root):
    a, _b = _setup_two_employees(db)
    unk = _unknown_event(db, _local(2026, 9, 10))
    ev_a, _row_a = _att(db, a, _local(2026, 9, 10))
    retention.cleanup_attendance_data(db, date(2026, 9, 10), date(2026, 9, 10), None, dry_run=False)
    assert db.get(Event, unk.id) is None
    assert db.get(Event, ev_a.id) is None


def test_override_note_days_deleted_too(db, root):
    a, _b = _setup_two_employees(db)
    day = AttendanceDay(employee_id=a.id, date=date(2026, 9, 10), status="ontime", override_note="koreksi manual")
    db.add(day); db.commit()
    r = retention.cleanup_attendance_data(db, date(2026, 9, 10), date(2026, 9, 10), [a.id], dry_run=False)
    assert r["days"] == 1
    assert db.get(AttendanceDay, day.id) is None


def test_shared_file_referenced_outside_selection_kept(db, root):
    a, b = _setup_two_employees(db)
    shared = _file(root, "snapshots/shared.jpg")
    _ev_a, _row_a = _att(db, a, _local(2026, 9, 10), snap="snapshots/shared.jpg")
    _ev_b, row_b = _att(db, b, _local(2026, 9, 10), snap="snapshots/shared.jpg")  # b tidak dipilih
    r = retention.cleanup_attendance_data(db, date(2026, 9, 10), date(2026, 9, 10), [a.id], dry_run=False)
    assert r["files"] == 0
    assert os.path.exists(shared)
    db.refresh(row_b)
    assert row_b.snapshot_path == "snapshots/shared.jpg"


def test_dry_run_no_changes_and_per_employee_breakdown(db, root):
    a, b = _setup_two_employees(db)
    snap_a = _file(root, "snapshots/a.jpg")
    _ev_a, _row_a = _att(db, a, _local(2026, 9, 10), snap="snapshots/a.jpg")
    db.add(AttendanceDay(employee_id=a.id, date=date(2026, 9, 10), status="ontime")); db.commit()
    _ev_b, _row_b = _att(db, b, _local(2026, 9, 10))
    db.add(AttendanceDay(employee_id=b.id, date=date(2026, 9, 10), status="ontime")); db.commit()

    r = retention.cleanup_attendance_data(db, date(2026, 9, 10), date(2026, 9, 10), None, dry_run=True)
    assert r["dry_run"] is True
    assert (r["attendance_events"], r["days"], r["events"], r["files"]) == (2, 2, 2, 1)
    assert r["employees"] == [
        {"id": a.id, "name": "Ani", "attendance_events": 1, "days": 1},
        {"id": b.id, "name": "Budi", "attendance_events": 1, "days": 1},
    ]
    assert os.path.exists(snap_a)
    assert db.query(AttendanceEvent).count() == 2
    assert db.query(AttendanceDay).count() == 2
    assert db.query(Event).filter(Event.type == "attendance").count() == 2


@pytest.fixture
def client(db, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "admin_username", "admin")
    monkeypatch.setattr(settings, "admin_password", "boot123")
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_api_validation_422_and_viewer_403(client, root):
    h = admin_headers(client)
    yesterday = date.today() - timedelta(days=1)
    ok = {"date_from": str(yesterday), "date_to": str(yesterday), "mode": "attendance_data",
          "all_employees": True, "dry_run": True}
    assert client.post("/api/v1/storage/cleanup", json=ok, headers=h).status_code == 200
    today = date.today()
    bad_cases = (
        {**ok, "date_to": str(today)},  # hari ini belum boleh (shift mungkin masih berjalan)
        {**ok, "camera_ids": [1]},
        {**{k: v for k, v in ok.items() if k != "all_employees"}, "types": ["intrusion"]},
        {"date_from": str(yesterday), "date_to": str(yesterday), "mode": "attendance_data", "dry_run": True},  # neither
        {**ok, "employee_ids": [1]},  # both all_employees and employee_ids
        {"date_from": str(yesterday), "date_to": str(yesterday), "mode": "events", "employee_ids": [1], "dry_run": True},
        {"date_from": str(yesterday), "date_to": str(yesterday), "mode": "attendance_media",
         "all_employees": True, "dry_run": True},
    )
    for bad in bad_cases:
        assert client.post("/api/v1/storage/cleanup", json=bad, headers=h).status_code == 422, bad
    assert client.post("/api/v1/storage/cleanup", json=ok, headers=viewer_headers(client)).status_code == 403


def test_audit_log_has_ids_and_counts_not_names(client, db, root, caplog):
    yesterday = date.today() - timedelta(days=1)
    a = _employee(db, "RahasiaNama", "R-1")
    body = {"date_from": str(yesterday), "date_to": str(yesterday), "mode": "attendance_data",
            "employee_ids": [a.id], "dry_run": False}
    with caplog.at_level(logging.INFO, logger="app.api.storage"):
        r = client.post("/api/v1/storage/cleanup", json=body, headers=admin_headers(client))
    assert r.status_code == 200
    assert "attendance data cleanup by admin" in caplog.text
    assert str(a.id) in caplog.text and "0 attendance_events" in caplog.text
    assert "RahasiaNama" not in caplog.text
