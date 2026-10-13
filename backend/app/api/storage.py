from fastapi import Request
from app.services import audit
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin
from app.core.config import settings
from app.core.db import get_db
from app.models.setting import Setting
from app.schemas.storage import CleanupIn, StorageSettingsPatch
from app.services import retention, storage_settings

router = APIRouter(prefix="/api/v1/storage", tags=["storage"])

logger = logging.getLogger(__name__)

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
    s = storage_settings.get(db)
    disk = retention.disk_usage(root)
    return {
        "retention_days": s["clip_days"],  # kompatibilitas klien lama
        "settings": s,
        "storage_root": root,
        "disk": disk,
        "disk_alert": {"threshold": s["disk_alert_percent"], "over": disk["percent"] >= s["disk_alert_percent"]},
        "kinds": retention.kind_usage(root),
        "last_sweep": _last_sweep(db),
    }


@router.get("/settings")
def get_settings(db: Session = Depends(get_db), user=Depends(get_current_user)):
    return storage_settings.get(db)


@router.put("/settings")
def put_settings(request: Request, body: StorageSettingsPatch, db: Session = Depends(get_db), admin=Depends(require_admin)):
    old = storage_settings.get(db)
    changes = {k: v for k, v in body.model_dump(exclude_none=True).items() if old.get(k) != v}
    return storage_settings.put(db, body.model_dump(), before_commit=lambda: audit.record(db, action="storage_settings.update", actor=admin, target=("storage_settings", None, "global"), changes=changes,
                 ip=request.client.host if request.client else None,
                 user_agent=request.headers.get("user-agent")))


@router.post("/sweep")
def run_sweep(
    request: Request,
    dry_run: bool = Query(False),
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    audit.record(db, action="storage.sweep", actor=admin, target=("storage", None, "sweep"), changes={"dry_run": dry_run},
                 ip=request.client.host if request.client else None,
                 user_agent=request.headers.get("user-agent"))
    result = retention.sweep(db, dry_run=dry_run)
    return _record_sweep(db, result)


@router.post("/cleanup")
def cleanup_events(request: Request, body: CleanupIn, db: Session = Depends(get_db), admin=Depends(require_admin)):
    # None = semua karyawan; identitas karyawan tidak pernah masuk log (hanya id)
    employee_ids = None if body.all_employees else body.employee_ids
    audit.record(db, action="storage.cleanup", actor=admin, target=("storage", None, "cleanup"), changes={"mode": body.mode, "date_from": str(body.date_from), "date_to": str(body.date_to), "dry_run": body.dry_run},
                 ip=request.client.host if request.client else None,
                 user_agent=request.headers.get("user-agent"))
    if body.dry_run:
        result = retention.cleanup(db, body.date_from, body.date_to, body.camera_ids, body.types, dry_run=True,
                                 mode=body.mode, employee_ids=employee_ids)
        db.commit()
        return result
    try:
        result = retention.cleanup(db, body.date_from, body.date_to, body.camera_ids, body.types, dry_run=False,
                                   mode=body.mode, employee_ids=employee_ids)
    except Exception:
        logger.exception("event cleanup by %s failed: %s..%s cameras=%s types=%s",
                         admin.username, body.date_from, body.date_to, body.camera_ids or "all",
                         body.types or "all")
        raise
    if body.mode == "attendance_data":
        logger.info("attendance data cleanup by %s: %s..%s employees=%s → %s attendance_events, %s days, "
                    "%s events, %s files",
                    admin.username, body.date_from, body.date_to, "all" if body.all_employees else body.employee_ids,
                    result["attendance_events"], result["days"], result["events"], result["files"])
    else:
        logger.info("event cleanup by %s: %s..%s cameras=%s types=%s mode=%s → %s events, %s files, %s bytes",
                    admin.username, body.date_from, body.date_to, body.camera_ids or "all",
                    body.types or "all", body.mode, result["events"], result["files"], result["bytes"])
    db.commit()
    return result
