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
    monkeypatch.setattr(settings, "cookie_secure", True)  # httpx tidak replay cookie secure → uji 401 tanpa token valid
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:  # context manager memicu startup/bootstrap
        yield c
    app.dependency_overrides.clear()

def _admin_headers(client):
    tok = client.post("/api/v1/auth/login", json={"username": "admin", "password": "boot123"}).json()["token"]
    return {"Authorization": f"Bearer {tok}"}

def test_create_camera_requires_auth(client):
    assert client.post("/api/v1/cameras", json={"name": "cam1", "host": "1.2.3.4"}).status_code == 401

def test_create_camera_as_admin_and_list(client):
    h = _admin_headers(client)
    r = client.post("/api/v1/cameras", json={"name": "cam1", "host": "1.2.3.4", "node_id": 1}, headers=h)
    assert r.status_code == 200
    assert r.json()["name"] == "cam1" and r.json()["node_id"] == 1
    assert r.json()["enabled"] is True and r.json()["status"] == "unknown"
    assert r.json()["rtsp_main"] is None and r.json()["probe_main"] is None
    names = [c["name"] for c in client.get("/api/v1/cameras", headers=h).json()]
    assert "cam1" in names

def test_create_duplicate_name_same_node_conflict(client):
    h = _admin_headers(client)
    body = {"name": "cam1", "host": "1.2.3.4", "node_id": 1}
    assert client.post("/api/v1/cameras", json=body, headers=h).status_code == 200
    assert client.post("/api/v1/cameras", json=body, headers=h).status_code == 409

def test_create_camera_bad_node_422(client):
    h = _admin_headers(client)
    assert client.post("/api/v1/cameras", json={"name": "c", "host": "h", "node_id": 999}, headers=h).status_code == 422

def test_patch_camera_enabled_false(client):
    h = _admin_headers(client)
    cid = client.post("/api/v1/cameras", json={"name": "cam1", "host": "1.2.3.4"}, headers=h).json()["id"]
    r = client.patch(f"/api/v1/cameras/{cid}", json={"enabled": False}, headers=h)
    assert r.status_code == 200 and r.json()["enabled"] is False

def test_delete_camera_then_get_404(client):
    h = _admin_headers(client)
    cid = client.post("/api/v1/cameras", json={"name": "cam1", "host": "1.2.3.4"}, headers=h).json()["id"]
    assert client.delete(f"/api/v1/cameras/{cid}", headers=h).status_code == 200
    assert client.get(f"/api/v1/cameras/{cid}", headers=h).status_code == 404

def test_nodes_list_seeded(client):
    h = _admin_headers(client)
    r = client.get("/api/v1/nodes", headers=h)
    assert r.status_code == 200
    names = [(n["name"], n["type"], n["status"]) for n in r.json()]
    assert ("server", "server", "unknown") in names

def test_probe_persists_result_with_camera_id(client, monkeypatch):
    from unittest.mock import patch
    h = _admin_headers(client)
    cam = client.post("/api/v1/cameras", json={"name": "cam1", "host": "1.2.3.4"}, headers=h).json()
    fake = {"main": {"res": "2560x1440", "fps": 25.0, "codec": "h264"}, "sub": None,
            "main_path": "rtsp://x/main", "sub_path": None}
    with patch("app.api.probe.probe_camera", return_value=fake):
        r = client.post("/api/v1/cameras/probe", json={"host": "1.2.3.4", "camera_id": cam["id"]}, headers=h)
    assert r.status_code == 200 and r.json() == fake
    listed = [c for c in client.get("/api/v1/cameras", headers=h).json() if c["id"] == cam["id"]][0]
    assert listed["probe_main"] == fake["main"] and listed["probe_sub"] is None
    assert listed["status"] == "online"

    fake_off = {"main": None, "sub": None, "main_path": None, "sub_path": None}
    with patch("app.api.probe.probe_camera", return_value=fake_off):
        client.post("/api/v1/cameras/probe", json={"host": "1.2.3.4", "camera_id": cam["id"]}, headers=h)
    listed = [c for c in client.get("/api/v1/cameras", headers=h).json() if c["id"] == cam["id"]][0]
    assert listed["status"] == "offline"

def test_probe_without_camera_id_does_not_persist(client, monkeypatch):
    from unittest.mock import patch
    h = _admin_headers(client)
    client.post("/api/v1/cameras", json={"name": "cam1", "host": "1.2.3.4"}, headers=h)
    fake = {"main": {"res": "640x360", "fps": 15.0, "codec": "h264"}, "sub": None,
            "main_path": "rtsp://x/main", "sub_path": None}
    with patch("app.api.probe.probe_camera", return_value=fake):
        assert client.post("/api/v1/cameras/probe", json={"host": "1.2.3.4"}, headers=h).status_code == 200
    listed = client.get("/api/v1/cameras", headers=h).json()[0]
    assert listed["probe_main"] is None and listed["status"] == "unknown"
