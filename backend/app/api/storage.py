from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin
from app.core.config import settings
from app.core.db import get_db
from app.models.setting import Setting
from app.services import retention

router = APIRouter(prefix="/api/v1/storage", tags=["storage"])

LAST_SWEEP_KEY = "retention_last_sweep"


def _last_sweep(db: Session) -> dict | None:
    row = db.get(Setting, LAST_SWEEP_KEY)
    return row.value if row else None


def _record_sweep(db: Session, result: dict) -> dict:
    payload = {**result, "at": datetime.now(timezone.utc).isoformat()}
    row = db.get(Setting, LAST_SWEEP_KEY)
    if row is None:
        row = Setting(key=LAST_SWEEP_KEY, value=payload)
        db.add(row)
    else:
        row.value = payload
    db.commit()
    return payload


@router.get("/stats")
def storage_stats(db: Session = Depends(get_db), user=Depends(get_current_user)):
    root = settings.storage_root
    return {
        "retention_days": settings.retention_days,
        "storage_root": root,
        "disk": retention.disk_usage(root),
        "kinds": retention.kind_usage(root),
        "last_sweep": _last_sweep(db),
    }


@router.post("/sweep")
def run_sweep(
    dry_run: bool = Query(False),
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    result = retention.sweep(db, dry_run=dry_run)
    return _record_sweep(db, result)
