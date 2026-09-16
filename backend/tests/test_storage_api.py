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
