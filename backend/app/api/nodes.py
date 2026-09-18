from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
import re
from sqlalchemy.orm import Session
from app.core.db import get_db
from app.api.deps import get_current_user, require_admin
from app.models.node import Node, mark_stale_nodes
from app.schemas.camera import NodeOut
from app.services.config_push import publish_node_config

router = APIRouter(prefix="/api/v1/nodes", tags=["nodes"])

_CUDA_RE = re.compile(r"^cuda:(\d+)$")

@router.get("", response_model=list[NodeOut])
def list_nodes(user=Depends(get_current_user), db: Session = Depends(get_db)):
    mark_stale_nodes(db)
    return db.query(Node).all()


class DetectorDeviceIn(BaseModel):
    device: str  # "" = auto; "cuda:N" = pin


@router.put("/{node_id}/detector-device", response_model=NodeOut)
def set_detector_device(node_id: int, body: DetectorDeviceIn,
                        user=Depends(require_admin), db: Session = Depends(get_db)):
    """Pin/unpin detector GPU via config push. Empty device = auto (env fallback)."""
    device = (body.device or "").strip()
    m = _CUDA_RE.match(device)
    if device and not m:
        raise HTTPException(422, "device must be 'cuda:N' or empty (auto)")
    node = db.get(Node, node_id)
    if node is None:
        raise HTTPException(404, "node not found")
    if device:
        # validasi lokal bila hw heartbeat tersedia; tanpa hw, vision memvalidasi
        # sendiri saat apply (reject-and-keep) — jangan blokir admin tanpa info
        n = len((node.hw or {}).get("gpus", []))
        if n and n <= int(m.group(1)):
            raise HTTPException(422, f"device {device} not found: node reports {n} GPU")
    node.detector_device = device or None
    db.commit()
    publish_node_config(None, db, node.name)
    db.refresh(node)
    return node
