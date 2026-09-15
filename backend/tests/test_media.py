import json
import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.db import get_db
from app.core.config import settings
from app.models.node import Node
from app.services import events_consumer as ec
from app.services.events_consumer import handle_message


@pytest.fixture
def client(db, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "admin_username", "admin")
    monkeypatch.setattr(settings, "admin_password", "boot123")
    monkeypatch.setattr(settings, "node_api_key", "test-node-key")
    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _admin_headers(client):
    tok = client.post("/api/v1/auth/login", json={"username": "admin", "password": "boot123"}).json()["token"]
    return {"Authorization": f"Bearer {tok}"}


def _key_headers():
    return {"Authorization": "Bearer test-node-key"}


def test_blob_upload_without_key_401(client):
    r = client.post("/internal/nodes/1/blobs?kind=snapshot", content=b"x")
    assert r.status_code == 401


def test_blob_upload_snapshot_saves_file(client, tmp_path):
    r = client.post("/internal/nodes/1/blobs?kind=snapshot", content=b"jpegbytes", headers=_key_headers())
    assert r.status_code == 200
    path = r.json()["path"]
    assert path.startswith("snapshots/") and path.endswith(".jpg")
    assert (tmp_path / path).read_bytes() == b"jpegbytes"


def test_blob_upload_clip_mp4(client):
    r = client.post("/internal/nodes/1/blobs?kind=clip", content=b"mp4", headers=_key_headers())
    assert r.status_code == 200
    assert r.json()["path"].endswith(".mp4")
    assert r.json()["path"].startswith("clips/")


def test_blob_upload_invalid_kind_422(client):
    r = client.post("/internal/nodes/1/blobs?kind=virus", content=b"x", headers=_key_headers())
    assert r.status_code == 422


def test_blob_upload_too_large_413(client):
    r = client.post(
        "/internal/nodes/1/blobs?kind=snapshot",
        headers={**_key_headers(), "Content-Length": str(201 * 1024 * 1024)},
    )
    assert r.status_code == 413


def test_media_get_streams_content(client, tmp_path):
    up = client.post("/internal/nodes/1/blobs?kind=snapshot", content=b"jpegbytes", headers=_key_headers())
    path = up.json()["path"]
    r = client.get(f"/api/v1/media/{path}", headers=_admin_headers(client))
    assert r.status_code == 200
    assert r.content == b"jpegbytes"
    assert r.headers["content-type"].startswith("image/jpeg")


def test_media_traversal_404(client):
    r = client.get("/api/v1/media/../../../etc/passwd", headers=_admin_headers(client))
    assert r.status_code == 404


def test_media_traversal_encoded_404(client):
    r = client.get("/api/v1/media/%2e%2e%2f%2e%2e%2fsecret.jpg", headers=_admin_headers(client))
    assert r.status_code == 404


def test_media_unknown_404(client):
    r = client.get("/api/v1/media/snapshots/nope.jpg", headers=_admin_headers(client))
    assert r.status_code == 404


def test_media_unauth_401(client):
    assert client.get("/api/v1/media/snapshots/x.jpg").status_code == 401


def _media_payload(event_id, **over):
    p = {"event_id": event_id, "clip_path": None, "snapshot_path": "snapshots/2026/01/01/x.jpg"}
    p.update(over)
    return p


def _seed_event(db):
    ev = ec.Event(
        event_id=str(uuid.uuid4()), node_id=None, type="intrusion", severity="warning",
        ts_event=datetime.now(timezone.utc), payload={},
    )
    db.add(ev)
    db.commit()
    return ev


def test_consumer_media_topic_updates_event(db):
    ev = _seed_event(db)
    handle_message(db, "isentinel/events/media", json.dumps(
        _media_payload(ev.event_id, clip_path="clips/2026/01/01/y.mp4")
    ).encode())
    db.refresh(ev)
    assert ev.snapshot_path == "snapshots/2026/01/01/x.jpg"
    assert ev.clip_path == "clips/2026/01/01/y.mp4"


def test_consumer_media_unknown_event_no_crash(db):
    handle_message(db, "isentinel/events/media", json.dumps(
        _media_payload(str(uuid.uuid4()))
    ).encode())


def test_consumer_media_malformed_no_crash(db):
    handle_message(db, "isentinel/events/media", b"{not json")


def test_consumer_subscribes_media_topic():
    assert ("isentinel/events/media", 1) in ec.EventConsumer()._subscriptions()
