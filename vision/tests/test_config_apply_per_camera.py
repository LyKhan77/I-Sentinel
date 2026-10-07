"""Per-camera config application with idle sources and no external services."""
from copy import deepcopy
import threading

import pytest

from vision.config import NodeSettings
from vision.node import VisionNode
from vision.pipeline.detector import MockDetector


class HoldSource:
    """Keep both worker kinds alive without producing inference frames."""

    target_fps = 5.0

    def __init__(self):
        self.closed = threading.Event()

    def __iter__(self):
        return self

    def __next__(self):
        self.closed.wait()
        raise StopIteration

    def next_frame(self, timeout=None):
        if self.closed.wait(timeout):
            raise StopIteration
        return None

    def close(self):
        self.closed.set()

    def stats(self):
        return {}


class FakeRecorder:
    instances = []

    def __init__(self, camera_id, cfg, transport=None, clip_ring=None):
        assert clip_ring is None
        self.camera_id = camera_id
        self.closed = 0
        self.instances.append(self)

    def close(self):
        self.closed += 1


class FakeFace:
    detect_n = 0
    embed_n = 0

    def loaded(self):
        return True

    def detect_faces(self, img):
        raise AssertionError("HoldSource must not produce frames")


class FakeTransport:
    def publish_event(self, event):
        pass

    def publish_heartbeat(self, heartbeat):
        pass

    def publish_detections(self, camera_id, boxes, kind="person"):
        pass

    def close(self):
        pass


def node_with(tmp_path, monkeypatch, api_key=""):
    monkeypatch.setattr("vision.recorder.Recorder", FakeRecorder)
    FakeRecorder.instances = []
    cfg = NodeSettings(node_id="n", cameras_json="[]", await_config=True,
                       data_dir=str(tmp_path), api_key=api_key)
    node = VisionNode(cfg=cfg, detector_factory=lambda cid: MockDetector([]),
                      source_factory=lambda cam: HoldSource(), transport=FakeTransport())
    node.face = FakeFace()
    return node


@pytest.fixture
def make_node(tmp_path, monkeypatch):
    """Always release workers, including when assertions fail during RED runs."""
    nodes = []

    def make(api_key=""):
        node = node_with(tmp_path, monkeypatch, api_key)
        nodes.append(node)
        return node

    yield make
    for node in nodes:
        node.stop_event.set()
        node._stop_workers()
        node.transport.close()


def cam_cfg(camera_id, attendance=False, **changes):
    polygon = [[0, 0], [1, 0], [1, 1], [0, 1]]
    zones = [{"id": 1, "polygon": polygon,
              "behaviors": [{"kind": "intrusion", "clip": False}]}]
    if attendance:
        zones.append({"id": 9, "polygon": deepcopy(polygon), "direction": "entry",
                      "behaviors": [{"kind": "attendance", "trigger_seconds": 3}]})
    return {"camera_id": camera_id, "source_url": f"test://{camera_id}",
            "ai_fps": 5.0, "confidence": 0.4, "zones": zones, **changes}


def workers(node, camera_id):
    return [w for w in node._workers if w.camera_id == camera_id]


def start_two(node):
    node._start_workers(node._cameras_from_config(
        {"cameras": [cam_cfg(1, attendance=True), cam_cfg(2, attendance=True)]}))


def test_stop_workers_with_filter_stops_only_those_cameras(make_node):
    node = make_node()
    start_two(node)
    before = list(node._workers)
    stopped = node._stop_workers({1})
    assert {w.camera_id for w in stopped} == {1}
    assert all(w.stop_event.is_set() and not w.is_alive() for w in stopped)
    assert node._workers == [w for w in before if w.camera_id == 2]
    assert all(not w.stop_event.is_set() and w.is_alive() for w in node._workers)


def test_stop_workers_without_filter_stops_everything(make_node):
    node = make_node()
    start_two(node)
    before = list(node._workers)
    stopped = node._stop_workers()
    assert stopped == before
    assert node._workers == []
    assert all(w.stop_event.is_set() and not w.is_alive() for w in stopped)


def test_filtered_stop_closes_only_the_recorder_of_stopped_cameras(make_node):
    node = make_node(api_key="k")
    start_two(node)
    rec1, rec2 = workers(node, 1)[0].recorder, workers(node, 2)[0].recorder
    assert all(w.recorder is rec1 for w in workers(node, 1))
    assert all(w.recorder is rec2 for w in workers(node, 2))
    node._stop_workers({1})
    assert rec1.closed == 1
    assert rec2.closed == 0


def test_start_workers_records_applied_for_every_camera(make_node):
    node = make_node()
    node._start_workers(node._cameras_from_config(
        {"cameras": [cam_cfg(1), cam_cfg(3, zones=[])]}))
    assert set(node._applied) == {1, 3}
    assert {w.camera_id for w in node._workers} == {1}


def assert_replaced(before, after):
    assert before and after
    assert not any(old is new for old in before for new in after)
    assert all(w.stop_event.is_set() and not w.is_alive() for w in before)
    assert all(not w.stop_event.is_set() and w.is_alive() for w in after)


def assert_kept(before, after):
    assert before == after
    assert all(not w.stop_event.is_set() and w.is_alive() for w in after)


def test_first_config_after_start_is_a_full_restart(make_node):
    node = make_node()
    node._start_workers(node._cameras_from_config({"cameras": [cam_cfg(9)]}))
    before = list(node._workers)
    # Even the unchanged static camera must restart on the first config push.
    node.apply_config({"cameras": [cam_cfg(9), cam_cfg(1)]})
    assert_replaced(before, workers(node, 9))
    assert all(w.is_alive() for w in workers(node, 1))
    node.apply_config({"cameras": [cam_cfg(1)]})
    assert not workers(node, 9)


def test_same_config_twice_keeps_every_worker(make_node):
    node = make_node(api_key="k")
    cfg = {"cameras": [cam_cfg(1, attendance=True), cam_cfg(2)]}
    node.apply_config(cfg)
    before = list(node._workers)
    recs = [w.recorder for w in before]
    node.apply_config(deepcopy(cfg))
    assert_kept(before, node._workers)
    assert all(w.recorder is rec for w, rec in zip(node._workers, recs))
    assert all(rec.closed == 0 for rec in recs)


@pytest.mark.parametrize("field,value", [
    ("ai_fps", 10),
    ("source_url", "test://changed"),
    ("zones", [{"id": 2, "polygon": [[0, 0], [1, 0], [1, 1], [0, 1]],
                "behaviors": [{"kind": "intrusion", "clip": False}]}]),
    ("confidence", 0.6),
    ("motion", {"enabled": True, "threshold": 25}),
    ("meters_per_pixel", 0.01),
])
def test_changed_camera_restarts_only_that_camera(make_node, field, value):
    node = make_node(api_key="k")
    node.apply_config({"cameras": [cam_cfg(1, attendance=True), cam_cfg(2, attendance=True)]})
    before1, before2 = workers(node, 1), workers(node, 2)
    rec1, rec2 = before1[0].recorder, before2[0].recorder
    node.apply_config({"cameras": [cam_cfg(1, attendance=True, **{field: value}),
                                   cam_cfg(2, attendance=True)]})
    assert_replaced(before1, workers(node, 1))
    assert_kept(before2, workers(node, 2))
    assert rec1.closed == 1 and workers(node, 1)[0].recorder is not rec1
    assert rec2.closed == 0 and workers(node, 2)[0].recorder is rec2


def test_removed_camera_is_stopped_and_added_camera_is_started(make_node):
    node = make_node()
    node.apply_config({"cameras": [cam_cfg(1), cam_cfg(2)]})
    before1, before2 = workers(node, 1), workers(node, 2)
    node.apply_config({"cameras": [cam_cfg(2), cam_cfg(3)]})
    assert not workers(node, 1)
    assert all(w.stop_event.is_set() and not w.is_alive() for w in before1)
    assert_kept(before2, workers(node, 2))
    assert workers(node, 3) and all(w.is_alive() for w in workers(node, 3))
    assert set(node._applied) == {2, 3}


@pytest.mark.parametrize("field,value", [
    ("model", "other.pt"), ("nms", True), ("conf", 0.6), ("imgsz", 960),
])
def test_global_detector_change_restarts_every_camera(make_node, field, value):
    node = make_node()
    cfg = {"detector": {"model": "m.pt", "nms": False, "conf": 0.4, "imgsz": 640},
           "cameras": [cam_cfg(1), cam_cfg(2)]}
    node.apply_config(cfg)
    before = list(node._workers)
    cfg["detector"][field] = value
    node.apply_config(cfg)
    assert_replaced(before, node._workers)


def test_face_settings_change_restarts_only_cameras_with_a_face_worker(make_node):
    node = make_node()
    cfg = {"cameras": [cam_cfg(1, attendance=True), cam_cfg(2)],
           "face": {"min_frames": 3}}
    node.apply_config(cfg)
    before1, before2 = workers(node, 1), workers(node, 2)
    cfg["face"]["min_frames"] = 5
    node.apply_config(cfg)
    assert_replaced(before1, workers(node, 1))
    assert_kept(before2, workers(node, 2))
    assert all(w.settings.min_frames == 5 for w in workers(node, 1) if hasattr(w, "settings"))


def test_failed_camera_start_does_not_block_others_and_reverted_config_restarts_it(make_node, monkeypatch):
    node = make_node()
    v1 = {"cameras": [cam_cfg(1), cam_cfg(2)]}
    node.apply_config(v1)
    before = workers(node, 1)
    original = node._start_camera

    def start(cam):
        if cam.camera_id == 2:
            raise RuntimeError("simulated camera start failure")
        original(cam)

    with monkeypatch.context() as patch:
        patch.setattr(node, "_start_camera", start)
        node.apply_config({"cameras": [cam_cfg(1, ai_fps=10), cam_cfg(2, ai_fps=10)]})
    assert_replaced(before, workers(node, 1))
    assert not workers(node, 2)
    assert 2 not in node._applied
    node.apply_config(v1)
    assert workers(node, 2) and all(w.is_alive() for w in workers(node, 2))
    assert set(node._applied) == {1, 2}


def test_unexpected_diff_error_falls_back_to_full_restart(make_node, monkeypatch, caplog):
    node = make_node()
    node.apply_config({"cameras": [cam_cfg(1), cam_cfg(2)]})
    before = list(node._workers)
    original = node._stop_workers
    raised = []

    def stop(camera_ids=None):
        if camera_ids is not None and not raised:
            raised.append(True)
            raise RuntimeError("simulated diff failure")
        return original(camera_ids)

    monkeypatch.setattr(node, "_stop_workers", stop)
    node.apply_config({"cameras": [cam_cfg(1, ai_fps=10), cam_cfg(2)]})
    assert raised == [True]
    assert "config diff failed; full restart" in caplog.text
    assert_replaced(before, node._workers)


def test_changed_camera_replaces_only_its_recorder(make_node):
    node = make_node(api_key="k")
    node.apply_config({"cameras": [cam_cfg(1, attendance=True), cam_cfg(2, attendance=True)]})
    rec1, rec2 = workers(node, 1)[0].recorder, workers(node, 2)[0].recorder
    node.apply_config({"cameras": [cam_cfg(1, attendance=True, ai_fps=10),
                                   cam_cfg(2, attendance=True)]})
    assert rec1.closed == 1
    assert rec2.closed == 0
    assert all(w.recorder is rec2 for w in workers(node, 2))
    assert all(w.recorder is workers(node, 1)[0].recorder for w in workers(node, 1))
    assert workers(node, 1)[0].recorder is not rec1


def test_camera_without_zones_starts_once_a_zone_arrives_and_readded_camera_forgets_old_confidence(make_node):
    node = make_node()
    node.apply_config({"cameras": [cam_cfg(1, zones=[], confidence=0.7)]})
    assert not workers(node, 1) and 1 in node._applied
    node.apply_config({"cameras": [cam_cfg(1, confidence=0.7)]})
    assert workers(node, 1) and all(w.is_alive() for w in workers(node, 1))
    node.apply_config({"cameras": []})
    assert 1 not in node._camera_conf
    readded = cam_cfg(1)
    readded.pop("confidence")
    node.apply_config({"cameras": [readded]})
    assert workers(node, 1) and 1 not in node._camera_conf


def test_apply_logs_restarted_added_removed_unchanged(make_node, caplog):
    node = make_node()
    node.apply_config({"cameras": [cam_cfg(1), cam_cfg(2)]})
    with caplog.at_level("INFO", logger="vision.node"):
        node.apply_config({"cameras": [cam_cfg(1, ai_fps=10), cam_cfg(3)]})
    assert "config applied: restarted [1], added [3], removed [2], unchanged 0" in caplog.text


def test_queued_configs_are_coalesced_to_the_latest(make_node):
    node = make_node()
    configs = [{"cameras": [cam_cfg(1, ai_fps=fps)]} for fps in (5, 10, 15)]
    applied = []
    latest_seen = threading.Event()

    def apply(cfg):
        applied.append(cfg)
        if cfg is configs[-1]:
            latest_seen.set()

    node.apply_config = apply
    for cfg in configs:
        node._config_q.put(cfg)
    runner = threading.Thread(target=node.run, daemon=True)
    runner.start()
    try:
        assert latest_seen.wait(5), "The latest queued snapshot was not applied"
    finally:
        node.stop_event.set()
        runner.join(timeout=5)
    assert not runner.is_alive()
    assert applied == [configs[-1]]
    assert applied[0] is configs[-1]
