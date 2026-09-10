from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.db import get_db
from app.api.deps import get_current_user
from app.models.node import Node, mark_stale_nodes
from app.schemas.camera import NodeOut

router = APIRouter(prefix="/api/v1/nodes", tags=["nodes"])

@router.get("", response_model=list[NodeOut])
def list_nodes(user=Depends(get_current_user), db: Session = Depends(get_db)):
    mark_stale_nodes(db)
    return db.query(Node).all()
