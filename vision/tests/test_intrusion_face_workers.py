"""Kabel IntrusionRegistry ke CameraWorker/FaceGateWorker + publish_face + unggah crop."""
import threading
import time

import numpy as np
import pytest

from vision.face import FaceDet
from vision.face_quality import FaceSettings
from vision.face_worker import FaceGateWorker
from vision.intrusion_face import IntrusionRegistry
from vision.node import CameraWorker
from vision.pipeline.detector import Detection, MockDetector
from vision.pipeline.source import Frame, FrameSource

FRAME = np.zeros((1080, 1920, 3), np.uint8)
SHARP = np.random.default_rng(0).integers(0, 255, (112, 112, 3), dtype=np.uint8)
FRONTAL = np.array([[40, 60], [80, 60], [60, 85], [45, 110], [75, 110]], dtype=np.float32)
E1 = [1.0] + [0.0] * 511
# person track: titik kaki di (0.5, 0.9) → bbox ternormalisasi; kepala memuat pusat wajah default
PERSON_BBOX = (0.40, 0.30, 0.60, 0.90)
ZONE = {"id": 9, "direction": "entry",
        "polygon": [[0.25, 0.25], [0.75, 0.25], [0.75, 0.75], [0.25, 0.75]]}


def face(cx=960.0, cy=540.0, width=120.0, score=0.9):
    kps = (FRONTAL - FRONTAL.mean(axis=0)) * (width / 60.0) + np.array([cx, cy], dtype=np.float32)
    return FaceDet(bbox=(cx - width / 2, cy - width * 0.6, cx + width / 2, cy + width * 1.2),
                   kps=kps, score=score)


class FakeFaces:
    def __init__(self, per_frame, vectors=None):
        self.per_frame = list(per_frame)
        self.vectors = list(vectors or [])
        self.embed_calls = 0

    def detect_faces(self, img):
        return self.per_frame.pop(0) if self.per_frame else []

    def align(self, img, kps):
        return SHARP

    def embed(self, aligned):
        self.embed_calls += 1
        return self.vectors.pop(0) if self.vectors else E1


class FakeTransport:
    def __init__(self, with_publish_face=True):
        self.events, self.detections, self.faces = [], [], []
        if with_publish_face:
            self.publish_face = self.faces.append

    def publish_event(self, ev):
        self.events.append(ev)

    def publish_detections(self, camera_id, boxes, kind="person"):
        self.detections.append((camera_id, kind, boxes))


class CropRecorder:
    def __init__(self, path="crops/2026/10/08/x.jpg", fail=False):
        self.path = path
        self.fail = fail
        self.uploads = []

    def upload_bytes(self, data, kind, content_type="image/jpeg", **kwargs):
        self.uploads.append((kind, data))
        return None if self.fail else self.path


def run_face_worker(registry, frames_faces, transport=None, recorder=None, motion=None):
    frames = len(frames_faces)
    w = FaceGateWorker(363, [ZONE], FakeFaces(frames_faces), transport or FakeTransport(),
                       "test-node", FaceSettings(), recorder=recorder,
                       motion=motion, registry=registry, max_age_s=0.5)
    w.source = FrameSource.from_frames([FRAME] * frames, fps=10.0)
    w.start()
    w.join(timeout=10)
    assert not w.is_alive()
    w.join_ident_threads(5.0)
    return w


def seeded_registry(event_id="ev-1"):
    """Registry berisi entri terikat di kepala person; ts sebanding monotonic frame (TTL 3 dtk)."""
    ts = time.monotonic()
    r = IntrusionRegistry()
    r.bind(5, 1, event_id, ts)
    r.touch(5, 1, PERSON_BBOX, ts)
    return r


def test_face_worker_bypasses_motion_gate_while_registry_active():
    # tanpa registry: motion gate melewatkan frame (perilaku lama)
    plain = FaceGateWorker(363, [ZONE], FakeFaces([[]] * 6), FakeTransport(), "test-node",
                           FaceSettings(), motion={"enabled": True, "force_interval_s": 10},
                           max_age_s=0.5)
    plain.source = FrameSource.from_frames([FRAME] * 6, fps=10)
    plain.start(); plain.join(timeout=10)
    assert plain.motion_skipped == 5
    # dengan registry segar: bypass, frame tetap diproses
    reg = seeded_registry()
    w = FaceGateWorker(363, [ZONE], FakeFaces([[]] * 6), FakeTransport(), "test-node",
                       FaceSettings(), motion={"enabled": True, "force_interval_s": 10},
                       registry=reg, max_age_s=0.5)
    w.source = FrameSource.from_frames([FRAME] * 6, fps=10)
    w.start(); w.join(timeout=10)
    assert w.motion_skipped == 0


def test_face_worker_publishes_one_face_result_after_bind():
    reg = seeded_registry()
    t = FakeTransport()
    # frame ts mulai ~0 (monotonic); registry entri di-touch ulang lewat drain TTL via observe fresh
    w = run_face_worker(reg, [[face()]] * 3, transport=t)
    assert len(t.faces) == 1
    msg = t.faces[0]
    assert msg["event_id"] == "ev-1"
    assert msg["embedding"] is not None
    assert msg["camera_id"] == 363 and msg["node_id"] == "test-node"


def test_face_worker_without_registry_never_needs_publish_face():
    t = FakeTransport(with_publish_face=False)
    w = run_face_worker(None, [[face()]] * 3, transport=t)
    assert len(t.events) == 1  # attendance tetap jalan seperti sebelumnya
    assert t.events[0]["type"] == "attendance"


def test_face_worker_uploads_crop_and_publishes_crop_path():
    reg = seeded_registry()
    t = FakeTransport()
    rec = CropRecorder()
    run_face_worker(reg, [[face()]] * 3, transport=t, recorder=rec)
    assert rec.uploads and rec.uploads[0][0] == "crop"
    assert len(t.faces) == 1
    assert t.faces[0]["crop_path"] == "crops/2026/10/08/x.jpg"
    assert "_crop" not in t.faces[0]


def test_face_worker_publishes_even_when_crop_upload_fails():
    reg = seeded_registry()
    t = FakeTransport()
    run_face_worker(reg, [[face()]] * 3, transport=t, recorder=CropRecorder(fail=True))
    assert len(t.faces) == 1 and t.faces[0]["crop_path"] is None


def test_face_worker_without_recorder_publishes_crop_path_none():
    reg = seeded_registry()
    t = FakeTransport()
    run_face_worker(reg, [[face()]] * 3, transport=t, recorder=None)
    assert len(t.faces) == 1 and t.faces[0]["crop_path"] is None


# --- CameraWorker: touch + bind ---------------------------------------------

def _camera_worker(registry, ident_zones, det_script, transport=None):
    from vision.analyzers import ANALYZERS
    spec = {"id": 5, "polygon": [[0.1, 0.1], [0.9, 0.1], [0.9, 0.95], [0.1, 0.95]],
            "trigger_seconds": 0}
    analyzer = ANALYZERS["intrusion"](spec)
    analyzer.media = {"snapshot": False, "clip": False}
    scripted = [[Detection(bbox=b, conf=0.9) for b in dets] for dets in det_script]
    stop = threading.Event()
    w = CameraWorker(type("C", (), {"camera_id": 7})(), lambda cid: MockDetector(scripted),
                     transport or FakeTransport(), stop, "n1", analyzers=[analyzer],
                     registry=registry, ident_zones=ident_zones)
    w.source = FrameSource.from_frames([np.zeros((4, 4, 3), np.uint8)] * len(det_script), fps=10.0)
    w.start()
    w.join(timeout=10)
    assert not w.is_alive()
    return w


IDENT_ZONE = [{"id": 5, "polygon": [[0.1, 0.1], [0.9, 0.1], [0.9, 0.95], [0.1, 0.95]]}]


def test_camera_worker_touches_ident_zone_tracks_and_binds_on_intrusion_event():
    reg = IntrusionRegistry()
    t = FakeTransport()
    dets = [[(0.4, 0.3, 0.6, 0.9)]] * 3  # titik kaki (0.5, 0.9) di dalam polygon zona 5
    _camera_worker(reg, IDENT_ZONE, dets, transport=t)
    intrusion = [ev for ev in t.events if ev["type"] == "intrusion"]
    assert intrusion, "event intrusion harus terbit (trigger 0)"
    track_id = intrusion[0]["payload"]["track_id"]
    assert [(e.track_id, e.event_id) for e in reg.entries()] == [(track_id, intrusion[0]["event_id"])]


def test_camera_worker_ignores_tracks_outside_ident_zone():
    reg = IntrusionRegistry()
    dets = [[(0.0, 0.0, 0.05, 0.05)]] * 3  # di luar zona ident
    _camera_worker(reg, IDENT_ZONE, dets)
    assert reg.entries() == []


def test_camera_worker_without_ident_zones_touches_nothing():
    reg = IntrusionRegistry()
    dets = [[(0.4, 0.3, 0.6, 0.9)]] * 3
    _camera_worker(reg, [], dets)
    assert reg.entries() == []


def test_camera_worker_untouched_track_miss_not_touched():
    """Track yang di-pertahankan tracker (misses > 0) tidak di-touch ulang; misses == 0 ya."""
    reg = IntrusionRegistry()
    w = CameraWorker(type("C", (), {"camera_id": 7})(), lambda cid: None,
                     FakeTransport(), threading.Event(), "n1",
                     registry=reg, ident_zones=IDENT_ZONE)
    fresh = type("T", (), {"id": 1, "bbox": (0.4, 0.3, 0.6, 0.9), "misses": 0})()
    stale = type("T", (), {"id": 2, "bbox": (0.4, 0.3, 0.6, 0.9), "misses": 1})()
    w._touch_ident([fresh, stale], 100.0, 100, 100)
    assert [e.track_id for e in reg.entries()] == [1]


# --- isolasi: kegagalan identitas tidak boleh mematikan absensi atau deteksi intrusion ---

@pytest.mark.parametrize("method", ["observe", "drain"])
def test_face_worker_keeps_attendance_alive_when_identity_raises(method, caplog):
    t = FakeTransport()
    w = FaceGateWorker(363, [ZONE], FakeFaces([[face()]] * 3), t, "test-node", FaceSettings(),
                       registry=seeded_registry(), max_age_s=0.5)

    def boom(*args, **kwargs):
        raise RuntimeError("identity bug")

    setattr(w.collector, method, boom)
    w.source = FrameSource.from_frames([FRAME] * 3, fps=10.0)
    w.start()
    w.join(timeout=10)
    assert [e["type"] for e in t.events] == ["attendance"]
    assert "face worker died" not in caplog.text


class BrokenRegistry(IntrusionRegistry):
    def __init__(self, method):
        super().__init__()
        setattr(self, method, self._boom)

    @staticmethod
    def _boom(*args, **kwargs):
        raise RuntimeError("registry bug")


@pytest.mark.parametrize("method", ["touch", "bind"])
def test_camera_worker_still_publishes_intrusion_when_registry_raises(method, caplog):
    t = FakeTransport()
    _camera_worker(BrokenRegistry(method), IDENT_ZONE, [[(0.4, 0.3, 0.6, 0.9)]] * 3, transport=t)
    assert any(ev["type"] == "intrusion" for ev in t.events)
    assert "worker died" not in caplog.text


def test_face_worker_without_attendance_zones_sends_identity_but_no_attendance_event():
    reg = seeded_registry()
    t = FakeTransport()
    w = FaceGateWorker(363, [], FakeFaces([[face()]] * 3), t, "test-node", FaceSettings(),
                       registry=reg, max_age_s=0.5)
    w.source = FrameSource.from_frames([FRAME] * 3, fps=10.0)
    w.start()
    w.join(timeout=10)
    w.join_ident_threads(5.0)
    assert t.events == []  # tanpa zona attendance: tidak ada event absensi
    assert len(t.faces) == 1 and t.faces[0]["embedding"] is not None


# --- overlay debugger: label identitas mengikuti kepala orang, bukan status zona -----------

def _face_labels(transport):
    return [b["label"] for _cam, kind, boxes in transport.detections if kind == "face" for b in boxes]


def test_identity_only_worker_overlay_follows_the_person_not_the_zone():
    reg = seeded_registry()
    t = FakeTransport()
    stray = face(cx=200.0, cy=900.0)  # bukan kepala siapa pun
    w = FaceGateWorker(363, [], FakeFaces([[face(), stray]] * 3), t, "test-node", FaceSettings(),
                       registry=reg, max_age_s=0.5)
    w.source = FrameSource.from_frames([FRAME] * 3, fps=10.0)
    w.start()
    w.join(timeout=10)
    labels = _face_labels(t)
    assert len(labels) == 3 and "zone" not in labels  # satu wajah terasosiasi per frame, tanpa "zone"
    assert all(lb == "0.90" for lb in labels)


def test_attendance_worker_with_identity_keeps_zone_label_for_other_faces():
    reg = seeded_registry()
    t = FakeTransport()
    stray = face(cx=200.0, cy=900.0)  # di luar zona attendance dan bukan kepala orang
    w = FaceGateWorker(363, [ZONE], FakeFaces([[face(), stray]] * 3), t, "test-node", FaceSettings(),
                       registry=reg, max_age_s=0.5)
    w.source = FrameSource.from_frames([FRAME] * 3, fps=10.0)
    w.start()
    w.join(timeout=10)
    labels = _face_labels(t)
    assert "zone" in labels and "0.90" in labels
