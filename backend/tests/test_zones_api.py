import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.core.db import get_db
from tests.conftest import *  # noqa

@pytest.fixture
def client(db, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "admin_username", "admin")
    monkeypatch.setattr(settings, "admin_password", "boot123")
    monkeypatch.setattr(settings, "cookie_secure", True)
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()

def _admin_headers(client):
    tok = client.post("/api/v1/auth/login", json={"username": "admin", "password": "boot123"}).json()["token"]
    return {"Authorization": f"Bearer {tok}"}

VALID = {"camera_id": 1, "name": "z1", "type": "restricted",
         "polygon": [[0.1, 0.1], [0.5, 0.1], [0.5, 0.5]]}

def _camera(client, h, name="cam1"):
    return client.post("/api/v1/cameras", json={"name": name, "host": "1.2.3.4"}, headers=h).json()

def test_create_zone_requires_auth(client):
    assert client.post("/api/v1/zones", json=VALID).status_code == 401

def test_create_zone_as_admin(client):
    h = _admin_headers(client)
    cam = _camera(client, h)
    r = client.post("/api/v1/zones", json={**VALID, "camera_id": cam["id"]}, headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "z1" and body["type"] == "restricted"
    assert body["camera_id"] == cam["id"] and body["camera_name"] == "cam1"
    assert body["severity"] == "warning" and body["rate_limit_min"] == 5
    assert body["snapshot"] is True and body["telegram"] is False and body["active"] is True
    assert body["direction"] is None and body["schedule"] is None

def test_create_zone_polygon_two_points_422(client):
    h = _admin_headers(client)
    cam = _camera(client, h)
    r = client.post("/api/v1/zones", json={**VALID, "camera_id": cam["id"], "polygon": [[0.1, 0.1], [0.5, 0.5]]}, headers=h)
    assert r.status_code == 422

def test_create_zone_polygon_coord_out_of_range_422(client):
    h = _admin_headers(client)
    cam = _camera(client, h)
    r = client.post("/api/v1/zones", json={**VALID, "camera_id": cam["id"], "polygon": [[0.1, 0.1], [1.5, 0.1], [0.5, 0.5]]}, headers=h)
    assert r.status_code == 422

def test_create_zone_absensi_without_direction_422(client):
    h = _admin_headers(client)
    cam = _camera(client, h)
    r = client.post("/api/v1/zones", json={**VALID, "camera_id": cam["id"], "type": "absensi"}, headers=h)
    assert r.status_code == 422

def test_create_zone_bad_type_422(client):
    h = _admin_headers(client)
    cam = _camera(client, h)
    r = client.post("/api/v1/zones", json={**VALID, "camera_id": cam["id"], "type": "nope"}, headers=h)
    assert r.status_code == 422

def test_list_zones_filter_camera_id(client):
    h = _admin_headers(client)
    cam1 = _camera(client, h, "cam1")
    cam2 = _camera(client, h, "cam2")
    client.post("/api/v1/zones", json={**VALID, "camera_id": cam1["id"]}, headers=h)
    client.post("/api/v1/zones", json={**VALID, "name": "z2", "camera_id": cam2["id"]}, headers=h)
    all_zones = client.get("/api/v1/zones", headers=h).json()
    assert len(all_zones) == 2
    filtered = client.get(f"/api/v1/zones?camera_id={cam2['id']}", headers=h).json()
    assert [z["name"] for z in filtered] == ["z2"]

def test_patch_zone_severity(client):
    h = _admin_headers(client)
    cam = _camera(client, h)
    zid = client.post("/api/v1/zones", json={**VALID, "camera_id": cam["id"]}, headers=h).json()["id"]
    r = client.patch(f"/api/v1/zones/{zid}", json={"severity": "critical"}, headers=h)
    assert r.status_code == 200 and r.json()["severity"] == "critical"

def test_delete_zone_then_get_404(client):
    h = _admin_headers(client)
    cam = _camera(client, h)
    zid = client.post("/api/v1/zones", json={**VALID, "camera_id": cam["id"]}, headers=h).json()["id"]
    assert client.delete(f"/api/v1/zones/{zid}", headers=h).status_code == 200
    assert client.get(f"/api/v1/zones/{zid}", headers=h).status_code == 404

def test_create_zone_invalid_schedule_day_422(client):
    h = _admin_headers(client)
    cam = _camera(client, h)
    sched = {"days": [0, 1], "start": "08:00", "end": "17:00"}
    r = client.post("/api/v1/zones", json={**VALID, "camera_id": cam["id"], "schedule": sched}, headers=h)
    assert r.status_code == 422

def test_patch_to_absensi_without_direction_rejected(client):
    h = _admin_headers(client)
    cam = client.post("/api/v1/cameras", headers=h, json={"name": "z-cam", "host": "1.2.3.4", "node_id": 1}).json()
    z = client.post("/api/v1/zones", headers=h, json={"name": "z", "type": "restricted", "camera_id": cam["id"], "polygon": [[0,0],[1,0],[1,1]]}).json()
    r = client.patch(f"/api/v1/zones/{z['id']}", headers=h, json={"type": "absensi"})
    assert r.status_code == 422


def test_zone_dwell_seconds_default_zero(client):
    h = _admin_headers(client)
    cam = _camera(client, h)
    z = client.post("/api/v1/zones", json={**VALID, "camera_id": cam["id"]}, headers=h).json()
    assert z["dwell_seconds"] == 0


def test_patch_zone_dwell_seconds(client):
    h = _admin_headers(client)
    cam = _camera(client, h)
    zid = client.post("/api/v1/zones", json={**VALID, "camera_id": cam["id"]}, headers=h).json()["id"]
    r = client.patch(f"/api/v1/zones/{zid}", json={"dwell_seconds": 3}, headers=h)
    assert r.status_code == 200 and r.json()["dwell_seconds"] == 3


def test_patch_zone_dwell_seconds_negative_422(client):
    h = _admin_headers(client)
    cam = _camera(client, h)
    zid = client.post("/api/v1/zones", json={**VALID, "camera_id": cam["id"]}, headers=h).json()["id"]
    assert client.patch(f"/api/v1/zones/{zid}", json={"dwell_seconds": -1}, headers=h).status_code == 422
