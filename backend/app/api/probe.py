from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.core.db import get_db
from app.api.deps import require_admin
from app.models.camera import Camera
from app.services.probe import probe_camera

router = APIRouter(prefix="/api/v1/cameras", tags=["cameras"])

class ProbeIn(BaseModel):
    host: str
    camera_id: int | None = None

@router.post("/probe")
def probe(body: ProbeIn, admin=Depends(require_admin), db: Session = Depends(get_db)):
    result = probe_camera(body.host)
    if body.camera_id is not None:
        cam = db.get(Camera, body.camera_id)
        if not cam: raise HTTPException(404, "camera not found")
        cam.probe_main = result["main"]
        cam.probe_sub = result["sub"]
        cam.status = "online" if result["main"] or result["sub"] else "offline"
        db.commit(); db.refresh(cam)
    return result
