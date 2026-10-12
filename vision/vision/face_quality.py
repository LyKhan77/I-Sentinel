"""Gerbang kualitas wajah attendance (R5b): fungsi murni, tanpa GPU.

Angka default dan dasarnya: spec 2026-09-23-attendance-face-first-design.md §5.2.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .analyzers.intrusion import point_in_polygon

ARCFACE_SIZE = 112.0
OUTLIER_COS = 0.5  # cosine di bawah ini dianggap embedding orang lain

# Parameter identitas intrusion critical (dulu konstanta modul `intrusion_face`); nilai awal
# dipakai saat sub-blok `face.ident` tidak ada di config push.
IDENT_MIN_WIDTH_PX = 60.0  # lebar wajah minimum untuk identitas (jarak sampai ±3 m); data: lebar bukan penentu skor
MAX_PITCH = 0.30           # deviasi pitch maksimum (menghadap bawah)
BEST_K = 5                 # embedding terbaik (berdasar kualitas) yang dipertahankan per orang
IDENT_WINDOW_S = 8.0       # kirim hasil setelah sekian detik terikat event meski min_frames belum tercapai


class BestK:
    """Simpan K kandidat terbaik berperingkat `rank`; dipakai bersama identitas intrusion dan absensi unified.

    `beats` memakai `>`: peringkat yang sama tidak mengalahkan yang sudah tersimpan, jadi frame
    bermutu setara tidak memicu embed berulang.
    """

    def __init__(self, k: int):
        self.k = k
        self._items: list[tuple[float, float, list[float]]] = []

    def beats(self, rank: float) -> bool:
        """True bila belum penuh atau `rank` lebih besar dari peringkat terendah yang tersimpan."""
        return len(self._items) < self.k or rank > min(item[0] for item in self._items)

    def add(self, rank: float, quality: float, vector: list[float]) -> None:
        """Simpan kandidat (rank, quality, vector); buang peringkat terendah bila melebihi K."""
        self._items.append((rank, quality, vector))
        if len(self._items) > self.k:
            self._items.remove(min(self._items, key=lambda item: item[0]))

    @property
    def items(self) -> list[tuple[float, float, list[float]]]:
        """Salinan daftar (rank, quality, vector) untuk dibaca pemanggil."""
        return list(self._items)

    def __len__(self) -> int:
        return len(self._items)


@dataclass(frozen=True)
class IdentSettings:
    """Kebijakan kolektor identitas dari sub-blok `face.ident` (config push)."""

    min_width_px: float = IDENT_MIN_WIDTH_PX
    max_pitch: float = MAX_PITCH
    best_k: int = BEST_K
    window_s: float = IDENT_WINDOW_S

    @classmethod
    def from_config(cls, ident: dict | None) -> IdentSettings:
        """Key yang hilang (backend lama) memakai nilai awal."""
        ident = ident or {}
        d = cls()
        return cls(
            min_width_px=float(ident.get("min_width_px", d.min_width_px)),
            max_pitch=float(ident.get("max_pitch", d.max_pitch)),
            best_k=int(ident.get("best_k", d.best_k)),
            window_s=float(ident.get("window_s", d.window_s)),
        )


@dataclass(frozen=True)
class FaceSettings:
    min_width_px: float = 80.0
    min_det_score: float = 0.6
    max_yaw: float = 0.35
    blur_min: float = 120.0
    min_frames: int = 3
    ident: IdentSettings = IdentSettings()
    # mode absensi tahap 2: "legacy" (gerbang lama) atau "unified" (gerbang identitas + jendela)
    attendance_mode: str = "legacy"
    attendance_window_s: float = 1.5

    @classmethod
    def from_config(cls, face: dict | None) -> FaceSettings:
        """Key `face` config push; key yang hilang (backend lama) memakai default."""
        face = face or {}
        d = cls()
        mode = str(face.get("attendance_mode", d.attendance_mode))
        return cls(
            min_width_px=float(face.get("min_width_px", d.min_width_px)),
            min_det_score=float(face.get("min_det_score", d.min_det_score)),
            max_yaw=float(face.get("max_yaw", d.max_yaw)),
            blur_min=float(face.get("blur_min", d.blur_min)),
            min_frames=int(face.get("min_frames", d.min_frames)),
            ident=IdentSettings.from_config(face.get("ident")),
            attendance_mode=mode if mode in ("legacy", "unified") else d.attendance_mode,
            attendance_window_s=float(face.get("attendance_window_s", d.attendance_window_s)),
        )


def yaw_ratio(kps) -> float:
    """|x_hidung − x_tengah_mata| ÷ jarak mata; 0 = frontal, ~0,35 ≈ yaw 30°."""
    le, re, nose = kps[0], kps[1], kps[2]
    eye_dist = float(np.hypot(float(re[0] - le[0]), float(re[1] - le[1])))
    if eye_dist <= 0.0:
        return 1.0
    return abs(float(nose[0]) - (float(le[0]) + float(re[0])) / 2.0) / eye_dist


def blur_score(aligned) -> float:
    """Variansi Laplacian crop ter-align; makin kecil makin buram."""
    import cv2
    gray = cv2.cvtColor(aligned, cv2.COLOR_BGR2GRAY) if aligned.ndim == 3 else aligned
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def quality(det_score: float, width_px: float, yaw: float) -> float:
    """Bobot embedding dari confidence, lebar wajah dan frontalitas."""
    return det_score * min(1.0, width_px / ARCFACE_SIZE) * max(0.0, 1.0 - yaw)


def zone_of(center_norm: tuple[float, float], zones: list[dict]) -> dict | None:
    """Zona pertama yang memuat tengah wajah, dengan koordinat ternormalisasi."""
    for z in zones:
        if point_in_polygon(center_norm, [tuple(p) for p in z["polygon"]]):
            return z
    return None


def gate_code(det, frame_w: int, frame_h: int, zones: list[dict],
              s: FaceSettings) -> tuple[str | None, dict | None]:
    """Kode gagal pertama (zone|small|score|yaw) + zona; blur dicek setelah align."""
    x1, y1, x2, y2 = det.bbox
    zone = zone_of(((x1 + x2) / 2.0 / frame_w, (y1 + y2) / 2.0 / frame_h), zones)
    if zone is None:
        return "zone", None
    if (x2 - x1) < s.min_width_px:
        return "small", zone
    if det.score < s.min_det_score:
        return "score", zone
    if yaw_ratio(det.kps) > s.max_yaw:
        return "yaw", zone
    return None, zone


def _unit(v: np.ndarray) -> np.ndarray | None:
    n = float(np.linalg.norm(v))
    return None if n == 0.0 else v / n


def aggregate(vectors: list[list[float]], weights: list[float]) -> list[float]:
    """Rata-rata berbobot kualitas, buang outlier (track tertukar), normalisasi ulang."""
    V = np.asarray(vectors, dtype=np.float64)
    w = np.asarray(weights, dtype=np.float64)
    best = [float(x) for x in V[int(np.argmax(w))]]
    mean = _unit((V * w[:, None]).sum(axis=0))
    if mean is None:
        return best
    keep = (V @ mean) >= OUTLIER_COS
    if not keep.any():
        return best
    out = _unit((V[keep] * w[keep, None]).sum(axis=0))
    return best if out is None else [float(x) for x in out]


def crop_box(bbox, frame_w: int, frame_h: int, pad: float = 0.30) -> tuple[int, int, int, int]:
    """Kotak wajah + padding, dipotong batas frame."""
    x1, y1, x2, y2 = bbox
    bw, bh = x2 - x1, y2 - y1
    return (max(0, int(x1 - bw * pad)), max(0, int(y1 - bh * pad)),
            min(frame_w, int(x2 + bw * pad)), min(frame_h, int(y2 + bh * pad)))
