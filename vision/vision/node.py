"""Vision node runner: per-camera worker threads, heartbeat, config hot-reload, graceful stop."""
from __future__ import annotations

import logging
import os
import queue
import signal
import threading
import time
import uuid
from datetime import datetime, timezone

from .analyzers import ANALYZERS
from .analyzers.base import Analyzer
from .config import CameraCfg, NodeSettings
from .pipeline.detector import PersonDetector
from .pipeline.source import FrameSource
from .pipeline.tracker import ByteTracker
from .transport import MqttTransport

log = logging.getLogger(__name__)

DEDUP_BUCKET_S = 10.0
DEFAULT_W, DEFAULT_H = 640, 480


def _iso(ts: float) -> str:
    # Terima timestamp WALL-CLOCK. Pipeline (source) memakai monotonic untuk pacing;
    # konversi monotonic → wall clock dilakukan di sini bila nilai jelas monotonic
    # (jauh di bawah epoch tahun ini). time.time() aman utk heartbeat.
    if ts < 1_700_000_000:  # monotonic (detik sejak boot) → tambah offset epoch
        ts += time.time() - time.monotonic()
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


def _merge_event(camera_id: int, node_id: str, partial: dict, ts: float) -> dict:
    """Analyzer partial {zone_id, type, severity, payload} -> full event envelope."""
    base = _make_event(camera_id, _PartialTrack(partial), ts)
    base["node_id"] = node_id
    base["type"] = partial["type"]
    base["zone_id"] = partial["zone_id"]
    base["severity"] = partial["severity"]
    base["payload"].update(partial["payload"])
    base["dedup_key"] = f"{camera_id}:{partial['type']}:{partial['payload']['track_id']}:{int(ts // DEDUP_BUCKET_S)}"
    return base


class _PartialTrack:
    """Adapts a partial dict to the track-like interface _make_event expects."""

    def __init__(self, partial: dict):
        self.id = partial["payload"]["track_id"]
        self.bbox = partial["payload"]["bbox_norm"]


class CameraWorker(threading.Thread):
    def __init__(self, camera_cfg, detector_factory, transport, stop_event, node_id,
                 analyzers: list[Analyzer] | None = None):
        super().__init__(daemon=True, name=f"cam-{camera_cfg.camera_id}")
        self.camera_cfg = camera_cfg
        self.detector_factory = detector_factory
        self.transport = transport
        self.stop_event = stop_event
        self.node_id = node_id
        self.analyzers = analyzers or []
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
                if frame.data is not None:
                    frame_h, frame_w = frame.data.shape[:2]
                else:
                    frame_w, frame_h = DEFAULT_W, DEFAULT_H
                for tr in tracks:
                    if tr.id not in seen:
                        seen.add(tr.id)
                        ev = _make_event(cam_id, tr, frame.ts)
                        ev["node_id"] = self.node_id
                        self.events.append(ev)
                        self.transport.publish_event(ev)
                for az in self.analyzers:
                    for partial in az.on_frame(frame.ts, tracks, frame_w, frame_h):
                        ev = _merge_event(cam_id, self.node_id, partial, frame.ts)
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
        self.transport = transport or MqttTransport(self.cfg, on_config=self._config_q.put)
        self._default_detector = detector_factory is None
        self.stop_event = threading.Event()
        self._config_q: queue.Queue = queue.Queue()
        self._workers: list[CameraWorker] = []
        self.events: list[dict] = []  # test hook: all worker events

    def _cameras_from_config(self, cfg_dict: dict) -> list[CameraCfg]:
        cams = []
        for c in cfg_dict.get("cameras", []):
            cam = CameraCfg(camera_id=c["camera_id"], source_url=c["source_url"],
                            ai_fps=c.get("ai_fps", 5.0),
                            zones=[z for z in c.get("zones", [])
                                   if z.get("type") == "restricted" and z.get("active", True)])
            cams.append(cam)
        return cams

    def _make_analyzers(self, cam: CameraCfg) -> list[Analyzer]:
        out = []
        for z in cam.zones:
            # zone type is 'restricted'; analyzer registry keyed by event type
            cls = ANALYZERS.get("intrusion" if z["type"] == "restricted" else z["type"])
            if cls:
                out.append(cls(z))
        return out

    def apply_config(self, cfg_dict: dict) -> None:
        """Hot-reload: stop current workers, start new ones from cfg_dict."""
        det = cfg_dict.get("detector")
        if det:
            self._detector_settings = {
                "model": det.get("model", self.cfg.detector_model),
                "nms": det.get("nms", self.cfg.detector_nms),
                "conf": det.get("conf", self.cfg.detector_conf),
                "imgsz": det.get("imgsz", self.cfg.detector_imgsz),
            }
            # only rebuild the default factory; injected factories (tests, custom
            # deployments) stay as-is
            if self._default_detector:
                s = self._detector_settings
                self.detector_factory = lambda cam_id: PersonDetector(
                    s["model"], nms=s["nms"], conf=s["conf"], imgsz=s["imgsz"]
                )
        self._start_workers(self._cameras_from_config(cfg_dict))

    def _start_workers(self, cameras: list[CameraCfg]) -> None:
        self._stop_workers()
        for cam in cameras:
            w = CameraWorker(cam, self.detector_factory, self.transport,
                             threading.Event(), self.cfg.node_id,
                             analyzers=self._make_analyzers(cam))
            w.source = self.source_factory(cam)
            w.start()
            self._workers.append(w)
        log.info("started %d camera worker(s)", len(cameras))

    def _stop_workers(self) -> list[CameraWorker]:
        for w in self._workers:
            w.stop_event.set()
            w.stop()
        for w in self._workers:
            w.join(timeout=5.0)
        stopped, self._workers = self._workers, []
        return stopped

    def run(self, join_timeout: float = 5.0):
        if threading.current_thread() is threading.main_thread():
            for sig in (signal.SIGINT, signal.SIGTERM):
                signal.signal(sig, self._signal)

        hb = threading.Thread(target=self._heartbeat_loop, daemon=True)
        hb.start()

        if not self._workers:
            self._start_workers(self.cfg.cameras())

        # wait for stop, natural worker completion (test mode: sources end),
        # or config message -> rebuild workers
        while not self.stop_event.is_set():
            try:
                cfg_dict = self._config_q.get(timeout=0.2)
            except queue.Empty:
                cfg_dict = None
            if cfg_dict is not None:
                self.apply_config(cfg_dict)
                continue
            if not any(w.is_alive() for w in self._workers):
                break
        self.stop_event.set()
        stopped = self._stop_workers()
        self.events = [e for w in stopped for e in w.events]
        self.transport.close()

    def _signal(self, signum, frame):
        self.stop_event.set()

    def _heartbeat_loop(self):
        while not self.stop_event.is_set():
            cam_ids = [w.camera_cfg.camera_id for w in getattr(self, "_workers", [])]
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
