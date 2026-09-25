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
from .face_quality import FaceSettings
from .face_worker import FaceGateWorker
from .config import CameraCfg, NodeSettings
from . import hardware
from .pipeline.detector import PersonDetector
from .pipeline.source import FrameSource
from .pipeline.tracker import ByteTracker
from .motion import FrameMotionGate
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


def main_stream_name(source_url: str) -> str | None:
    """go2rtc main stream name for a cam_* substream URL.

    "rtsp://host:8554/cam_4" -> "cam_4_main" (full-res sibling stream).
    None when the last path segment is not a cam_* stream.
    """
    seg = (source_url or "").rstrip("/").rsplit("/", 1)[-1]
    return f"{seg}_main" if seg.startswith("cam_") else None


def main_stream_url(source_url: str) -> str:
    """Full-resolution go2rtc sibling for cam_* streams; preserve other URLs."""
    name = main_stream_name(source_url)
    return source_url.rstrip("/").rsplit("/", 1)[0] + "/" + name if name else source_url


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
                 analyzers: list[Analyzer] | None = None, recorder=None,
                 emit_person_detect: bool = False, motion: dict | None = None):
        super().__init__(daemon=True, name=f"cam-{camera_cfg.camera_id}")
        self.camera_cfg = camera_cfg
        self.camera_id = camera_cfg.camera_id
        self.detector_factory = detector_factory
        self.transport = transport
        self.stop_event = stop_event
        self.node_id = node_id
        self.analyzers = analyzers or []
        self.recorder = recorder
        self.emit_person_detect = emit_person_detect
        motion = motion or {}
        # Config pra-R5 tidak mengirim `motion` → gate OFF (perilaku lama). R5 selalu
        # mengirim dict berisi `enabled`, jadi default-nya ON kecuali dimatikan.
        self.motion_gate = (
            FrameMotionGate(threshold=motion.get("threshold", 25.0),
                            min_area=motion.get("min_area", 0.01),
                            force_interval_s=motion.get("force_interval_s", 2.0))
            if (motion and motion.get("enabled", True)) else None
        )
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
                if self.motion_gate is not None and not self.motion_gate.update(frame.data, frame.ts):
                    # Tanpa gerak: lewati inferensi (hemat GPU), tapi tracker tetap
                    # diberi update kosong supaya track lama expire secara alami —
                    # objek diam tetap terdeteksi via force_interval_s gate.
                    tracker.update([], frame.ts)
                    continue
                try:
                    detections = detector.detect(frame.data, ts=frame.ts)
                except Exception:
                    log.exception("camera %s: detector error, skipping frame", cam_id)
                    continue
                tracks = tracker.update(detections, frame.ts)
                if self.recorder is not None and tracks:
                    self.recorder.touch([t.id for t in tracks])
                if tracks and self.transport is not None:
                    self.transport.publish_detections(cam_id, [
                        {"id": t.id, "bbox_norm": [round(v, 4) for v in t.bbox], "label": None}
                        for t in tracks
                    ], kind="person")
                if self.recorder is not None:
                    if detections and frame.data is not None:
                        try:
                            import cv2
                            ok, enc = cv2.imencode(".jpg", frame.data)
                            if ok:
                                self.recorder.push_jpeg(frame.ts, enc.tobytes())
                        except ImportError:
                            pass  # no cv2: ring stays empty, snapshots skipped
                    elif detections:
                        self.recorder.push_jpeg(frame.ts, b"")  # tests: no frame data
                if frame.data is not None:
                    frame_h, frame_w = frame.data.shape[:2]
                else:
                    frame_w, frame_h = DEFAULT_W, DEFAULT_H
                for tr in tracks:
                    if tr.id not in seen:
                        seen.add(tr.id)
                        if self.emit_person_detect:
                            ev = _make_event(cam_id, tr, frame.ts)
                            ev["node_id"] = self.node_id
                            self.events.append(ev)
                            self.transport.publish_event(ev)
                            if self.recorder is not None:
                                self.recorder.enqueue(ev)
                for az in self.analyzers:
                    for partial in az.on_frame(frame.ts, tracks, frame_w, frame_h):
                        ev = _merge_event(cam_id, self.node_id, partial, frame.ts)
                        media = getattr(az, "media", None)
                        if media is not None:
                            ev["snapshot"] = media.get("snapshot", True)
                            ev["clip"] = media.get("clip", True)
                        self.events.append(ev)
                        self.transport.publish_event(ev)
                        if self.recorder is not None:
                            self.recorder.enqueue(ev)
        except Exception:
            if not self.stop_event.is_set():
                log.exception("camera %s worker died", cam_id)

    def stop(self):
        if self.source is not None:
            self.source.close()


def attendance_zones(cam: CameraCfg) -> list[dict]:
    """Active attendance gates with valid direction, including legacy absensi."""
    return [z for z in cam.zones
            if z.get("direction") in ("entry", "exit")
            and any(b.get("kind") == "attendance" for b in behaviors_of(z))]


def behaviors_of(z: dict) -> list[dict]:
    """Daftar behavior zona; fallback kolom lama bila config pra-R5 terpasang."""
    bs = z.get("behaviors")
    if bs:
        return list(bs)
    legacy: list[dict] = []
    ztype = z.get("type")
    dwell = z.get("dwell_seconds", 0) or 0
    if ztype in ("restricted", "free"):
        legacy.append({"kind": "intrusion", "trigger_seconds": dwell,
                       "enabled": ztype == "restricted"})
    if ztype in ("absensi", "attendance"):
        legacy.append({"kind": "attendance",
                       "trigger_seconds": z.get("trigger_seconds", dwell) or 0})
    if (z.get("loiter_seconds", 0) or 0) > 0:
        legacy.append({"kind": "loitering", "trigger_seconds": z.get("loiter_seconds", 0)})
    if (z.get("speed_limit_mps", 0) or 0) > 0:
        legacy.append({"kind": "running", "trigger_seconds": dwell,
                       "speed_limit_mps": z.get("speed_limit_mps", 0)})
    return [b for b in legacy if b.get("enabled", True)]


class VisionNode:
    def __init__(self, cfg: NodeSettings | None = None, detector_factory=None, source_factory=None,
                 transport=None):
        self.cfg = cfg or NodeSettings()
        # confidence per kamera (config R5) menimpa conf global; diisi saat config apply
        self._camera_conf: dict[int, float] = {}
        self.detector_factory = detector_factory or (
            lambda cam_id: PersonDetector(self.cfg.detector_model, nms=self.cfg.detector_nms,
                                          conf=self._camera_conf.get(cam_id) or self.cfg.detector_conf,
                                          imgsz=self.cfg.detector_imgsz,
                                          device=self.cfg.detector_device)
        )
        self.source_factory = source_factory or (
            lambda cam: FrameSource(cam.source_url, cam.ai_fps)
        )
        self._config_q: queue.Queue = queue.Queue()
        self._calib_warned: set[int] = set()  # log "no calibration" once per camera
        self.transport = transport or MqttTransport(self.cfg, on_config=self._config_q.put)
        self._default_detector = detector_factory is None
        self.stop_event = threading.Event()
        self._workers: list[CameraWorker | FaceGateWorker] = []
        self._await_config = False  # a configured node must not exit with zero workers
        self._face_settings = FaceSettings()
        self.events: list[dict] = []  # test hook: all worker events
        from .face import FaceEmbedder
        self.face = (FaceEmbedder(self.cfg.face_model_dir
                                  or os.path.join(self.cfg.data_dir, "faces_models"),
                                  self.cfg.face_device)
                     if self.cfg.face_embed else None)

    def _cameras_from_config(self, cfg_dict: dict) -> list[CameraCfg]:
        cams = []
        for c in cfg_dict.get("cameras", []):
            if c.get("confidence"):
                self._camera_conf[c["camera_id"]] = float(c["confidence"])
            cam = CameraCfg(camera_id=c["camera_id"], source_url=c["source_url"],
                            ai_fps=c.get("ai_fps", 5.0),
                            confidence=c.get("confidence"),
                            analyzers=c.get("analyzers"),
                            motion=c.get("motion") or {},
                            meters_per_pixel=c.get("meters_per_pixel"),
                            zones=[z for z in c.get("zones", [])
                                   if z.get("active", True)
                                   and (z.get("behaviors") or behaviors_of(z))])
            cams.append(cam)
        return cams

    def _make_analyzers(self, cam: CameraCfg) -> list[Analyzer]:
        """Build person behavior analyzers; FaceGateWorker handles attendance separately."""
        out = []
        for z in cam.zones:
            for b in behaviors_of(z):
                kind = b.get("kind")
                if kind == "attendance":
                    continue  # FaceGateWorker owns this zone
                # zona = satu-satunya aturan: mask camera.analyzers (lama) tidak dibaca lagi.
                # Media per behavior; zona lama tanpa key per behavior → flag zona.
                media = {"snapshot": b.get("snapshot", z.get("snapshot", True)),
                         "clip": b.get("clip", z.get("clip", True))}
                spec = dict(z)
                spec["trigger_seconds"] = b.get("trigger_seconds", 0) or 0
                if kind == "intrusion":
                    out.append(self._with_media(ANALYZERS["intrusion"](spec), media))
                elif kind == "loitering":
                    # loitering: dwell = trigger behavior (legacy: loiter_seconds)
                    spec["loiter_seconds"] = spec["trigger_seconds"]
                    out.append(self._with_media(ANALYZERS["loitering"](spec), media))
                elif kind == "running":
                    if b.get("speed_limit_mps") is not None:
                        spec["speed_limit_mps"] = b["speed_limit_mps"]
                    if not spec.get("speed_limit_mps", 0):
                        continue
                    if cam.meters_per_pixel is None:
                        if cam.camera_id not in self._calib_warned:
                            self._calib_warned.add(cam.camera_id)
                            log.info("running analyzer skipped camera %s (no calibration)",
                                     cam.camera_id)
                    else:
                        out.append(self._with_media(
                            ANALYZERS["running"](spec, cam.meters_per_pixel), media))
        return out

    @staticmethod
    def _with_media(analyzer, media: dict):
        """Tempel flag snapshot/clip zona ke analyzer — dibawa worker ke event."""
        analyzer.media = media
        return analyzer

    def _wants_clip(self, analyzers: list) -> bool:
        """Mainstream ring only for cameras whose events can carry a clip."""
        return self.cfg.emit_person_detect or any(
            getattr(a, "media", {}).get("clip", True) for a in analyzers)

    def apply_config(self, cfg_dict: dict) -> None:
        """Hot-reload: stop current workers, start new ones from cfg_dict."""
        det = cfg_dict.get("detector")
        if det:
            # model dari config bisa nama file relatif (mis. "yolo26s.engine");
            # resolve ke direktori model env bila file relatif tidak ada di cwd.
            model = det.get("model") or self.cfg.detector_model
            if model and not os.path.isabs(model):
                local = os.path.abspath(model)
                env_dir = os.path.dirname(os.path.abspath(self.cfg.detector_model))
                candidate = os.path.join(env_dir, os.path.basename(model))
                if not os.path.exists(local) and os.path.exists(candidate):
                    model = candidate
            self._detector_settings = {
                "model": model,
                "nms": det.get("nms", self.cfg.detector_nms),
                "conf": det.get("conf", self.cfg.detector_conf),
                "imgsz": det.get("imgsz", self.cfg.detector_imgsz),
            }
            # device pin dari config push (UI/DB) — SELALU menang bila key ada
            # (DB > env > auto). "" = auto eksplisit dari UI. Pin invalid ->
            # reject config, tetap pakai device lama; node tetap hidup
            # (beda dari fail-fast start).
            if "device" in det:
                dev = (det.get("device") or "").strip()
                err = hardware.validate_device_pin(dev)
                if err:
                    log.error("config push rejected: %s", err)
                else:
                    self.cfg.detector_device = dev
            # only rebuild the default factory; injected factories (tests, custom
            # deployments) stay as-is
            if self._default_detector:
                s = self._detector_settings
                self.detector_factory = lambda cam_id: PersonDetector(
                    s["model"], nms=s["nms"],
                    conf=self._camera_conf.get(cam_id) or s["conf"], imgsz=s["imgsz"],
                    device=self.cfg.detector_device
                )
        face = cfg_dict.get("face")
        if face and "device" in face and self.face is not None:
            dev = (face.get("device") or "").strip()
            err = hardware.validate_device_pin(dev)
            if err:
                log.error("config push rejected (face): %s", err)
            elif dev != self.cfg.face_device:
                # rebuild embedder dengan pin baru (InsightFace dibuat ulang,
                # provider onnxruntime mengikuti device)
                from .face import FaceEmbedder
                root = self.cfg.face_model_dir or os.path.join(self.cfg.data_dir,
                                                               "faces_models")
                self.face = FaceEmbedder(root, dev)
                self.cfg.face_device = dev
        self._face_settings = FaceSettings.from_config(cfg_dict.get("face"))
        self._await_config = True
        self._start_workers(self._cameras_from_config(cfg_dict))

    def _start_workers(self, cameras: list[CameraCfg]) -> None:
        self._stop_workers()
        self._await_config |= bool(cameras)
        for cam in cameras:
            analyzers = self._make_analyzers(cam)
            gates = attendance_zones(cam) if self.face is not None else []
            run_yolo = bool(analyzers) or self.cfg.emit_person_detect
            if not run_yolo and not gates:
                continue  # tanpa zona aktif: live view saja (go2rtc), tanpa inferensi
            recorder = None
            if self.cfg.api_key:  # production: upload blobs to backend
                from .recorder import Recorder
                ring = None
                if run_yolo and self._wants_clip(analyzers):
                    from . import clipring
                    ring = clipring.ClipRing(cam.camera_id, main_stream_url(cam.source_url),
                                             self.cfg.clip_ring_dir)
                    ring.start()
                recorder = Recorder(cam.camera_id, self.cfg, self.transport, clip_ring=ring)
            if run_yolo:
                w = CameraWorker(cam, self.detector_factory, self.transport,
                                 threading.Event(), self.cfg.node_id,
                                 analyzers=analyzers, recorder=recorder,
                                 emit_person_detect=self.cfg.emit_person_detect,
                                 motion=cam.motion)
                w.source = self.source_factory(cam)
                w.start()
                self._workers.append(w)
            if gates:
                fw = FaceGateWorker(cam.camera_id, gates, self.face, self.transport,
                                    self.cfg.node_id, self._face_settings,
                                    recorder=recorder, motion=cam.motion)
                fw.source = self.source_factory(
                    cam.model_copy(update={"source_url": main_stream_url(cam.source_url)}))
                fw.start()
                self._workers.append(fw)
        log.info("started %d worker(s) for %d camera(s)", len(self._workers), len(cameras))

    def _stop_workers(self) -> list[CameraWorker | FaceGateWorker]:
        for w in self._workers:
            w.stop_event.set()
            w.stop()
        recorders = {}
        for w in self._workers:
            w.join(timeout=5.0)
            if w.recorder is not None:
                recorders[id(w.recorder)] = w.recorder
        for rec in recorders.values():
            rec.close()
        stopped, self._workers = self._workers, []
        return stopped

    def run(self, join_timeout: float = 5.0):
        # fail-fast: device pin tidak valid -> jangan mulai deteksi di GPU salah
        err = hardware.validate_device_pin(self.cfg.detector_device)
        if err:
            log.error("%s", err)
            raise SystemExit(1)
        if threading.current_thread() is threading.main_thread():
            for sig in (signal.SIGINT, signal.SIGTERM):
                signal.signal(sig, self._signal)

        hb = threading.Thread(target=self._heartbeat_loop, daemon=True)
        hb.start()

        if not self._workers and not self._await_config:
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
            if self._workers and not any(w.is_alive() for w in self._workers):
                break
            if not self._workers and not self._await_config:
                break
        self.stop_event.set()
        stopped = self._stop_workers()
        self.events = [e for w in stopped for e in w.events]
        self.transport.close()

    def _signal(self, signum, frame):
        self.stop_event.set()

    def _detector_module_info(self) -> dict:
        """modules.detector payload: device pin, model name, ms/frame measurement."""
        model = getattr(self, "_detector_settings", {}).get("model") or self.cfg.detector_model
        ms = None
        if self._default_detector and PersonDetector.detect_n:
            ms = round(PersonDetector.detect_ms_total / PersonDetector.detect_n, 1)
        return {"device": self.cfg.detector_device or "auto",
                "model": os.path.basename(model), "ms_per_frame": ms,
                "detect_n": PersonDetector.detect_n}

    def _face_module_info(self) -> dict:
        """Report face model state and inference counters without forcing model load."""
        f = self.face
        return {"device": self.cfg.face_device or "auto",
                "loaded": bool(f is not None and f.loaded()),
                "detect_n": f.detect_n if f is not None else 0,
                "embed_n": f.embed_n if f is not None else 0}

    def _heartbeat_loop(self):
        while not self.stop_event.is_set():
            cam_ids = sorted({w.camera_id for w in getattr(self, "_workers", [])})
            try:
                cpu = os.getloadavg()[0]
            except (AttributeError, OSError):
                cpu = None
            hb = {"ts": _iso(time.time()), "cpu_percent": cpu, "gpu_mem": None,
                  "cameras": cam_ids}
            hw = hardware.collect_gpu_info()
            if hw:
                hb["hw"] = hw
            hb["modules"] = {"detector": self._detector_module_info(),
                             "face": self._face_module_info()}
            self.transport.publish_heartbeat(hb)
            self.stop_event.wait(self.cfg.heartbeat_s)


def main():
    logging.basicConfig(level=os.environ.get("VISION_LOG_LEVEL", "INFO"))
    VisionNode().run()


if __name__ == "__main__":
    main()
