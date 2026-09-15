import json

import pytest

from app.core.config import settings
from app.models.node import Node
from app.models.camera import Camera
from app.models.zone import Zone
from app.services import config_push
from tests.conftest import *  # noqa


def _node(db, name="server", type="server"):
    n = Node(name=name, type=type)
    db.add(n); db.commit(); db.refresh(n)
    return n

def _cam(db, node_id, enabled=True, name="cam1"):
    c = Camera(name=name, host="1.2.3.4", node_id=node_id, enabled=enabled)
    db.add(c); db.commit(); db.refresh(c)
    return c

def _zone(db, camera_id, name="z1", active=True):
    z = Zone(camera_id=camera_id, name=name, type="restricted",
             polygon=[[0.1, 0.1], [0.5, 0.1], [0.5, 0.5]], active=active)
    db.add(z); db.commit(); db.refresh(z)
    return z


def test_build_node_config_server_includes_active_cam_and_zones_excludes_disabled(db):
    node = _node(db)
    cam_on = _cam(db, node.id, enabled=True, name="cam_on")
    _cam(db, node.id, enabled=False, name="cam_off")
    z_on = _zone(db, cam_on.id, name="z_on", active=True)
    _zone(db, cam_on.id, name="z_off", active=False)

    cfg = config_push.build_node_config(db, node)

    assert cfg["node_id"] == "server"
    assert cfg["detector"] == {
        "model": settings.detector_model,
        "nms": settings.detector_nms,
        "conf": settings.detector_conf,
        "imgsz": settings.detector_imgsz,
    }
    assert len(cfg["cameras"]) == 1
    cam = cfg["cameras"][0]
    assert cam["camera_id"] == cam_on.id
    assert cam["source_url"] == f"rtsp://localhost:8554/cam_{cam_on.id}"
    assert isinstance(cam["ai_fps"], float)
    assert cam["meters_per_pixel"] is None
    assert cam["zones"] == [{
        "id": z_on.id, "name": "z_on", "type": "restricted",
        "direction": None, "polygon": z_on.polygon, "schedule": None,
        "severity": "warning", "rate_limit_min": 5,
        "loiter_seconds": 0, "speed_limit_mps": 0,
        "snapshot": True, "telegram": False,
    }]


class FakeClient:
    calls = []

    def __init__(self, *a, **k):
        FakeClient.calls.append(self)
        self.published = []

    def username_pw_set(self, *a): pass
    def connect(self, *a, **k): pass
    def loop_start(self): pass
    def loop_stop(self): pass
    def disconnect(self): pass

    def publish(self, topic, payload, qos=0, retain=False):
        self.published.append((topic, payload, qos, retain))


@pytest.fixture
def fake_mqtt(monkeypatch):
    FakeClient.calls = []
    monkeypatch.setattr(config_push.mqtt, "Client", FakeClient)
    return FakeClient


def test_publish_node_config_retained_qos1(db, fake_mqtt):
    node = _node(db)
    cam = _cam(db, node.id)
    _zone(db, cam.id)

    ok = config_push.publish_node_config(None, db, node.name)

    assert ok is True
    (client,) = fake_mqtt.calls
    (topic, payload, qos, retain) = client.published[0]
    assert topic == f"isentinel/config/{node.name}"
    assert qos == 1 and retain is True
    body = json.loads(payload.decode())
    assert body["cameras"][0]["camera_id"] == cam.id


def test_publish_node_config_error_returns_false(db, fake_mqtt):
    _node(db)

    class Boom(FakeClient):
        def connect(self, *a, **k): raise ConnectionError("broker down")

    fake_mqtt.__init__  # keep class registered
    import app.services.config_push as cp
    orig = cp.mqtt.Client
    cp.mqtt.Client = Boom
    try:
        assert config_push.publish_node_config(None, db, "server") is False
    finally:
        cp.mqtt.Client = orig


def test_publish_node_config_for_camera_resolves_node(db, fake_mqtt):
    node = _node(db)
    cam = _cam(db, node.id)

    assert config_push.publish_node_config_for_camera(db, cam.id) is True
    (client,) = fake_mqtt.calls
    assert client.published[0][0] == f"isentinel/config/{node.name}"


def test_republish_all_iterates_nodes(db, fake_mqtt):
    _node(db, name="n1")
    _node(db, name="n2")

    assert config_push.republish_all(db) is True
    topics = [c.published[0][0] for c in fake_mqtt.calls for _ in c.published]
    assert topics == ["isentinel/config/n1", "isentinel/config/n2"]
