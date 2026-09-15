"""Config apply (hot reload) tests: transport subscribe + node worker rebuild."""
import json
import threading

import numpy as np

from vision.config import NodeSettings
from vision.node import VisionNode
from vision.pipeline.detector import Detection, MockDetector
from vision.pipeline.source import FrameSource
from vision.transport import MqttTransport
from vision.transport import mqtt as mqtt_mod


class FakeResult:
    def __init__(self, rc):
        self.rc = rc


class FakeClient:
    def __init__(self, *a, **kw):
        self.published = []       # (topic, payload, qos, retain)
        self.subscribed = []      # (topic, qos)
        self.publish_rc = 0
        self.connected = True
        self._lock = threading.Lock()

    def username_pw_set(self, u, p=None):
        pass

    def will_set(self, topic, payload, retain=False, qos=0):
        pass

    def connect(self, host, port):
        self.host_port = (host, port)
        self.on_connect(self, None, None, 0, None)

    def loop_start(self):
        pass

    def loop_stop(self):
        pass

    def disconnect(self):
        pass

    def is_connected(self):
        return self.connected

    def subscribe(self, topic, qos=0):
        self.subscribed.append((topic, qos))
        return FakeResult(0)

    def publish(self, topic, payload, qos=0, retain=False):
        with self._lock:
            self.published.append((topic, payload, qos, retain))
        return FakeResult(0)


def frame():
    return np.zeros((4, 4, 3), dtype=np.uint8)


def make_node(cameras_scripts, cfg=None, det_scripts=None):
    """cameras_scripts: {camera_id: frame-detection-lists}.
    det_scripts: detector scripts keyed by cid (defaults to cameras_scripts).
    Returns (node, transport)."""
    cfg = cfg or NodeSettings(node_id="server", cameras_json=json.dumps([
        {"camera_id": cid, "source_url": f"test://{cid}", "ai_fps": 5.0}
        for cid in cameras_scripts
    ]))
    srcs = {cid: FrameSource.from_frames([frame()] * len(s), fps=5.0)
            for cid, s in cameras_scripts.items()}
    det_scripts = cameras_scripts if det_scripts is None else det_scripts
    dets = {cid: MockDetector([[Detection(bbox=b, conf=0.9) for b in dets] for dets in s])
            for cid, s in det_scripts.items()}
    t = FakeTransportWithCfg()
    node = VisionNode(cfg=cfg, detector_factory=lambda cid: dets[cid],
                      source_factory=lambda cam: srcs[cam.camera_id], transport=t)
    return node, t


class FakeTransportWithCfg:
    """Fake that behaves like MqttTransport incl. on_config callback."""

    def __init__(self):
        self.events = []
        self.heartbeats = []
        self.close_calls = 0

    def publish_event(self, ev):
        self.events.append(ev)

    def publish_heartbeat(self, hb):
        self.heartbeats.append(hb)

    def close(self):
        self.close_calls += 1


def test_transport_subscribes_config_topic(tmp_path, monkeypatch):
    monkeypatch.setattr(mqtt_mod.mqtt, "Client", lambda *a, **kw: FakeClient())
    cfg = type("Cfg", (), {
        "node_id": "server", "mqtt_url": "localhost:1883", "mqtt_username": "",
        "mqtt_password": "", "data_dir": str(tmp_path / "data"),
    })()
    received = []
    t = MqttTransport(cfg, on_config=received.append)
    assert ("isentinel/config/server", 1) in t._client.subscribed
    # on_config callback fires on message to config topic
    t._on_message(t._client, None, type("M", (), {"topic": "isentinel/config/server",
                                                  "payload": b'{"x":1}'})())
    assert received == [{"x": 1}]


def test_apply_config_rebuilds_workers(tmp_path):
    # start with camera 2; apply config: cameras 3 (zone) + 4, camera 2 removed.
    # sources for new cams: 1 frame each; detectors scripted for 3 and 4.
    new_srcs = {3: FrameSource.from_frames([frame()], fps=5.0),
                4: FrameSource.from_frames([frame()], fps=5.0)}
    node, t = make_node(
        {2: [[(0.4, 0.4, 0.6, 0.6)]]},
        det_scripts={2: [[]], 3: [[(0.4, 0.4, 0.6, 0.6)]], 4: [[(0.4, 0.4, 0.6, 0.6)]]},
    )
    real_factory = node.detector_factory
    node.source_factory = lambda cam: new_srcs.get(cam.camera_id) or node.source_factory(cam)
    node.apply_config({
        "cameras": [
            {"camera_id": 3, "source_url": "test://3", "ai_fps": 5.0,
             "zones": [{"id": 7, "name": "Z", "type": "restricted", "severity": "warning",
                        "polygon": [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]],
                        "schedule": None}]},
            {"camera_id": 4, "source_url": "test://4", "ai_fps": 5.0, "zones": []},
        ],
        "detector": {"model": "yolo26s.pt", "nms": False, "conf": 0.4, "imgsz": 640},
    })
    node.run()
    # camera 3: person inside polygon -> intrusion event
    intrusion = [e for e in t.events if e["type"] == "intrusion"]
    assert len(intrusion) == 1
    ev = intrusion[0]
    assert ev["zone_id"] == 7 and ev["severity"] == "warning"
    assert ev["camera_id"] == 3 and ev["node_id"] == "server"
    assert ev["payload"]["zone_name"] == "Z" and ev["payload"]["track_id"] == 1
    # camera 4: person outside any zone -> plain person_detect only (cam 3 emits
    # person_detect + intrusion; both already asserted above)
    plain = [e for e in t.events if e["type"] == "person_detect"]
    assert {e["camera_id"] for e in plain} == {3, 4}
    # camera 2 worker stopped: no events from it
    assert not any(e["camera_id"] == 2 for e in t.events)


def test_apply_config_camera_removal_stops_worker(tmp_path):
    node, t = make_node(
        {2: [[]], 5: [[(0.1, 0.1, 0.3, 0.4)]]},
        det_scripts={2: [[(0.1, 0.1, 0.3, 0.4)], [(0.1, 0.1, 0.3, 0.4)], [(0.1, 0.1, 0.3, 0.4)]],
                     5: [[(0.1, 0.1, 0.3, 0.4)]]},
    )
    # apply config that drops camera 2 before running — but workers already
    # started from cameras_json? No: apply before run replaces cfg entirely.
    node.apply_config({"cameras": [{"camera_id": 5, "source_url": "test://5",
                                    "ai_fps": 5.0, "zones": []}]})
    node.run()
    assert not any(e["camera_id"] == 2 for e in t.events)
    assert {e["camera_id"] for e in t.events} == {5}


def test_no_config_backward_compat(tmp_path):
    node, t = make_node({2: [[(0.1, 0.1, 0.3, 0.4)]]})
    node.run()
    assert len(t.events) == 1
    assert t.events[0]["type"] == "person_detect"
