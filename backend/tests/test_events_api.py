import pytest
import uuid
from fastapi.testclient import TestClient
from app.main import app
from app.core.db import get_db

@pytest.fixture

def client(db, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "admin_username", "admin")
    monkeypatch.setattr(settings, "admin_password", "boot123")
    monkeypatch.setattr(settings, "node_api_key", "test-node-key")
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()

def _admin_headers(client):
    tok = client.post("/api/v1/auth/login", json={"username": "admin", "password": "boot123"}).json()["token"]
    return {"Authorization": f"Bearer {tok}"}

def _ingest_headers():
    return {"Authorization": "Bearer test-node-key"}

def _payload(**kw):
    from datetime import datetime, timezone, timedelta
    ts = datetime.now(timezone.utc).isoformat()
    p = {"event_id": str(uuid.uuid4()), "type": "intrusion", "camera_id": 1,
         "ts_event": ts, "payload": {"x": 1}}
    p.update(kw)
    return p

def test_ingest_without_api_key_401(client):
    assert client.post("/internal/nodes/1/events", json=_payload()).status_code == 401

def test_ingest_bad_api_key_401(client):
    r = client.post("/internal/nodes/1/events", json=_payload(), headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401

def test_ingest_created_then_duplicate(client):
    body = _payload()
    r1 = client.post("/internal/nodes/1/events", json=body, headers=_ingest_headers())
    assert r1.status_code == 200
    assert r1.json()["status"] == "created" and r1.json()["id"] > 0
    r2 = client.post("/internal/nodes/1/events", json=body, headers=_ingest_headers())
    assert r2.status_code == 200 and r2.json()["status"] == "duplicate"

def test_ingest_dedup_key_collision_returns_existing_id(client):
    dedup = "node1-cam1-2024"
    r1 = client.post("/internal/nodes/1/events", json=_payload(dedup_key=dedup), headers=_ingest_headers())
    assert r1.status_code == 200 and r1.json()["status"] == "created"
    id_a = r1.json()["id"]
    r2 = client.post("/internal/nodes/1/events", json=_payload(dedup_key=dedup), headers=_ingest_headers())
    assert r2.status_code == 200 and r2.json()["status"] == "duplicate"
    assert r2.json()["id"] == id_a

def test_ingest_validates_uuid(client):
    r = client.post("/internal/nodes/1/events", json=_payload(event_id="not-a-uuid"), headers=_ingest_headers())
    assert r.status_code == 422

def test_ingest_validates_type(client):
    r = client.post("/internal/nodes/1/events", json=_payload(type="weird"), headers=_ingest_headers())
    assert r.status_code == 422

def test_ingest_unknown_node_still_ok(client):
    r = client.post("/internal/nodes/999/events", json=_payload(), headers=_ingest_headers())
    assert r.status_code == 200 and r.json()["status"] == "created"

def test_ingest_updates_node_last_seen(client, db):
    from app.models.node import Node
    r = client.post("/internal/nodes/1/events", json=_payload(), headers=_ingest_headers())
    assert r.status_code == 200
    db.expire_all()
    assert db.get(Node, 1).last_seen is not None

def test_list_events_requires_auth(client):
    assert client.get("/api/v1/events").status_code == 401

def test_list_events_filter_type(client):
    client.post("/internal/nodes/1/events", json=_payload(), headers=_ingest_headers())
    client.post("/internal/nodes/1/events", json=_payload(type="loitering"), headers=_ingest_headers())
    h = _admin_headers(client)
    all_events = client.get("/api/v1/events", headers=h).json()
    assert len(all_events) == 2
    only = client.get("/api/v1/events?type=intrusion", headers=h).json()
    assert len(only) == 1 and only[0]["type"] == "intrusion"

def test_list_events_limit(client):
    for _ in range(3):
        client.post("/internal/nodes/1/events", json=_payload(), headers=_ingest_headers())
    h = _admin_headers(client)
    assert len(client.get("/api/v1/events?limit=2", headers=h).json()) == 2

def test_stats_today(client):
    client.post("/internal/nodes/1/events", json=_payload(), headers=_ingest_headers())
    client.post("/internal/nodes/1/events", json=_payload(type="loitering"), headers=_ingest_headers())
    h = _admin_headers(client)
    s = client.get("/api/v1/events/stats/today", headers=h).json()
    assert s["total"] >= 2
    assert s["by_type"]["intrusion"] >= 1 and s["by_type"]["loitering"] >= 1

def test_ws_close_on_bad_token(client):
    try:
        with client.websocket_connect("/api/v1/ws/events?token=bad") as ws:
            ws.receive_json()
        assert False, "should not connect"
    except Exception as e:
        assert getattr(e, "code", None) == 1008

def test_ws_receives_ingest_broadcast(client):
    tok = client.post("/api/v1/auth/login", json={"username": "admin", "password": "boot123"}).json()["token"]
    with client.websocket_connect(f"/api/v1/ws/events?token={tok}") as ws:
        client.post("/internal/nodes/1/events", json=_payload(), headers=_ingest_headers())
        msg = ws.receive_json()
        assert msg["type"] == "intrusion" and msg["event_id"]
