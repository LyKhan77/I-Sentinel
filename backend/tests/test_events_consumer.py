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
