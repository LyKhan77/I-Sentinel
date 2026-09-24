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
        self.detections = []

    def publish_event(self, ev):
        self.events.append(ev)

    def publish_detections(self, camera_id, boxes, kind="person"):
        self.detections.append((camera_id, kind, boxes))

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
    result = rec._upload_one(str(tmp_path / "x.jpg"), "snapshot", "image/jpeg")
    rec.close()
    assert result is None
    assert len(calls) == 3
    assert sleeps == [1, 2]  # backoff between retries


def test_worker_recorder_media_publish(tmp_path):
    """Full flow: worker + detector + recorder (mocked urlopen) -> snapshot media payload."""
    import vision.recorder as rec_mod

    def fake_urlopen(target, timeout=None):
        url = target if isinstance(target, str) else target.full_url
        if "stream.mp4" in url:
            raise RuntimeError("go2rtc down")
        return FakeResp(b'{"path": "/media/snap.jpg"}')

    t = FakeTransport()
    rec = Recorder(1, make_cfg(tmp_path), transport=t)
    orig = rec_mod.urlopen
    rec_mod.urlopen = fake_urlopen  # recorder thread uses module attr at call time
    try:
        frame = np.zeros((4, 4, 3), dtype=np.uint8)
        src = FrameSource.from_frames([frame] * 3, fps=100.0)
        det = MockDetector([[Detection(bbox=(0.1, 0.1, 0.3, 0.4), conf=0.9)]] * 3)
        w = CameraWorker(CameraCfg(camera_id=1, source_url="test://1"), lambda cid: det,
                         t, threading.Event(), "test-node", recorder=rec, emit_person_detect=True)
        w.source = src
        w.start()
        w.join(timeout=10)
        _wait(lambda: len(t.media) >= 1)
        rec.close()
    finally:
        rec_mod.urlopen = orig

    assert len(t.events) == 1
    assert t.media == [{"event_id": t.events[0]["event_id"], "snapshot_path": "/media/snap.jpg"}]


# --- R2: toggle snapshot/clip per event + bbox/ID pada snapshot ---------------

def _ev(snapshot=None, clip=None, tid=7):
    ev = {"event_id": "ev-x", "type": "intrusion", "severity": "warning",
          "payload": {"track_id": tid, "bbox_norm": [0.1, 0.1, 0.5, 0.6]}}
    if snapshot is not None:
        ev["snapshot"] = snapshot
    if clip is not None:
        ev["clip"] = clip
    return ev


def test_snapshot_draws_bbox_and_track_id(tmp_path):
    import cv2
    import numpy as np
    cfg = make_cfg(tmp_path)
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
    border = np.concatenate([region[0:3].reshape(-1, 3), region[-3:].reshape(-1, 3)])
    # rect severity-warning (oranye) di atas background putih — cukup buktikan
    # border sudah bukan putih murni
    drawn = (border.sum(axis=1) < 720).sum()
    assert drawn > 20, "rect track tidak tergambar pada snapshot"


# --- clip insiden per kamera (pre-buffer) -------------------------------------

import os
import time as _time


def _wait(cond, timeout=5.0):
    end = _time.monotonic() + timeout
    while not cond():
        assert _time.monotonic() < end, "timeout"
        _time.sleep(0.01)


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


class FakeRing:
    def __init__(self, healthy=True, cut_ok=True):
        self._healthy = healthy
        self.cut_ok = cut_ok
        self.cuts = []
        self.checks = 0
        self.prunes = []
        self.stopped = self.closed = False

    def healthy(self):
        return self._healthy

    def cut(self, t0, t1, out_path, *, must_cover, include_open=False):
        self.cuts.append((t0, t1, must_cover, include_open))
        if not self.cut_ok:
            return None
        with open(out_path, "wb") as f:
            f.write(b"mp4")
        return out_path

    def check(self):
        self.checks += 1

    def prune(self, keep_from):
        self.prunes.append(keep_from)

    def stop(self):
        self.stopped = True

    def close(self):
        self.closed = True


def _clip_recorder(tmp_path, ring=None, clock=None, **cfg_kw):
    t = FakeTransport()
    rec = Recorder(1, make_cfg(tmp_path, **cfg_kw), t, clip_ring=ring or FakeRing(),
                   clock=clock or Clock(), autostart=False)
    uploads = []

    def upload(path, kind, content_type, **kw):
        uploads.append((kind, kw))
        return f"{kind}s/x"

    rec._upload_one = upload
    return rec, t, uploads


def _sec_ev(eid, tid, snapshot=False, clip=None):
    ev = {"event_id": eid, "type": "intrusion", "severity": "warning",
          "payload": {"track_id": tid, "bbox_norm": [0.1, 0.1, 0.5, 0.6]}, "snapshot": snapshot}
    if clip is not None:
        ev["clip"] = clip
    return ev


def _run_jobs(rec):
    while not rec._q.empty():
        kind, ev = rec._q.get_nowait()
        rec._run_job(kind, ev)


def test_two_events_one_incident_one_clip(tmp_path):
    clock = Clock(1000.0)
    ring = FakeRing()
    rec, t, uploads = _clip_recorder(tmp_path, ring, clock)
    rec.enqueue(_sec_ev("a", 1))
    clock.t = 1005.0
    rec.enqueue(_sec_ev("b", 2))
    clock.t = 1022.9                      # end 1020 + settle 3 s not reached
    rec.tick()
    assert ring.cuts == []
    clock.t = 1023.0
    rec.tick()
    assert ring.cuts == [(990.0, 1020.0, 1000.0, False)]
    assert uploads == [("clip", {})]
    assert t.media == [{"event_id": "a", "clip_path": "clips/x"},
                       {"event_id": "b", "clip_path": "clips/x"}]
    assert os.listdir(tmp_path / "data" / "outbox") == []   # local clip removed after upload


def test_touch_extends_incident(tmp_path):
    clock = Clock(1000.0)
    ring = FakeRing()
    rec, t, _ = _clip_recorder(tmp_path, ring, clock)
    rec.enqueue(_sec_ev("a", 7))
    clock.t = 1010.0
    rec.touch([7])
    clock.t = 1020.0
    rec.touch([99])                       # a passer-by track does not extend
    clock.t = 1027.9
    rec.tick()
    assert ring.cuts == []
    clock.t = 1028.0
    rec.tick()
    assert ring.cuts[0][1] == 1025.0


def test_incident_capped_at_max(tmp_path):
    clock = Clock(1000.0)
    ring = FakeRing()
    rec, _, _ = _clip_recorder(tmp_path, ring, clock, clip_max_s=30.0)
    rec.enqueue(_sec_ev("a", 1))
    clock.t = 1019.0
    rec.touch([1])
    clock.t = 1023.0
    rec.tick()
    assert ring.cuts == [(990.0, 1020.0, 1000.0, False)]


def test_event_after_close_opens_new_incident(tmp_path):
    clock = Clock(1000.0)
    ring = FakeRing()
    rec, t, _ = _clip_recorder(tmp_path, ring, clock)
    rec.enqueue(_sec_ev("a", 1))
    clock.t = 1023.0
    rec.tick()
    clock.t = 1100.0
    rec.enqueue(_sec_ev("b", 1))
    clock.t = 1118.0
    rec.tick()
    assert [c[0] for c in ring.cuts] == [990.0, 1090.0]
    assert [m["event_id"] for m in t.media] == ["a", "b"]


def test_snapshot_published_before_clip(tmp_path):
    rec, t, _ = _clip_recorder(tmp_path)
    rec.push_jpeg(1.0, b"jpeg-bytes")
    rec.enqueue(_sec_ev("a", 1, snapshot=True))
    _run_jobs(rec)
    assert t.media == [{"event_id": "a", "snapshot_path": "snapshots/x"}]
    assert rec._incident is not None     # clip still pending


def test_clip_false_skips_incident(tmp_path):
    clock = Clock(1000.0)
    ring = FakeRing()
    rec, t, _ = _clip_recorder(tmp_path, ring, clock)
    rec.enqueue(_sec_ev("a", 1, clip=False))
    clock.t = 1100.0
    rec.tick()
    assert rec._incident is None and ring.cuts == [] and t.media == []


def test_unhealthy_ring_falls_back_to_live_mainstream(tmp_path, monkeypatch):
    import vision.recorder as rec_mod
    calls = []

    def fake_urlopen(url, timeout=None):
        calls.append(url)
        return FakeResp(b"mp4-bytes")

    monkeypatch.setattr(rec_mod, "urlopen", fake_urlopen)
    rec, t, _ = _clip_recorder(tmp_path, FakeRing(healthy=False))
    rec.enqueue(_sec_ev("a", 1))
    assert rec._incident is None
    _run_jobs(rec)
    assert calls == ["http://go2rtc:1984/api/stream.mp4?src=cam_1_main&duration=15"]
    assert t.media == [{"event_id": "a", "clip_path": "clips/x"}]


def test_ring_miss_publishes_no_clip(tmp_path):
    clock = Clock(1000.0)
    rec, t, uploads = _clip_recorder(tmp_path, FakeRing(cut_ok=False), clock)
    rec.enqueue(_sec_ev("a", 1))
    clock.t = 1023.0
    rec.tick()
    assert uploads == [] and t.media == [] and rec._incident is None


def test_close_finalizes_open_incident(tmp_path):
    clock = Clock(1000.0)
    ring = FakeRing()
    rec, t, uploads = _clip_recorder(tmp_path, ring, clock)
    rec.enqueue(_sec_ev("a", 1))
    clock.t = 1003.0
    rec.close()
    assert ring.stopped and ring.closed
    assert ring.cuts == [(990.0, 1015.0, 1000.0, True)]
    assert uploads == [("clip", {"timeout": 10, "retries": 1})]
    assert t.media == [{"event_id": "a", "clip_path": "clips/x"}]


def test_tick_prunes_to_open_incident_start(tmp_path):
    clock = Clock(1000.0)
    ring = FakeRing()
    rec, _, _ = _clip_recorder(tmp_path, ring, clock)
    clock.t = 1005.0
    rec.tick()
    assert ring.prunes[-1] == 995.0      # no incident: keep the pre window
    rec.enqueue(_sec_ev("a", 1))        # start = 995
    clock.t = 1012.0
    rec.tick()
    assert ring.prunes[-1] == 995.0      # min(open start 995, 1012 - 10)
    assert ring.checks == 2


def test_queue_drops_oldest_when_full(tmp_path):
    rec = Recorder(1, make_cfg(tmp_path), autostart=False)
    for i in range(60):
        rec.enqueue(make_event(f"ev-{i}"))   # no ring: snapshot + live_clip job each
    assert rec._q.qsize() == 50
    assert rec._q.get_nowait()[1]["event_id"] == "ev-35"
    rec.close()
