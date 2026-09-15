from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.db import get_db
from app.api.deps import get_current_user, require_admin
from app.models.camera import Camera
from app.models.node import Node
from app.schemas.camera import CameraOut, CameraIn, CameraPatch
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

@router.delete("/{camera_id}")
def delete_camera(camera_id: int, admin=Depends(require_admin), db: Session = Depends(get_db)):
    cam = db.get(Camera, camera_id)
    if not cam: raise HTTPException(404, "camera not found")
    node_name = db.get(Node, cam.node_id).name if cam.node_id else None
    db.delete(cam); db.commit()
    try:
        remove_stream(f"cam_{camera_id}"); remove_stream(f"cam_{camera_id}_main")
    except Exception: logger.warning("go2rtc sync after delete failed", exc_info=True)
    if node_name: _config_push(db, camera_id, node_name)
    return {"ok": True}
