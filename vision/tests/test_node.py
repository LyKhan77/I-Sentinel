"""VisionNode end-to-end with injected sources/detectors/transport. No cv2, no MQTT."""
import json
import re
import threading
import time
import uuid
from datetime import datetime

import numpy as np
import pytest


from vision.config import CameraCfg, NodeSettings
from vision.node import CameraWorker, VisionNode, attendance_zones, main_stream_name, main_stream_url
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

    def publish_detections(self, camera_id, boxes, kind="person"):
        self.detections = getattr(self, 'detections', [])
        self.detections.append((camera_id, kind, boxes))

    def close(self):
        pass


def script(frames_dets):
    """frames_dets: list of detection-lists -> MockDetector consuming one per frame."""
    return MockDetector([[Detection(bbox=b, conf=0.9) for b in dets] for dets in frames_dets])


def make_node(tmp_path, cameras_scripts, transport=None):
    """cameras_scripts: {camera_id: list-of-frame-detection-lists}"""
    frame = np.zeros((4, 4, 3), dtype=np.uint8)
    cfg = NodeSettings(node_id="test-node", emit_person_detect=True, cameras_json=json.dumps([
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


# --- R5: analyzer dibangun dari behaviors + master per kamera -----------------

BEHAVIOR_ZONE = {
    "id": 21, "name": "Lorong", "type": "behavior", "direction": None,
    "polygon": [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]],
    "behaviors": [{"kind": "intrusion", "trigger_seconds": 0},
                  {"kind": "loitering", "trigger_seconds": 30}],
    "snapshot": True, "clip": True,
}


def _node_with(cam: dict):
    import json
    from vision.config import NodeSettings
    from vision.node import VisionNode
    cfg = NodeSettings(node_id="n", cameras_json=json.dumps([cam]))
    return VisionNode(cfg=cfg, transport=object(), source_factory=lambda c: None)


def test_make_analyzers_from_behaviors_master_filters():
    cam = {"camera_id": 1, "source_url": "test://1", "zones": [BEHAVIOR_ZONE],
           "analyzers": ["intrusion"]}
    node = _node_with(cam)
    cams = node._cameras_from_config({"cameras": [cam]})
    assert [type(a).__name__ for a in node._make_analyzers(cams[0])] == ["IntrusionAnalyzer"]


def test_make_analyzers_all_behaviors_when_master_none():
    cam = {"camera_id": 1, "source_url": "test://1", "zones": [BEHAVIOR_ZONE]}
    node = _node_with(cam)
    cams = node._cameras_from_config({"cameras": [cam]})
    kinds = sorted(type(a).__name__ for a in node._make_analyzers(cams[0]))
    assert kinds == ["IntrusionAnalyzer", "LoiteringAnalyzer"]


def test_make_analyzers_empty_master_means_no_analyzer():
    cam = {"camera_id": 1, "source_url": "test://1", "zones": [BEHAVIOR_ZONE],
           "analyzers": []}
    node = _node_with(cam)
    cams = node._cameras_from_config({"cameras": [cam]})
    assert node._make_analyzers(cams[0]) == []


def test_legacy_zone_without_behaviors_still_builds_analyzers():
    """Config pra-R5 (type + loiter_seconds) tetap jalan selama transisi."""
    legacy = {"id": 22, "name": "Legacy", "type": "restricted",
              "polygon": [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0]],
              "loiter_seconds": 30}
    cam = {"camera_id": 1, "source_url": "test://1", "zones": [legacy]}
    node = _node_with(cam)
    cams = node._cameras_from_config({"cameras": [cam]})
    kinds = sorted(type(a).__name__ for a in node._make_analyzers(cams[0]))
    assert kinds == ["IntrusionAnalyzer", "LoiteringAnalyzer"]


def test_camera_confidence_overrides_global():
    """confidence per kamera dari config R5 benar-benar dipakai detektor."""
    from vision.config import NodeSettings
    from vision.node import VisionNode
    import json
    cam = {"camera_id": 5, "source_url": "test://1", "confidence": 0.45, "zones": []}
    cfg = NodeSettings(node_id="n", cameras_json=json.dumps([cam]))
    node = VisionNode(cfg=cfg, transport=object(), source_factory=lambda c: None)
    node._cameras_from_config({"cameras": [cam]})
    assert node.detector_factory(5).conf == 0.45
    assert node.detector_factory(99).conf == node.cfg.detector_conf   # tanpa override

def test_worker_publishes_person_detection_kind(tmp_path):
    """Debugger receives the producer kind as a top-level detection field."""
    node, transport = make_node(tmp_path, {2: [[(0.1, 0.1, 0.3, 0.4)]]})

    node.run()

    camera_id, kind, boxes = transport.detections[0]
    assert camera_id == 2
    assert kind == "person"
    assert boxes == [{"id": 1, "bbox_norm": [0.1, 0.1, 0.3, 0.4], "label": None}]


ATTENDANCE_ZONE = {
    "id": 9, "name": "Gate", "type": "attendance", "direction": "entry",
    "polygon": [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]],
    "behaviors": [{"kind": "attendance", "trigger_seconds": 3}],
}


@pytest.mark.parametrize("master", [["intrusion"], []])
def test_attendance_zone_not_filtered_by_camera_master(master):
    cam = {"camera_id": 1, "source_url": "test://1", "zones": [ATTENDANCE_ZONE],
           "analyzers": master}
    node = _node_with(cam)
    camera = node._cameras_from_config({"cameras": [cam]})[0]
    assert [z["id"] for z in attendance_zones(camera)] == [9]
    assert node._make_analyzers(camera) == []


def test_legacy_absensi_zone_is_attendance():
    legacy = {"id": 11, "type": "absensi", "direction": "entry",
              "polygon": ATTENDANCE_ZONE["polygon"], "dwell_seconds": 3}
    cam = {"camera_id": 1, "source_url": "test://1", "zones": [legacy]}
    node = _node_with(cam)
    camera = node._cameras_from_config({"cameras": [cam]})[0]
    assert [z["id"] for z in attendance_zones(camera)] == [11]


@pytest.mark.parametrize("direction", [None, "sideways"])
def test_behavior_attendance_without_valid_direction_is_not_a_gate(direction, tmp_path):
    invalid = {"id": 22, "type": "behavior", "direction": direction,
               "polygon": ATTENDANCE_ZONE["polygon"],
               "behaviors": [{"kind": "attendance"}]}
    cam = {"camera_id": 363, "source_url": "test://363", "zones": [invalid]}
    node = _node_with(cam)
    assert attendance_zones(node._cameras_from_config({"cameras": [cam]})[0]) == []
    _, workers, urls, _ = _wired_node(tmp_path, [invalid, ATTENDANCE_ZONE])
    assert [type(w).__name__ for w in workers] == ["FaceGateWorker"]
    assert [z["id"] for z in workers[0].zones] == [9]
    assert urls == ["rtsp://h:8554/cam_363_main"]


def test_main_stream_url_and_name():
    assert main_stream_name("rtsp://localhost:8554/cam_4") == "cam_4_main"
    assert main_stream_name("rtsp://localhost:8554/cam_12/") == "cam_12_main"
    assert main_stream_name("test://1") is None
    assert main_stream_url("rtsp://h:8554/cam_363") == "rtsp://h:8554/cam_363_main"
    assert main_stream_url("test://1") == "test://1"


class _NoFaces:
    detect_n = 0
    embed_n = 0

    def loaded(self):
        return True

    def detect_faces(self, img):
        return []


def _wired_node(tmp_path, zones, api_key="", analyzers=None):
    urls, det_calls = [], []
    frame = np.zeros((4, 4, 3), np.uint8)
    cfg = NodeSettings(node_id="n", cameras_json="[]", api_key=api_key, data_dir=str(tmp_path))

    def source_factory(cam):
        urls.append(cam.source_url)
        return FrameSource.from_frames([frame] * 2, fps=5.0)

    def detector_factory(cid):
        det_calls.append(cid)
        return MockDetector([[], []])

    node = VisionNode(cfg=cfg, detector_factory=detector_factory,
                      source_factory=source_factory, transport=FakeTransport())
    node.face = _NoFaces()
    node.apply_config({"cameras": [{"camera_id": 363, "source_url": "rtsp://h:8554/cam_363",
                                    "zones": zones, "analyzers": analyzers}],
                       "face": {"device": "", "min_frames": 5}})
    workers = list(node._workers)
    node._stop_workers()
    return node, workers, urls, det_calls


def test_attendance_only_camera_runs_face_worker_without_yolo(tmp_path):
    node, workers, urls, det_calls = _wired_node(tmp_path, [ATTENDANCE_ZONE])
    assert [type(w).__name__ for w in workers] == ["FaceGateWorker"]
    assert urls == ["rtsp://h:8554/cam_363_main"]
    assert det_calls == []
    assert node._face_settings.min_frames == 5 and node._face_settings.min_width_px == 80.0


def test_mixed_camera_runs_both_workers_sharing_one_recorder(tmp_path, monkeypatch):
    import vision.recorder as recorder
    recorders, closes = [], []
    original = recorder.Recorder

    def make_recorder(*args):
        rec = original(*args)
        close = rec.close
        def close_once():
            closes.append(rec)
            close()
        rec.close = close_once
        recorders.append(rec)
        return rec

    monkeypatch.setattr(recorder, "Recorder", make_recorder)
    _, workers, urls, det_calls = _wired_node(tmp_path, [ATTENDANCE_ZONE, BEHAVIOR_ZONE],
                                              api_key="k")
    assert sorted(type(w).__name__ for w in workers) == ["CameraWorker", "FaceGateWorker"]
    assert sorted(urls) == ["rtsp://h:8554/cam_363", "rtsp://h:8554/cam_363_main"]
    assert workers[0].recorder is workers[1].recorder is recorders[0]
    assert recorders == closes  # shared recorder closed only once
    assert det_calls == [363]


def test_legacy_absensi_runs_face_worker_without_yolo(tmp_path):
    legacy = {"id": 11, "type": "absensi", "direction": "entry",
              "polygon": ATTENDANCE_ZONE["polygon"]}
    _, workers, urls, det_calls = _wired_node(tmp_path, [legacy])
    assert [type(w).__name__ for w in workers] == ["FaceGateWorker"]
    assert [z["id"] for z in workers[0].zones] == [11]
    assert urls == ["rtsp://h:8554/cam_363_main"] and det_calls == []


def test_disabled_face_does_not_start_orphan_recorder(tmp_path, monkeypatch):
    import vision.recorder as recorder
    created = []
    monkeypatch.setattr(recorder, "Recorder", lambda *args: created.append(args))
    cfg = NodeSettings(node_id="n", cameras_json="[]", face_embed=False,
                       api_key="k", data_dir=str(tmp_path))
    node = VisionNode(cfg, detector_factory=lambda _: pytest.fail("YOLO started"),
                      source_factory=lambda _: pytest.fail("source opened"),
                      transport=FakeTransport())
    node.apply_config({"cameras": [{"camera_id": 363, "source_url": "test://363",
                                    "zones": [ATTENDANCE_ZONE]}]})
    assert node._workers == []
    assert created == []


@pytest.mark.parametrize("preapply", [False, True])
def test_no_face_workers_keep_node_listening_for_config(tmp_path, preapply):
    transport = FakeTransport()
    closed = []
    transport.close = lambda: closed.append(True)
    attendance_cam = {"camera_id": 363, "source_url": "test://363",
                      "zones": [ATTENDANCE_ZONE]}
    cfg = NodeSettings(node_id="n", cameras_json="[]" if preapply else json.dumps([attendance_cam]),
                       face_embed=False, heartbeat_s=0.02, data_dir=str(tmp_path))
    det_calls = []
    node = VisionNode(cfg, detector_factory=lambda cid: det_calls.append(cid) or MockDetector([[]]),
                      source_factory=lambda cam: FrameSource.from_frames(
                          [np.zeros((4, 4, 3), np.uint8)], fps=5), transport=transport)
    if preapply:
        node.apply_config({"cameras": [attendance_cam]})
        assert node._workers == []
    runner = threading.Thread(target=node.run, daemon=True)
    runner.start()
    try:
        deadline = time.monotonic() + 2
        while not transport.heartbeats and time.monotonic() < deadline:
            time.sleep(0.01)
        assert transport.heartbeats
        time.sleep(0.3)  # past run loop's 0.2 s config poll; must still be receptive
        assert runner.is_alive() and not closed and not node.stop_event.is_set()
        assert node._workers == []
        assert det_calls == []  # attendance-only stays off YOLO while disabled
        node._config_q.put({"cameras": [{"camera_id": 363, "source_url": "test://363",
                                          "zones": [BEHAVIOR_ZONE]}]})
        deadline = time.monotonic() + 2
        while not det_calls and time.monotonic() < deadline:
            time.sleep(0.01)
        assert det_calls == [363]  # hot reload still consumed
    finally:
        node.stop_event.set()
        runner.join(timeout=3)
    assert not runner.is_alive() and closed == [True]


def test_heartbeat_reports_face_module_and_distinct_cameras(tmp_path):
    node, workers, *_ = _wired_node(tmp_path, [ATTENDANCE_ZONE, BEHAVIOR_ZONE])
    assert node._face_module_info() == {"device": "auto", "loaded": True,
                                        "detect_n": 0, "embed_n": 0}
    node._workers = workers
    def publish_once(hb):
        node.transport.heartbeats.append(hb)
        node.stop_event.set()
    node.transport.publish_heartbeat = publish_once
    node._heartbeat_loop()
    assert node.transport.heartbeats[0]["cameras"] == [363]
    assert node.transport.heartbeats[0]["modules"]["face"] == node._face_module_info()
