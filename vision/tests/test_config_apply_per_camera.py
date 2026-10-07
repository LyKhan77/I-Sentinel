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
