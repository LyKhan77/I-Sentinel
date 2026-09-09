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
