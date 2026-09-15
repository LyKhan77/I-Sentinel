"""Event recorder: frame ring buffer, snapshot+clip capture via go2rtc, blob upload queue.

Pure stdlib network (urllib) — no new deps. Upload runs on a dedicated thread so
the camera loop never blocks on HTTP.
"""
from __future__ import annotations

import json
import logging
import queue
import threading
import time
import urllib.request

urlopen = urllib.request.urlopen  # module-level for test monkeypatching

log = logging.getLogger(__name__)

MEDIA_TOPIC = "isentinel/events/media"
UPLOAD_RETRIES = 3
UPLOAD_MAX_QUEUE = 50


class FrameRing:
    """In-memory ring of (ts, jpeg_bytes). Keeps last max_frames encoded frames."""

    def __init__(self, max_frames: int = 40):
        self.max_frames = max_frames
        self._buf: list[tuple[float, bytes]] = []

    def push(self, ts: float, jpeg: bytes) -> None:
        if not jpeg:
            return
        self._buf.append((ts, jpeg))
        if len(self._buf) > self.max_frames:
            self._buf.pop(0)

    def pre_clip(self) -> list[tuple[float, bytes]]:
        return list(self._buf)


class Recorder:
    """Per-camera: capture snapshot+clip to outbox, upload blobs in background thread."""

    def __init__(self, camera_id: int, cfg, transport=None):
        self.camera_id = camera_id
        self.cfg = cfg
        self.transport = transport  # publish_media on upload success; None = silent
        self.ring = FrameRing()
        self._q: queue.Queue = queue.Queue(maxsize=UPLOAD_MAX_QUEUE)
        self._stopped = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name=f"recorder-cam{camera_id}")
        self._thread.start()

    def push_jpeg(self, ts: float, jpeg: bytes) -> None:
        self.ring.push(ts, jpeg)

    def push_frame(self, ts: float, frame) -> None:
        """Encode ndarray via cv2 (lazy) and push. Skips when cv2 missing."""
        try:
            import cv2
        except ImportError:
            log.debug("cv2 not installed; skipping ring push")
            return
        ok, enc = cv2.imencode(".jpg", frame)
        if ok:
            self.ring.push(ts, enc.tobytes())

    def enqueue(self, event: dict, track_bbox_norm=None) -> None:
        try:
            self._q.put_nowait((event, track_bbox_norm))
        except queue.Full:
            # ponytail: drop-oldest via get+retry; racy under concurrent producers,
            # single camera worker per recorder so fine
            try:
                self._q.get_nowait()
                log.warning("recorder cam%s: upload queue full, dropped oldest", self.camera_id)
            except queue.Empty:
                pass
            self._q.put_nowait((event, track_bbox_norm))

    def _loop(self) -> None:
        while not self._stopped.is_set():
            try:
                event, bbox = self._q.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                local = self.capture(event, bbox)
                if local is None:
                    continue
                uploaded = self.upload(local)
                if uploaded and self.transport is not None:
                    self.transport.publish_media({
                        "event_id": uploaded["event_id"],
                        "clip_path": uploaded.get("clip_path"),
                        "snapshot_path": uploaded.get("snapshot_path"),
                    })
            except Exception:
                log.exception("recorder cam%s: failed event %s", self.camera_id,
                              event.get("event_id"))

    def capture(self, event: dict, track_bbox_norm=None) -> dict | None:
        event_id = event["event_id"]
        outbox = self._outbox_dir()
        snapshot_path = self._save_snapshot(event_id, outbox)
        clip_path = self._save_clip(event_id, outbox)
        if snapshot_path is None and clip_path is None:
            return None
        return {"event_id": event_id, "snapshot_local": snapshot_path, "clip_local": clip_path}

    def _outbox_dir(self) -> str:
        import os
        d = os.path.join(os.path.expanduser(str(self.cfg.data_dir)), "outbox")
        os.makedirs(d, exist_ok=True)
        return d

    def _save_snapshot(self, event_id: str, outbox: str) -> str | None:
        import os
        frames = self.ring.pre_clip()
        if not frames:
            log.warning("recorder cam%s: no ring frames for snapshot", self.camera_id)
            return None
        # ponytail: 'best' = latest frame; bbox-area scoring deferred until needed
        _, jpeg = frames[-1]
        path = os.path.join(outbox, f"{event_id}.jpg")
        with open(path, "wb") as f:
            f.write(jpeg)
        return path

    def _save_clip(self, event_id: str, outbox: str) -> str | None:
        import os
        url = (f"{self.cfg.go2rtc_url}/api/stream.mp4"
               f"?src=cam_{self.camera_id}&duration={self.cfg.record_clip_s}")
        try:
            with urlopen(url, timeout=60) as resp:
                data = resp.read()
        except Exception as e:
            log.warning("recorder cam%s: go2rtc clip failed (%s), clip skipped",
                        self.camera_id, e)
            return None
        if not data:
            return None
        path = os.path.join(outbox, f"{event_id}.mp4")
        with open(path, "wb") as f:
            f.write(data)
        return path

    def _upload_one(self, path: str, kind: str, content_type: str) -> str | None:
        """POST raw bytes to blob endpoint. Returns backend path or None on final failure."""
        import os
        url = (f"{self.cfg.api_url}/internal/nodes/{self.cfg.node_id}/blobs?kind={kind}")
        for attempt in range(UPLOAD_RETRIES):
            if attempt:
                time.sleep(2 ** (attempt - 1))
            try:
                req = urllib.request.Request(
                    url, method="POST",
                    headers={"Content-Type": content_type,
                             "Authorization": f"Bearer {self.cfg.api_key}"},
                )
                with open(path, "rb") as f:
                    req.data = f.read()
                with urlopen(req, timeout=60) as resp:
                    body = json.loads(resp.read().decode("utf-8"))
                    return body.get("path")
            except Exception as e:
                log.warning("recorder cam%s: upload %s attempt %s failed: %s",
                            self.camera_id, kind, attempt + 1, e)
        return None

    def upload(self, local: dict) -> dict | None:
        results: dict = {"event_id": local["event_id"]}
        if local.get("snapshot_local"):
            p = self._upload_one(local["snapshot_local"], "snapshot", "image/jpeg")
            if p is None:
                return None
            results["snapshot_path"] = p
        if local.get("clip_local"):
            p = self._upload_one(local["clip_local"], "clip", "video/mp4")
            if p is None:
                return None
            results["clip_path"] = p
        return results if len(results) > 1 else None

    def close(self) -> None:
        self._stopped.set()
        self._thread.join(timeout=5.0)

