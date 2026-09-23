"""FaceGateWorker: face-first on main frames without GPU or YOLO."""

import threading
import time

import cv2
import numpy as np
import pytest

from vision.face import FaceDet
from vision.face_quality import FaceSettings
from vision.face_worker import FaceGateWorker
from vision.pipeline.source import Frame, FrameSource

FRAME = np.zeros((1080, 1920, 3), np.uint8)
SHARP = np.random.default_rng(0).integers(0, 255, (112, 112, 3), dtype=np.uint8)
FRONTAL = np.array([[40, 60], [80, 60], [60, 85], [45, 110], [75, 110]], dtype=np.float32)
ZONE = {"id": 9, "direction": "entry",
        "polygon": [[0.25, 0.25], [0.75, 0.25], [0.75, 0.75], [0.25, 0.75]]}
E1 = [1.0] + [0.0] * 511
NEG = [-1.0] + [0.0] * 511


def face(cx=960.0, cy=540.0, width=120.0, score=0.9):
    x1, y1 = cx - width / 2, cy - width * 0.6
    kps = (FRONTAL - FRONTAL.mean(axis=0)) * (width / 60.0) + np.array([cx, cy], dtype=np.float32)
    return FaceDet(bbox=(x1, y1, x1 + width, y1 + width * 1.2), kps=kps, score=score)


GOOD = face()


class FakeFaces:
    def __init__(self, per_frame, vectors=None, aligned=SHARP):
        self.per_frame = list(per_frame)
        self.vectors = list(vectors or [])
        self.aligned = aligned
        self.embed_calls = 0

    def detect_faces(self, img):
        item = self.per_frame.pop(0) if self.per_frame else []
        if isinstance(item, Exception):
            raise item
        return item

    def align(self, img, kps):
        return self.aligned

    def embed(self, aligned):
        self.embed_calls += 1
        return self.vectors.pop(0) if self.vectors else E1


class FakeTransport:
    def __init__(self):
        self.events, self.detections = [], []

    def publish_event(self, ev):
        self.events.append(ev)

    def publish_detections(self, camera_id, boxes, kind="person"):
        self.detections.append((camera_id, kind, boxes))


class FakeRecorder:
    def __init__(self, fail=False):
        self.fail = fail
        self.uploads = []

    def upload_bytes(self, data, kind, content_type="image/jpeg", **kwargs):
        self.uploads.append((kind, data))
        return None if self.fail else f"{kind}s/x.jpg"


def run_worker(frames_faces, engine=None, transport=None, recorder=None, settings=FaceSettings()):
    t = transport or FakeTransport()
    eng = engine or FakeFaces(frames_faces)
    w = FaceGateWorker(363, [ZONE], eng, t, "test-node", settings, recorder=recorder, max_age_s=0.5)
    w.source = FrameSource.from_frames([FRAME] * len(frames_faces), fps=10.0)
    w.start()
    w.join(timeout=10)
    assert not w.is_alive()
    return w, t, eng


def labels(t):
    return [b["label"] for _, kind, boxes in t.detections if kind == "face" for b in boxes]


def test_one_event_after_k_good_frames():
    _, t, eng = run_worker([[GOOD]] * 5)
    assert len(t.events) == 1
    ev = t.events[0]
    assert (ev["type"], ev["zone_id"], ev["camera_id"], ev["node_id"]) == ("attendance", 9, 363, "test-node")
    p = ev["payload"]
    assert p["direction"] == "entry" and len(p["embedding"]) == 512
    assert p["face_stats"]["frames"] == 3 and p["face_stats"]["width_px"] == 120
    assert ev["clip_path"] is None
    assert eng.embed_calls == 3


def test_no_event_when_no_frame_passes_gates():
    _, t, eng = run_worker([[face(width=40.0)]] * 5)
    assert t.events == [] and eng.embed_calls == 0
    assert set(labels(t)) == {"small"}


def test_detection_threshold_and_quality_score_are_distinct():
    _, t, eng = run_worker([[face(score=0.49)], [face(score=0.55)]])
    assert labels(t) == ["score"]
    assert t.events == [] and eng.embed_calls == 0


def test_face_outside_zone_is_labelled_and_not_embedded():
    _, t, eng = run_worker([[face(cx=100.0)]] * 3)
    assert t.events == [] and eng.embed_calls == 0
    assert set(labels(t)) == {"zone"}


def test_short_pass_emits_when_track_expires():
    _, t, _ = run_worker([[GOOD]] + [[]] * 8)
    assert len(t.events) == 1
    assert t.events[0]["payload"]["face_stats"]["frames"] == 1


def test_short_pass_expires_while_stream_stalls():
    class StalledSource:
        def __init__(self):
            self.first = True
            self.closed = threading.Event()

        def __iter__(self):
            return self

        def __next__(self):
            if self.first:
                self.first = False
                return Frame(time.monotonic(), FRAME)
            self.closed.wait()
            raise StopIteration

        def next_frame(self, timeout):
            if self.first:
                return next(self)
            self.closed.wait(timeout)
            return None

        def close(self):
            self.closed.set()

    t = FakeTransport()
    w = FaceGateWorker(363, [ZONE], FakeFaces([[GOOD]]), t, "test-node",
                       FaceSettings(), max_age_s=0.15)
    w.source = StalledSource()
    w.start()
    try:
        deadline = time.monotonic() + 1.0
        while not t.events and time.monotonic() < deadline:
            time.sleep(0.01)
        assert len(t.events) == 1
        assert t.events[0]["payload"]["face_stats"]["frames"] == 1
    finally:
        w.stop()
        w.join(timeout=2)
    assert not w.is_alive()


def test_overlay_published_before_embedding():
    t = FakeTransport()

    class Recording(FakeFaces):
        seen = []

        def embed(self, aligned):
            Recording.seen.append(len(t.detections))
            return super().embed(aligned)

    run_worker([[GOOD]] * 3, engine=Recording([[GOOD]] * 3), transport=t)
    assert Recording.seen[0] >= 1


def test_swapped_track_outlier_is_dropped():
    _, t, _ = run_worker([[GOOD]] * 3, engine=FakeFaces([[GOOD]] * 3, vectors=[E1, E1, NEG]))
    assert t.events[0]["payload"]["embedding"][0] == pytest.approx(1.0)


def test_face_engine_error_does_not_kill_worker():
    frames = [RuntimeError("onnx"), [GOOD], [GOOD], [GOOD]]
    _, t, _ = run_worker(frames, engine=FakeFaces(frames))
    assert len(t.events) == 1


def test_two_faces_same_frame_two_events():
    left, right = face(cx=700.0), face(cx=1220.0)
    _, t, _ = run_worker([[left, right]] * 4)
    assert len(t.events) == 2
    assert len({ev["payload"]["track_id"] for ev in t.events}) == 2


def test_two_faces_do_not_mix_embeddings():
    left, right = face(cx=700.0), face(cx=1220.0)
    vectors = [v for _ in range(3) for v in (E1, NEG)]
    _, t, _ = run_worker([[left, right]] * 3,
                         engine=FakeFaces([[left, right]] * 3, vectors=vectors))
    assert len(t.events) == 2
    assert {ev["payload"]["embedding"][0] for ev in t.events} == {-1.0, 1.0}


def test_brief_detection_gap_keeps_one_track():
    _, t, _ = run_worker([[GOOD], [], [GOOD], [GOOD]])
    assert len(t.events) == 1
    assert t.events[0]["payload"]["face_stats"]["frames"] == 3


def test_crop_and_snapshot_come_from_best_frame():
    rec = FakeRecorder()
    _, t, _ = run_worker([[GOOD]] * 3, recorder=rec)
    assert [kind for kind, _ in rec.uploads] == ["crop", "snapshot"]
    crop = cv2.imdecode(np.frombuffer(rec.uploads[0][1], np.uint8), cv2.IMREAD_COLOR)
    snap = cv2.imdecode(np.frombuffer(rec.uploads[1][1], np.uint8), cv2.IMREAD_COLOR)
    assert crop.shape[1] == 192
    assert snap.shape[1] == 1280
    ev = t.events[0]
    assert ev["snapshot_path"] == "snapshots/x.jpg"
    assert ev["payload"]["crop_path"] == "crops/x.jpg"
    assert ev["payload"]["face_bbox"][0] == pytest.approx(36.0)


def test_crop_upload_exception_does_not_skip_snapshot():
    class BrokenCrop(FakeRecorder):
        def upload_bytes(self, data, kind, content_type="image/jpeg", **kwargs):
            if kind == "crop":
                raise OSError("crop upload failed")
            return super().upload_bytes(data, kind, content_type, **kwargs)

    _, t, _ = run_worker([[GOOD]] * 3, recorder=BrokenCrop())
    assert t.events[0]["payload"]["crop_path"] is None
    assert t.events[0]["snapshot_path"] == "snapshots/x.jpg"


def test_upload_timeout_does_not_hold_event_or_next_overlay(monkeypatch, tmp_path):
    from vision.recorder import Recorder

    class Cfg:
        api_url = "http://localhost:8000"
        api_key = "test"
        node_id = "test-node"
        data_dir = str(tmp_path)

    rec = Recorder(363, Cfg())
    calls = []

    def slow_urlopen(req, timeout):
        calls.append(timeout)
        time.sleep(timeout)
        raise TimeoutError("stalled API")

    monkeypatch.setattr("vision.recorder.urlopen", slow_urlopen)
    try:
        start = time.monotonic()
        _, t, _ = run_worker([[GOOD]] * 5, recorder=rec)
        assert time.monotonic() - start < 2.0
        assert len(t.events) == 1
        assert t.events[0]["payload"]["crop_path"] is None
        assert t.events[0]["snapshot_path"] is None
        assert len(t.detections) == 5
        assert calls == [0.5, 0.5]  # one bounded attempt per image; no 60s retries
    finally:
        rec.close()


def test_upload_failure_still_publishes_event():
    _, t, _ = run_worker([[GOOD]] * 3, recorder=FakeRecorder(fail=True))
    ev = t.events[0]
    assert ev["payload"]["crop_path"] is None and ev["snapshot_path"] is None
    assert len(ev["payload"]["embedding"]) == 512
