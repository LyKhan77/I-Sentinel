"""Pencocokan ketat intrusion: top2 + match_strict (ambang + margin top-1/top-2)."""
import pytest

from app.core.config import settings
from app.services import face
from app.services.face import FaceGallery, MatchResult, cosine, match_strict


@pytest.fixture(autouse=True)
def _gallery(monkeypatch):
    monkeypatch.setattr(face, "gallery", FaceGallery())


def _add(db, code, vectors):
    from app.models.employee import Employee
    from app.models.face_embedding import FaceEmbedding
    e = Employee(name="Budi", employee_code=code)
    db.add(e); db.flush()
    for v in vectors:
        db.add(FaceEmbedding(employee_id=e.id, vector=v, quality=0.9))
    db.commit(); db.refresh(e)
    face.gallery._by_employee[e.id] = [list(v) for v in vectors]
    return e


def test_top2_returns_two_distinct_employees_best_first():
    g = FaceGallery()
    g._by_employee = {1: [[1.0, 0.0]], 2: [[0.9397, 0.3420]]}  # cos(20°)≈0.9397
    top = g.top2([1.0, 0.0])
    assert [emp for emp, _ in top] == [1, 2]
    assert top[0][1] == pytest.approx(1.0)
    assert top[1][1] == pytest.approx(0.9397, rel=1e-3)


def test_top2_single_employee_no_runner_up_duplicate():
    g = FaceGallery()
    g._by_employee = {1: [[1.0, 0.0], [0.7071, 0.7071]]}  # dua vektor karyawan sama
    top = g.top2([1.0, 0.0])
    assert [emp for emp, _ in top] == [1]


def test_match_strict_matched_returns_employee_score_and_margin(db):
    _add(db, "E1", [[1.0, 0.0, 0.0, 0.0]])
    _add(db, "E2", [[0.0, 1.0, 0.0, 0.0]])
    res = match_strict([1.0, 0.0, 0.0, 0.0])
    assert res.reason == "matched" and res.employee_id is not None
    assert res.score == pytest.approx(1.0)
    assert res.margin == pytest.approx(1.0)  # top2 ortogonal → 0
    assert isinstance(res, MatchResult)


def test_match_strict_ambiguous_when_two_employees_are_close(db):
    _add(db, "E1", [[1.0, 0.0, 0.0, 0.0]])
    _add(db, "E2", [[0.995, 0.1, 0.0, 0.0]])  # cos ≈ 0.995 → margin kecil
    res = match_strict([1.0, 0.0, 0.0, 0.0])
    assert res.reason == "ambiguous" and res.employee_id is None
    assert res.margin is not None and res.margin < settings.face_id_margin


def test_match_strict_no_match_below_threshold(db):
    _add(db, "E1", [[1.0, 0.0, 0.0, 0.0]])
    res = match_strict([0.0, 1.0, 0.0, 0.0])
    assert res.reason == "no_match" and res.employee_id is None


def test_match_strict_low_quality_before_matching(db):
    _add(db, "E1", [[1.0, 0.0, 0.0, 0.0]])
    res = match_strict([1.0, 0.0, 0.0, 0.0], quality=settings.face_min_quality - 0.01)
    assert res.reason == "low_quality" and res.employee_id is None


def test_match_strict_single_employee_not_penalised_by_margin(db):
    # query 0.8/0.6 (norm 1.0) vs galeri [1,0] → top1 ≈ 0.8 ≥ 0.50; tanpa runner-up margin = top1 − 0
    _add(db, "E1", [[1.0, 0.0, 0.0, 0.0]])
    res = match_strict([0.8, 0.6, 0.0, 0.0])
    assert res.reason == "matched"
    assert res.margin == pytest.approx(0.8, rel=1e-3)  # top2 = 0.0 → margin = top1


def test_match_strict_empty_gallery_is_no_match():
    res = match_strict([1.0, 0.0, 0.0, 0.0])
    assert res.reason == "no_match" and res.margin is None
