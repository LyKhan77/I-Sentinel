"""Pengaturan retensi & peringatan disk (tabel setting, key "storage").

Field yang belum pernah disimpan mengikuti env (RETENTION_DAYS) / default, jadi .env tetap berlaku
sampai admin menyimpan nilai lain dari UI.
"""
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.setting import Setting

KEY = "storage"
DEFAULT_ALERT_PERCENT = 85


def _stored(db: Session) -> dict:
    row = db.get(Setting, KEY)
    return dict(row.value or {}) if row is not None else {}


def get(db: Session) -> dict:
    v = _stored(db)
    days = settings.retention_days
    return {
        "clip_days": int(v.get("clip_days", days)),
        "snapshot_days": int(v.get("snapshot_days", days)),
        "disk_alert_percent": int(v.get("disk_alert_percent", DEFAULT_ALERT_PERCENT)),
    }


def put(db: Session, patch: dict) -> dict:
    stored = {**_stored(db), **{k: v for k, v in patch.items() if v is not None}}
    row = db.get(Setting, KEY)
    if row is None:
        db.add(Setting(key=KEY, value=stored))
    else:
        row.value = stored  # dict baru → SQLAlchemy mendeteksi perubahan JSON
    db.commit()
    return get(db)
