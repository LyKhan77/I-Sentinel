"""Face identity untuk intrusion critical: registry person, asosiasi wajah, kolektor embedding.

Dipakai FaceGateWorker (main stream) bersama CameraWorker (substream) lewat IntrusionRegistry
bersama. Tanpa dependensi CUDA; cv2 hanya diimpor di dalam jpeg_crop.
Spec: docs/superpowers/specs/2026-10-08-intrusion-face-id-design.md §5.2.
"""
from __future__ import annotations

import threading
import time
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
BEST_K = 5             # embedding terbaik (berdasar kualitas) yang dipertahankan per orang
UPDATE_EVERY_S = 10.0   # jeda minimum antar-pembaruan identitas untuk orang yang masih di zona
MAX_TRACK_S = 90.0     # berhenti mengumpulkan sekian detik setelah event
MAX_UPDATES = 6        # pembaruan maksimum per event sesudah hasil pertama


class ErrorThrottle:
    """Catat exception di dalam blok `except` paling sering sekali per `every` dtk.

    Jalur identitas bersifat opsional dan berjalan per frame: kegagalannya harus terisolasi dan
    tidak boleh membanjiri log.
    """

    def __init__(self, every: float = 60.0):
        self.every = every
        self._last = float("-inf")

    def log(self, logger, msg: str, *args) -> None:
        now = time.monotonic()
        if now - self._last >= self.every:
            self._last = now
            logger.exception(msg, *args)


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
        # kunci yang hasilnya sudah dikirim: track yang masih berdiam di zona tidak dikumpulkan lagi
        # ponytail: bertambah satu pasang int per event; kosong lagi saat kamera restart (registry baru)
        self._finished: set[tuple[int, int]] = set()

    def touch(self, zone_id: int, track_id: int, bbox: tuple, ts: float) -> None:
        with self._lock:
            if (zone_id, track_id) in self._finished:
                return
            ent = self._entries.get((zone_id, track_id))
            if ent is None:
                self._entries[(zone_id, track_id)] = PersonEntry(zone_id, track_id, tuple(bbox), ts)
            else:
                ent.bbox = tuple(bbox)
                ent.seen_ts = ts

    def bind(self, zone_id: int, track_id: int, event_id: str, ts: float) -> None:
        with self._lock:
            if (zone_id, track_id) in self._finished:
                return
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
            self._finished.add((zone_id, track_id))


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
    kept: list = field(default_factory=list)  # (kualitas, vektor): BEST_K terbaik, bukan K pertama
    crop_rank: float = -1.0
    crop: bytes | None = None
    rejects: dict = field(default_factory=lambda: dict.fromkeys(
        ("small", "score", "yaw", "pitch", "blur", "quality"), 0))
    faces: int = 0
    sent: int = 0            # pesan yang sudah dikirim (seq berikutnya)
    last_sent: float = 0.0
    dirty: bool = False      # K terbaik berubah sejak pesan terakhir
    crop_dirty: bool = False


class IdentCollector:
    """Kumpulkan embedding terbaik + kandidat crop per entri terikat; satu pesan per event.

    Frame awal biasanya terburuk (orang masih jauh atau menunduk), jadi hasil pertama dikirim di akhir
    jendela (`IDENT_WINDOW_S` sesudah event) atau saat orang pergi. Titik terbaik sering datang
    belakangan, jadi pengumpulan berlanjut selama orang di zona (maks `MAX_TRACK_S`) dan pembaruan
    dikirim bila K terbaik berubah (jeda `UPDATE_EVERY_S`, maks `MAX_UPDATES`); API tidak menurunkan hasil.
    """

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
                now: float) -> dict[int, str]:
        """Proses wajah frame ini; kembalikan {id(wajah): label overlay} untuk wajah di kepala orang."""
        labels: dict[int, str] = {}
        entries = [e for e in self.registry.entries() if now - e.seen_ts <= REGISTRY_TTL_S]
        for f in faces:
            cx_norm = (f.bbox[0] + f.bbox[2]) / 2.0 / frame_w
            cy_norm = (f.bbox[1] + f.bbox[3]) / 2.0 / frame_h
            ent = associate((cx_norm, cy_norm), entries)
            if ent is None:
                continue
            st = self._states.setdefault((ent.zone_id, ent.track_id), _IdentState())
            st.faces += 1
            labels[id(f)] = self._reject_or_keep(f, ent, st, frame_data, frame_w, frame_h)
        return labels

    def _reject_or_keep(self, f: FaceDet, ent: PersonEntry, st: _IdentState,
                        frame_data, frame_w: int, frame_h: int) -> str:
        """Gerbang kualitas untuk embedding + kandidat crop (bebas dari hasil gerbang).

        Mengembalikan label overlay: kode penolakan, atau kualitas ("0.62") bila lolos gerbang.
        """
        width_px = f.bbox[2] - f.bbox[0]
        yaw = yaw_ratio(f.kps)
        pitch = pitch_dev(f.kps)
        q = quality(f.score, width_px, yaw)
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
            code = "pitch" if pitch > MAX_PITCH else "quality" if q < IDENT_MIN_QUALITY else None
        if code is not None:
            st.rejects[code] = st.rejects.get(code, 0) + 1  # kode tak terduga (mis. "zone") tetap dihitung
        if f.score >= MIN_CROP_SCORE:
            # kandidat terbaik: besar, yakin, dan paling frontal (bukan sekadar yang paling lebar)
            rank = width_px * f.score * max(0.0, 1.0 - yaw) * max(0.0, 1.0 - pitch)
            if rank > st.crop_rank:
                box = crop_box(f.bbox, frame_w, frame_h)
                data = self.encode(frame_data, box)
                if data is not None:
                    st.crop_rank = rank
                    st.crop = data
                    st.crop_dirty = True
        label = code or f"{q:.2f}"
        if code is not None:
            return label
        if len(st.kept) >= BEST_K and q <= min(k[0] for k in st.kept):
            return label  # tidak mengalahkan K terbaik: tanpa embed berulang
        try:
            vec = self.face.embed(aligned)
        except Exception:
            return label
        if vec is None:
            return label
        st.kept.append((q, vec))
        if len(st.kept) > BEST_K:
            st.kept.remove(min(st.kept, key=lambda k: k[0]))
        st.dirty = True
        return label

    def _message(self, ent: PersonEntry, st: _IdentState, now: float) -> dict:
        qualities = [q for q, _ in st.kept]
        msg = {
            "event_id": ent.event_id,
            "camera_id": self.camera_id,
            "node_id": self.node_id,
            "track_id": ent.track_id,
            "seq": st.sent,
            "embedding": aggregate([v for _, v in st.kept], qualities) if st.kept else None,
            "quality": round(max(qualities), 3) if st.kept else None,
            "crop_path": None,
            "stats": {"faces": st.faces, "rejects": dict(st.rejects), "frames_used": len(st.kept)},
            "_crop": st.crop if (st.sent == 0 or st.crop_dirty) else None,
        }
        st.sent += 1
        st.last_sent = now
        st.dirty = False
        st.crop_dirty = False
        return msg

    def drain(self, now: float) -> list[dict]:
        """Hasil pertama di akhir jendela (atau saat orang pergi), lalu pembaruan bila K terbaik membaik.

        Entri basi yang belum terikat dibuang tanpa pesan. Entri dilepas saat orang pergi, melewati
        `MAX_TRACK_S`, atau setelah `MAX_UPDATES` pembaruan.
        """
        self.registry.prune(now)
        entries = self.registry.entries()
        live = {(e.zone_id, e.track_id) for e in entries}
        self._states = {k: s for k, s in self._states.items() if k in live}  # orang yang sudah pergi
        out: list[dict] = []
        for ent in entries:
            if ent.event_id is None:
                continue
            key = (ent.zone_id, ent.track_id)
            st = self._states.setdefault(key, _IdentState())
            gone = now - ent.seen_ts > REGISTRY_TTL_S
            age = now - (ent.bound_ts or now)
            if st.sent == 0:
                if age < IDENT_WINDOW_S and not gone:
                    continue
                out.append(self._message(ent, st, now))
            else:
                due = st.dirty and now - st.last_sent >= UPDATE_EVERY_S and st.sent <= MAX_UPDATES
                if not (due or gone or age >= MAX_TRACK_S):
                    continue
                if st.dirty and st.sent <= MAX_UPDATES:
                    out.append(self._message(ent, st, now))
            if gone or age >= MAX_TRACK_S or st.sent > MAX_UPDATES:
                self._states.pop(key, None)
                self.registry.release(*key)
        return out

    def flush(self, now: float = 0.0) -> list[dict]:
        """Worker berhenti: kirim hasil yang belum terkirim (atau pembaruan tertunda) dan lepas semua."""
        out: list[dict] = []
        for ent in self.registry.entries():
            if ent.event_id is None:
                continue
            key = (ent.zone_id, ent.track_id)
            st = self._states.pop(key, _IdentState())
            if st.sent == 0 or st.dirty:
                out.append(self._message(ent, st, now))
            self.registry.release(*key)
        self._states.clear()
        return out
