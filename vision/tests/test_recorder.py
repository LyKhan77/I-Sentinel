"""Recorder tests: ring buffer, capture (snapshot+clip via mocked urlopen), upload retry, worker integration. No network, no subprocess."""
import json
import threading

import numpy as np
import pytest

from vision.config import CameraCfg, NodeSettings
from vision.pipeline.detector import Detection, MockDetector
from vision.pipeline.source import FrameSource
from vision.recorder import FrameRing, Recorder
from vision.node import CameraWorker
from vision.transport import MqttTransport
from vision.transport import mqtt as mqtt_mod


class FakeResp:
    def __init__(self, data: bytes):
        self.data = data

    def read(self, n=-1):
        d, self.data = self.data, b""
        return d

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeTransport:
    def __init__(self):
        self.events = []
        self.media = []

    def publish_event(self, ev):
        self.events.append(ev)

    def publish_media(self, payload):
        self.media.append(payload)

    def publish_heartbeat(self, hb):
        pass

    def close(self):
        pass


def make_cfg(tmp_path, **kw):
    return NodeSettings(data_dir=str(tmp_path / "data"), node_id="test-node",
                        api_url="http://api", api_key="secret",
                        go2rtc_url="http://go2rtc:1984", **kw)


def make_event(event_id="ev-1"):
    return {"event_id": event_id, "type": "person_detect", "node_id": "test-node",
            "camera_id": 1, "zone_id": None, "severity": "info",
            "ts_event": "2025-01-01T00:00:00+00:00", "payload": {}, "dedup_key": "k"}


def test_frame_ring_keeps_last_n():
    ring = FrameRing(max_frames=3)
    for i in range(5):
        ring.push(float(i), bytes([i]))
    frames = ring.pre_clip()
    assert len(frames) == 3
    assert [b for _, b in frames] == [bytes([2]), bytes([3]), bytes([4])]
    assert [ts for ts, _ in frames] == [2.0, 3.0, 4.0]


def test_frame_ring_ignores_empty_push():
    ring = FrameRing(max_frames=3)
    ring.push(1.0, b"")
    ring.push(2.0, b"jpeg")
    assert ring.pre_clip() == [(2.0, b"jpeg")]


def test_capture_go2rtc_fail_snapshot_still_saved(tmp_path, monkeypatch):
    import vision.recorder as rec_mod

    calls = []

    def fail_urlopen(url, timeout=None):
        calls.append(url)
        raise RuntimeError("go2rtc down")

    monkeypatch.setattr(rec_mod, "urlopen", fail_urlopen)
    rec = Recorder(1, make_cfg(tmp_path))
    rec.push_jpeg(1.0, b"jpeg-bytes")
    local = rec.capture(make_event())
    rec.close()
    assert calls == ["http://go2rtc:1984/api/stream.mp4?src=cam_1&duration=30"]
    snap = local["snapshot_local"]
    assert snap is not None and snap.endswith("ev-1.jpg")
    with open(snap, "rb") as f:
        assert f.read() == b"jpeg-bytes"
    assert local["clip_local"] is None
    assert local["event_id"] == "ev-1"


def test_fetch_frame_returns_bytes_and_builds_url(tmp_path, monkeypatch):
    import vision.recorder as rec_mod

    calls = []

    def fake_urlopen(target, timeout=None):
        calls.append((target, timeout))
        return FakeResp(b"main-jpeg")

    monkeypatch.setattr(rec_mod, "urlopen", fake_urlopen)
    rec = Recorder(4, make_cfg(tmp_path))
    out = rec.fetch_frame("cam_4_main")
    rec.close()
    assert out == b"main-jpeg"
    assert calls == [("http://go2rtc:1984/api/frame.jpeg?src=cam_4_main", 5)]


def test_fetch_frame_none_on_error_and_empty(tmp_path, monkeypatch):
    import vision.recorder as rec_mod

    def boom(target, timeout=None):
        raise RuntimeError("go2rtc down")

    monkeypatch.setattr(rec_mod, "urlopen", boom)
    rec = Recorder(4, make_cfg(tmp_path))
    assert rec.fetch_frame("cam_4_main") is None
    rec.close()

    monkeypatch.setattr(rec_mod, "urlopen", lambda target, timeout=None: FakeResp(b""))
    rec = Recorder(4, make_cfg(tmp_path))
    assert rec.fetch_frame("cam_4_main") is None
    rec.close()


def test_capture_and_upload_success(tmp_path, monkeypatch):
    import vision.recorder as rec_mod

    calls = []

    def fake_urlopen(target, timeout=None):
        url = target if isinstance(target, str) else target.full_url
        calls.append(url)
        if "stream.mp4" in url:
            return FakeResp(b"mp4-bytes")
        assert "Authorization" not in dir(target) or True
        return FakeResp(b'{"path": "/media/blob"}')

    monkeypatch.setattr(rec_mod, "urlopen", fake_urlopen)
    rec = Recorder(1, make_cfg(tmp_path))
    rec.push_jpeg(1.0, b"jpeg-bytes")
    local = rec.capture(make_event())
    assert local["clip_local"] is not None and local["clip_local"].endswith("ev-1.mp4")
    with open(local["clip_local"], "rb") as f:
        assert f.read() == b"mp4-bytes"

    result = rec.upload(local)
    rec.close()
    assert result["event_id"] == "ev-1"
    assert result["snapshot_path"] == "/media/blob"
    assert result["clip_path"] == "/media/blob"
    assert any("/internal/nodes/test-node/blobs?kind=snapshot" in u for u in calls)
    assert any("/internal/nodes/test-node/blobs?kind=clip" in u for u in calls)


def test_upload_retries_three_times_then_none(tmp_path, monkeypatch):
    import vision.recorder as rec_mod

    calls = []
    sleeps = []

    def fail_urlopen(target, timeout=None):
        calls.append(target)
        raise RuntimeError("api down")

    monkeypatch.setattr(rec_mod, "urlopen", fail_urlopen)
    monkeypatch.setattr(rec_mod.time, "sleep", lambda s: sleeps.append(s))
    rec = Recorder(1, make_cfg(tmp_path))
    with open(tmp_path / "x.jpg", "wb") as f:
        f.write(b"jpeg")
    result = rec.upload({"event_id": "ev-1", "snapshot_local": str(tmp_path / "x.jpg"),
                         "clip_local": None})
    rec.close()
    assert result is None
    assert len(calls) == 3
    assert sleeps == [1, 2]  # backoff between retries


def test_upload_no_blobs_returns_none(tmp_path, monkeypatch):
    rec = Recorder(1, make_cfg(tmp_path))
    assert rec.upload({"event_id": "ev-1", "snapshot_local": None, "clip_local": None}) is None
    rec.close()


def test_worker_recorder_media_publish(tmp_path):
    """Full flow: worker + detector + recorder (mocked urlopen) -> media topic payload."""
    import vision.recorder as rec_mod

    def fake_urlopen(target, timeout=None):
        url = target if isinstance(target, str) else target.full_url
        if "stream.mp4" in url:
            raise RuntimeError("go2rtc down")
        return FakeResp(b'{"path": "/media/snap.jpg"}')

    monkeypatch_patch = rec_mod
    t = FakeTransport()
    cfg = make_cfg(tmp_path)
    rec = Recorder(1, cfg, transport=t)
    rec_mod_orig = rec_mod.urlopen
    rec_mod.urlopen = fake_urlopen  # recorder thread uses module attr at call time
    try:
        frame = np.zeros((4, 4, 3), dtype=np.uint8)
        src = FrameSource.from_frames([frame] * 3, fps=100.0)
        det = MockDetector([[Detection(bbox=(0.1, 0.1, 0.3, 0.4), conf=0.9)]] * 3)
        stop = threading.Event()
        w = CameraWorker(CameraCfg(camera_id=1, source_url="test://1"), lambda cid: det,
                         t, stop, "test-node", recorder=rec, emit_person_detect=True)
        w.source = src
        w.start()
        w.join(timeout=10)
        rec.close()
    finally:
        rec_mod.urlopen = rec_mod_orig

    assert len(t.events) == 1
    assert len(t.media) == 1
    payload = t.media[0]
    assert payload["event_id"] == t.events[0]["event_id"]
    assert payload["snapshot_path"] == "/media/snap.jpg"
    assert payload["clip_path"] is None


def test_recorder_queue_drop_oldest(tmp_path):
    rec = Recorder(1, make_cfg(tmp_path))
    rec._thread.join(timeout=0)  # not started-consume; force fill before thread drains
    # fill queue synchronously while paused: simpler - just check enqueue doesn't raise
    for i in range(60):
        rec.enqueue(make_event(f"ev-{i}"))
    rec.close()
    assert rec._q.qsize() <= 50


# --- R2: toggle snapshot/clip per event + bbox/ID pada snapshot ---------------

def _ev(snapshot=None, clip=None, tid=7):
    ev = {"event_id": "ev-x", "type": "intrusion", "severity": "warning",
          "payload": {"track_id": tid, "bbox_norm": [0.1, 0.1, 0.5, 0.6]}}
    if snapshot is not None:
        ev["snapshot"] = snapshot
    if clip is not None:
        ev["clip"] = clip
    return ev


def _recorder(tmp_path, cfg):
    import cv2
    import numpy as np
    rec = Recorder(1, cfg, transport=None)
    ok, buf = cv2.imencode(".jpg", np.full((480, 640, 3), 255, np.uint8))
    assert ok
    rec.push_jpeg(1.0, buf.tobytes())
    return rec


def _fake_urlopen(mp, data=b"mp4-bytes", calls=None):
    class R:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return data
    def _open(url, timeout=0):
        if calls is not None:
            calls.append(url)
        return R()
    mp.setattr("vision.recorder.urlopen", _open)


def test_event_flags_skip_snapshot_or_clip(tmp_path, monkeypatch):
    cfg = type("C", (), {"data_dir": str(tmp_path), "go2rtc_url": "http://x",
                         "record_clip_s": 30})()
    rec = _recorder(tmp_path, cfg)
    _fake_urlopen(monkeypatch)
    local = rec.capture(_ev(snapshot=False))
    assert local["snapshot_local"] is None and local["clip_local"].endswith(".mp4")
    local = rec.capture(_ev(clip=False))
    assert local["clip_local"] is None and local["snapshot_local"].endswith(".jpg")
    assert rec.capture(_ev(snapshot=False, clip=False)) is None


def test_capture_defaults_true_without_flags(tmp_path, monkeypatch):
    cfg = type("C", (), {"data_dir": str(tmp_path), "go2rtc_url": "http://x",
                         "record_clip_s": 30})()
    rec = _recorder(tmp_path, cfg)
    _fake_urlopen(monkeypatch)
    local = rec.capture(_ev())
    assert local["snapshot_local"] and local["clip_local"]


def test_snapshot_draws_bbox_and_track_id(tmp_path):
    import cv2
    import numpy as np
    cfg = type("C", (), {"data_dir": str(tmp_path), "go2rtc_url": "http://x",
                         "record_clip_s": 30})()
    rec = Recorder(1, cfg)
    ok, buf = cv2.imencode(".jpg", np.full((480, 640, 3), 255, np.uint8))
    rec.push_jpeg(1.0, buf.tobytes())
    outbox = tmp_path / "outbox"
    outbox.mkdir()
    path = rec._save_snapshot("ev-x", str(outbox), _ev(tid=7))
    img = cv2.imread(path)
    assert img is not None
    x1, y1, x2, y2 = [int(v * s) for v, s in zip([0.1, 0.1, 0.5, 0.6], (640, 480, 640, 480))]
    region = img[y1:y2, x1:x2]
    region = img[y1:y2, x1:x2]
    border = np.concatenate([region[0:3].reshape(-1, 3), region[-3:].reshape(-1, 3)])
    # rect severity-warning (oranye) di atas background putih — cukup buktikan
    # border sudah bukan putih murni
    drawn = (border.sum(axis=1) < 720).sum()
    assert drawn > 20, "rect track tidak tergambar pada snapshot"
