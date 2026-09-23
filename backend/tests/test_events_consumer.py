import json
import uuid
from datetime import datetime, timezone

import pytest

from app.models.node import Node
from app.services import events_consumer as ec
from app.services.events_consumer import handle_message
from app.ws.hub import hub


def _event(node_id=None, **over):
    data = {
        "event_id": str(uuid.uuid4()),
        "type": "intrusion",
        "severity": "critical",
        "ts_event": datetime.now(timezone.utc).isoformat(),
    }
    if node_id is not None:
        data["node_id"] = node_id
    data.update(over)
    return data


@pytest.fixture
def broadcast(monkeypatch):
    sent = []
    async def fake_broadcast(payload):
        sent.append(payload)
    monkeypatch.setattr(hub, "broadcast", fake_broadcast)
    return sent


def test_valid_event_ingests_and_broadcasts(db, broadcast):
    handle_message(db, "isentinel/events", json.dumps(_event()).encode())
    assert db.query(ec.Event).count() == 1
    assert len(broadcast) == 1
    assert broadcast[0]["type"] == "intrusion"


def test_malformed_payload_no_raise_no_row(db, broadcast):
    handle_message(db, "isentinel/events", b"{not json")
    assert db.query(ec.Event).count() == 0
    assert broadcast == []


def test_invalid_event_no_raise_no_row(db, broadcast):
    # missing required fields (no event_id) -> validation error, swallowed
    handle_message(db, "isentinel/events", b'{"type":"intrusion"}')
    assert db.query(ec.Event).count() == 0
    assert broadcast == []


def test_lwt_sets_node_offline_and_system_event(db, broadcast):
    db.add(Node(name="server"))
    db.commit()
    handle_message(db, "isentinel/nodes/server/lwt", b'{"status":"offline"}')
    node = db.query(Node).filter_by(name="server").one()
    assert node.status == "offline"
    ev = db.query(ec.Event).one()
    assert ev.type == "system" and ev.severity == "warning"
    assert ev.payload == {"node": "server", "reason": "lwt"}


def test_duplicate_event_id_no_error_no_double_row(db, broadcast):
    payload = json.dumps(_event()).encode()
    handle_message(db, "isentinel/events", payload)
    handle_message(db, "isentinel/events", payload)
    assert db.query(ec.Event).count() == 1


def test_heartbeat_saves_hw_and_modules(db, broadcast):
    db.add(Node(name="vision-1"))
    db.commit()
    hb = {"ts": datetime.now(timezone.utc).isoformat(), "cpu_percent": 5.0,
          "cameras": [1, 2],
          "hw": {"gpus": [{"idx": 0, "name": "RTX 4090", "vram_used_mb": 900,
                           "vram_total_mb": 24564, "util_pct": 10, "processes": []}]},
          "modules": {"detector": {"device": "cuda:0", "model": "yolo26s.engine"}}}
    handle_message(db, "isentinel/nodes/vision-1/heartbeat", json.dumps(hb).encode())
    node = db.query(Node).filter_by(name="vision-1").one()
    assert node.hw["gpus"][0]["name"] == "RTX 4090"
    assert node.modules["detector"]["device"] == "cuda:0"


def test_heartbeat_without_hw_backward_compatible(db, broadcast):
    db.add(Node(name="vision-1"))
    db.commit()
    hb = {"ts": datetime.now(timezone.utc).isoformat(), "cpu_percent": 5.0, "cameras": []}
    handle_message(db, "isentinel/nodes/vision-1/heartbeat", json.dumps(hb).encode())
    node = db.query(Node).filter_by(name="vision-1").one()
    assert node.status == "online"
    assert node.hw is None and node.modules is None


def test_heartbeat_bad_hw_shape_ignored(db, broadcast):
    db.add(Node(name="vision-1"))
    db.commit()
    handle_message(db, "isentinel/nodes/vision-1/heartbeat",
                   json.dumps({"ts": "x", "hw": "junk"}).encode())
    node = db.query(Node).filter_by(name="vision-1").one()
    assert node.hw is None and node.status == "online"


# --- R3: relay detections topic → WS -----------------------------------------

DETECTIONS_TOPIC = "isentinel/detections/test-node"


def test_detections_relayed_to_hub(db, broadcast):
    payload = json.dumps({"camera_id": 7, "boxes": [
        {"id": 1, "bbox_norm": [0.1, 0.1, 0.5, 0.6]}]}).encode()
    handle_message(db, DETECTIONS_TOPIC, payload)
    assert broadcast == [{
        "type": "detections", "camera_id": 7,
        "boxes": [{"id": 1, "bbox_norm": [0.1, 0.1, 0.5, 0.6]}],
    }]


def test_detections_malformed_no_raise_no_broadcast(db, broadcast):
    handle_message(db, DETECTIONS_TOPIC, b"not-json")
    assert broadcast == []


def test_attendance_embedding_never_persisted_or_broadcast_when_matching_fails(db, broadcast, monkeypatch):
    """Embedding biometrik tidak boleh sampai ke tabel event/WS, bahkan saat match melempar error
    (dulu: ingest commit payload ber-embedding, rollback menyisakannya permanen)."""
    from app.models.event import Event
    from app.services import attendance
    seen = {}

    def boom(vector, quality=None):
        seen["len"] = len(vector)
        raise RuntimeError("matcher down")

    monkeypatch.setattr(attendance.face, "match_vector", boom)
    ev = _event(type="attendance", severity="info",
                payload={"direction": "entry", "embedding": [0.1] * 512, "face_quality": 0.8})
    handle_message(db, "isentinel/events", json.dumps(ev).encode())

    assert seen["len"] == 512                       # matcher tetap menerima embedding
    row = db.query(Event).filter_by(event_id=ev["event_id"]).one()
    assert "embedding" not in (row.payload or {})
    assert all("embedding" not in (m.get("payload") or {}) for m in broadcast)
