from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.db import get_db
from app.api.deps import get_current_user, require_admin
from app.models.zone import Zone
from app.schemas.zone import ZoneIn, ZonePatch, ZoneOut
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/zones", tags=["zones"])


def _config_push(db: Session, camera_id: int) -> None:
    try:
        from app.services.config_push import publish_node_config_for_camera
        publish_node_config_for_camera(db, camera_id)
    except Exception:
        logger.warning("config push after zone mutation failed", exc_info=True)


_ATTENDANCE_TYPES = ("absensi", "attendance")


def _check_direction_conflict(db: Session, zone: Zone) -> None:
    """Satu kamera: zona absensi aktif hanya boleh satu arah (satu FaceGateWorker per kamera)."""
    if zone.type not in _ATTENDANCE_TYPES or not zone.active:
        return
    q = db.query(Zone).filter(
        Zone.camera_id == zone.camera_id,
        Zone.type.in_(_ATTENDANCE_TYPES),
        Zone.active.is_(True),
        Zone.direction != zone.direction,
    )
    if zone.id is not None:
        q = q.filter(Zone.id != zone.id)
    if q.first() is not None:
        db.rollback()  # buang perubahan patch yang belum di-commit
        raise HTTPException(422, "camera already has an active attendance zone with another direction")


@router.get("", response_model=list[ZoneOut])
def list_zones(camera_id: int | None = None, user=Depends(get_current_user), db: Session = Depends(get_db)):
    q = db.query(Zone)
    if camera_id is not None:
        q = q.filter(Zone.camera_id == camera_id)
    return q.all()

@router.post("", response_model=ZoneOut)
def create_zone(body: ZoneIn, admin=Depends(require_admin), db: Session = Depends(get_db)):
    zone = Zone(**body.model_dump())
    _check_direction_conflict(db, zone)
    db.add(zone); db.commit(); db.refresh(zone)
    _config_push(db, zone.camera_id)
    return zone

@router.get("/{zone_id}", response_model=ZoneOut)
def get_zone(zone_id: int, user=Depends(get_current_user), db: Session = Depends(get_db)):
    zone = db.get(Zone, zone_id)
    if not zone: raise HTTPException(404, "zone not found")
    return zone

@router.patch("/{zone_id}", response_model=ZoneOut)
def update_zone(zone_id: int, body: ZonePatch, admin=Depends(require_admin), db: Session = Depends(get_db)):
    zone = db.get(Zone, zone_id)
    if not zone: raise HTTPException(404, "zone not found")
    changes = body.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(zone, k, v)
    # zona attendance (dulu absensi) wajib direction — cek hasil gabungan patch + nilai lama
    if zone.type in ("absensi", "attendance") and not zone.direction:
        raise HTTPException(422, "direction (entry|exit) required for attendance zone")
    _check_direction_conflict(db, zone)
    db.commit(); db.refresh(zone)
    _config_push(db, zone.camera_id)
    return zone

@router.delete("/{zone_id}")
def delete_zone(zone_id: int, admin=Depends(require_admin), db: Session = Depends(get_db)):
    zone = db.get(Zone, zone_id)
    if not zone: raise HTTPException(404, "zone not found")
    camera_id = zone.camera_id
    db.delete(zone); db.commit()
    _config_push(db, camera_id)
    return {"ok": True}
