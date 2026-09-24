"""Face service tests — CPU only, no insightface/numpy needed.

Vektor dummy 4-dim (buffalo_l = 512-d di produksi; kode tidak boleh hardcode panjang).
"""
import math

import pytest

from app.core.config import settings
from app.models.employee import Employee
from app.models.face_embedding import FaceEmbedding
from app.services import face
from app.services.face import (
    FaceEngine,
    FaceGallery,
    FaceResult,
    MatchResult,
    cosine,
    enroll_embedding,
    match_crop,
    refresh_gallery,
)


@pytest.fixture(autouse=True)
def _fresh_gallery(monkeypatch):
    """Isolate module-level gallery singleton antar test."""
    monkeypatch.setattr(face, "gallery", FaceGallery())


def _unit(v):
    n = math.sqrt(sum(x * x for x in v))
    return [x / n for x in v]


def _employee(db, code="E1"):
    e = Employee(name="Budi", employee_code=code)
    db.add(e)
    db.commit()
    db.refresh(e)
    return e


def _fake_embed(monkeypatch, *results):
    """monkeypatch FaceEngine.embed → hasil tetap."""
    monkeypatch.setattr(FaceEngine, "embed", lambda self, path: list(results))


# --- (a) cosine ---

def test_cosine_dot_same_vector():
    assert cosine([1.0, 0.0, 0.0, 0.0], [1.0, 0.0, 0.0, 0.0]) == pytest.approx(1.0)

def test_cosine_orthogonal_is_zero():
    assert cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)

def test_cosine_ignores_magnitude():
    assert cosine([2.0, 0.0, 0.0, 0.0], [5.0, 0.0, 0.0, 0.0]) == pytest.approx(1.0)

def test_cosine_zero_norm_guard():
    assert cosine([0.0, 0.0], [1.0, 0.0]) == 0.0


def test_cosine_length_mismatch_raises():
    with pytest.raises(ValueError, match="length mismatch"):
        cosine([1.0, 0.0], [1.0, 0.0, 0.0])


# --- (b) gallery.match exact vector ---

def test_gallery_match_exact(db):
    e = _employee(db)
    v = _unit([1.0, 0.0, 0.0, 0.0])
    db.add(FaceEmbedding(employee_id=e.id, vector=v, quality=0.9))
    db.commit()

    g = FaceGallery()
    g.load(db)

    m = g.match(v)
    assert m is not None
    assert m[0] == e.id
    assert m[1] == pytest.approx(1.0)
    assert g.size() == 1


# --- (c) orthogonal vector → None ---

def test_gallery_match_orthogonal_below_threshold(db):
    e = _employee(db)
    db.add(FaceEmbedding(employee_id=e.id, vector=[1.0, 0.0, 0.0, 0.0], quality=0.9))
    db.commit()

    g = FaceGallery()
    g.load(db)

    assert g.match([0.0, 1.0, 0.0, 0.0]) is None


# --- (d) threshold naik → match ditolak ---

def test_gallery_match_rejected_when_threshold_raised(db, monkeypatch):
    e = _employee(db)
    db.add(FaceEmbedding(employee_id=e.id, vector=[1.0, 0.0, 0.0, 0.0], quality=0.9))
    db.commit()

    g = FaceGallery()
    g.load(db)
    query = _unit([1.0, 1.0, 0.0, 0.0])  # cos ~0.707

    assert g.match(query) is not None

    monkeypatch.setattr(settings, "face_match_threshold", 0.99)
    assert g.match(query) is None


# --- (e) engine unavailable ---

def test_engine_unavailable_returns_not_configured(db, monkeypatch):
    def _boom(self):
        raise RuntimeError("insightface tidak terpasang")
    monkeypatch.setattr(FaceEngine, "_ensure_loaded", _boom)

    r = match_crop(db, "crop.jpg")
    assert r == MatchResult(None, None, None, "not_configured")


def test_engine_available_false_when_model_dir_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "face_model_dir", str(tmp_path))
    eng = FaceEngine()
    assert eng.available() is False


# --- (f) enroll_embedding ---

def test_enroll_saves_row(db, monkeypatch):
    e = _employee(db)
    v = _unit([1.0, 0.5, 0.0, 0.0])
    _fake_embed(monkeypatch, FaceResult(vector=v, det_score=0.9, bbox=[0.0, 0.0, 120.0, 120.0], quality=0.9))

    row = enroll_embedding(db, e.id, "faces/budi.jpg")

    assert row.employee_id == e.id
    assert row.vector == pytest.approx(v)
    assert row.quality == pytest.approx(0.9)
    assert row.source_image_path == "faces/budi.jpg"
    assert db.query(FaceEmbedding).count() == 1


def test_enroll_no_face_raises(db, monkeypatch):
    e = _employee(db)
    _fake_embed(monkeypatch)

    with pytest.raises(ValueError, match="no_face"):
        enroll_embedding(db, e.id, "faces/empty.jpg")
    assert db.query(FaceEmbedding).count() == 0


def test_enroll_low_quality_raises(db, monkeypatch):
    e = _employee(db)
    _fake_embed(monkeypatch, FaceResult(vector=[0.1] * 4, det_score=0.2, bbox=[0.0, 0.0, 30.0, 30.0], quality=0.1))

    with pytest.raises(ValueError, match="low_quality"):
        enroll_embedding(db, e.id, "faces/small.jpg")
    assert db.query(FaceEmbedding).count() == 0


def test_enroll_picks_largest_face(db, monkeypatch):
    e = _employee(db)
    small = FaceResult(vector=[1.0, 0.0, 0.0, 0.0], det_score=0.9, bbox=[0.0, 0.0, 40.0, 40.0], quality=0.9)
    big = FaceResult(vector=[0.0, 1.0, 0.0, 0.0], det_score=0.9, bbox=[0.0, 0.0, 120.0, 120.0], quality=0.9)
    _fake_embed(monkeypatch, small, big)  # besar bukan elemen pertama

    row = enroll_embedding(db, e.id, "faces/group.jpg")

    assert row.vector == pytest.approx([0.0, 1.0, 0.0, 0.0])


# --- (g) match_crop flows ---

def test_match_crop_matched(db, monkeypatch):
    e = _employee(db)
    v = _unit([1.0, 0.0, 0.0, 0.0])
    db.add(FaceEmbedding(employee_id=e.id, vector=v, quality=0.9))
    db.commit()
    refresh_gallery(db)

    _fake_embed(monkeypatch, FaceResult(vector=v, det_score=0.9, bbox=[0.0, 0.0, 200.0, 200.0], quality=0.9))

    r = match_crop(db, "crop.jpg")
    assert r.reason == "matched"
    assert r.employee_id == e.id
    assert r.score == pytest.approx(1.0)
    assert r.quality == pytest.approx(0.9)


def test_match_crop_no_face(db, monkeypatch):
    _fake_embed(monkeypatch)
    r = match_crop(db, "crop.jpg")
    assert r == MatchResult(None, None, None, "no_face")


def test_match_crop_low_quality(db, monkeypatch):
    _fake_embed(monkeypatch, FaceResult(vector=[0.1] * 4, det_score=0.3, bbox=[0.0, 0.0, 20.0, 20.0], quality=0.1))
    r = match_crop(db, "crop.jpg")
    assert r.reason == "low_quality"
    assert r.employee_id is None


def test_match_crop_no_match(db, monkeypatch):
    _fake_embed(monkeypatch, FaceResult(vector=[0.0, 1.0, 0.0, 0.0], det_score=0.9, bbox=[0.0, 0.0, 200.0, 200.0], quality=0.9))
    r = match_crop(db, "crop.jpg")
    assert r.reason == "no_match"
    assert r.employee_id is None
    assert r.score is None


# --- (h) gallery refresh dari db nyata ---

def test_refresh_gallery_loads_rows(db):
    e1 = _employee(db, "E1")
    e2 = _employee(db, "E2")
    db.add(FaceEmbedding(employee_id=e1.id, vector=[1.0, 0.0, 0.0, 0.0], quality=0.9))
    db.add(FaceEmbedding(employee_id=e1.id, vector=[0.0, 1.0, 0.0, 0.0], quality=0.8))
    db.add(FaceEmbedding(employee_id=e2.id, vector=[0.0, 0.0, 1.0, 0.0], quality=0.9))
    db.commit()

    refresh_gallery(db)

    assert face.gallery.size() == 2
    m = face.gallery.match([0.0, 0.0, 1.0, 0.0])
    assert m is not None and m[0] == e2.id
    m2 = face.gallery.match(_unit([0.0, 1.0, 1.0, 0.0]))  # cocok e1 (cos ~0.707) > e2 (0.707) tie → salah satu
    assert m2 is not None and m2[0] in (e1.id, e2.id)


# --- (i) remove ---

def test_gallery_remove(db):
    e = _employee(db)
    db.add(FaceEmbedding(employee_id=e.id, vector=[1.0, 0.0, 0.0, 0.0], quality=0.9))
    db.commit()
    refresh_gallery(db)
    assert face.gallery.size() == 1

    face.gallery.remove(e.id)

    assert face.gallery.size() == 0
    assert face.gallery.match([1.0, 0.0, 0.0, 0.0]) is None


# --- (j) karyawan nonaktif tidak di gallery ---

def test_refresh_gallery_skips_inactive_employees(db):
    a = _employee(db, "E1")
    b = _employee(db, "E2")
    b.active = False
    db.add(FaceEmbedding(employee_id=a.id, vector=[1.0, 0.0, 0.0, 0.0], quality=0.9))
    db.add(FaceEmbedding(employee_id=b.id, vector=[0.0, 1.0, 0.0, 0.0], quality=0.9))
    db.commit()

    refresh_gallery(db)

    assert face.gallery.size() == 1
    assert face.gallery.match([0.0, 1.0, 0.0, 0.0]) is None
    m = face.gallery.match([1.0, 0.0, 0.0, 0.0])
    assert m is not None and m[0] == a.id
