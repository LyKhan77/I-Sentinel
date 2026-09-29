from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.db import get_db
from app.models.event import Event
from app.models.setting import Setting
from tests.conftest import *  # noqa


@pytest.fixture
def client(db, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "admin_username", "admin")
    monkeypatch.setattr(settings, "admin_password", "boot123")
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_stats_shape(client, db, tmp_path, monkeypatch):
    from app.services import retention

    monkeypatch.setattr(retention.settings, "storage_root", str(tmp_path))
    monkeypatch.setattr(retention.settings, "retention_days", 30)
    client.get("/api/v1/cameras")  # pastikan app jalan
    r = client.get("/api/v1/storage/stats", headers=admin_headers(client))
    assert r.status_code == 200
    body = r.json()
    assert body["retention_days"] == 30
    assert body["storage_root"] == str(tmp_path)
    assert set(body["kinds"].keys()) == {"clips", "snapshots", "crops"}
    assert body["disk"]["total"] > 0
    assert body["last_sweep"] is None


def test_sweep_requires_admin(client, db, tmp_path, monkeypatch):
    from app.services import retention

    monkeypatch.setattr(retention.settings, "storage_root", str(tmp_path))
    assert client.post("/api/v1/storage/sweep").status_code == 401
    viewer = viewer_headers(client)
    assert client.post("/api/v1/storage/sweep", headers=viewer).status_code == 403


def test_sweep_records_last_run(client, db, tmp_path, monkeypatch):
    from app.services import retention

    monkeypatch.setattr(retention.settings, "storage_root", str(tmp_path))
    monkeypatch.setattr(retention.settings, "retention_days", 30)
    now = datetime.now(timezone.utc)
    ev = Event(
        type="intrusion",
        ts_event=now - timedelta(days=90),
        clip_path="clips/old.mp4",
    )
    db.add(ev)
    db.commit()

    r = client.post("/api/v1/storage/sweep?dry_run=true", headers=admin_headers(client))
    assert r.status_code == 200
    assert r.json()["events_marked"] == 1

    row = db.get(Setting, "retention_last_sweep")
    assert row is not None
    assert row.value["events_marked"] == 1
    assert "at" in row.value

    stats = client.get("/api/v1/storage/stats", headers=admin_headers(client)).json()
    assert stats["last_sweep"]["events_marked"] == 1


def test_settings_default_from_env_and_partial_put(client, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "retention_days", 30)
    h = admin_headers(client)
    assert client.get("/api/v1/storage/settings", headers=h).json() == \
        {"clip_days": 30, "snapshot_days": 30, "disk_alert_percent": 85}
    r = client.put("/api/v1/storage/settings", json={"clip_days": 7}, headers=h)
    assert r.status_code == 200 and r.json()["clip_days"] == 7
    monkeypatch.setattr(settings, "retention_days", 45)  # yang tidak disimpan tetap ikut env
    assert client.get("/api/v1/storage/settings", headers=h).json() == \
        {"clip_days": 7, "snapshot_days": 45, "disk_alert_percent": 85}


def test_settings_validation_and_admin_only(client):
    h = admin_headers(client)
    for body in ({"clip_days": 0}, {"snapshot_days": 3651}, {"disk_alert_percent": 49},
                 {"disk_alert_percent": 100}, {"foo": 1}, {"clip_days": "tujuh"}):
        assert client.put("/api/v1/storage/settings", json=body, headers=h).status_code == 422, body
    assert client.put("/api/v1/storage/settings", json={"clip_days": 7},
                      headers=viewer_headers(client)).status_code == 403


def test_stats_includes_settings_and_disk_alert(client, tmp_path, monkeypatch):
    from app.services import retention
    monkeypatch.setattr(retention.settings, "storage_root", str(tmp_path))
    monkeypatch.setattr(retention.settings, "retention_days", 30)
    h = admin_headers(client)
    client.put("/api/v1/storage/settings", json={"clip_days": 14, "disk_alert_percent": 85}, headers=h)
    usage = {"total": 100, "used": 90, "free": 10, "percent": 90.0}
    monkeypatch.setattr(retention, "disk_usage", lambda root: usage)
    body = client.get("/api/v1/storage/stats", headers=h).json()
    assert body["settings"] == {"clip_days": 14, "snapshot_days": 30, "disk_alert_percent": 85}
    assert body["retention_days"] == 14
    assert body["disk_alert"] == {"threshold": 85, "over": True}
    usage["percent"] = 80.0
    assert client.get("/api/v1/storage/stats", headers=h).json()["disk_alert"]["over"] is False
