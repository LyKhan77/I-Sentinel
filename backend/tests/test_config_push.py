import json

import pytest

from app.core.config import settings
from app.models.node import Node
from app.models.camera import Camera
from app.models.credential_profile import CredentialProfile
from app.models.stream_source import StreamSource
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
        "device": "",
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
        "loiter_seconds": 0, "dwell_seconds": 0, "speed_limit_mps": 0,
        "behaviors": [], "trigger_seconds": 0,
        "snapshot": True, "clip": True, "telegram": False,
    }]

def test_build_node_config_edge_uses_resolved_exact_substream(db, monkeypatch):
    monkeypatch.setenv("CAMERA_CRED_EDGE", "edge-pass")
    node = _node(db, name="edge-1", type="edge")
    profile = CredentialProfile(name="edge-cred", username="edge-user", secret_ref="env:CAMERA_CRED_EDGE")
    source = StreamSource(
        name="edge-camera",
        kind="ip_camera",
        host="10.0.0.9",
        port=8554,
        default_credential=profile,
    )
    camera = Camera(
        name="edge-cam",
        host="legacy",
        node_id=node.id,
        source=source,
        rtsp_sub="/vendor/low?profile=ai",
    )
    db.add(camera)
    db.commit()

    config = config_push.build_node_config(db, node)

    assert config["cameras"][0]["source_url"] == (
        "rtsp://edge-user:edge-pass@10.0.0.9:8554/vendor/low?profile=ai"
    )


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


def test_build_node_config_includes_detector_device(db):
    from app.models.node import Node
    from app.services.config_push import build_node_config
    node = Node(name="n1", detector_device="cuda:1")
    db.add(node)
    db.commit()
    cfg = build_node_config(db, node)
    assert cfg["detector"]["device"] == "cuda:1"


def test_build_node_config_device_empty_when_unset(db):
    from app.models.node import Node
    from app.services.config_push import build_node_config
    node = Node(name="n1")
    db.add(node)
    db.commit()
    cfg = build_node_config(db, node)
    assert cfg["detector"]["device"] == ""


# --- R2: toggle clip per zona -----------------------------------------------

def test_build_node_config_zone_includes_clip_toggle(db):
    from app.models.camera import Camera
    from app.models.node import Node
    from app.models.zone import Zone
    n = Node(name="n1", type="server")
    db.add(n)
    db.commit()
    cam = Camera(name="CamX", host="127.0.0.1", node_id=n.id)
    db.add(cam)
    db.commit()
    db.refresh(cam)
    z = Zone(camera_id=cam.id, name="Gate", type="absensi",
             polygon=[[0, 0], [1, 0], [1, 1], [0, 1]], snapshot=False, clip=False)
    db.add(z)
    db.commit()
    from app.services.config_push import build_node_config as bnc
    payload = bnc(db, n)
    zcfg = payload["cameras"][0]["zones"][0]
    assert zcfg["snapshot"] is False
    assert zcfg["clip"] is False


# --- R4: dwell trigger per zona ---------------------------------------------

def test_build_node_config_zone_includes_dwell_seconds(db):
    from app.models.camera import Camera
    from app.models.node import Node
    from app.models.zone import Zone
    n = Node(name="n1", type="server")
    db.add(n)
    db.commit()
    cam = Camera(name="CamX", host="127.0.0.1", node_id=n.id)
    db.add(cam)
    db.commit()
    db.refresh(cam)
    z = Zone(camera_id=cam.id, name="Gate", type="absensi", direction="entry",
             polygon=[[0, 0], [1, 0], [1, 1], [0, 1]], dwell_seconds=3)
    db.add(z)
    db.commit()
    from app.services.config_push import build_node_config as bnc
    zcfg = bnc(db, n)["cameras"][0]["zones"][0]
    assert zcfg["dwell_seconds"] == 3


def test_build_node_config_zone_dwell_defaults_zero(db):
    from app.models.camera import Camera
    from app.models.node import Node
    from app.models.zone import Zone
    n = Node(name="n2", type="server")
    db.add(n)
    db.commit()
    cam = Camera(name="CamY", host="127.0.0.1", node_id=n.id)
    db.add(cam)
    db.commit()
    db.refresh(cam)
    z = Zone(camera_id=cam.id, name="Z", type="restricted",
             polygon=[[0, 0], [1, 0], [1, 1]])
    db.add(z)
    db.commit()
    from app.services.config_push import build_node_config as bnc
    assert bnc(db, n)["cameras"][0]["zones"][0]["dwell_seconds"] == 0


# --- R5: behaviors zona + setelan deteksi per kamera -------------------------

def test_build_node_config_zone_includes_behaviors_and_trigger(db):
    from app.models.camera import Camera
    from app.models.node import Node
    from app.models.zone import Zone
    n = Node(name="r5", type="server")
    db.add(n); db.commit()
    cam = Camera(name="CamR5", host="127.0.0.1", node_id=n.id)
    db.add(cam); db.commit(); db.refresh(cam)
    db.add(Zone(camera_id=cam.id, name="Gate", type="attendance", direction="entry",
                polygon=[[0, 0], [1, 0], [1, 1]], trigger_seconds=3,
                behaviors=[{"kind": "attendance", "trigger_seconds": 3}]))
    db.add(Zone(camera_id=cam.id, name="Lorong", type="behavior",
                polygon=[[0, 0], [1, 0], [1, 1]],
                behaviors=[{"kind": "intrusion", "trigger_seconds": 0},
                           {"kind": "loitering", "trigger_seconds": 30}]))
    db.commit()
    from app.services.config_push import build_node_config as bnc
    zones = {z["id"]: z for z in bnc(db, n)["cameras"][0]["zones"]}
    gate = next(z for z in zones.values() if z["name"] == "Gate")
    lorong = next(z for z in zones.values() if z["name"] == "Lorong")
    assert gate["trigger_seconds"] == 3
    assert gate["behaviors"] == [{"kind": "attendance", "trigger_seconds": 3}]
    assert lorong["behaviors"] == [{"kind": "intrusion", "trigger_seconds": 0},
                                   {"kind": "loitering", "trigger_seconds": 30}]


def test_build_node_config_camera_detection_overrides(db):
    from app.models.camera import Camera
    from app.models.node import Node
    n = Node(name="r5b", type="server")
    db.add(n); db.commit()
    db.add(Camera(name="Cfg", host="127.0.0.1", node_id=n.id, ai_fps=8.0, confidence=0.45,
                  analyzers=["intrusion"], motion_enabled=False))
    db.commit()
    from app.services.config_push import build_node_config as bnc
    cam = bnc(db, n)["cameras"][0]
    assert cam["ai_fps"] == 8.0
    assert cam["confidence"] == 0.45
    assert cam["analyzers"] == ["intrusion"]
    assert cam["motion"]["enabled"] is False
    assert cam["motion"]["threshold"] == settings.motion_threshold


def test_build_node_config_camera_uses_global_defaults(db):
    from app.models.camera import Camera
    from app.models.node import Node
    n = Node(name="r5c", type="server")
    db.add(n); db.commit()
    db.add(Camera(name="Def", host="127.0.0.1", node_id=n.id))
    db.commit()
    from app.services.config_push import build_node_config as bnc
    cam = bnc(db, n)["cameras"][0]
    assert cam["ai_fps"] == settings.default_ai_fps
    assert cam["confidence"] == settings.detector_conf
    assert cam["analyzers"] is None          # None = semua analyzer aktif
    assert cam["motion"]["enabled"] is True
