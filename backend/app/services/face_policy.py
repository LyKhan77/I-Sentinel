"""Kebijakan pengenalan wajah dari baris `detector_setting` (id=1); fallback ke `Settings`.

Modul ini hanya mengimpor `core.config` dan model (tanpa `app.services.face`) supaya
`face.py` bisa mengimpornya tanpa siklus impor.
"""
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.detector_setting import DetectorSetting


@dataclass(frozen=True)
class FacePolicy:
    """Ambang kecocokan dan margin top-1/top-2 yang berlaku untuk satu keputusan."""

    match_threshold: float
    match_margin: float


def from_settings() -> FacePolicy:
    """Nilai env sebagai cadangan saat baris `detector_setting` belum ada."""
    return FacePolicy(settings.face_match_threshold, settings.face_id_margin)


def load(db: Session) -> FacePolicy:
    """Baris id=1 bila ada, selain itu `from_settings()`.

    Sengaja tidak di-cache: perubahan nilai di UI harus berlaku pada event berikutnya.
    """
    row = db.get(DetectorSetting, 1)
    if row is None:
        return from_settings()
    return FacePolicy(row.face_match_threshold, row.face_match_margin)
