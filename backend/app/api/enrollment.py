"""Face enrollment + biometrik PDP endpoints. Foto disimpan di {storage_root}/faces/{id}/."""
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from typing import List
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin
from app.core.config import settings
from app.core.db import get_db
from app.models.employee import Employee, MIN_PHOTOS
from app.models.face_embedding import FaceEmbedding
from app.services import face

router = APIRouter(prefix="/api/v1/employees", tags=["enrollment"])

MAX_PHOTOS = 5
MAX_FACE_UPLOAD = 10 * 1024 * 1024  # 10MB


def _employee(db: Session, employee_id: int) -> Employee:
    emp = db.get(Employee, employee_id)
    if not emp:
        raise HTTPException(404, "employee not found")
    return emp


def _faces_dir(employee_id: int) -> Path:
    return Path(settings.storage_root) / "faces" / str(employee_id)


@router.post("/{employee_id}/photos")
def upload_photo(
    employee_id: int,
    file: UploadFile = File(...),
    admin=Depends(require_admin),
    db: Session = Depends(get_db),
):
    _employee(db, employee_id)
    count = db.query(FaceEmbedding).filter(FaceEmbedding.employee_id == employee_id).count()
    if count >= MAX_PHOTOS:
        raise HTTPException(409, f"max {MAX_PHOTOS} photos")

    data = file.file.read(MAX_FACE_UPLOAD + 1)
    if len(data) > MAX_FACE_UPLOAD:
        raise HTTPException(413, "face photo too large")

    rel = f"faces/{employee_id}/{uuid.uuid4()}.jpg"
    abs_path = Path(settings.storage_root) / rel
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    abs_path.write_bytes(data)

    try:
        row = face.enroll_embedding(db, employee_id, str(abs_path))
    except ValueError as e:  # no_face / low_quality
        abs_path.unlink(missing_ok=True)
        raise HTTPException(422, str(e))
    except RuntimeError:  # engine tidak tersedia
        abs_path.unlink(missing_ok=True)
        raise HTTPException(422, "not_configured")
    except Exception:
        abs_path.unlink(missing_ok=True)
        raise

    row.source_image_path = rel  # simpan path relatif (disajikan via /api/v1/media)
    db.commit()
    db.refresh(row)
    face.refresh_gallery(db)
    return {"embedding_id": row.id, "quality": row.quality}


@router.post("/{employee_id}/photos/batch")
def upload_photos_batch(
    employee_id: int,
    files: List[UploadFile] = File(...),
    admin=Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Enrollment multi-foto: embed + auto-crop wajah + dup-warn per file.

    Hasil per file (tidak fatal): ok=True → tersimpan (crop saja, bukan foto
    mentah); ok=False → reason no_face|low_quality|too_large|max_photos.
    duplicate_of = warning wajah mirip employee lain (bukan reject).
    """
    _employee(db, employee_id)
    results = []
    for f in files:
        r = _enroll_one(db, employee_id, f)
        results.append(r)
    face.refresh_gallery(db)
    return {"results": results}


def _enroll_one(db, employee_id: int, f: UploadFile) -> dict:
    """Proses satu file batch → dict hasil. Database error = raise (caller 500)."""
    count = db.query(FaceEmbedding).filter(FaceEmbedding.employee_id == employee_id).count()
    if count >= MAX_PHOTOS:
        return {"ok": False, "reason": "max_photos"}

    data = f.file.read(MAX_FACE_UPLOAD + 1)
    if len(data) > MAX_FACE_UPLOAD:
        return {"ok": False, "reason": "too_large"}

    raw = Path(settings.storage_root) / f"faces/{employee_id}/{uuid.uuid4()}.jpg"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_bytes(data)
    try:
        faces = face.engine.embed(str(raw))
    except RuntimeError:
        raw.unlink(missing_ok=True)
        return {"ok": False, "reason": "not_configured"}
    except Exception:
        raw.unlink(missing_ok=True)
        raise
    if not faces:
        raw.unlink(missing_ok=True)
        return {"ok": False, "reason": "no_face"}

    best = face._best_face(faces)
    if best.quality < settings.face_min_quality:
        raw.unlink(missing_ok=True)
        return {"ok": False, "reason": "low_quality", "quality": best.quality}

    crop_abs = face.crop_face(str(raw), best.bbox)
    raw.unlink(missing_ok=True)  # foto mentah tidak dipertahankan
    if crop_abs is None:
        return {"ok": False, "reason": "no_face"}

    rel = str(Path(crop_abs).relative_to(settings.storage_root))
    row = face._save_embedding(db, employee_id, best, rel)
    dup = face.find_duplicate(best.vector, employee_id)
    return {
        "ok": True,
        "embedding_id": row.id,
        "quality": row.quality,
        "path": rel,
        "duplicate_of": ({"employee_id": dup[0], "score": round(dup[1], 3)} if dup else None),
    }


@router.get("/{employee_id}/photos")
def list_photos(employee_id: int, user=Depends(get_current_user), db: Session = Depends(get_db)):
    _employee(db, employee_id)
    rows = db.query(FaceEmbedding).filter(FaceEmbedding.employee_id == employee_id).all()
    return [
        {"id": r.id, "quality": r.quality, "created_at": r.created_at, "path": r.source_image_path}
        for r in rows
    ]


@router.get("/{employee_id}/enrollment-status")
def enrollment_status(employee_id: int, user=Depends(get_current_user), db: Session = Depends(get_db)):
    _employee(db, employee_id)
    n = db.query(FaceEmbedding).filter(FaceEmbedding.employee_id == employee_id).count()
    return {"photos": n, "active": n >= MIN_PHOTOS}


@router.delete("/{employee_id}/photos/{embedding_id}")
def delete_photo(
    employee_id: int,
    embedding_id: int,
    admin=Depends(require_admin),
    db: Session = Depends(get_db),
):
    _employee(db, employee_id)
    row = (
        db.query(FaceEmbedding)
        .filter(FaceEmbedding.id == embedding_id, FaceEmbedding.employee_id == employee_id)
        .first()
    )
    if not row:
        raise HTTPException(404, "embedding not found")
    if row.source_image_path:
        (Path(settings.storage_root) / row.source_image_path).unlink(missing_ok=True)
    db.delete(row)
    db.commit()
    face.refresh_gallery(db)
    return {"ok": True}


@router.delete("/{employee_id}/biometrics")
def purge_biometrics(employee_id: int, admin=Depends(require_admin), db: Session = Depends(get_db)):
    _employee(db, employee_id)
    deleted = (
        db.query(FaceEmbedding)
        .filter(FaceEmbedding.employee_id == employee_id)
        .delete(synchronize_session=False)
    )
    db.commit()
    shutil.rmtree(_faces_dir(employee_id), ignore_errors=True)
    face.refresh_gallery(db)
    return {"deleted": deleted}
