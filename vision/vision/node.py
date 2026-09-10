"""Vision node runner: per-camera worker threads, heartbeat, graceful stop."""
from __future__ import annotations

import logging
import os
import signal
import threading
import time
import uuid
from datetime import datetime, timezone

from .config import NodeSettings
from .pipeline.detector import PersonDetector
from .pipeline.source import FrameSource
from .pipeline.tracker import ByteTracker
from .transport import MqttTransport

log = logging.getLogger(__name__)

DEDUP_BUCKET_S = 10.0


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def _make_event(camera_id: int, track, ts: float) -> dict:
    return {
        "event_id": str(uuid.uuid4()),
        "type": "person_detect",
        "node_id": None,  # filled by caller
        "camera_id": camera_id,
        "zone_id": None,
        "severity": "info",
        "ts_event": _iso(ts),
        "payload": {
            "track_id": track.id,
            "confidence": None,
            "speed_mps": None,
            "duration_s": None,
            "direction": None,
            "employee_id": None,
            "face_score": None,
            "bbox_norm": list(track.bbox),
            "snapshot_crop": None,
        },
        "dedup_key": f"{camera_id}:person_detect:{track.id}:{int(ts // DEDUP_BUCKET_S)}",
    }


class CameraWorker(threading.Thread):
    def __init__(self, camera_cfg, detector_factory, transport, stop_event, node_id):
        super().__init__(daemon=True, name=f"cam-{camera_cfg.camera_id}")
        self.camera_cfg = camera_cfg
        self.detector_factory = detector_factory
        self.transport = transport
        self.stop_event = stop_event
        self.node_id = node_id
        self.events: list[dict] = []  # test hook
        self.source = None

    def run(self):
        cam_id = self.camera_cfg.camera_id
        detector = self.detector_factory(cam_id)
        tracker = ByteTracker()
        seen: set[int] = set()
        try:
            for frame in self.source:
                if self.stop_event.is_set():
                    break
                try:
                    detections = detector.detect(frame.data, ts=frame.ts)
                except Exception:
                    log.exception("camera %s: detector error, skipping frame", cam_id)
                    continue
                tracks = tracker.update(detections, frame.ts)
                for tr in tracks:
                    if tr.id not in seen:
                        seen.add(tr.id)
                        ev = _make_event(cam_id, tr, frame.ts)
                        ev["node_id"] = self.node_id
                        self.events.append(ev)
                        self.transport.publish_event(ev)
        except Exception:
            if not self.stop_event.is_set():
                log.exception("camera %s worker died", cam_id)

    def stop(self):
        if self.source is not None:
            self.source.close()


class VisionNode:
    def __init__(self, cfg: NodeSettings | None = None, detector_factory=None, source_factory=None,
                 transport=None):
        self.cfg = cfg or NodeSettings()
        self.detector_factory = detector_factory or (
            lambda cam_id: PersonDetector(self.cfg.detector_model, nms=self.cfg.detector_nms,
                                          conf=self.cfg.detector_conf, imgsz=self.cfg.detector_imgsz)
        )
        self.source_factory = source_factory or (
            lambda cam: FrameSource(cam.source_url, cam.ai_fps)
        )
        self.transport = transport or MqttTransport(self.cfg)
        self.stop_event = threading.Event()
        self.events: list[dict] = []  # test hook: all worker events

    def run(self, join_timeout: float = 5.0):
        if threading.current_thread() is threading.main_thread():
            for sig in (signal.SIGINT, signal.SIGTERM):
                signal.signal(sig, self._signal)

        hb = threading.Thread(target=self._heartbeat_loop, daemon=True)
        hb.start()

        workers = []
        for cam in self.cfg.cameras():
            w = CameraWorker(cam, self.detector_factory, self.transport, self.stop_event, self.cfg.node_id)
            w.source = self.source_factory(cam)
            w.start()
            workers.append(w)

        # wait for stop or natural worker completion (test mode: sources end)
        while not self.stop_event.is_set() and any(w.is_alive() for w in workers):
            self.stop_event.wait(0.2)
        self.stop_event.set()
        for w in workers:
            w.join(timeout=join_timeout)
        self.events = [e for w in workers for e in w.events]
        self.transport.close()

    def _signal(self, signum, frame):
        self.stop_event.set()

    def _heartbeat_loop(self):
        cam_ids = [c.camera_id for c in self.cfg.cameras()]
        while not self.stop_event.is_set():
            try:
                cpu = os.getloadavg()[0]
            except (AttributeError, OSError):
                cpu = None
            self.transport.publish_heartbeat(
                {"ts": _iso(time.time()), "cpu_percent": cpu, "gpu_mem": None, "cameras": cam_ids}
            )
            self.stop_event.wait(self.cfg.heartbeat_s)


def main():
    logging.basicConfig(level=os.environ.get("VISION_LOG_LEVEL", "INFO"))
    VisionNode().run()


if __name__ == "__main__":
    main()
