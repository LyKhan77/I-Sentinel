from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from urllib.parse import urlsplit
from app.core.db import get_db
from app.api.deps import get_current_user, require_admin
from app.models.camera import Camera
from app.models.attendance import AttendanceEvent
from app.models.node import Node
from app.schemas.camera import CameraOut, CameraIn, CameraPatch, CameraImportIn
from app.services.go2rtc import sync_camera, remove_stream
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/cameras", tags=["cameras"])


def _config_push(db: Session, camera_id: int, node_name: str | None = None) -> None:
    try:
        from app.services.config_push import publish_node_config
        if node_name is None:
            from app.services.config_push import publish_node_config_for_camera
            publish_node_config_for_camera(db, camera_id)
        else:
            publish_node_config(None, db, node_name)
    except Exception:
        logger.warning("config push after camera mutation failed", exc_info=True)

def _check_node(db: Session, node_id: int | None) -> None:
    if node_id is not None and not db.query(Node).filter_by(id=node_id).first():
        raise HTTPException(422, "node not found")

def _dup_name(db: Session, name: str, node_id: int | None, exclude_id: int | None = None) -> bool:
    q = db.query(Camera).filter_by(name=name, node_id=node_id)
    if exclude_id is not None:
        q = q.filter(Camera.id != exclude_id)
    return q.first() is not None

def _import_host(value: str) -> str:
    raw = value.strip().lower()
    parsed = urlsplit(raw if "://" in raw else f"//{raw}")
    host = parsed.hostname or raw
    try:
        port = parsed.port
    except ValueError:
        return raw
    return f"{host}:{port}" if port and port != 554 else host

def _import_path(value: str) -> str:
    raw = value.strip()
    if "://" in raw:
        parsed = urlsplit(raw)
        raw = parsed.path + (f"?{parsed.query}" if parsed.query else "")
    return raw if raw.startswith("/") else f"/{raw}"

def _import_key(host: str, path: str) -> tuple[str, str]:
    return _import_host(host), _import_path(path)

def _import_snapshot(cam: Camera) -> dict:
    return {
        "name": cam.name,
        "location": cam.location,
        "host": cam.host,
        "rtsp_main": cam.rtsp_main,
        "rtsp_sub": cam.rtsp_sub,
    }

@router.post("", response_model=CameraOut)
def create_camera(body: CameraIn, admin=Depends(require_admin), db: Session = Depends(get_db)):
    _check_node(db, body.node_id)
    if _dup_name(db, body.name, body.node_id):
        raise HTTPException(409, "camera name already exists on this node")
    cam = Camera(**body.model_dump())
    db.add(cam); db.commit(); db.refresh(cam)
    if cam.enabled:
        try: sync_camera(cam)
        except Exception: logger.warning("go2rtc sync after create failed", exc_info=True)
    _config_push(db, cam.id)
    return cam

@router.get("", response_model=list[CameraOut])
def list_cameras(user=Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(Camera).all()

@router.get("/{camera_id}", response_model=CameraOut)
def get_camera(camera_id: int, user=Depends(get_current_user), db: Session = Depends(get_db)):
    cam = db.get(Camera, camera_id)
    if not cam: raise HTTPException(404, "camera not found")
    return cam

@router.patch("/{camera_id}", response_model=CameraOut)
def update_camera(camera_id: int, body: CameraPatch, admin=Depends(require_admin), db: Session = Depends(get_db)):
    cam = db.get(Camera, camera_id)
    if not cam: raise HTTPException(404, "camera not found")
    data = body.model_dump(exclude_unset=True)
    if "node_id" in data:
        _check_node(db, data["node_id"])
    if "name" in data and _dup_name(db, data["name"], data.get("node_id", cam.node_id), exclude_id=cam.id):
        raise HTTPException(409, "camera name already exists on this node")
    for k, v in data.items():
        setattr(cam, k, v)
    db.commit(); db.refresh(cam)
    try:
        if cam.enabled: sync_camera(cam)
        else: sync_camera(cam, delete=True)
    except Exception: logger.warning("go2rtc sync after update failed", exc_info=True)
    _config_push(db, cam.id)
    return cam

@router.post("/import")
def import_cameras(
    body: CameraImportIn,
    apply_changes: bool = Query(False, alias="apply"),
    admin=Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Preview or apply an idempotent path-keyed camera inventory update."""
    by_key: dict[tuple[str, str], Camera] = {}
    duplicate_keys: set[tuple[str, str]] = set()
    for cam in db.query(Camera).all():
        if not cam.rtsp_main:
            continue
        key = _import_key(cam.host, cam.rtsp_main)
        if key in by_key:
            duplicate_keys.add(key)
        else:
            by_key[key] = cam

    errors: list[str] = []
    items: list[dict] = []
    seen_keys: set[tuple[str, str]] = set()
    seen_names: set[str] = set()
    for entry in body.entries:
        name = entry.name.strip()
        location = entry.location.strip() if entry.location else None
        host = _import_host(entry.host)
        rtsp_main = _import_path(entry.rtsp_main)
        rtsp_sub = _import_path(entry.rtsp_sub) if entry.rtsp_sub else None
        key = (host, rtsp_main)

        if key in seen_keys:
            errors.append(f"duplicate input stream: {host}{rtsp_main}")
        seen_keys.add(key)
        if name in seen_names:
            errors.append(f"duplicate input name: {name}")
        seen_names.add(name)

        cam = None if key in duplicate_keys else by_key.get(key)
        if cam is None:
            items.append({
                "camera_id": None,
                "matched": False,
                "changed": False,
                "before": None,
                "after": {
                    "name": name,
                    "location": location,
                    "host": host,
                    "rtsp_main": rtsp_main,
                    "rtsp_sub": rtsp_sub,
                },
            })
            continue

        if _dup_name(db, name, cam.node_id, exclude_id=cam.id):
            errors.append(f"camera name already exists on node: {name}")
        before = _import_snapshot(cam)
        after = {
            "name": name,
            "location": location,
            "host": host,
            "rtsp_main": rtsp_main,
            "rtsp_sub": rtsp_sub,
        }
        items.append({
            "camera_id": cam.id,
            "matched": True,
            "changed": before != after,
            "before": before,
            "after": after,
        })

    unmatched = [item for item in items if not item["matched"]]
    changed = [item for item in items if item["changed"]]
    result = {
        "applied": False,
        "total": len(items),
        "matched": len(items) - len(unmatched),
        "updated": len(changed),
        "unmatched": unmatched,
        "errors": errors,
        "items": items,
    }
    if not apply_changes or errors or unmatched:
        return result

    try:
        for item in changed:
            cam = db.get(Camera, item["camera_id"])
            for field, value in item["after"].items():
                setattr(cam, field, value)
        db.commit()
    except Exception:
        db.rollback()
        raise

    for item in changed:
        cam = db.get(Camera, item["camera_id"])
        try:
            if cam.enabled:
                sync_camera(cam)
            else:
                sync_camera(cam, delete=True)
        except Exception:
            logger.warning("go2rtc sync after import failed", exc_info=True)
        _config_push(db, cam.id)
    result["applied"] = True
    return result

@router.delete("/{camera_id}")
def delete_camera(camera_id: int, admin=Depends(require_admin), db: Session = Depends(get_db)):
    cam = db.get(Camera, camera_id)
    if not cam: raise HTTPException(404, "camera not found")
    if db.query(AttendanceEvent).filter(AttendanceEvent.camera_id == camera_id).first():
        raise HTTPException(409, "camera has attendance records; deactivate instead")
    node_name = db.get(Node, cam.node_id).name if cam.node_id else None
    db.delete(cam); db.commit()
    try:
        remove_stream(f"cam_{camera_id}"); remove_stream(f"cam_{camera_id}_main")
    except Exception: logger.warning("go2rtc sync after delete failed", exc_info=True)
    if node_name: _config_push(db, camera_id, node_name)
    return {"ok": True}
