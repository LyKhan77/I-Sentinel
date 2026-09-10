from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.db import get_db
from app.api.deps import get_current_user
from app.models.node import Node
from app.schemas.camera import NodeOut

router = APIRouter(prefix="/api/v1/nodes", tags=["nodes"])

@router.get("", response_model=list[NodeOut])
def list_nodes(user=Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(Node).all()
