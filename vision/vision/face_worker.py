"""Face-first attendance worker: track faces on main frames, emit once per track.

Motion gate -> SCRFD -> face tracker -> overlay -> quality gates -> ArcFace.
See 2026-09-23-attendance-face-first-design.md §5.
"""
from __future__ import annotations

import logging
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field

from .face_quality import (FaceSettings, aggregate, blur_score, crop_box, gate_code,
                           quality, yaw_ratio)
from .motion import FrameMotionGate
from .pipeline.detector import Detection
from .pipeline.tracker import ByteTracker

log = logging.getLogger(__name__)
DEDUP_BUCKET_S = 10.0
SNAPSHOT_W = 1280
BOX_BGR = (255, 169, 120)  # #78a9ff
MEDIA_WAIT_S = 1.1  # event deadline; slow upload falls back to event without media


@dataclass
class _TrackState:
    zone: dict
    vectors: list = field(default_factory=list)
    weights: list = field(default_factory=list)
    best_q: float = -1.0
    best: dict | None = None
    done: bool = False


def _jpeg(img) -> bytes:
    import cv2
    ok, buf = cv2.imencode(".jpg", img)
    if not ok:
        raise ValueError("imencode failed")
    return buf.tobytes()


def _snapshot_jpeg(frame, bbox) -> bytes:
    import cv2
    img = frame.copy()
    x1, y1, x2, y2 = (int(v) for v in bbox)
    cv2.rectangle(img, (x1, y1), (x2, y2), BOX_BGR, 3)
    h, w = img.shape[:2]
    if w > SNAPSHOT_W:
        img = cv2.resize(img, (SNAPSHOT_W, int(h * SNAPSHOT_W / w)), interpolation=cv2.INTER_AREA)
    return _jpeg(img)


class FaceGateWorker(threading.Thread):
    """Analyze main-stream frames; publish face overlays and one attendance event per track."""

    def __init__(self, camera_id: int, zones: list[dict], face, transport, node_id: str,
                 settings: FaceSettings, recorder=None, motion: dict | None = None,
                 max_age_s: float = 3.0):
        super().__init__(daemon=True, name=f"face-{camera_id}")
        self.camera_id = camera_id
        self.zones = zones
        self.face = face
        self.transport = transport
        self.node_id = node_id
        self.settings = settings
        self.recorder = recorder
        self.stop_event = threading.Event()
        self.source = None  # set by node when main-stream source is built (Task 6)
        self.events: list[dict] = []
        motion = motion or {}
        self.motion_gate = (
            FrameMotionGate(threshold=motion.get("threshold", 25.0),
                            min_area=motion.get("min_area", 0.01),
                            force_interval_s=motion.get("force_interval_s", 2.0))
            if (motion and motion.get("enabled", True)) else None
        )
        self._tracker = ByteTracker(max_age_s=max_age_s, min_conf=0.5)
        self._states: dict[int, _TrackState] = {}
        self._faces_shown = False
        self._media_busy = threading.Event()
        self._pending_events: queue.SimpleQueue = queue.SimpleQueue()

    def run(self) -> None:
        """Consume source until stopped; event/media finalization runs separately."""
        finalizer = threading.Thread(target=self._finalize_events, daemon=True,
                                     name=f"face-events-{self.camera_id}")
        finalizer.start()
        try:
            while not self.stop_event.is_set():
                try:
                    frame = self.source.next_frame(timeout=min(0.1, self._tracker.max_age_s / 2))
                except StopIteration:
                    break
                if frame is None:
                    self._tracker.update([], time.monotonic())
                    if self._tracker.lost_ids:
                        self._publish([])
                    self._expire()
                    continue
                if frame.data is None:
                    continue
                if self.motion_gate is not None and not self.motion_gate.update(frame.data, frame.ts):
                    self._tracker.update([], frame.ts)
                    if self._tracker.lost_ids:
                        self._publish([])
                    self._expire()
                    continue
                self._process(frame)
        except Exception:
            if not self.stop_event.is_set():
                log.exception("camera %s: face worker died", self.camera_id)
        finally:
            self._pending_events.put(None)
            finalizer.join()

    def stop(self) -> None:
        """Stop consuming frames and close capture without waiting for inference."""
        self.stop_event.set()
        if self.source is not None:
            self.source.close()

    def _process(self, frame) -> None:
        h, w = frame.data.shape[:2]
        try:
            faces = self.face.detect_faces(frame.data)
        except Exception:
            log.warning("camera %s: face detect failed", self.camera_id, exc_info=True)
            faces = []
        dets = [Detection(bbox=(f.bbox[0] / w, f.bbox[1] / h, f.bbox[2] / w, f.bbox[3] / h),
                          conf=f.score) for f in faces]
        by_bbox = {d.bbox: f for d, f in zip(dets, faces)}
        tracks = self._tracker.update(dets, frame.ts)
        boxes, passed = [], []
        for tr in tracks:
            f = by_bbox.get(tr.bbox)
            if f is None:
                continue  # retained track without detection: no stale face overlay
            code, zone = gate_code(f, w, h, self.zones, self.settings)
            aligned = None
            if code is None:
                try:
                    aligned = self.face.align(frame.data, f.kps)
                    if blur_score(aligned) < self.settings.blur_min:
                        code = "blur"
                except Exception:
                    log.warning("camera %s: face align failed", self.camera_id, exc_info=True)
                    code = "blur"
            q = quality(f.score, f.bbox[2] - f.bbox[0], yaw_ratio(f.kps))
            boxes.append({"id": tr.id, "bbox_norm": [round(v, 4) for v in tr.bbox],
                          "label": code or f"{q:.2f}"})
            if code is None:
                passed.append((tr.id, f, zone, aligned, q))
        self._publish(boxes)  # overlay before ArcFace embedding and uploads
        for tid, f, zone, aligned, q in passed:
            self._accumulate(tid, f, zone, aligned, q, frame)
        self._expire()

    def _publish(self, boxes: list[dict]) -> None:
        if self.transport is None:
            return
        if boxes or self._faces_shown:
            self.transport.publish_detections(self.camera_id, boxes, kind="face")
        self._faces_shown = bool(boxes)

    def _accumulate(self, tid, f, zone, aligned, q, frame) -> None:
        st = self._states.setdefault(tid, _TrackState(zone=zone))
        if st.done:
            return
        try:
            vec = self.face.embed(aligned)
        except Exception:
            log.warning("camera %s: face embed failed", self.camera_id, exc_info=True)
            return
        if vec is None:
            return
        st.vectors.append(vec)
        st.weights.append(q)
        if q > st.best_q:
            st.best_q = q
            st.best = {"frame": frame.data, "bbox": f.bbox, "ts": frame.ts,
                       "stats": {"width_px": round(f.bbox[2] - f.bbox[0]),
                                 "det_score": round(f.score, 3),
                                 "yaw": round(yaw_ratio(f.kps), 3),
                                 "blur": round(blur_score(aligned), 1)}}
        if len(st.vectors) >= self.settings.min_frames:
            self._emit(tid, st)

    def _expire(self) -> None:
        """Emit expired tracks with at least one good frame, exactly once."""
        for tid in self._tracker.lost_ids:
            st = self._states.pop(tid, None)
            if st is not None and not st.done and st.vectors:
                self._emit(tid, st)

    def _emit(self, tid: int, st: _TrackState) -> None:
        st.done = True
        best, st.best = st.best, None
        self._pending_events.put((tid, st, best))

    def _finalize_events(self) -> None:
        """Publish queued events without holding frame reads or overlay updates."""
        while (item := self._pending_events.get()) is not None:
            try:
                self._finalize_event(*item)
            except Exception:
                log.exception("camera %s: face event finalization failed", self.camera_id)

    def _finalize_event(self, tid: int, st: _TrackState, best: dict) -> None:
        from .node import _iso  # lazy import: node imports this worker in Task 6
        frame, bbox, ts = best["frame"], best["bbox"], best["ts"]
        h, w = frame.shape[:2]
        x1, y1, x2, y2 = bbox
        crop_path = snapshot_path = face_bbox = None
        if self.recorder is not None:
            cx1, cy1, cx2, cy2 = crop_box(bbox, w, h)
            face_bbox = [x1 - cx1, y1 - cy1, x2 - cx1, y2 - cy1]
            if not self.stop_event.is_set() and not self._media_busy.is_set():
                paths: dict[str, str | None] = {}
                finished = threading.Event()
                abandoned = threading.Event()
                self._media_busy.set()

                def upload_media() -> None:
                    try:
                        for kind, image in (("crop", lambda: _jpeg(frame[cy1:cy2, cx1:cx2])),
                                            ("snapshot", lambda: _snapshot_jpeg(frame, bbox))):
                            if abandoned.is_set():
                                break
                            try:
                                paths[kind] = self.recorder.upload_bytes(
                                    image(), kind, timeout=0.5, retries=1)
                            except Exception:
                                log.warning("camera %s: face %s upload failed", self.camera_id,
                                            kind, exc_info=True)
                    finally:
                        self._media_busy.clear()
                        finished.set()

                threading.Thread(target=upload_media, daemon=True,
                                 name=f"face-media-{self.camera_id}").start()
                if finished.wait(MEDIA_WAIT_S):
                    crop_path, snapshot_path = paths.get("crop"), paths.get("snapshot")
                else:
                    abandoned.set()
                    log.warning("camera %s: face media timed out; event sent without media",
                                self.camera_id)
        ev = {
            "event_id": str(uuid.uuid4()),
            "type": "attendance",
            "node_id": self.node_id,
            "camera_id": self.camera_id,
            "zone_id": st.zone["id"],
            "severity": "info",
            "ts_event": _iso(ts),
            "payload": {
                "track_id": tid,
                "direction": st.zone.get("direction"),
                "bbox_norm": [x1 / w, y1 / h, x2 / w, y2 / h],
                "embedding": aggregate(st.vectors, st.weights),
                "face_quality": round(st.best_q, 3),
                "face_bbox": face_bbox,
                "crop_path": crop_path,
                "face_stats": {**best["stats"], "frames": len(st.vectors)},
            },
            "dedup_key": f"{self.camera_id}:attendance:face{tid}:{int(ts // DEDUP_BUCKET_S)}",
            "snapshot_path": snapshot_path,
            "clip_path": None,
        }
        self.events.append(ev)
        self.transport.publish_event(ev)
