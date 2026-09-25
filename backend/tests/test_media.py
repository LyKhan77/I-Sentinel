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


def test_consumer_media_clip_offset_merged_into_payload(db):
    ev = _seed_event(db)
    ev.payload = {"track_id": 6}
    db.commit()
    handle_message(db, "isentinel/events/media", json.dumps(
        {"event_id": ev.event_id, "clip_path": "clips/y.mp4", "clip_offset_s": 12.4}
    ).encode())
    db.refresh(ev)
    assert ev.clip_path == "clips/y.mp4"
    assert ev.payload == {"track_id": 6, "clip_offset_s": 12.4}


def test_consumer_media_clip_offset_rejects_non_number(db):
    ev = _seed_event(db)
    for bad in ("12", -3, True, None):
        handle_message(db, "isentinel/events/media", json.dumps(
            {"event_id": ev.event_id, "clip_path": "clips/y.mp4", "clip_offset_s": bad}
        ).encode())
    db.refresh(ev)
    assert "clip_offset_s" not in (ev.payload or {})


def test_consumer_media_unknown_event_no_crash(db):
    handle_message(db, "isentinel/events/media", json.dumps(
        _media_payload(str(uuid.uuid4()))
    ).encode())


def test_consumer_media_malformed_no_crash(db):
    handle_message(db, "isentinel/events/media", b"{not json")


def test_consumer_subscribes_media_topic():
    assert ("isentinel/events/media", 1) in ec.EventConsumer()._subscriptions()


# --- F5: snapshot absensi datang belakangan tetap diberi label -----------------

def test_late_attendance_snapshot_labeled_with_name(db, monkeypatch):
    from app.models.camera import Camera
    from app.models.employee import Employee
    from app.services import attendance
    from app.services.face import MatchResult
    monkeypatch.setattr(attendance, "annotate_face_crop", lambda *a, **k: None)
    monkeypatch.setattr(attendance, "annotate_snapshot",
                        lambda path, label, bbox, color=None: calls.append(label))
    calls: list[str] = []
    db.add(Camera(name="Gate", host="127.0.0.1"))
    e = Employee(name="Budi", employee_code="E1")
    db.add(e)
    db.commit()
    monkeypatch.setattr(attendance.face, "match_crop",
                        lambda _db, _path: MatchResult(e.id, 0.9, 0.9, "matched"))

    ev = {"event_id": str(uuid.uuid4()), "type": "attendance", "camera_id": 1, "severity": "info",
          "ts_event": datetime.now(timezone.utc).isoformat(),
          "payload": {"crop_path": "crops/x.jpg", "direction": "entry",
                      "bbox_norm": [0.1, 0.1, 0.2, 0.2]}}
    handle_message(db, "isentinel/events", json.dumps(ev).encode())
    row = db.query(ec.Event).filter_by(event_id=ev["event_id"]).one()
    assert row.snapshot_path is None  # snapshot belum ada saat attendance diproses

    handle_message(db, "isentinel/events/media", json.dumps(
        {"event_id": ev["event_id"], "snapshot_path": "snapshots/late.jpg"}).encode())
    db.refresh(row)
    assert row.snapshot_path == "snapshots/late.jpg"
    assert calls == ["Budi"]


def test_late_attendance_snapshot_unknown_orange(db, monkeypatch):
    from app.models.camera import Camera
    from app.services import attendance
    from app.services.face import MatchResult
    calls: list[tuple[str, str, object]] = []
    db.add(Camera(name="Gate", host="127.0.0.1"))
    db.commit()
    monkeypatch.setattr(attendance, "annotate_face_crop", lambda *a, **k: None)
    monkeypatch.setattr(attendance, "annotate_snapshot",
                        lambda path, label, bbox, color=None: calls.append((label, color, bbox)))
    monkeypatch.setattr(attendance.face, "match_crop",
                        lambda _db, _path: MatchResult(None, None, 0.9, "no_match"))

    ev = {"event_id": str(uuid.uuid4()), "type": "attendance", "camera_id": 1, "severity": "info",
          "ts_event": datetime.now(timezone.utc).isoformat(),
          "payload": {"crop_path": "crops/x.jpg", "direction": "entry"}}
    handle_message(db, "isentinel/events", json.dumps(ev).encode())
    handle_message(db, "isentinel/events/media", json.dumps(
        {"event_id": ev["event_id"], "snapshot_path": "snapshots/late.jpg"}).encode())
    from app.services.annotate import ORANGE
    assert calls == [("Unknown", ORANGE, None)]


def test_media_update_non_attendance_not_annotated(db, monkeypatch):
    from app.services import attendance
    calls: list = []
    monkeypatch.setattr(attendance, "annotate_snapshot",
                        lambda *a, **k: calls.append(1))
    ev = _seed_event(db)
    handle_message(db, "isentinel/events/media", json.dumps(
        _media_payload(ev.event_id)).encode())
    assert calls == []
