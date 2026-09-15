import pytest
from datetime import datetime, timezone, timedelta
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

def _hb_headers():
    return {"Authorization": "Bearer test-node-key"}

def _hb_body(**kw):
    b = {"ts": datetime.now(timezone.utc).isoformat(), "cpu_percent": 12.5,
         "gpu_mem": None, "cameras": [1, 2]}
    b.update(kw)
    return b

def test_heartbeat_without_api_key_401(client):
    assert client.post("/internal/nodes/1/heartbeat", json=_hb_body()).status_code == 401

def test_heartbeat_bad_api_key_401(client):
    r = client.post("/internal/nodes/1/heartbeat", json=_hb_body(),
                    headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401

def test_heartbeat_unknown_node_404(client):
    r = client.post("/internal/nodes/999/heartbeat", json=_hb_body(), headers=_hb_headers())
    assert r.status_code == 404

def test_heartbeat_updates_node(client, db):
    from app.models.node import Node
    r = client.post("/internal/nodes/1/heartbeat", json=_hb_body(), headers=_hb_headers())
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "node_id": 1, "seen": True}
    db.expire_all()
    node = db.get(Node, 1)
    assert node.status == "online"
    assert node.last_seen is not None
    assert node.last_seen is not None  # tz preserved on Postgres; SQLite drops tzinfo

def test_mark_stale_flips_old_node(db):
    from app.models.node import Node, mark_stale_nodes
    old = Node(name="stale-node", status="online",
               last_seen=datetime.now(timezone.utc) - timedelta(seconds=60))
    fresh = Node(name="fresh-node", status="online", last_seen=datetime.now(timezone.utc))
    db.add_all([old, fresh])
    db.commit()
    assert mark_stale_nodes(db) == 1
    db.expire_all()
    assert db.get(Node, old.id).status == "offline"
    assert db.get(Node, fresh.id).status == "online"

def test_mark_stale_endpoint(client, db):
    from app.models.node import Node
    db.add(Node(name="old-node", status="online",
                last_seen=datetime.now(timezone.utc) - timedelta(seconds=60)))
    db.commit()
    assert client.post("/internal/maintenance/mark-stale").status_code == 401
    r = client.post("/internal/maintenance/mark-stale", headers=_hb_headers())
    assert r.status_code == 200 and r.json()["marked"] == 1

def test_nodes_list_runs_sweeper(client, db):
    from app.models.node import Node
    db.add(Node(name="old-node", status="online",
                last_seen=datetime.now(timezone.utc) - timedelta(seconds=60)))
    db.commit()
    tok = client.post("/api/v1/auth/login", json={"username": "admin", "password": "boot123"}).json()["token"]
    rows = client.get("/api/v1/nodes", headers={"Authorization": f"Bearer {tok}"}).json()
    old = next(n for n in rows if n["name"] == "old-node")
    assert old["status"] == "offline"
