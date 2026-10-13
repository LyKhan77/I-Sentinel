import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.db import get_db
from app.models.audit_log import AuditLog
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


def test_camera_crud_recorded(client, db):
    h = admin_headers(client)
    r = client.post("/api/v1/cameras", json={
        "name": "Gerbang", "host": "10.0.0.9", "rtsp_main": "/live/ch1",
    }, headers=h)
    assert r.status_code == 200, r.text
    cam_id = r.json()["id"]

    r = client.patch(f"/api/v1/cameras/{cam_id}", json={"location": "Lobby Utama"}, headers=h)
    assert r.status_code == 200
    row = db.query(AuditLog).filter_by(action="camera.update").one()
    assert row.target_type == "camera"
    assert row.target_id == str(cam_id)
    assert row.target_label == "Gerbang"
    assert row.changes == {"location": "Lobby Utama"}
    assert row.category == "config"

    r = client.delete(f"/api/v1/cameras/{cam_id}", headers=h)
    assert r.status_code == 200
    row = db.query(AuditLog).filter_by(action="camera.delete").one()
    assert row.target_label == "Gerbang"
    assert row.changes is None

    assert "camera.create" in _actions(db)


def test_location_group_crud_recorded(client, db):
    h = admin_headers(client)
    r = client.post("/api/v1/location-groups", json={"name": "Gedung A"}, headers=h)
    assert r.status_code == 200
    gid = r.json()["id"]
    client.patch(f"/api/v1/location-groups/{gid}", json={"sort_order": 5}, headers=h)
    client.delete(f"/api/v1/location-groups/{gid}", headers=h)
    assert {"location_group.create", "location_group.update", "location_group.delete"} <= _actions(db)
    row = db.query(AuditLog).filter_by(action="location_group.update").one()
    assert row.changes == {"sort_order": 5}
    assert row.target_label == "Gedung A"


def test_stream_source_and_zone_recorded(client, db):
    h = admin_headers(client)
    r = client.post("/api/v1/cameras", json={"name": "Parkir", "host": "10.0.0.10",
                                             "rtsp_main": "/live/ch2"}, headers=h)
    cam_id = r.json()["id"]
    r = client.post("/api/v1/stream-sources", json={"name": "NVR-2", "host": "10.0.0.20",
                                                    "port": 554}, headers=h)
    assert r.status_code == 200, r.text
    sid = r.json()["id"]
    client.patch(f"/api/v1/stream-sources/{sid}", json={"port": 8554}, headers=h)
    assert "stream_source.update" in _actions(db)
    row = db.query(AuditLog).filter_by(action="stream_source.update").one()
    assert row.changes == {"port": 8554}

    # zona wajib 200: bila 422, lengkapi body sesuai field wajib ZoneIn (app/schemas/zone.py)
    r = client.post("/api/v1/zones", json={
        "camera_id": cam_id, "name": "Zona Uji", "polygon": [[0, 0], [1, 0], [1, 1]],
        "type": "restricted", "behaviors": [],
    }, headers=h)
    assert r.status_code == 200, r.text
    zid = r.json()["id"]
    client.delete(f"/api/v1/zones/{zid}", headers=h)
    assert {"zone.create", "zone.delete"} <= _actions(db)
