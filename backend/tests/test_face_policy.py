"""Kebijakan pengenalan wajah: baris `detector_setting` menimpa `Settings`, tanpa cache."""
import math

import pytest

from app.core.config import settings
from app.models.detector_setting import DetectorSetting
from app.services import face, face_policy
from app.services.face import FaceGallery, match_strict, match_vector
from app.services.face_policy import FacePolicy

GAL = [1.0, 0.0, 0.0, 0.0]
# cos ≈ 0.38 terhadap GAL: di atas ambang 0.35, di bawah 0.40
QUERY_038 = [0.38, 0.925, 0.0, 0.0]
# cos = 0.88 terhadap GAL: margin top-1/top-2 = 0.12
RUNNER_UP_088 = [0.88, math.sqrt(1 - 0.88 ** 2), 0.0, 0.0]


@pytest.fixture(autouse=True)
def _gallery(monkeypatch):
    monkeypatch.setattr(face, "gallery", FaceGallery())


def _row(db, **over):
    """Baris id=1 lengkap (semua kolom NOT NULL) supaya GET/PUT dan policy bisa membacanya."""
    values = {
        "default_ai_fps": 5.0, "default_confidence": 0.4, "motion_enabled": True,
        "motion_threshold": 25.0, "motion_min_area": 0.01, "motion_force_interval_s": 2.0,
        "face_min_width_px": 80.0, "face_min_det_score": 0.6, "face_max_yaw": 0.35,
        "face_blur_min": 120.0, "face_min_frames": 3,
        "face_match_threshold": 0.40, "face_match_margin": 0.15, "face_max_pitch": 0.30,
        "face_best_k": 5, "face_ident_min_width_px": 60.0, "face_ident_window_s": 8.0,
    }
    row = DetectorSetting(id=1, **{**values, **over})
    db.add(row)
    db.commit()
    return row


def _employees(db):
    from app.models.employee import Employee

    e1 = Employee(name="Budi", employee_code="E1")
    e2 = Employee(name="Siti", employee_code="E2")
    db.add(e1)
    db.add(e2)
    db.commit()
    db.refresh(e1)
    db.refresh(e2)
    return e1, e2


def test_load_without_row_uses_settings(db, monkeypatch):
    monkeypatch.setattr(settings, "face_match_threshold", 0.42)
    monkeypatch.setattr(settings, "face_id_margin", 0.12)

    assert face_policy.load(db) == FacePolicy(0.42, 0.12)


def test_load_row_overrides_settings(db, monkeypatch):
    monkeypatch.setattr(settings, "face_match_threshold", 0.42)
    monkeypatch.setattr(settings, "face_id_margin", 0.12)
    _row(db, face_match_threshold=0.55, face_match_margin=0.2)

    assert face_policy.load(db) == FacePolicy(0.55, 0.2)


def test_match_vector_uses_policy_threshold(db):
    e1, _e2 = _employees(db)
    face.gallery._by_employee = {e1.id: [GAL]}

    assert match_vector(QUERY_038, None, FacePolicy(0.35, 0.15)).reason == "matched"
    assert match_vector(QUERY_038, None, FacePolicy(0.40, 0.15)).reason == "no_match"


def test_match_strict_uses_policy_margin(db):
    e1, e2 = _employees(db)
    face.gallery._by_employee = {e1.id: [GAL], e2.id: [RUNNER_UP_088]}

    hit = match_strict(GAL, None, FacePolicy(0.40, 0.10))
    assert hit.reason == "matched" and hit.employee_id == e1.id and hit.margin == pytest.approx(0.12)

    ragu = match_strict(GAL, None, FacePolicy(0.40, 0.15))
    assert ragu.reason == "ambiguous" and ragu.employee_id is None


def test_policy_change_applies_without_restart(db):
    row = _row(db, face_match_threshold=0.40)
    assert face_policy.load(db).match_threshold == 0.40

    row.face_match_threshold = 0.99
    db.commit()

    assert face_policy.load(db).match_threshold == 0.99
