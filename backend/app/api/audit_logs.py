import logging
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.core.db import get_db
from app.models.audit_log import AuditLog
from app.models.user import User
from app.schemas.audit_log import AuditLogPage, AuditVerifyOut
from app.services import audit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/audit-logs", tags=["audit-logs"])


@router.get("", response_model=AuditLogPage)
def list_audit_logs(
    from_: datetime | None = Query(None, alias="from"),
    to: datetime | None = None,
    category: str | None = Query(None, max_length=16),
    action: str | None = Query(None, max_length=48),
    actor: str | None = Query(None, max_length=64),
    target_type: str | None = Query(None, max_length=32),
    target_id: str | None = Query(None, max_length=64),
    status: str | None = Query(None, max_length=16),
    q: str | None = Query(None, max_length=100),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0, le=100_000),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """List retained audit entries with admin-only filters and bounded pagination."""
    query = db.query(AuditLog)
    if from_ is not None:
        query = query.filter(AuditLog.ts >= from_)
    if to is not None:
        query = query.filter(AuditLog.ts <= to)
    if category:
        query = query.filter(AuditLog.category == category)
    if action:
        query = query.filter(AuditLog.action == action)
    if actor:
        query = query.filter(AuditLog.actor_label == actor)
    if target_type:
        query = query.filter(AuditLog.target_type == target_type)
    if target_id:
        query = query.filter(AuditLog.target_id == target_id)
    if status:
        query = query.filter(AuditLog.status == status)
    if q and q.strip():
        term = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pat = f"%{term}%"
        query = query.filter(or_(
            AuditLog.action.ilike(pat, escape="\\"),
            AuditLog.target_label.ilike(pat, escape="\\"),
            AuditLog.actor_label.ilike(pat, escape="\\"),
        ))
    total = query.count()
    items = query.order_by(AuditLog.ts.desc(), AuditLog.id.desc()).offset(offset).limit(limit).all()
    return {"total": total, "items": items}


@router.get("/actors")
def list_actors(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Return distinct actor labels for the administrator filter."""
    rows = (
        db.query(AuditLog.actor_label)
        .distinct()
        .order_by(AuditLog.actor_label)
        .all()
    )
    return [r[0] for r in rows]


@router.post("/verify", response_model=AuditVerifyOut)
def verify_chain(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Verify the retained audit chain and identify its first broken entry."""
    return audit.verify(db)
