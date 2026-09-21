import pytest
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient
from app.main import app
from app.core.db import get_db
from app.models.node import Node

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


def test_nodes_list_returns_hw(client, db):
    from app.models.node import Node
    db.add(Node(name="vision-1", status="online", hw={"gpus": [{"idx": 0, "name": "RTX 4090"}]}))
    db.commit()
    tok = client.post("/api/v1/auth/login", json={"username": "admin", "password": "boot123"}).json()["token"]
    rows = client.get("/api/v1/nodes", headers={"Authorization": f"Bearer {tok}"}).json()
    row = next(n for n in rows if n["name"] == "vision-1")
    assert row["hw"]["gpus"][0]["name"] == "RTX 4090"


def _admin_tok(client):
    return client.post("/api/v1/auth/login", json={"username": "admin", "password": "boot123"}).json()["token"]


def test_nodes_api_get_returns_detector_device(client, db):
    from app.models.node import Node
    db.add(Node(name="n1", detector_device="cuda:1"))
    db.commit()
    tok = _admin_tok(client)
    rows = client.get("/api/v1/nodes", headers={"Authorization": f"Bearer {tok}"}).json()
    assert next(n for n in rows if n["name"] == "n1")["detector_device"] == "cuda:1"


def test_nodes_api_put_detector_device_roundtrip(client, db):
    from app.models.node import Node
    db.add(Node(name="n1"))
    db.commit()
    tok = _admin_tok(client)
    r = client.put("/api/v1/nodes/1/detector-device", json={"device": "cuda:1"},
                   headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200
    db.expire_all()
    assert db.get(Node, 1).detector_device == "cuda:1"
    rows = client.get("/api/v1/nodes", headers={"Authorization": f"Bearer {tok}"}).json()
    assert rows[0]["detector_device"] == "cuda:1"


def test_nodes_api_put_detector_device_rejects_invalid(client, db):
    from app.models.node import Node
    db.add(Node(name="n1"))
    db.commit()
    tok = _admin_tok(client)
    r = client.put("/api/v1/nodes/1/detector-device", json={"device": "notcuda"},
                   headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 422
    # hw tersedia (1 GPU): cuda:0 OK, cuda:1 ditolak (idx >= count)
    n1 = db.get(Node, 1)
    n1.hw = {"gpus": [{"idx": 0, "name": "RTX 4090"}]}
    db.commit()
    r = client.put("/api/v1/nodes/1/detector-device", json={"device": "cuda:0"},
                   headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200
    r = client.put("/api/v1/nodes/1/detector-device", json={"device": "cuda:1"},
                   headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 422


def test_nodes_api_put_detector_device_clears_to_auto(client, db):
    from app.models.node import Node
    db.add(Node(name="n1", detector_device="cuda:1"))
    db.commit()
    tok = _admin_tok(client)
    r = client.put("/api/v1/nodes/1/detector-device", json={"device": ""},
                   headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200
    db.expire_all()
    assert db.get(Node, 1).detector_device in (None, "")


# --- R1: face_device — pin per-analyzer terpisah ------------------------------

def test_nodes_api_put_face_device_roundtrip(client, db):
    n = Node(name="n1", detector_device="cuda:2")
    db.add(n)
    db.commit()
    db.refresh(n)
    tok = _admin_tok(client)
    r = client.put(f"/api/v1/nodes/{n.id}/face-device", json={"device": "cuda:1"},
                   headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200
    db.expire_all()
    row = db.get(Node, n.id)
    assert row.face_device == "cuda:1"
    assert row.detector_device == "cuda:2"  # tak terganggu

    r2 = client.put(f"/api/v1/nodes/{n.id}/face-device", json={"device": ""},
                    headers={"Authorization": f"Bearer {tok}"})
    assert r2.status_code == 200
    db.expire_all()
    assert db.get(Node, n.id).face_device is None


def test_nodes_api_put_face_device_invalid(client, db):
    n = Node(name="n1")
    db.add(n)
    db.commit()
    db.refresh(n)
    tok = _admin_tok(client)
    r = client.put(f"/api/v1/nodes/{n.id}/face-device", json={"device": "gpu-x"},
                   headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 422
