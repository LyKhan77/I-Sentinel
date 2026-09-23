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

    def fetch_frame(self, stream_name: str) -> bytes | None:
        """Single jpeg snapshot from go2rtc (main stream): raw bytes or None.

        Used to crop attendance faces at full resolution instead of the
        low-res substream the detector runs on.
        """
        url = f"{self.cfg.go2rtc_url}/api/frame.jpeg?src={stream_name}"
        try:
            with urlopen(url, timeout=5) as resp:
                data = resp.read()
        except Exception as e:
            log.warning("recorder cam%s: frame fetch %s failed: %s",
                        self.camera_id, stream_name, e)
            return None
        return data or None

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
        snapshot_path = None
        if event.get("snapshot") is not False:  # default True (zona tanpa flag)
            snapshot_path = self._save_snapshot(event_id, outbox, event)
        clip_path = self._save_clip(event_id, outbox, event)
        if snapshot_path is None and clip_path is None:
            return None
        return {"event_id": event_id, "snapshot_local": snapshot_path, "clip_local": clip_path}

    def _outbox_dir(self) -> str:
        import os
        d = os.path.join(os.path.expanduser(str(self.cfg.data_dir)), "outbox")
        os.makedirs(d, exist_ok=True)
        return d

    def _save_snapshot(self, event_id: str, outbox: str, event: dict | None = None) -> str | None:
        import os
        frames = self.ring.pre_clip()
        if not frames:
            log.warning("recorder cam%s: no ring frames for snapshot", self.camera_id)
            return None
        # ponytail: 'best' = latest frame; bbox-area scoring deferred until needed
        _, jpeg = frames[-1]
        if event is not None:
            jpeg = self._draw_track_box(jpeg, event) or jpeg
        path = os.path.join(outbox, f"{event_id}.jpg")
        with open(path, "wb") as f:
            f.write(jpeg)
        return path

    _TRACK_COLORS = {"critical": (0, 0, 230), "warning": (0, 160, 230),
                     "info": (0, 200, 0)}

    def _draw_track_box(self, jpeg: bytes, event: dict) -> bytes | None:
        """Bbox track + label 'ID n' pada jpeg ring (warna = severity event).

        Mengikat visual orang-pemicu ke snapshot; bbox_norm = relatif frame.
        """
        payload = event.get("payload") or {}
        bbox = payload.get("bbox_norm")
        if not bbox or len(bbox) != 4:
            return None
        try:
            import cv2
            import numpy as np
            img = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                return None
            h, w = img.shape[:2]
            x1, y1, x2, y2 = [int(v * s) for v, s in zip(bbox, (w, h, w, h))]
            color = self._TRACK_COLORS.get(event.get("severity", "info"), (0, 200, 0))
            cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
            label = f"ID {payload.get('track_id')}"
            cv2.putText(img, label, (x1, max(16, y1 - 6)), cv2.FONT_HERSHEY_SIMPLEX,
                        0.6, color, 2, cv2.LINE_AA)
            ok, buf = cv2.imencode(".jpg", img)
            return buf.tobytes() if ok else None
        except Exception:
            log.warning("track box draw gagal — snapshot polos", exc_info=True)
            return None

    def _save_clip(self, event_id: str, outbox: str, event: dict | None = None) -> str | None:
        import os
        if event is not None and event.get("clip") is False:
            return None
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

    def upload_bytes(self, data: bytes, kind: str, content_type: str = "image/jpeg",
                     *, timeout: float = 60, retries: int = UPLOAD_RETRIES) -> str | None:
        """Upload blob; latency-sensitive callers may limit socket wait and attempts."""
        import os
        import uuid
        if not self.cfg.api_url or not self.cfg.api_key:
            return None
        tmp = os.path.join(self._outbox_dir(), f"{uuid.uuid4().hex}.tmp")
        try:
            with open(tmp, "wb") as f:
                f.write(data)
            return self._upload_one(tmp, kind, content_type, timeout=timeout, retries=retries)
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass

    def _upload_one(self, path: str, kind: str, content_type: str, *,
                    timeout: float = 60, retries: int = UPLOAD_RETRIES) -> str | None:
        """POST raw bytes to blob endpoint. Returns backend path or None on final failure."""
        import os
        url = (f"{self.cfg.api_url}/internal/nodes/{self.cfg.node_id}/blobs?kind={kind}")
        for attempt in range(retries):
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
                with urlopen(req, timeout=timeout) as resp:
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

