"""VisionNode end-to-end with injected sources/detectors/transport. No cv2, no MQTT."""
import json
import re
import threading
import uuid
from datetime import datetime

import numpy as np


from vision.config import CameraCfg, NodeSettings
from vision.node import CameraWorker, VisionNode
from vision.pipeline.detector import Detection, MockDetector
from vision.pipeline.source import FrameSource

CONTRACT_KEYS = {"event_id", "type", "node_id", "camera_id", "zone_id", "severity",
                 "ts_event", "payload", "dedup_key"}
PAYLOAD_KEYS = {"track_id", "confidence", "speed_mps", "duration_s", "direction",
                "employee_id", "face_score", "bbox_norm", "snapshot_crop"}
ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?\+00:00$")


class FakeTransport:
    def __init__(self):
        self.events = []
        self.heartbeats = []

    def publish_event(self, ev):
        self.events.append(ev)

    def publish_heartbeat(self, hb):
        self.heartbeats.append(hb)

    def close(self):
        pass


def script(frames_dets):
    """frames_dets: list of detection-lists -> MockDetector consuming one per frame."""
    return MockDetector([[Detection(bbox=b, conf=0.9) for b in dets] for dets in frames_dets])


def make_node(tmp_path, cameras_scripts, transport=None):
    """cameras_scripts: {camera_id: list-of-frame-detection-lists}"""
    frame = np.zeros((4, 4, 3), dtype=np.uint8)
    cfg = NodeSettings(node_id="test-node", cameras_json=json.dumps([
        {"camera_id": cid, "source_url": f"test://{cid}", "ai_fps": 5.0}
        for cid in cameras_scripts
    ]))
    srcs = {cid: FrameSource.from_frames([frame] * len(s), fps=5.0)
            for cid, s in cameras_scripts.items()}
    dets = {cid: script(s) for cid, s in cameras_scripts.items()}
    t = transport or FakeTransport()
    node = VisionNode(
        cfg=cfg,
        detector_factory=lambda cid: dets[cid],
        source_factory=lambda cam: srcs[cam.camera_id],
        transport=t,
    )
    return node, t


def test_node_two_cameras_event_contract(tmp_path):
    # cam 2: person appears frame1, stays; cam 3: person appears frame1 only
    node, t = make_node(tmp_path, {
        2: [[(0.1, 0.1, 0.3, 0.4)], [(0.1, 0.1, 0.3, 0.4)], [(0.1, 0.1, 0.3, 0.4)]],
        3: [[(0.5, 0.5, 0.7, 0.8)], [], []],
    })
    node.run()
    assert len(t.events) == 2  # one new track per camera
    for ev in t.events:
        assert set(ev) == CONTRACT_KEYS
        assert set(ev["payload"]) == PAYLOAD_KEYS
        assert uuid.UUID(ev["event_id"])
        assert ev["type"] == "person_detect" and ev["severity"] == "info"
        assert ev["node_id"] == "test-node" and ev["zone_id"] is None
        assert ISO_RE.match(ev["ts_event"])
        assert datetime.fromisoformat(ev["ts_event"]).tzinfo is not None
        assert all(0.0 <= v <= 1.0 for v in ev["payload"]["bbox_norm"])
        assert ev["payload"]["track_id"] in (1,)
        assert all(ev["payload"][k] is None for k in
                   ("confidence", "speed_mps", "duration_s", "direction",
                    "employee_id", "face_score", "snapshot_crop"))
        m = re.match(r"^(\d+):person_detect:(\d+):(\d+)$", ev["dedup_key"])
        assert m and m.group(1) == str(ev["camera_id"]) and m.group(2) == str(ev["payload"]["track_id"])
    by_cam = {ev["camera_id"] for ev in t.events}
    assert by_cam == {2, 3}


def test_detector_exception_worker_survives(tmp_path):
    node, t = make_node(tmp_path, {4: [[], [], []]})
    calls = {"n": 0}
    det = script([[(0.1, 0.1, 0.3, 0.4)], [], []])
    real_detect = det.detect

    def flaky(data, ts=0.0):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return real_detect(data, ts=ts)

    node.detector_factory = lambda cid: type("D", (), {"detect": staticmethod(flaky)})()
    node.run()
    assert calls["n"] == 3  # all frames attempted despite exception
    # event still emitted for track created on frame 2
    assert len(t.events) == 1


def test_camera_worker_stop_event(tmp_path):
    cfg = CameraCfg(camera_id=1, source_url="test://1", ai_fps=5.0)
    stop = threading.Event()
    src = FrameSource.from_frames([np.zeros((4, 4, 3), dtype=np.uint8)] * 100, fps=100.0)
    w = CameraWorker(cfg, lambda cid: script([[(0.1, 0.1, 0.3, 0.4)]] * 100),
                     FakeTransport(), stop, "n1")
    w.source = src
    w.start()
    stop.set()
    w.join(timeout=3)
    assert not w.is_alive()
