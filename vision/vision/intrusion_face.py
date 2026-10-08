"""Face identity untuk intrusion critical: registry person, asosiasi wajah, kolektor embedding.

Dipakai FaceGateWorker (main stream) bersama CameraWorker (substream) lewat IntrusionRegistry
bersama. Tanpa dependensi CUDA; cv2 hanya diimpor di dalam jpeg_crop.
Spec: docs/superpowers/specs/2026-10-08-intrusion-face-id-design.md §5.2.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field

import numpy as np

from .analyzers.base import point_in_polygon
from .face import FaceDet
from .face_quality import (FaceSettings, aggregate, blur_score, crop_box, gate_code,
                           quality, yaw_ratio)

REGISTRY_TTL_S = 3.0   # sama dengan max_age_s tracker; motion gate bisa melewatkan frame saat orang diam
HEAD_FRAC = 0.40       # area kepala = 40% atas bbox person
HEAD_PAD = 0.10        # diperlebar 10% ke kiri/kanan/atas
IDENT_WINDOW_S = 8.0   # kirim hasil setelah sekian detik terikat event meski min_frames belum tercapai
MAX_PITCH = 0.30       # deviasi pitch maksimum (menghadap bawah)
IDENT_MIN_QUALITY = 0.5  # sama dengan face_min_quality API: frame yang pasti ditolak API tidak dihitung
MIN_CROP_SCORE = 0.5   # keyakinan SCRFD minimum untuk kandidat crop bukti manual


@dataclass
class PersonEntry:
    zone_id: int
    track_id: int
    bbox: tuple[float, float, float, float]
    seen_ts: float
    event_id: str | None = None
    bound_ts: float | None = None


class IntrusionRegistry:
    """Person track di zona critical ber-face_id; thread-safe (dipakai dua worker)."""

    _Entry = PersonEntry  # alias tes

    def __init__(self):
        self._lock = threading.Lock()
        self._entries: dict[tuple[int, int], PersonEntry] = {}

    def touch(self, zone_id: int, track_id: int, bbox: tuple, ts: float) -> None:
        with self._lock:
            ent = self._entries.get((zone_id, track_id))
            if ent is None:
                self._entries[(zone_id, track_id)] = PersonEntry(zone_id, track_id, tuple(bbox), ts)
            else:
                ent.bbox = tuple(bbox)
                ent.seen_ts = ts

    def bind(self, zone_id: int, track_id: int, event_id: str, ts: float) -> None:
        with self._lock:
            ent = self._entries.get((zone_id, track_id))
            if ent is None:
                ent = PersonEntry(zone_id, track_id, (0.0, 0.0, 0.0, 0.0), ts)
                self._entries[(zone_id, track_id)] = ent
            ent.event_id = event_id
            ent.bound_ts = ts

    def entries(self) -> list[PersonEntry]:
        with self._lock:
            return list(self._entries.values())

    def active(self, now: float) -> bool:
        with self._lock:
            return any(now - e.seen_ts <= REGISTRY_TTL_S for e in self._entries.values())

    def prune(self, now: float) -> None:
        with self._lock:
            self._entries = {k: e for k, e in self._entries.items()
                             if e.event_id is not None or now - e.seen_ts <= REGISTRY_TTL_S}

    def release(self, zone_id: int, track_id: int) -> None:
        with self._lock:
            self._entries.pop((zone_id, track_id), None)


def _head_region(bbox: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    """Area kepala: 40% atas bbox, diperlebar 10% ke kiri/kanan/atas (ternormalisasi)."""
    x1, y1, x2, y2 = bbox
    return (x1 - (x2 - x1) * HEAD_PAD, max(0.0, y1 - (y2 - y1) * HEAD_PAD),
            x2 + (x2 - x1) * HEAD_PAD, y1 + (y2 - y1) * HEAD_FRAC)


def associate(face_center: tuple[float, float],
              entries: list[PersonEntry]) -> PersonEntry | None:
    """Pusat wajah → entri person dengan area kepala memuatnya; yang terdekat menang."""
    best = None
    best_d = float("inf")
    for ent in entries:
        hx1, hy1, hx2, hy2 = _head_region(ent.bbox)
        if not (hx1 <= face_center[0] <= hx2 and hy1 <= face_center[1] <= hy2):
            continue
        d = (hx1 + hx2) / 2.0 - face_center[0], (hy1 + hy2) / 2.0 - face_center[1]
        dist = float(np.hypot(*d))
        if dist < best_d:
            best, best_d = ent, dist
    return best


def pitch_dev(kps: np.ndarray) -> float:
    """Deviasi pitch dari 5 landmark: 0 = frontal, naik saat menghadap bawah."""
    eye_y = (float(kps[0][1]) + float(kps[1][1])) / 2.0
    mouth_y = (float(kps[3][1]) + float(kps[4][1])) / 2.0
    nose_y = float(kps[2][1])
    denom = mouth_y - eye_y
    if denom <= 0.0:
        return 1.0
    return abs((nose_y - eye_y) / denom - 0.5)


def jpeg_crop(frame: np.ndarray, box: tuple[int, int, int, int]) -> bytes | None:
    """JPEG kualitas 90 dari region box; None bila encode gagal."""
    import cv2
    x1, y1, x2, y2 = box
    region = frame[y1:y2, x1:x2]
    if region.size == 0:
        return None
    ok, buf = cv2.imencode(".jpg", region, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
    return buf.tobytes() if ok else None


def _dummy_zone(zone_id: int) -> dict:
    """Zona satu frame penuh untuk gate_code: cek poligon selalu lolos, gerbang lain tetap jalan."""
    return {"id": zone_id, "polygon": [[0, 0], [1, 0], [1, 1], [0, 1]]}


@dataclass
class _IdentState:
    vectors: list = field(default_factory=list)
    weights: list = field(default_factory=list)
    best_quality: float = -1.0
    crop_rank: float = -1.0
    crop: bytes | None = None
    rejects: dict = field(default_factory=lambda: dict.fromkeys(
        ("small", "score", "yaw", "pitch", "blur", "quality"), 0))
    faces: int = 0


class IdentCollector:
    """Kumpulkan embedding + kandidat crop per entri terikat; kirim satu pesan per event."""

    def __init__(self, registry: IntrusionRegistry, face, settings: FaceSettings,
                 camera_id: int, node_id: str, encode=jpeg_crop):
        self.registry = registry
        self.face = face
        self.settings = settings
        self.camera_id = camera_id
        self.node_id = node_id
        self.encode = encode
        self._states: dict[tuple[int, int], _IdentState] = {}
        self.entries_seen: list[int] = []  # test hook

    def observe(self, faces: list[FaceDet], frame_data, frame_w: int, frame_h: int,
                now: float) -> None:
        entries = [e for e in self.registry.entries() if now - e.seen_ts <= REGISTRY_TTL_S]
        for f in faces:
            cx_norm = (f.bbox[0] + f.bbox[2]) / 2.0 / frame_w
            cy_norm = (f.bbox[1] + f.bbox[3]) / 2.0 / frame_h
            ent = associate((cx_norm, cy_norm), entries)
            if ent is None:
                continue
            st = self._states.setdefault((ent.zone_id, ent.track_id), _IdentState())
            st.faces += 1
            self._reject_or_keep(f, ent, st, frame_data, frame_w, frame_h)

    def _reject_or_keep(self, f: FaceDet, ent: PersonEntry, st: _IdentState,
                        frame_data, frame_w: int, frame_h: int) -> None:
        """Gerbang kualitas untuk embedding + kandidat crop (bebas dari hasil gerbang)."""
        code, _zone = gate_code(f, frame_w, frame_h, [_dummy_zone(ent.zone_id)], self.settings)
        aligned = None
        if code is None:
            try:
                aligned = self.face.align(frame_data, f.kps)
                if blur_score(aligned) < self.settings.blur_min:
                    code = "blur"
            except Exception:
                code = "blur"
        if code is None:
            code = ("pitch" if pitch_dev(f.kps) > MAX_PITCH
                    else "quality" if quality(f.score, f.bbox[2] - f.bbox[0], yaw_ratio(f.kps))
                    < IDENT_MIN_QUALITY else None)
        if code is not None:
            st.rejects[code] += 1
        width_px = f.bbox[2] - f.bbox[0]
        if f.score >= MIN_CROP_SCORE:
            rank = width_px * f.score
            if rank > st.crop_rank:
                box = crop_box(f.bbox, frame_w, frame_h)
                data = self.encode(frame_data, box)
                if data is not None:
                    st.crop_rank = rank
                    st.crop = data
        if code is not None:
            return
        try:
            vec = self.face.embed(aligned)
        except Exception:
            return
        if vec is None:
            return
        q = quality(f.score, width_px, yaw_ratio(f.kps))
        st.vectors.append(vec)
        st.weights.append(q)
        st.best_quality = max(st.best_quality, q)

    def drain(self, now: float) -> list[dict]:
        """Kirim pesan entri terikat yang siap; entri basi belum terikat dibuang tanpa pesan."""
        self.registry.prune(now)
        out: list[dict] = []
        for ent in self.registry.entries():
            key = (ent.zone_id, ent.track_id)
            if ent.event_id is None:
                continue
            st = self._states.get(key, _IdentState())
            ready = (len(st.vectors) >= self.settings.min_frames
                     or now - (ent.bound_ts or now) >= IDENT_WINDOW_S
                     or now - ent.seen_ts > REGISTRY_TTL_S)
            if not ready:
                continue
            self.registry.release(*key)
            self._states.pop(key, None)
            out.append({
                "event_id": ent.event_id,
                "camera_id": self.camera_id,
                "node_id": self.node_id,
                "track_id": ent.track_id,
                "embedding": aggregate(st.vectors, st.weights) if st.vectors else None,
                "quality": round(st.best_quality, 3) if st.vectors else None,
                "crop_path": None,
                "stats": {"faces": st.faces, "rejects": st.rejects,
                          "frames_used": len(st.vectors)},
                "_crop": st.crop,
            })
        return out
