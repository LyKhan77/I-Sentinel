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
                {**ok, "date_from": "kemarin"},
                {**ok, "hapus_semua": True}):
        assert client.post("/api/v1/storage/cleanup", json=bad, headers=h).status_code == 422, bad
    assert client.post("/api/v1/storage/cleanup", json=ok, headers=viewer_headers(client)).status_code == 403
