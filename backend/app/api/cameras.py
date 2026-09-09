from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from app.core.db import get_db
from app.api.deps import get_current_user, require_admin
from app.models.camera import Camera
from app.models.node import Node
from app.schemas.camera import CameraOut, CameraIn

router = APIRouter(prefix="/api/v1/cameras", tags=["cameras"])

class CameraPatch(BaseModel):
    name: str | None = None
    location: str | None = None
    host: str | None = None
    rtsp_main: str | None = None
    rtsp_sub: str | None = None
    node_id: int | None = None
    enabled: bool | None = None

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
    return cam

@router.delete("/{camera_id}")
def delete_camera(camera_id: int, admin=Depends(require_admin), db: Session = Depends(get_db)):
    cam = db.get(Camera, camera_id)
    if not cam: raise HTTPException(404, "camera not found")
    db.delete(cam); db.commit()
    return {"ok": True}
