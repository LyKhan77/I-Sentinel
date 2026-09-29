import os
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.db import get_db
from app.models.alert import Alert
from app.models.camera import Camera
from app.models.event import Event
from app.services import retention
from tests.conftest import *  # noqa


def _local(y, m, d, hh=12, mm=0):
    """Waktu lokal server (cleanup memakai tanggal lokal)."""
    return datetime(y, m, d, hh, mm).astimezone()


def _file(root, rel, size=100):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(b"x" * size)
    return path


def _ev(db, ts, type_="intrusion", cam=None, clip=None, snap=None):
    ev = Event(type=type_, ts_event=ts, camera_id=cam, clip_path=clip, snapshot_path=snap)
    db.add(ev); db.commit(); db.refresh(ev)
    return ev


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(retention.settings, "storage_root", str(tmp_path))
    return str(tmp_path)


def test_cleanup_dry_run_changes_nothing(db, root):
    clip = _file(root, "clips/a.mp4", 300)
    ev = _ev(db, _local(2026, 9, 10), clip="clips/a.mp4")
    r = retention.cleanup(db, date(2026, 9, 10), date(2026, 9, 10), dry_run=True)
    assert r == {"events": 1, "files": 1, "bytes": 300, "dry_run": True}
    assert os.path.exists(clip) and db.get(Event, ev.id) is not None


def test_cleanup_deletes_events_media_and_alerts(db, root):
    clip = _file(root, "clips/a.mp4")
    snap = _file(root, "snapshots/a.jpg")
    ev = _ev(db, _local(2026, 9, 10), clip="clips/a.mp4", snap="snapshots/a.jpg")
    db.add(Alert(event_id=ev.id, type="intrusion", status="sent")); db.commit()
    outside = _ev(db, _local(2026, 9, 12))
    r = retention.cleanup(db, date(2026, 9, 10), date(2026, 9, 11), dry_run=False)
    assert (r["events"], r["files"]) == (1, 2)
    assert not os.path.exists(clip) and not os.path.exists(snap)
    assert db.get(Event, ev.id) is None and db.query(Alert).count() == 0
    assert db.get(Event, outside.id) is not None


def test_cleanup_never_deletes_attendance(db, root):
    att = _ev(db, _local(2026, 9, 10), type_="attendance")
    assert retention.cleanup(db, date(2026, 9, 10), date(2026, 9, 10), dry_run=False)["events"] == 0
    r = retention.cleanup(db, date(2026, 9, 10), date(2026, 9, 10), types=["attendance"], dry_run=False)
    assert r["events"] == 0 and db.get(Event, att.id) is not None


def test_cleanup_keeps_clip_shared_with_event_outside_range(db, root):
    clip = _file(root, "clips/shared.mp4")
    _ev(db, _local(2026, 9, 10, 23, 59), clip="clips/shared.mp4")
    keep = _ev(db, _local(2026, 9, 11, 0, 1), clip="clips/shared.mp4")
    r = retention.cleanup(db, date(2026, 9, 10), date(2026, 9, 10), dry_run=False)
    assert (r["events"], r["files"]) == (1, 0)
    assert os.path.exists(clip) and db.get(Event, keep.id).clip_path == "clips/shared.mp4"


def test_cleanup_local_day_boundaries(db, root):
    late = _ev(db, _local(2026, 9, 10, 23, 30))
    early = _ev(db, _local(2026, 9, 11, 0, 30))
    retention.cleanup(db, date(2026, 9, 11), date(2026, 9, 11), dry_run=False)
    assert db.get(Event, late.id) is not None and db.get(Event, early.id) is None


def test_cleanup_filters_camera_and_type(db, root):
    db.add_all([Camera(id=1, name="c1", host="h"), Camera(id=2, name="c2", host="h")]); db.commit()
    a = _ev(db, _local(2026, 9, 10), cam=1, type_="intrusion")
    b = _ev(db, _local(2026, 9, 10), cam=2, type_="intrusion")
    c = _ev(db, _local(2026, 9, 10), cam=1, type_="loitering")
    r = retention.cleanup(db, date(2026, 9, 10), date(2026, 9, 10), camera_ids=[1], types=["loitering"], dry_run=False)
    assert r["events"] == 1
    assert db.get(Event, c.id) is None and db.get(Event, a.id) is not None and db.get(Event, b.id) is not None


@pytest.fixture
def client(db, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "admin_username", "admin")
    monkeypatch.setattr(settings, "admin_password", "boot123")
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_cleanup_api_validation_and_admin_only(client, root):
    h = admin_headers(client)
    today = date.today()
    ok = {"date_from": str(today - timedelta(days=3)), "date_to": str(today), "dry_run": True}
    r = client.post("/api/v1/storage/cleanup", json=ok, headers=h)
    assert r.status_code == 200 and r.json() == {"events": 0, "files": 0, "bytes": 0, "dry_run": True}
    for bad in ({**ok, "date_from": str(today), "date_to": str(today - timedelta(days=1))},
                {**ok, "date_to": str(today + timedelta(days=1))},
                {**ok, "types": ["meteor"]},
                {**ok, "types": ["attendance"]},
                {**ok, "date_from": "kemarin"},
                {**ok, "hapus_semua": True}):
        assert client.post("/api/v1/storage/cleanup", json=bad, headers=h).status_code == 422, bad
    assert client.post("/api/v1/storage/cleanup", json=ok, headers=viewer_headers(client)).status_code == 403


def test_system_logs_only_deleted_when_selected(db, root):
    """Log sistem (node offline/LWT): tidak ikut bila Jenis kosong; terhapus bila dipilih eksplisit."""
    sys_ev = _ev(db, _local(2026, 9, 10), type_="system")
    beh = _ev(db, _local(2026, 9, 10), type_="intrusion")
    r = retention.cleanup(db, date(2026, 9, 10), date(2026, 9, 10), dry_run=False)
    assert r["events"] == 1 and db.get(Event, sys_ev.id) is not None and db.get(Event, beh.id) is None
    r = retention.cleanup(db, date(2026, 9, 10), date(2026, 9, 10), types=["system"], dry_run=False)
    assert r["events"] == 1 and db.get(Event, sys_ev.id) is None


def test_system_type_accepted_by_api(client, root):
    today = date.today()
    body = {"date_from": str(today), "date_to": str(today), "types": ["system"], "dry_run": True}
    assert client.post("/api/v1/storage/cleanup", json=body, headers=admin_headers(client)).status_code == 200


def test_cleanup_dry_run_keeps_alerts(db, root):
    ev = _ev(db, _local(2026, 9, 10))
    db.add(Alert(event_id=ev.id, type="intrusion", status="sent")); db.commit()
    retention.cleanup(db, date(2026, 9, 10), date(2026, 9, 10), dry_run=True)
    assert db.query(Alert).count() == 1 and db.get(Event, ev.id) is not None


def test_cleanup_keeps_rows_when_file_removal_fails(db, root, monkeypatch):
    """Baris & alert dihapus lebih dulu; file gagal hapus → sisa file disapu orphan sweep, tanpa baris rusak."""
    clip = _file(root, "clips/a.mp4")
    ev = _ev(db, _local(2026, 9, 10), clip="clips/a.mp4")
    db.add(Alert(event_id=ev.id, type="intrusion", status="sent")); db.commit()

    def _boom(_path):
        raise OSError("device busy")

    monkeypatch.setattr(retention.os, "remove", _boom)
    r = retention.cleanup(db, date(2026, 9, 10), date(2026, 9, 10), dry_run=False)
    assert (r["events"], r["files"], r["bytes"]) == (1, 0, 0)
    assert db.get(Event, ev.id) is None and db.query(Alert).count() == 0 and os.path.exists(clip)


def test_cleanup_defaults_to_dry_run_when_field_omitted(client, db, root):
    clip = _file(root, "clips/keep.mp4")
    today = date.today()
    ev = _ev(db, datetime.now().astimezone(), clip="clips/keep.mp4")
    body = {"date_from": str(today), "date_to": str(today)}
    r = client.post("/api/v1/storage/cleanup", json=body, headers=admin_headers(client))
    assert r.status_code == 200 and r.json()["dry_run"] is True
    assert os.path.exists(clip) and db.get(Event, ev.id) is not None


def test_cleanup_audit_log_records_success_and_failure(client, db, root, caplog, monkeypatch):
    import logging

    from fastapi.testclient import TestClient

    from app.main import app

    today = date.today()
    body = {"date_from": str(today), "date_to": str(today), "dry_run": False}
    with caplog.at_level(logging.INFO, logger="app.api.storage"):
        assert client.post("/api/v1/storage/cleanup", json=body, headers=admin_headers(client)).status_code == 200
    assert "event cleanup by admin" in caplog.text and "0 events" in caplog.text

    caplog.clear()
    monkeypatch.setattr(retention, "cleanup", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app, raise_server_exceptions=False) as c:
        with caplog.at_level(logging.INFO, logger="app.api.storage"):
            h = admin_headers(client)
            assert c.post("/api/v1/storage/cleanup", json=body, headers=h).status_code == 500
    assert "event cleanup by admin failed" in caplog.text


# --- mode "attendance_media": hapus foto/crop absensi, rekap & riwayat tetap ---

def _employee(db):
    from app.models.employee import Employee
    if db.get(Camera, 1) is None:  # attendance_event.camera_id → FK camera (SQLite tes menegakkan FK)
        db.add(Camera(id=1, name="c1", host="h")); db.commit()
    emp = Employee(name="Uji", employee_code="UJI-1")
    db.add(emp); db.commit(); db.refresh(emp)
    return emp


def _att(db, emp, ts, snap=None, crop=None, cam=None):
    from app.models.attendance import AttendanceEvent
    ev = Event(type="attendance", ts_event=ts, camera_id=cam, snapshot_path=snap,
               payload={"direction": "entry", "employee_id": emp.id, "crop_path": crop})
    db.add(ev); db.commit(); db.refresh(ev)
    row = AttendanceEvent(employee_id=emp.id, camera_id=cam or 1, direction="entry", ts_event=ts,
                          snapshot_path=crop, event_id=ev.event_id)
    db.add(row); db.commit(); db.refresh(row)
    return ev, row


def test_attendance_media_mode_keeps_rows_and_recap(db, root):
    from app.models.attendance import AttendanceDay, AttendanceEvent
    emp = _employee(db)
    snap = _file(root, "snapshots/att.jpg", 200)
    crop = _file(root, "crops/att.jpg", 50)
    ev, row = _att(db, emp, _local(2026, 9, 10), snap="snapshots/att.jpg", crop="crops/att.jpg")
    db.add(AttendanceDay(employee_id=emp.id, date=date(2026, 9, 10), status="ontime")); db.commit()
    beh = _ev(db, _local(2026, 9, 10), clip=None, snap=None)

    r = retention.cleanup(db, date(2026, 9, 10), date(2026, 9, 10), mode="attendance_media", dry_run=True)
    assert r == {"events": 1, "files": 2, "bytes": 250, "dry_run": True}
    assert os.path.exists(snap) and os.path.exists(crop)

    r = retention.cleanup(db, date(2026, 9, 10), date(2026, 9, 10), mode="attendance_media", dry_run=False)
    assert (r["events"], r["files"], r["bytes"]) == (1, 2, 250)
    assert not os.path.exists(snap) and not os.path.exists(crop)
    db.refresh(row)
    assert db.get(Event, ev.id) is None  # entri Inbox absensi ikut hilang (media habis)
    assert row.snapshot_path is None and db.get(AttendanceEvent, row.id) is not None  # riwayat tetap
    assert db.query(AttendanceDay).count() == 1 and db.get(Event, beh.id) is not None


def test_attendance_media_mode_filters_camera_and_keeps_shared_files(db, root):
    db.add_all([Camera(id=1, name="c1", host="h"), Camera(id=2, name="c2", host="h")]); db.commit()
    emp = _employee(db)
    shared = _file(root, "snapshots/shared.jpg")
    other = _file(root, "snapshots/cam2.jpg")
    _att(db, emp, _local(2026, 9, 10), snap="snapshots/shared.jpg", cam=1)
    _att(db, emp, _local(2026, 9, 12), snap="snapshots/shared.jpg", cam=1)  # di luar rentang
    ev2, _ = _att(db, emp, _local(2026, 9, 10), snap="snapshots/cam2.jpg", cam=2)
    r = retention.cleanup(db, date(2026, 9, 10), date(2026, 9, 10), camera_ids=[1],
                          mode="attendance_media", dry_run=False)
    assert (r["events"], r["files"]) == (1, 0)
    assert os.path.exists(shared) and os.path.exists(other)
    db.refresh(ev2)
    assert ev2.snapshot_path == "snapshots/cam2.jpg"


def test_attendance_media_mode_api(client, root):
    h = admin_headers(client)
    today = date.today()
    base = {"date_from": str(today), "date_to": str(today), "dry_run": True}
    r = client.post("/api/v1/storage/cleanup", json={**base, "mode": "attendance_media"}, headers=h)
    assert r.status_code == 200 and r.json()["events"] == 0
    for bad in ({**base, "mode": "attendance_media", "types": ["intrusion"]}, {**base, "mode": "semua"}):
        assert client.post("/api/v1/storage/cleanup", json=bad, headers=h).status_code == 422, bad
