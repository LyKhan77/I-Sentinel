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
from dataclasses import dataclass, field, replace
from statistics import median

from .face_quality import (BestK, FaceSettings, aggregate, blur_score, crop_box, gate_code,
                           quality, yaw_ratio)
from .intrusion_face import ErrorThrottle, IdentCollector, IntrusionRegistry, pitch_dev
from .motion import FrameMotionGate
from .pipeline.detector import Detection
from .pipeline.tracker import ByteTracker

log = logging.getLogger(__name__)
DEDUP_BUCKET_S = 10.0
SNAPSHOT_W = 1280
BOX_BGR = (255, 169, 120)  # #78a9ff
MEDIA_WAIT_S = 1.1  # event deadline; slow upload falls back to event without media
# unified: tanpa kandidat sebesar ini orang dianggap pergi dan event dikirim, tidak menunggu tracker
# (max_age_s 3 dtk) melepas track; lebih pendek dari jendela tetapi lebih panjang dari celah gerbang biasa
UNIFIED_GONE_S = 0.5
EVENT_HISTORY_MAX = 32  # test hook only; do not retain lifetime biometric payloads


@dataclass
class _TrackState:
    zone: dict
    vectors: list = field(default_factory=list)
    weights: list = field(default_factory=list)
    best_q: float = -1.0
    best: dict | None = None
    done: bool = False
    unified: bool = False              # jalur unified: gerbang identitas + K terbaik + jendela
    keeper: BestK | None = None        # jalur unified: K kandidat terbaik (rank, quality, vector)
    first_ts: float | None = None      # jalur unified: ts vektor pertama yang masuk keeper (awal jendela)
    last_cand_ts: float | None = None  # jalur unified: ts kandidat lolos gerbang terakhir
    emit_ts: float = 0.0               # jalur unified: ts saat event dikirim
    zone_start_ts: float | None = None  # jalur unified: ts wajah pertama di zona (diambil saat emit)


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
                 max_age_s: float = 3.0, registry: IntrusionRegistry | None = None):
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
        self._media_pending = threading.Event()
        self._pending_events: queue.SimpleQueue = queue.SimpleQueue()
        self.frames = 0  # frame main-stream diproses (heartbeat: fps jendela)
        self.motion_skipped = 0
        self._in_zone: dict[int, float] = {}
        self._funnel = self._empty_funnel()
        self._last_frame_ts = 0.0  # jalur unified: `_expire` tanpa timestamp memakai frame terakhir
        # gerbang unified: lebar identitas + tanpa blur absolut (pitch dicek terpisah di `_gate_unified`)
        self._unified_settings = replace(settings, min_width_px=settings.ident.min_width_px, blur_min=0.0)
        # registry ≠ None → kamera ini juga menjalankan identitas intrusion critical
        self.collector = (IdentCollector(registry, face, settings, camera_id, node_id)
                          if registry is not None else None)
        self._ident_threads: list[threading.Thread] = []
        self._ident_err = ErrorThrottle()  # identitas opsional: gagal = terisolasi, absensi tetap jalan

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
                    self._emit_due(time.monotonic())
                    self._expire(time.monotonic())
                    self._ident_step(time.monotonic(), idle=True)
                    continue
                self.frames += 1
                if frame.data is None:
                    continue
                moving = self.motion_gate is None or self.motion_gate.update(frame.data, frame.ts)
                if not moving and not self._faces_shown and not (
                        self.collector is not None and self.collector.registry.active(frame.ts)):
                    self.motion_skipped += 1
                    self._tracker.update([], frame.ts)
                    if self._tracker.lost_ids:
                        self._publish([])
                    self._emit_due(frame.ts)
                    self._expire(frame.ts)
                    self._ident_step(frame.ts, idle=True)
                    continue
                self._process(frame)
        except Exception:
            if not self.stop_event.is_set():
                log.exception("camera %s: face worker died", self.camera_id)
        finally:
            self._ident_step(time.monotonic(), flush=True)  # worker berhenti: kirim hasil sebagian
            self._pending_events.put(None)
            finalizer.join()
            self.join_ident_threads(5.0)

    def join_ident_threads(self, timeout: float = 5.0) -> None:
        """Join thread pengirim hasil identitas yang belum selesai (maks total `timeout` dtk)."""
        deadline = time.monotonic() + timeout
        for th in self._ident_threads:
            th.join(timeout=max(0.0, deadline - time.monotonic()))
        self._ident_threads = [th for th in self._ident_threads if th.is_alive()]

    def _ident_step(self, now: float, idle: bool = False, flush: bool = False) -> None:
        """Drain hasil identitas dan kirim lewat thread pendek per pesan (loop frame tak menunggu)."""
        if self.collector is None:
            return
        try:
            if idle:
                self.collector.registry.prune(now)
            for msg in (self.collector.flush() if flush else self.collector.drain(now)):
                th = threading.Thread(target=self._ship_ident, args=(msg,), daemon=True,
                                      name=f"ident-ship-{self.camera_id}")
                self._ident_threads.append(th)
                th.start()
        except Exception:
            self._ident_err.log(log, "camera %s: identity step failed (isolated)", self.camera_id)

    def _ship_ident(self, msg: dict) -> None:
        """Unggah crop (bila ada) lalu publish pesan identitas; kegagalan unggah tidak menahan pesan."""
        crop = msg.pop("_crop", None)
        msg["crop_path"] = None
        if crop and self.recorder is not None:
            try:
                msg["crop_path"] = self.recorder.upload_bytes(crop, "crop", timeout=3.0, retries=1)
            except Exception:
                log.warning("camera %s: ident crop upload failed", self.camera_id, exc_info=True)
        self.transport.publish_face(msg)

    def stop(self) -> None:
        """Stop consuming frames and close capture without waiting for inference."""
        self.stop_event.set()
        if self.source is not None:
            self.source.close()

    def pending(self) -> int:
        """Jumlah event wajah yang menunggu finalisasi media (heartbeat: antrean face)."""
        return self._pending_events.qsize()

    @staticmethod
    def _empty_funnel() -> dict:
        """Create a fresh heartbeat window without sharing mutable counters."""
        return {"faces": 0, "rejects": dict.fromkeys(("zone", "small", "score", "yaw", "blur"), 0),
                "tracks_emitted": 0, "tracks_silent": 0, "_ttfg": []}

    def take_funnel(self) -> dict:
        """Return the completed heartbeat window, resetting counters by swapping dictionaries."""
        # ponytail: a one-count cross-thread skew is acceptable; swap the dict without a lock.
        counts, self._funnel = self._funnel, self._empty_funnel()
        return {**{key: value for key, value in counts.items() if key != "_ttfg"},
                "ttfg_median_s": round(median(counts["_ttfg"]), 2) if counts["_ttfg"] else None}

    def _process(self, frame) -> None:
        h, w = frame.data.shape[:2]
        self._last_frame_ts = frame.ts
        try:
            faces = self.face.detect_faces(frame.data)
        except Exception:
            log.warning("camera %s: face detect failed", self.camera_id, exc_info=True)
            faces = []
        dets = [Detection(bbox=(f.bbox[0] / w, f.bbox[1] / h, f.bbox[2] / w, f.bbox[3] / h),
                          conf=f.score) for f in faces]
        ident_labels: dict[int, str] = {}  # label overlay wajah di kepala orang (bukan status zona)
        if self.collector is not None and frame.data is not None:
            try:
                ident_labels = self.collector.observe(faces, frame.data, w, h, frame.ts)
            except Exception:
                self._ident_err.log(log, "camera %s: identity observe failed (isolated)",
                                    self.camera_id)
        by_bbox = {d.bbox: f for d, f in zip(dets, faces)}
        tracks = self._tracker.update(dets, frame.ts)
        unified = self.settings.attendance_mode == "unified"
        boxes, passed = [], []
        for tr in tracks:
            f = by_bbox.get(tr.bbox)
            if f is None:
                continue  # retained track without detection: no stale face overlay
            ident_label = ident_labels.get(id(f))
            if not self.zones:
                # worker identitas-saja (tanpa zona attendance): hanya wajah di kepala orang yang digambar
                if ident_label is not None:
                    boxes.append({"id": tr.id, "bbox_norm": [round(v, 4) for v in tr.bbox],
                                  "label": ident_label})
                continue
            self._funnel["faces"] += 1
            aligned, blur = None, 0.0
            if unified:
                code, zone = self._gate_unified(f, w, h)
                if code is None:
                    try:
                        aligned = self.face.align(frame.data, f.kps)
                        blur = blur_score(aligned)  # hanya untuk peringkat, bukan gerbang
                    except Exception:
                        log.warning("camera %s: face align failed", self.camera_id, exc_info=True)
                        code = "blur"
            else:
                code, zone = gate_code(f, w, h, self.zones, self.settings)
                if code is None:
                    try:
                        aligned = self.face.align(frame.data, f.kps)
                        if blur_score(aligned) < self.settings.blur_min:
                            code = "blur"
                    except Exception:
                        log.warning("camera %s: face align failed", self.camera_id, exc_info=True)
                        code = "blur"
            if code != "zone":
                self._in_zone.setdefault(tr.id, frame.ts)
            if code is not None:
                # `.get`: kode `pitch` (khusus unified) hanya muncul di kamus bila benar-benar terjadi
                self._funnel["rejects"][code] = self._funnel["rejects"].get(code, 0) + 1
            q = quality(f.score, f.bbox[2] - f.bbox[0], yaw_ratio(f.kps))
            boxes.append({"id": tr.id, "bbox_norm": [round(v, 4) for v in tr.bbox],
                          "label": ident_label or code or f"{q:.2f}"})
            if code is None:
                passed.append((tr.id, f, zone, aligned, q, blur))
        self._publish(boxes)  # overlay before ArcFace embedding and uploads
        for tid, f, zone, aligned, q, blur in passed:
            if unified:
                self._accumulate_unified(tid, f, zone, aligned, q, blur, frame)
            else:
                self._accumulate(tid, f, zone, aligned, q, frame)
        if unified:
            self._emit_due(frame.ts)
        self._expire(frame.ts)
        self._ident_step(frame.ts)

    def _gate_unified(self, f, w: int, h: int) -> tuple[str | None, dict | None]:
        """Gerbang absensi unified: zona, lebar identitas, skor, yaw, pitch — tanpa blur absolut."""
        code, zone = gate_code(f, w, h, self.zones, self._unified_settings)
        if code is None and pitch_dev(f.kps) > self._unified_settings.ident.max_pitch:
            code = "pitch"
        return code, zone

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
        if not st.vectors:
            self._funnel["_ttfg"].append(frame.ts - self._in_zone[tid])
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

    def _accumulate_unified(self, tid, f, zone, aligned, q, blur, frame) -> None:
        """Kandidat unified: simpan K terbaik berperingkat `skor × ketajaman`; embed hanya bila mengalahkan."""
        st = self._states.setdefault(tid, _TrackState(zone=zone))
        if st.done:
            return  # track tetap hidup sesudah kirim: tidak boleh event kedua
        st.unified = True
        st.last_cand_ts = frame.ts  # tiap frame lolos gerbang, juga yang tak mengalahkan K terbaik
        keeper = st.keeper
        if keeper is None:
            keeper = st.keeper = BestK(self.settings.ident.best_k)
        if q > st.best_q:
            st.best_q = q
            st.best = {"frame": frame.data, "bbox": f.bbox, "ts": frame.ts,
                       "stats": {"width_px": round(f.bbox[2] - f.bbox[0]),
                                 "det_score": round(f.score, 3),
                                 "yaw": round(yaw_ratio(f.kps), 3),
                                 "blur": round(blur, 1)}}
        rank = f.score * blur
        if not keeper.beats(rank):
            return  # tidak mengalahkan K terbaik: tanpa embed berulang
        try:
            vec = self.face.embed(aligned)
        except Exception:
            log.warning("camera %s: face embed failed", self.camera_id, exc_info=True)
            return
        if vec is None:
            return
        if not len(keeper):
            self._funnel["_ttfg"].append(frame.ts - self._in_zone.get(tid, st.first_ts))
        keeper.add(rank, q, vec)
        if st.first_ts is None:
            st.first_ts = frame.ts  # jendela mulai dari vektor pertama; embed gagal tidak memulai jendela

    def _emit_due(self, now: float) -> None:
        """Kirim track unified yang jendelanya habis atau yang kandidatnya sudah berhenti (orang pergi).

        Track tetap hidup sesudah kirim (`done`), jadi maksimum sekali; track tanpa vektor tidak dikirim.
        """
        for tid, st in list(self._states.items()):
            if not st.unified or st.done or st.first_ts is None:
                continue
            window_over = now - st.first_ts >= self.settings.attendance_window_s
            gone = now - (st.last_cand_ts or st.first_ts) >= UNIFIED_GONE_S
            if window_over or gone:
                st.emit_ts = now
                self._emit(tid, st)

    def _expire(self, now: float | None = None) -> None:
        """Emit expired tracks with at least one good frame, exactly once."""
        for tid in self._tracker.lost_ids:
            st = self._states.pop(tid, None)
            if st is not None and not st.done and (st.keeper if st.unified else st.vectors):
                st.emit_ts = now if now is not None else self._last_frame_ts
                self._emit(tid, st)
            if tid in self._in_zone and (st is None or not st.vectors):
                self._funnel["tracks_silent"] += 1
            self._in_zone.pop(tid, None)

    def _emit(self, tid: int, st: _TrackState) -> None:
        st.done = True
        self._funnel["tracks_emitted"] += 1
        if st.unified:
            # `_finalize_event` membaca vectors/weights untuk agregat: isi dari K terbaik
            st.vectors = [v for _, _, v in st.keeper.items]
            st.weights = [q for _, q, _ in st.keeper.items]
            st.zone_start_ts = self._in_zone.get(tid, st.first_ts)  # diambil sebelum `_expire` pop
        best, st.best = st.best, None
        if self.recorder is not None and (self._media_pending.is_set() or
                                          self._media_busy.is_set()):
            # A burst must not queue serial media waits; later faces keep metadata.
            self._finalize_event(tid, st, best, allow_media=False)
        else:
            if self.recorder is not None:
                self._media_pending.set()
            self._pending_events.put((tid, st, best))

    def _finalize_events(self) -> None:
        """Publish queued events without holding frame reads or overlay updates."""
        while (item := self._pending_events.get()) is not None:
            try:
                self._finalize_event(*item)
            except Exception:
                log.exception("camera %s: face event finalization failed", self.camera_id)
            finally:
                if self.recorder is not None:
                    self._media_pending.clear()

    def _finalize_event(self, tid: int, st: _TrackState, best: dict,
                        allow_media: bool = True) -> None:
        from .node import _iso  # lazy import: node imports this worker in Task 6
        frame, bbox, ts = best["frame"], best["bbox"], best["ts"]
        h, w = frame.shape[:2]
        x1, y1, x2, y2 = bbox
        crop_path = snapshot_path = face_bbox = None
        if self.recorder is not None:
            cx1, cy1, cx2, cy2 = crop_box(bbox, w, h)
            face_bbox = [x1 - cx1, y1 - cy1, x2 - cx1, y2 - cy1]
            if allow_media and not self.stop_event.is_set() and not self._media_busy.is_set():
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
        payload = {
            "track_id": tid,
            "direction": st.zone.get("direction"),
            "bbox_norm": [x1 / w, y1 / h, x2 / w, y2 / h],
            "embedding": aggregate(st.vectors, st.weights),
            "face_quality": round(st.best_q, 3),
            "face_bbox": face_bbox,
            "crop_path": crop_path,
            "face_stats": {**best["stats"], "frames": len(st.vectors)},
        }
        if st.unified:
            payload["policy"] = "unified"
            payload["face_stats"]["collect_s"] = round(max(0.0, st.emit_ts - st.first_ts), 2)
            payload["face_stats"]["zone_s"] = round(max(0.0, st.emit_ts - st.zone_start_ts), 2)
        ev = {
            "event_id": str(uuid.uuid4()),
            "type": "attendance",
            "node_id": self.node_id,
            "camera_id": self.camera_id,
            "zone_id": st.zone["id"],
            "severity": "info",
            "ts_event": _iso(ts),
            "payload": payload,
            "dedup_key": f"{self.camera_id}:attendance:face{tid}:{int(ts // DEDUP_BUCKET_S)}",
            "snapshot_path": snapshot_path,
            "clip_path": None,
        }
        self.events.append(ev)
        if len(self.events) > EVENT_HISTORY_MAX:
            del self.events[:-EVENT_HISTORY_MAX]
        self.transport.publish_event(ev)
