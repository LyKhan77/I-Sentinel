"""DiskQueue + MqttTransport tests. No real MQTT broker — fake client monkeypatched in."""
import json
import threading

import pytest

from vision.transport import DiskQueue, MqttTransport
from vision.transport import mqtt as mqtt_mod


class FakeResult:
    def __init__(self, rc):
        self.rc = rc


class FakeClient:
    """Recording fake paho client. publish_rc controls success/failure."""

    def __init__(self, *a, **kw):
        self.published = []  # (topic, payload, qos, retain)
        self.publish_rc = 0
        self.will = None
        self.connected = True
        self._lock = threading.Lock()

    def username_pw_set(self, u, p=None):
        self.user = (u, p)

    def will_set(self, topic, payload, retained=False, qos=0):
        self.will = (topic, payload, retained, qos)

    def connect(self, host, port):
        self.host_port = (host, port)

    def loop_start(self):
        pass

    def loop_stop(self):
        pass

    def disconnect(self):
        pass

    def is_connected(self):
        return self.connected

    def on_connect(self, client, userdata, flags, reason_code, properties):
        mqtt_mod.MqttTransport._on_connect(self._transport_ref, self, userdata, flags, reason_code, properties)

    def publish(self, topic, payload, qos=0, retain=False):
        if qos == 1 and self.publish_rc != 0:
            self._fail_next = True
        with self._lock:
            self.published.append((topic, payload, qos, retain))
        if self.publish_rc != 0 and qos == 1:
            # simulate failure: record but return rc != 0 (transport must queue, not rely on record)
            self.published.pop()
            return FakeResult(self.publish_rc)
        return FakeResult(0)


@pytest.fixture
def transport(tmp_path, monkeypatch):
    cfg = type("Cfg", (), {
        "node_id": "test-node", "mqtt_url": "localhost:1883", "mqtt_username": "",
        "mqtt_password": "", "data_dir": str(tmp_path / "data"),
    })()
    monkeypatch.setattr(mqtt_mod.mqtt, "Client", lambda *a, **kw: FakeClient())
    t = MqttTransport(cfg)
    t._client._transport_ref = t
    yield t


def test_queue_fifo_atomic(tmp_path):
    q = DiskQueue(str(tmp_path / "q"))
    assert q.pop() is None
    q.put({"n": 1})
    q.put({"n": 2})
    assert q.size() == 2
    seq1, item1 = q.pop()
    q.remove(seq1)
    seq2, item2 = q.pop()
    q.remove(seq2)
    q.remove(seq1)
    q.remove(seq2)
    assert q.size() == 0
    # atomic write: no .tmp leftovers
    assert not [f for f in (tmp_path / "q").iterdir() if f.name.endswith(".tmp")]


def test_queue_drop_oldest(tmp_path):
    q = DiskQueue(str(tmp_path / "q"), max_bytes=200)
    for i in range(10):
        q.put({"i": i, "pad": "x" * 30})
    assert q.size() < 10  # oldest dropped
    seq, first = q.pop()
    assert first["i"] > 0  # oldest items gone


def test_publish_success_no_queue(transport):
    transport.publish_event({"event_id": "e1"})
    assert len(transport._client.published) == 1
    topic, payload, qos, retain = transport._client.published[0]
    assert topic == "isentinel/events" and qos == 1
    assert json.loads(payload) == {"event_id": "e1"}
    assert transport._queue.size() == 0


def test_publish_fail_queues(transport):
    transport._client.publish_rc = 1
    transport.publish_event({"event_id": "e1"})
    assert transport._client.published == []  # failed publish not kept
    assert transport._queue.size() == 1
    seq, ev = transport._queue.pop()
    assert ev == {"event_id": "e1"}


def test_flush_on_reconnect_in_order(transport):
    transport._client.publish_rc = 1
    for i in range(3):
        transport.publish_event({"n": i})
    assert transport._queue.size() == 3
    transport._client.publish_rc = 0
    transport._client.connected = True
    transport._on_connect(transport._client, None, None, 0, None)  # simulate reconnect
    assert transport._queue.size() == 0
    assert [json.loads(p)["n"] for _, p, _, _ in transport._client.published] == [0, 1, 2]


def test_will_set_and_heartbeat(transport):
    topic, payload, retained, qos = transport._client.will
    assert topic == "isentinel/nodes/test-node/lwt"
    assert json.loads(payload) == {"status": "offline"}
    assert retained is True and qos == 1
    transport.publish_heartbeat({"ts": "now"})
    topic, payload, qos, retain = transport._client.published[-1]
    assert topic == "isentinel/nodes/test-node/heartbeat"
    assert qos == 0 and retain is False
