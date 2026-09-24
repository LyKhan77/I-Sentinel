"""Event recorder: snapshot per event right away, one mainstream clip per incident.

An incident opens on the first clip-enabled event of a camera; later events join it and
share its clip. It closes clip_post_s after its tracks were last seen (cap clip_max_s);
the clip is cut from the ClipRing segments. Pure stdlib network (urllib).
"""
from __future__ import annotations

import json
import logging
import os
import queue
import threading
import time
import urllib.request

from .clipring import SEGMENT_S

urlopen = urllib.request.urlopen  # module-level for test monkeypatching

log = logging.getLogger(__name__)

MEDIA_TOPIC = "isentinel/events/media"
UPLOAD_RETRIES = 3
UPLOAD_MAX_QUEUE = 50

SETTLE_S = SEGMENT_S + 1  # wait until the segment holding the clip end is closed


class _Incident:
    """Clip window of one camera; events that happen while it is open share its clip."""

    def __init__(self, start: float, now: float, event: dict):
        self.start = start
        self.last_active = now
        self.events: list[dict] = []
        self.tracks: set[int] = set()
        self.add(event, now)

    def add(self, event: dict, now: float) -> None:
        self.events.append(event)
        self.last_active = max(self.last_active, now)
        tid = (event.get("payload") or {}).get("track_id")
        if tid is not None:
            self.tracks.add(tid)


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
    """Per-camera: snapshot per event right away; one mainstream clip per incident."""

    def __init__(self, camera_id: int, cfg, transport=None, clip_ring=None, *,
                 clock=time.time, autostart: bool = True):
        self.camera_id = camera_id
        self.cfg = cfg
        self.transport = transport  # publish_media on upload success; None = silent
        self.clip_ring = clip_ring  # ClipRing | None (None = live fallback per event)
        self.ring = FrameRing()     # substream JPEGs for snapshots
        self._clock = clock
        self._lock = threading.Lock()
        self._incident: _Incident | None = None
        self._q: queue.Queue = queue.Queue(maxsize=UPLOAD_MAX_QUEUE)
        self._stopped = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name=f"recorder-cam{camera_id}")
        if autostart:
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

    def enqueue(self, event: dict) -> None:
        """Called by the camera worker for every event (non-blocking)."""
        if event.get("snapshot") is not False:
            self._put(("snapshot", event))
        if event.get("clip") is False:
            return
        if self.clip_ring is None or not self.clip_ring.healthy():
            self._put(("live_clip", event))  # degraded: post-only live pull, as before
            return
        now = self._clock()
        with self._lock:
            if self._incident is None:
                self._incident = _Incident(now - self.cfg.clip_pre_s, now, event)
            else:
                self._incident.add(event, now)

    def touch(self, track_ids) -> None:
        """Tracks seen this frame; keeps the incident open while its tracks are visible."""
        with self._lock:
            inc = self._incident
            if inc is not None and not inc.tracks.isdisjoint(track_ids):
                inc.last_active = max(inc.last_active, self._clock())

    def _put(self, job: tuple[str, dict]) -> None:
        try:
            self._q.put_nowait(job)
        except queue.Full:
            # ponytail: drop-oldest via get+retry; racy under concurrent producers,
            # single camera worker per recorder so fine
            try:
                self._q.get_nowait()
                log.warning("recorder cam%s: queue full, dropped oldest", self.camera_id)
            except queue.Empty:
                pass
            self._q.put_nowait(job)

    def _end(self, inc: _Incident) -> float:
        return min(inc.start + self.cfg.clip_max_s, inc.last_active + self.cfg.clip_post_s)

    def tick(self, force: bool = False) -> None:
        """Close the incident once its window has passed (force: now); ring upkeep."""
        now = self._clock()
        with self._lock:
            inc = self._incident
            due = inc is not None and (force or now >= self._end(inc) + SETTLE_S)
            if due:
                self._incident = None
        if due:
            upload_kw = {"timeout": 10, "retries": 1} if force else {}
            self._finish(inc, include_open=force, **upload_kw)
        if self.clip_ring is not None and not force:
            self.clip_ring.check()
            with self._lock:
                open_start = self._incident.start if self._incident else now
            self.clip_ring.prune(min(open_start, now - self.cfg.clip_pre_s))

    def _finish(self, inc: _Incident, *, include_open: bool = False, **upload_kw) -> None:
        first = inc.events[0]["event_id"]
        out = os.path.join(self._outbox_dir(), f"{first}.mp4")
        local = self.clip_ring.cut(inc.start, self._end(inc), out,
                                   must_cover=inc.start + self.cfg.clip_pre_s,
                                   include_open=include_open)
        if local is None:
            log.warning("recorder cam%s: ring missed incident %s, no clip",
                        self.camera_id, first)
            return
        self._ship(local, "clip", "video/mp4", [e["event_id"] for e in inc.events], **upload_kw)

    def _run_job(self, kind: str, event: dict) -> None:
        event_id = event["event_id"]
        outbox = self._outbox_dir()
        if kind == "snapshot":
            local = self._save_snapshot(event_id, outbox, event)
            if local:
                self._ship(local, "snapshot", "image/jpeg", [event_id])
        else:  # live_clip
            local = self._save_clip(event_id, outbox)
            if local:
                self._ship(local, "clip", "video/mp4", [event_id])

    def _ship(self, local: str, kind: str, content_type: str, event_ids: list[str],
              **upload_kw) -> None:
        """Upload once, drop the local file, publish the backend path for every event."""
        try:
            path = self._upload_one(local, kind, content_type, **upload_kw)
        finally:
            try:
                os.remove(local)
            except OSError:
                pass
        if path is None or self.transport is None:
            return
        for event_id in event_ids:
            self.transport.publish_media({"event_id": event_id, f"{kind}_path": path})

    def _loop(self) -> None:
        while not self._stopped.is_set():
            try:
                job = self._q.get(timeout=0.5)
            except queue.Empty:
                job = None
            try:
                if job is not None:
                    self._run_job(*job)
                self.tick()
            except Exception:
                log.exception("recorder cam%s: job failed", self.camera_id)

    def _outbox_dir(self) -> str:
        d = os.path.join(os.path.expanduser(str(self.cfg.data_dir)), "outbox")
        os.makedirs(d, exist_ok=True)
        return d

    def _save_snapshot(self, event_id: str, outbox: str, event: dict | None = None) -> str | None:
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

    def _save_clip(self, event_id: str, outbox: str) -> str | None:
        """Degraded path (no healthy ring): live mainstream pull starting now."""
        url = (f"{self.cfg.go2rtc_url}/api/stream.mp4"
               f"?src=cam_{self.camera_id}_main&duration={int(self.cfg.clip_post_s)}")
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

    def close(self) -> None:
        self._stopped.set()
        if self._thread.ident is not None:
            self._thread.join(timeout=5.0)
        if self.clip_ring is None:
            return
        self.clip_ring.stop()  # flush the open segment before the final cut
        try:
            self.tick(force=True)
        except Exception:
            log.exception("recorder cam%s: final clip failed", self.camera_id)
        self.clip_ring.close()

