"""Enrollment API tests — face engine di-mock (tanpa insightface).

Dua lapis: API-level (patch face.enroll_embedding) dan integrasi (patch FaceEngine.embed
saja, enroll_embedding asli yang menyimpan row).
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.db import get_db
from app.core.config import settings
from app.models.employee import Employee
from app.models.face_embedding import FaceEmbedding
from app.services import face
from app.services.face import FaceEngine, FaceGallery, FaceResult
from tests.conftest import *  # noqa


@pytest.fixture
def client(db, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "admin_username", "admin")
    monkeypatch.setattr(settings, "admin_password", "boot123")
    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _fresh_gallery(monkeypatch):
    monkeypatch.setattr(face, "gallery", FaceGallery())


def _admin_headers(client):
    tok = client.post("/api/v1/auth/login", json={"username": "admin", "password": "boot123"}).json()["token"]
    return {"Authorization": f"Bearer {tok}"}


def _employee(db, code="E1"):
    e = Employee(name="Budi", employee_code=code)
    db.add(e)
    db.commit()
    db.refresh(e)
    return e


def _patch_enroll(monkeypatch):
    """enroll_embedding palsu tapi tetap menyimpan row nyata."""
    def _enroll(db, employee_id, image_path):
        row = FaceEmbedding(employee_id=employee_id, vector=[1.0, 0.0, 0.0, 0.0], quality=0.9,
                            source_image_path=image_path)
        db.add(row)
        db.commit()
        db.refresh(row)
        return row
    monkeypatch.setattr(face, "enroll_embedding", _enroll)


def _upload(client, h, eid, name="p.jpg"):
    return client.post(
        f"/api/v1/employees/{eid}/photos",
        files={"file": (name, b"fake-jpeg-bytes", "image/jpeg")},
        headers=h,
    )


# --- (a) upload 3 → active --------------------------------------------------

def test_upload_three_activates(client, db, monkeypatch):
    _patch_enroll(monkeypatch)
    e = _employee(db)
    h = _admin_headers(client)

    for i in range(3):
        r = _upload(client, h, e.id, f"{i}.jpg")
        assert r.status_code == 200
        assert r.json()["embedding_id"] is not None
        assert r.json()["quality"] == pytest.approx(0.9)

    s = client.get(f"/api/v1/employees/{e.id}/enrollment-status", headers=h).json()
    assert s == {"photos": 3, "active": True}

    listed = client.get(f"/api/v1/employees/{e.id}/photos", headers=h).json()
    assert len(listed) == 3
    assert listed[0]["path"].startswith(f"faces/{e.id}/")


# --- (b) upload ke-6 → 409 --------------------------------------------------

def test_upload_sixth_conflict(client, db, monkeypatch):
    _patch_enroll(monkeypatch)
    e = _employee(db)
    h = _admin_headers(client)

    for i in range(5):
        assert _upload(client, h, e.id, f"{i}.jpg").status_code == 200

    r = _upload(client, h, e.id, "6.jpg")
    assert r.status_code == 409
    assert "max 5 photos" in r.json()["detail"]


# --- (c) ValueError → 422 + file tidak tersisa ------------------------------

def test_upload_bad_quality_422_cleans_file(client, db, monkeypatch, tmp_path):
    def _boom(db_, employee_id, image_path):
        raise ValueError("low_quality")
    monkeypatch.setattr(face, "enroll_embedding", _boom)

    e = _employee(db)
    h = _admin_headers(client)

    r = _upload(client, h, e.id)
    assert r.status_code == 422
    assert "low_quality" in r.json()["detail"]
    d = tmp_path / "faces" / str(e.id)
    assert not any(d.glob("*"))  # tidak ada orphan
    assert db.query(FaceEmbedding).count() == 0


def test_upload_oversize_413_no_orphan(client, db, monkeypatch, tmp_path):
    _patch_enroll(monkeypatch)
    e = _employee(db)
    h = _admin_headers(client)

    big = b"x" * (10 * 1024 * 1024 + 1)
    r = client.post(
        f"/api/v1/employees/{e.id}/photos",
        files={"file": ("big.jpg", big, "image/jpeg")},
        headers=h,
    )
    assert r.status_code == 413
    assert "too large" in r.json()["detail"]
    assert db.query(FaceEmbedding).count() == 0
    d = tmp_path / "faces" / str(e.id)
    assert not d.exists() or not any(d.glob("*"))  # tidak ada orphan


def test_upload_unexpected_error_cleans_file(client, db, monkeypatch, tmp_path):
    def _boom(db_, employee_id, image_path):
        raise KeyError("kaboom")
    monkeypatch.setattr(face, "enroll_embedding", _boom)

    e = _employee(db)
    h = _admin_headers(client)
    with pytest.raises(KeyError):
        _upload(client, h, e.id)
    d = tmp_path / "faces" / str(e.id)
    assert not any(d.glob("*"))  # exception apa pun tetap bersihkan file


def test_upload_engine_unavailable_422(client, db, monkeypatch):
    def _boom(db_, employee_id, image_path):
        raise RuntimeError("insightface tidak terpasang")
    monkeypatch.setattr(face, "enroll_embedding", _boom)

    e = _employee(db)
    h = _admin_headers(client)
    r = _upload(client, h, e.id)
    assert r.status_code == 422
    assert r.json()["detail"] == "not_configured"


# --- (d) delete photo → row + file hilang -----------------------------------

def test_delete_photo_removes_row_and_file(client, db, monkeypatch, tmp_path):
    _patch_enroll(monkeypatch)
    e = _employee(db)
    h = _admin_headers(client)

    pid = _upload(client, h, e.id).json()["embedding_id"]
    rel = db.get(FaceEmbedding, pid).source_image_path
    assert (tmp_path / rel).is_file()

    r = client.delete(f"/api/v1/employees/{e.id}/photos/{pid}", headers=h)
    assert r.status_code == 200
    assert db.get(FaceEmbedding, pid) is None
    assert not (tmp_path / rel).exists()


# --- (e) purge biometrics → rows + folder hilang, employee tetap ------------

def test_purge_biometrics(client, db, monkeypatch, tmp_path):
    _patch_enroll(monkeypatch)
    e = _employee(db)
    h = _admin_headers(client)
    for i in range(3):
        _upload(client, h, e.id, f"{i}.jpg")

    r = client.delete(f"/api/v1/employees/{e.id}/biometrics", headers=h)
    assert r.status_code == 200
    assert r.json() == {"deleted": 3}
    assert db.query(FaceEmbedding).filter(FaceEmbedding.employee_id == e.id).count() == 0
    assert not (tmp_path / "faces" / str(e.id)).exists()
    assert db.get(Employee, e.id) is not None  # riwayat/employee tetap


# --- (f) 404 employee tidak ada ---------------------------------------------

def test_all_endpoints_404_unknown_employee(client, db, monkeypatch):
    _patch_enroll(monkeypatch)
    h = _admin_headers(client)
    assert _upload(client, h, 999).status_code == 404
    assert client.get("/api/v1/employees/999/photos", headers=h).status_code == 404
    assert client.get("/api/v1/employees/999/enrollment-status", headers=h).status_code == 404
    assert client.delete("/api/v1/employees/999/photos/1", headers=h).status_code == 404
    assert client.delete("/api/v1/employees/999/biometrics", headers=h).status_code == 404


# --- (g) refresh_gallery dipanggil ------------------------------------------

def test_refresh_gallery_called_on_mutations(client, db, monkeypatch):
    _patch_enroll(monkeypatch)
    e = _employee(db)
    h = _admin_headers(client)

    calls = []
    orig = face.refresh_gallery
    monkeypatch.setattr(face, "refresh_gallery", lambda d: calls.append(1) or orig(d))

    eid = _upload(client, h, e.id).json()["embedding_id"]
    assert len(calls) >= 1  # setelah enroll

    client.delete(f"/api/v1/employees/{e.id}/photos/{eid}", headers=h)
    assert len(calls) >= 2  # setelah delete photo

    _upload(client, h, e.id)
    client.delete(f"/api/v1/employees/{e.id}/biometrics", headers=h)
    assert len(calls) >= 4  # setelah purge


# --- integrasi: FaceEngine.embed asli, enroll_embedding asli ---------------

def test_integration_real_enroll(client, db, monkeypatch):
    e = _employee(db)
    h = _admin_headers(client)
    monkeypatch.setattr(
        FaceEngine, "embed",
        lambda self, path: [FaceResult(vector=[1.0, 0.0, 0.0, 0.0], det_score=0.9,
                                       bbox=[0.0, 0.0, 120.0, 120.0], quality=0.9)],
    )

    r = _upload(client, h, e.id)
    assert r.status_code == 200
    assert db.query(FaceEmbedding).count() == 1
    s = client.get(f"/api/v1/employees/{e.id}/enrollment-status", headers=h).json()
    assert s == {"photos": 1, "active": False}
    assert face.gallery.size() == 1  # gallery ikut ter-refresh


# --- R1: multi-upload batch + auto-crop + dup warn ---------------------------

def _jpg_bytes(w=320, h=240):
    from PIL import Image
    import io
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (200, 200, 200)).save(buf, format="JPEG")
    return buf.getvalue()


def test_batch_upload_multi_files(client, db, monkeypatch, tmp_path):
    """POST photos/batch 2 file ok + 1 no_face → hasil per file."""
    h = _admin_headers(client)
    e = _employee(db)
    monkeypatch.setattr(face, "enroll_embedding", _fake_enroll(tmp_path))
    files = [("files", (f"{i}.jpg", _jpg_bytes(), "image/jpeg")) for i in range(3)]
    calls = {"n": 0}

    def _embed(path):
        calls["n"] += 1
        if calls["n"] >= 3:
            return []  # foto ke-3: tidak ada wajah
        return [FaceResult(vector=[1.0, 0.0], det_score=0.9,
                           bbox=[10.0, 10.0, 100.0, 100.0], quality=0.9)]

    monkeypatch.setattr(face.engine, "embed", _embed)
    r = client.post(f"/api/v1/employees/{e.id}/photos/batch", files=files, headers=h)
    assert r.status_code == 200
    res = r.json()["results"]
    assert len(res) == 3
    assert [x["ok"] for x in res] == [True, True, False]
    assert res[2]["reason"] == "no_face"


def test_batch_upload_stores_cropped_face(client, db, monkeypatch, tmp_path):
    """source_image_path mengarah ke file crop hasil SCRFD, bukan foto mentah."""
    h = _admin_headers(client)
    e = _employee(db)
    monkeypatch.setattr(face.engine, "embed", _fake_embed_with_bbox())
    r = client.post(
        f"/api/v1/employees/{e.id}/photos/batch",
        files=[("files", ("p.jpg", _jpg_bytes(), "image/jpeg"))],
        headers=h,
    )
    assert r.status_code == 200
    listed = client.get(f"/api/v1/employees/{e.id}/photos", headers=h).json()
    p = tmp_path / listed[0]["path"]
    assert p.is_file()
    from PIL import Image
    img = Image.open(p)
    # crop lebih kecil dari foto sumber 320x240 (bbox + margin)
    assert img.size[0] < 320 and img.size[1] < 240


def test_batch_upload_duplicate_warns(client, db, monkeypatch, tmp_path):
    """Vektor mirip embedding employee lain → warn, bukan reject."""
    h = _admin_headers(client)
    e1 = _employee(db, "E1")
    e2 = _employee(db, "E2")
    db.add(FaceEmbedding(employee_id=e2.id, vector=[1.0, 0.0], quality=0.9))
    db.commit()
    monkeypatch.setattr(face, "gallery", FaceGallery())
    face.gallery.load(db)
    monkeypatch.setattr(face.engine, "embed",
                        lambda path: [FaceResult(vector=[1.0, 0.0], det_score=0.9,
                                                 bbox=[10.0, 10.0, 100.0, 100.0], quality=0.9)])
    r = client.post(
        f"/api/v1/employees/{e1.id}/photos/batch",
        files=[("files", ("p.jpg", _jpg_bytes(), "image/jpeg"))],
        headers=h,
    )
    assert r.status_code == 200
    res = r.json()["results"][0]
    assert res["ok"] is True
    assert res["duplicate_of"]["employee_id"] == e2.id
    assert res["duplicate_of"]["score"] >= 0.6


def _fake_enroll(tmp_path):
    def _enroll(db, employee_id, image_path):
        row = FaceEmbedding(employee_id=employee_id, vector=[1.0, 0.0, 0.0, 0.0], quality=0.9,
                            source_image_path=image_path)
        db.add(row)
        db.commit()
        db.refresh(row)
        return row
    return _enroll


def _fake_embed_with_bbox():
    def _embed(path):
        return [FaceResult(vector=[1.0, 0.0], det_score=0.9,
                           bbox=[10.0, 10.0, 100.0, 100.0], quality=0.9)]
    return _embed
