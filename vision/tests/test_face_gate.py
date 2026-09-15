"""FaceGateAnalyzer (absensi zone attendance) + crop/upload tests. No network."""
import json
import threading

import numpy as np

from vision.analyzers.face_gate import FaceGateAnalyzer, crop_upper_body
from vision.config import CameraCfg, NodeSettings
from vision.node import CameraWorker, VisionNode
from vision.pipeline.detector import Detection, MockDetector
from vision.pipeline.source import FrameSource

SQUARE = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]


class FakeTrack:
    def __init__(self, tid, bbox, centroid):
        self.id = tid
        self.bbox = bbox
        self.centroid = centroid


class FakeTransport:
    def __init__(self):
        self.events = []

    def publish_event(self, ev):
        self.events.append(ev)

    def publish_heartbeat(self, hb):
        pass

    def close(self):
        pass


class FakeRecorder:
    """Spy recorder: upload_bytes returns a fixed path."""

    def __init__(self, path="crops/x.jpg"):
        self.path = path
        self.uploaded = []
        self.enqueued = []
        self.pushed = []

    def push_jpeg(self, ts, jpeg):
        self.pushed.append(jpeg)

    def upload_bytes(self, data, kind, content_type="image/jpeg"):
        self.uploaded.append((kind, content_type, data))
        return self.path

    def enqueue(self, ev):
        self.enqueued.append(ev)

    def close(self):
        pass


def zone(**kw):
    z = {"id": 11, "type": "absensi", "direction": "entry", "polygon": SQUARE}
    z.update(kw)
    return z


def one_track(tid, centroid, bbox=(0.4, 0.4, 0.5, 0.6)):
    return [FakeTrack(tid, bbox, centroid)]


def frame():
    return np.zeros((480, 640, 3), dtype=np.uint8)


def run_worker(analyzers, detector, frames, recorder):
    cfg = CameraCfg(camera_id=1, source_url="test://1", ai_fps=5.0)
    t = FakeTransport()
    w = CameraWorker(cfg, lambda cid: detector, t, threading.Event(), "test-node",
                     analyzers=analyzers, recorder=recorder)
    w.source = FrameSource.from_frames(frames, fps=100.0)
    w.start()
    w.join(timeout=10)
    return w, t


# --- FaceGateAnalyzer ---

def test_enter_emits_attendance_with_needs_crop():
    az = FaceGateAnalyzer(zone())
    evs = az.on_frame(1000.0, one_track(1, (0.5, 0.5)), 640, 480)
    assert evs == [{
        "zone_id": 11, "type": "attendance", "severity": "info",
        "payload": {"direction": "entry", "track_id": 1,
                    "bbox_norm": [0.4, 0.4, 0.5, 0.6], "needs_crop": True},
    }]


def test_stay_silent_reenter_after_cooldown_emits():
    az = FaceGateAnalyzer(zone())
    assert len(az.on_frame(1000.0, one_track(1, (0.5, 0.5)), 640, 480)) == 1
    # still inside -> nothing
    assert az.on_frame(1000.5, one_track(1, (0.55, 0.5)), 640, 480) == []
    # leaves polygon -> nothing
    assert az.on_frame(1001.0, one_track(1, (1.5, 0.5)), 640, 480) == []
    # re-enters after cooldown -> emits again
    assert len(az.on_frame(1011.0, one_track(1, (0.5, 0.5)), 640, 480)) == 1


def test_direction_none_or_invalid_inert():
    assert FaceGateAnalyzer(zone(direction=None)).on_frame(
        1000.0, one_track(1, (0.5, 0.5)), 640, 480) == []
    assert FaceGateAnalyzer(zone(direction="sideways")).on_frame(
        1000.0, one_track(1, (0.5, 0.5)), 640, 480) == []


def test_cooldown_blocks_fast_reentry():
    az = FaceGateAnalyzer(zone())
    az.on_frame(1000.0, one_track(1, (0.5, 0.5)), 640, 480)
    az.on_frame(1001.0, one_track(1, (1.5, 0.5)), 640, 480)  # out
    assert az.on_frame(1002.0, one_track(1, (0.5, 0.5)), 640, 480) == []  # < 10s
    assert len(az.on_frame(1011.0, one_track(1, (0.5, 0.5)), 640, 480)) == 1


# --- worker crop + upload ---

def test_worker_uploads_crop_and_sets_crop_path():
    rec = FakeRecorder()
    det = MockDetector([[Detection(bbox=(0.2, 0.1, 0.4, 0.9), conf=0.9)]] * 2)
    _, t = run_worker([FaceGateAnalyzer(zone())], det, [frame()] * 2, rec)
    assert len(t.events) == 1
    ev = t.events[0]
    assert ev["type"] == "attendance" and ev["zone_id"] == 11
    assert ev["payload"]["crop_path"] == "crops/x.jpg"
    assert "needs_crop" not in ev["payload"]
    assert rec.uploaded and rec.uploaded[0][0] == "crop"
    assert rec.uploaded[0][1] == "image/jpeg" and isinstance(rec.uploaded[0][2], bytes)


def test_worker_without_recorder_emits_no_crop_path():
    det = MockDetector([[Detection(bbox=(0.2, 0.1, 0.4, 0.9), conf=0.9)]] * 2)
    _, t = run_worker([FaceGateAnalyzer(zone())], det, [frame()] * 2, None)
    assert len(t.events) == 1
    assert "crop_path" not in t.events[0]["payload"]
    assert "needs_crop" not in t.events[0]["payload"]


# --- crop math ---

def test_crop_upper_body_expand_20pct_upper_60pct():
    f = np.zeros((480, 640, 3), dtype=np.uint8)
    # bbox 0.4..0.6 x, 0.4..0.8 y -> expand 20%, keep top 60% height
    assert crop_upper_body(f, [0.4, 0.4, 0.6, 0.8]).shape == (161, 179, 3)
    # full-frame bbox clamps to frame bounds
    assert crop_upper_body(f, [0.0, 0.0, 1.0, 1.0]).shape == (288, 640, 3)
    assert crop_upper_body(None, [0.4, 0.4, 0.6, 0.8]) is None


# --- node config wiring ---

def test_absensi_zone_passes_filter_and_builds_analyzer():
    cfg = NodeSettings(node_id="n", cameras_json=json.dumps([
        {"camera_id": 1, "source_url": "test://1", "zones": [
            {"id": 11, "type": "absensi", "direction": "entry", "polygon": SQUARE},
            {"id": 12, "type": "free", "polygon": SQUARE},  # dropped by filter
        ]},
    ]))
    node = VisionNode(cfg=cfg, transport=object(), source_factory=lambda c: None)
    cams = node._cameras_from_config({"cameras": json.loads(cfg.cameras_json)})
    assert [z["id"] for z in cams[0].zones] == [11]
    assert [type(a).__name__ for a in node._make_analyzers(cams[0])] == ["FaceGateAnalyzer"]
