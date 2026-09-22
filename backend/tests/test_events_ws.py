"""WS /api/v1/ws/events auth: query token ATAU httpOnly cookie.

UI tidak bisa menaruh JWT di query (cookie httpOnly) — handshake selalu ditolak
sebelum fallback cookie ada, sehingga bbox realtime tidak pernah sampai browser.
"""
import pytest
import uuid
from fastapi.testclient import TestClient
from app.main import app
from app.core.db import get_db
from app.ws.hub import hub


@pytest.fixture
def client(db, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "admin_username", "admin")
    monkeypatch.setattr(settings, "admin_password", "boot123")
    monkeypatch.setattr(settings, "node_api_key", "test-node-key")
    from app.models.camera import Camera
    db.add(Camera(id=1, name="cam1", host="1.2.3.4")); db.commit()
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _login(client):
    """Login lewat API — cookie httpOnly (isentinel_token) masuk ke jar client."""
    r = client.post("/api/v1/auth/login", json={"username": "admin", "password": "boot123"})
    return r.json()["token"]


def test_ws_accepts_cookie_without_query_token(client):
    _login(client)
    assert client.cookies.get("isentinel_token")
    with client.websocket_connect("/api/v1/ws/events") as ws:
        # broadcast sampai ke koneksi ini -> handshake benar-benar diterima
        client.post(
            "/internal/nodes/1/events",
            json={"event_id": str(uuid.uuid4()), "type": "intrusion", "camera_id": 1,
                  "ts_event": "2026-09-22T09:00:00+07:00", "payload": {"x": 1}},
            headers={"Authorization": "Bearer test-node-key"},
        )
        assert ws.receive_json()["type"] == "intrusion"


def test_ws_rejects_without_cookie_and_token(client):
    client.cookies.clear()
    try:
        with client.websocket_connect("/api/v1/ws/events") as ws:
            ws.receive_json()
        assert False, "should not connect"
    except Exception as e:
        assert getattr(e, "code", None) == 1008


def test_ws_rejects_bad_cookie(client):
    client.cookies.set("isentinel_token", "not-a-jwt")
    try:
        with client.websocket_connect("/api/v1/ws/events") as ws:
            ws.receive_json()
        assert False, "should not connect"
    except Exception as e:
        assert getattr(e, "code", None) == 1008


def test_ws_query_token_still_works(client):
    tok = _login(client)
    client.cookies.clear()
    with client.websocket_connect(f"/api/v1/ws/events?token={tok}") as ws:
        client.post(
            "/internal/nodes/1/events",
            json={"event_id": str(uuid.uuid4()), "type": "loitering", "camera_id": 1,
                  "ts_event": "2026-09-22T09:00:01+07:00", "payload": {"x": 1}},
            headers={"Authorization": "Bearer test-node-key"},
        )
        assert ws.receive_json()["type"] == "loitering"
