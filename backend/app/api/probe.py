from fastapi import APIRouter, Depends
from pydantic import BaseModel
from app.api.deps import require_admin
from app.services.probe import probe_camera

router = APIRouter(prefix="/api/v1/cameras", tags=["cameras"])

class ProbeIn(BaseModel):
    host: str

@router.post("/probe")
def probe(body: ProbeIn, admin=Depends(require_admin)):
    return probe_camera(body.host)
