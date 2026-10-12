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


def test_motion_skipped_frames_clear_expired_overlay():
    t = FakeTransport()
    w = FaceGateWorker(363, [ZONE], FakeFaces([[GOOD]]), t, "test-node",
                       FaceSettings(), motion={"enabled": True, "force_interval_s": 10},
                       max_age_s=0.25)
    w.source = FrameSource.from_frames([FRAME] * 6, fps=10)
    w.start()
    w.join(timeout=10)
    assert not w.is_alive()
    overlays = [boxes for _, kind, boxes in t.detections if kind == "face"]
    assert len(overlays) == 2 and len(overlays[0]) == 1 and overlays[1] == []


def test_overlay_keeps_cadence_while_media_upload_stalls():
    class BlockedRecorder(FakeRecorder):
        def __init__(self):
            super().__init__()
            self.release = threading.Event()

        def upload_bytes(self, data, kind, content_type="image/jpeg", **kwargs):
            self.release.wait(2)
            return super().upload_bytes(data, kind, content_type, **kwargs)

    class TimedTransport(FakeTransport):
        def __init__(self):
            super().__init__()
            self.overlay_times = []

        def publish_detections(self, camera_id, boxes, kind="person"):
            if kind == "face" and boxes:
                self.overlay_times.append(time.monotonic())
            super().publish_detections(camera_id, boxes, kind)

    rec, t = BlockedRecorder(), TimedTransport()
    w = FaceGateWorker(363, [ZONE], FakeFaces([[GOOD]] * 5), t, "test-node",
                       FaceSettings(), recorder=rec, max_age_s=0.5)
    w.source = FrameSource.from_frames([FRAME] * 5, fps=10)
    w.start()
    try:
        deadline = time.monotonic() + 0.6
        while len(t.overlay_times) < 5 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert len(t.overlay_times) == 5
        assert t.overlay_times[3] - t.overlay_times[2] < 0.2
    finally:
        rec.release.set()
        w.join(timeout=10)
    assert not w.is_alive()
    assert len(t.events) == 1


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


def test_blocked_uploader_cannot_hold_event_or_overlay():
    class BlockingRecorder(FakeRecorder):
        def upload_bytes(self, data, kind, content_type="image/jpeg", **kwargs):
            time.sleep(2)  # ignores socket timeout; event must still be sent
            return super().upload_bytes(data, kind, content_type, **kwargs)

    start = time.monotonic()
    _, t, _ = run_worker([[GOOD]] * 5, recorder=BlockingRecorder())
    assert time.monotonic() - start < 1.5
    assert len(t.events) == 1 and len(t.detections) == 5
    assert t.events[0]["payload"]["crop_path"] is None
    assert t.events[0]["snapshot_path"] is None


def test_three_faces_publish_before_serial_uploads_can_delay_them():
    class SlowSuccess(FakeRecorder):
        def upload_bytes(self, data, kind, content_type="image/jpeg", **kwargs):
            time.sleep(0.4)
            return super().upload_bytes(data, kind, content_type, **kwargs)

    class TimedTransport(FakeTransport):
        def __init__(self):
            super().__init__()
            self.published = []

        def publish_event(self, ev):
            self.published.append(time.monotonic())
            super().publish_event(ev)

    faces = [face(cx=x) for x in (700, 960, 1220)]
    rec, t = SlowSuccess(), TimedTransport()
    start = time.monotonic()
    run_worker([faces] * 3, transport=t, recorder=rec)
    assert len(t.events) == 3 and len({e["payload"]["track_id"] for e in t.events}) == 3
    assert max(t.published) - start < 1.5  # third must not wait for 3 x 0.8 s media
    assert [kind for kind, _ in rec.uploads] == ["crop", "snapshot"]
    assert [e["payload"]["crop_path"] is None for e in t.events] == [True, True, False]


def test_worker_event_history_is_bounded_without_dropping_transport_events():
    count = 34
    t = FakeTransport()
    w = FaceGateWorker(363, [ZONE], FakeFaces([[GOOD]] * count), t, "test-node",
                       FaceSettings(min_frames=1), max_age_s=0.5)
    w.source = FrameSource.from_frames([FRAME] * count, fps=1)
    w.start()
    w.join(timeout=10)
    assert not w.is_alive()
    assert len(t.events) == count
    assert 0 < len(w.events) <= 32
    assert w.events[-1] is t.events[-1]


def test_stalled_media_allows_second_face_without_spawning_another_upload():
    class BlockedRecorder(FakeRecorder):
        def __init__(self):
            super().__init__()
            self.started = threading.Event()
            self.release = threading.Event()
            self.calls = 0

        def upload_bytes(self, data, kind, content_type="image/jpeg", **kwargs):
            self.calls += 1
            self.started.set()
            self.release.wait(3)
            return super().upload_bytes(data, kind, content_type, **kwargs)

    rec = BlockedRecorder()
    left, right = face(cx=700), face(cx=1220)
    try:
        start = time.monotonic()
        _, t, _ = run_worker([[left, right]] * 3, recorder=rec)
        assert time.monotonic() - start < 1.5
        assert rec.started.is_set() and rec.calls == 1
        assert len(t.events) == 2
        assert all(e["payload"]["crop_path"] is None for e in t.events)
    finally:
        rec.release.set()


def test_upload_failure_still_publishes_event():
    _, t, _ = run_worker([[GOOD]] * 3, recorder=FakeRecorder(fail=True))
    ev = t.events[0]
    assert ev["payload"]["crop_path"] is None and ev["snapshot_path"] is None
    assert len(ev["payload"]["embedding"]) == 512


def test_stationary_face_keeps_processing_after_motion_stops():
    t, eng = FakeTransport(), FakeFaces([[GOOD]] * 6)
    w = FaceGateWorker(363, [ZONE], eng, t, "test-node", FaceSettings(),
                       motion={"enabled": True, "force_interval_s": 10}, max_age_s=0.5)
    w.source = FrameSource.from_frames([FRAME] * 6, fps=10)
    w.start()
    w.join(timeout=10)
    assert not w.is_alive()
    assert len(t.events) == 1
    assert t.events[0]["payload"]["face_stats"]["frames"] == 3
    assert eng.embed_calls == 3


def test_motion_gate_still_skips_when_no_face_visible():
    t = FakeTransport()
    w = FaceGateWorker(363, [ZONE], FakeFaces([[]] * 6), t, "test-node", FaceSettings(),
                       motion={"enabled": True, "force_interval_s": 10}, max_age_s=0.5)
    w.source = FrameSource.from_frames([FRAME] * 6, fps=10)
    w.start()
    w.join(timeout=10)
    assert not w.is_alive()
    assert w.motion_skipped == 5


def test_motion_gate_resumes_skipping_after_face_disappears():
    t = FakeTransport()
    w = FaceGateWorker(363, [ZONE], FakeFaces([[GOOD], []]), t, "test-node", FaceSettings(),
                       motion={"enabled": True, "force_interval_s": 10}, max_age_s=0.25)
    w.source = FrameSource.from_frames([FRAME] * 6, fps=10)
    w.start()
    w.join(timeout=10)
    assert not w.is_alive()
    assert w.motion_skipped == 4
    assert t.detections[-1][2] == []


def test_funnel_counts_rejects_per_gate_code():
    w, t, _ = run_worker([[face(width=40.0)]] * 5)
    funnel = w.take_funnel()
    assert funnel["faces"] == len(labels(t)) >= 3
    assert funnel["rejects"] == {"zone": 0, "small": funnel["faces"], "score": 0, "yaw": 0, "blur": 0}
    assert funnel["tracks_emitted"] == 0
    assert w.take_funnel() == {
        "faces": 0, "rejects": {"zone": 0, "small": 0, "score": 0, "yaw": 0, "blur": 0},
        "tracks_emitted": 0, "tracks_silent": 0, "ttfg_median_s": None,
    }


@pytest.mark.parametrize("code", ["zone", "score", "yaw", "blur"])
def test_funnel_other_reject_codes(code):
    det = face(cx=100.0) if code == "zone" else face(score=0.55) if code == "score" else face()
    if code == "yaw":
        det.kps[2, 0] += 100
    eng = FakeFaces([[det]] * 5, aligned=np.zeros_like(SHARP) if code == "blur" else SHARP)
    w, t, _ = run_worker([[det]] * 5, engine=eng)
    f = w.take_funnel()
    assert f["faces"] == len(labels(t)) >= 3
    assert f["rejects"][code] == f["faces"]
    assert sum(f["rejects"].values()) == f["faces"]


def test_funnel_silent_track_counts_only_tracks_that_entered_zone():
    inside, _, _ = run_worker([[face(width=40.0)]] * 3 + [[]] * 8)
    assert inside.take_funnel()["tracks_silent"] == 1
    assert inside._in_zone == {}
    outside, _, _ = run_worker([[face(cx=100.0)]] * 3 + [[]] * 8)
    assert outside.take_funnel()["tracks_silent"] == 0
    assert outside._in_zone == {}


def test_funnel_emitted_and_time_to_first_good_frame():
    w, _, _ = run_worker([[face(score=0.55)]] * 2 + [[GOOD]] * 3)
    f = w.take_funnel()
    assert f["tracks_emitted"] == 1
    assert f["tracks_silent"] == 0
    assert f["ttfg_median_s"] == pytest.approx(0.2, abs=0.01)


# --- jalur absensi unified: gerbang identitas, K terbaik, jendela pendek ---

SMOOTH = np.full((112, 112, 3), 128, np.uint8)


def unified(**over):
    return FaceSettings(attendance_mode="unified", **over)


def test_unified_waits_for_the_window_even_after_k_candidates():
    """K kandidat terkumpul tidak memicu kirim; event baru terbit setelah jendela (10 fps → 1,0 dtk)."""
    t = FakeTransport()
    eng = FakeFaces([[GOOD]] * 15)
    w = FaceGateWorker(363, [ZONE], eng, t, "test-node", unified(attendance_window_s=1.0), max_age_s=0.5)
    w.source = FrameSource.from_frames([FRAME] * 15, fps=10.0)
    w.start()
    w.join(timeout=10)
    assert not w.is_alive()
    assert len(t.events) == 1
    p = t.events[0]["payload"]
    assert p["policy"] == "unified"
    assert p["face_stats"]["frames"] <= 5
    assert p["face_stats"]["collect_s"] >= 1.0  # bukan pada K kandidat (0,4 dtk) dan tidak lebih awal
    assert p["face_stats"]["zone_s"] >= 1.0


def test_unified_emits_exactly_once_when_window_elapses_then_track_is_lost():
    t = FakeTransport()
    w = FaceGateWorker(363, [ZONE], FakeFaces([[GOOD]] * 15 + [[]] * 8), t, "test-node",
                       unified(attendance_window_s=1.0), max_age_s=0.5)
    w.source = FrameSource.from_frames([FRAME] * 23, fps=10.0)
    w.start()
    w.join(timeout=10)
    assert not w.is_alive()
    assert len(t.events) == 1
    assert t.events[0]["payload"]["face_stats"]["frames"] <= 5


def test_unified_track_lost_before_window_emits_one_event():
    t = FakeTransport()
    w = FaceGateWorker(363, [ZONE], FakeFaces([[GOOD]] * 3 + [[]] * 8), t, "test-node",
                       unified(attendance_window_s=3.0), max_age_s=0.5)
    w.source = FrameSource.from_frames([FRAME] * 11, fps=10.0)
    w.start()
    w.join(timeout=10)
    assert not w.is_alive()
    assert len(t.events) == 1
    p = t.events[0]["payload"]
    assert p["policy"] == "unified"
    assert p["face_stats"]["frames"] == 3
    assert p["face_stats"]["collect_s"] < 3.0


def test_unified_accepts_small_blurry_face_that_legacy_rejects():
    """Pembeda: wajah 70 px dan buram (blur < 120) ditolak legacy, diterima unified (tanpa gerbang blur)."""
    frames = [[face(width=70.0)]] * 5 + [[]] * 8
    _, legacy_t, _ = run_worker(frames, engine=FakeFaces(frames, aligned=SMOOTH))
    assert legacy_t.events == []

    _, t, _ = run_worker(frames, engine=FakeFaces(frames, aligned=SMOOTH), settings=unified())
    assert len(t.events) == 1
    assert t.events[0]["payload"]["policy"] == "unified"


def test_unified_rejects_small_and_pitched_faces_with_gate_labels():
    _, t, eng = run_worker([[face(width=50.0)]] * 5 + [[]] * 8, settings=unified())
    assert t.events == [] and eng.embed_calls == 0
    assert set(labels(t)) == {"small"}

    pitched = face()
    pitched.kps[2, 1] += 40  # hidung turun → pitch_dev 0,8 > 0,30
    w, t2, eng2 = run_worker([[pitched]] * 5 + [[]] * 8, settings=unified())
    assert t2.events == [] and eng2.embed_calls == 0
    assert set(labels(t2)) == {"pitch"}
    assert w.take_funnel()["rejects"]["pitch"] > 0

    legacy, _, _ = run_worker([[face(width=40.0)]] * 5)
    assert set(legacy.take_funnel()["rejects"]) == {"zone", "small", "score", "yaw", "blur"}


def test_unified_ranking_embeds_only_frames_that_beat_the_worst_kept():
    class Alternating(FakeFaces):
        """align() bergantian halus/tajam sesuai pola; embed() mengembalikan vektor sesuai gambar."""

        def __init__(self, per_frame, kinds):
            super().__init__(per_frame)
            self.kinds = list(kinds)
            self._i = -1

        def align(self, img, kps):
            self._i += 1
            return SHARP if self.kinds[self._i % len(self.kinds)] == "sharp" else SMOOTH

    kinds = ["smooth"] * 5 + ["sharp"]
    frames = [[GOOD]] * 6 + [[]] * 8
    eng = Alternating(frames, kinds)
    eng.vectors = [E1, E1, [0.8, 0.6] + [0.0] * 510]
    t = FakeTransport()
    w = FaceGateWorker(363, [ZONE], eng, t, "test-node",
                       FaceSettings.from_config({"attendance_mode": "unified", "ident": {"best_k": 2}}),
                       max_age_s=0.5)
    w.source = FrameSource.from_frames([FRAME] * 14, fps=10.0)
    w.start()
    w.join(timeout=10)
    assert not w.is_alive()
    assert eng.embed_calls == 3  # dua frame halus mengisi K, lalu hanya frame tajam yang mengalahkan
    ev = t.events[0]
    assert ev["payload"]["face_stats"]["frames"] == 2
    # frame tajam ikut dalam agregat (vektor halus saja akan menghasilkan [1, 0, ...])
    assert ev["payload"]["embedding"][1] == pytest.approx(0.316, abs=0.01)


# --- unified: orang pergi tidak menunggu tracker (max_age_s 3 dtk) dan jendela mulai dari embed pertama ---

def run_unified(per_frame, max_age_s=3.0, engine=None, **settings):
    """Worker unified dengan tracker lambat seperti produksi (max_age_s 3,0), bukan 0,5 milik `run_worker`."""
    t = FakeTransport()
    w = FaceGateWorker(363, [ZONE], engine or FakeFaces(per_frame), t, "test-node", unified(**settings),
                       max_age_s=max_age_s)
    w.source = FrameSource.from_frames([FRAME] * len(per_frame), fps=10.0)
    w.start()
    w.join(timeout=10)
    assert not w.is_alive()
    return w, t


def test_unified_quick_pass_is_sent_when_the_face_is_gone_not_after_the_tracker_gives_up():
    # wajah terlihat 0,4 dtk lalu hilang; tracker baru melepas track setelah 3 dtk (belum tercapai di 1,4 dtk)
    _, t = run_unified([[GOOD]] * 4 + [[]] * 10)
    assert len(t.events) == 1
    stats = t.events[0]["payload"]["face_stats"]
    assert stats["frames"] == 4
    assert 0.5 <= stats["zone_s"] < 2.0  # sudah termasuk jeda "wajah hilang", bukan hanya durasi terlihat


def test_unified_short_gap_in_candidates_does_not_send_early():
    # 0,3 dtk wajah tak lolos gerbang (terlalu kecil) di tengah: bukan "pergi"; jendela 1,0 dtk tetap berlaku
    _, t = run_unified([[GOOD]] * 3 + [[face(width=40.0)]] * 3 + [[GOOD]] * 12, attendance_window_s=1.0)
    assert len(t.events) == 1
    assert t.events[0]["payload"]["face_stats"]["collect_s"] >= 1.0


def test_unified_failed_embeds_do_not_start_the_window_or_kill_the_track():
    # 12 embed pertama gagal (None): jendela 1,0 dtk tidak boleh habis dengan keranjang kosong dan menutup track
    _, t = run_unified([[GOOD]] * 20 + [[]] * 8, engine=FakeFaces([[GOOD]] * 20 + [[]] * 8, vectors=[None] * 12),
                        attendance_window_s=1.0)
    assert len(t.events) == 1
    assert t.events[0]["payload"]["face_stats"]["frames"] >= 1
    assert len(t.events[0]["payload"]["embedding"]) == 512
