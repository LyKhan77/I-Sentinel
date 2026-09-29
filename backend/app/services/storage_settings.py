"""Pengaturan retensi & peringatan disk (tabel setting, key "storage").

Field yang belum pernah disimpan mengikuti env (RETENTION_DAYS) / default, jadi .env tetap berlaku
sampai admin menyimpan nilai lain dari UI. Nilai di DB divalidasi ulang di sini (defense in depth):
retensi mengontrol penghapusan permanen, jadi nilai rusak/0 tidak boleh diam-diam dipakai.
"""
import logging

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.setting import Setting

logger = logging.getLogger(__name__)

KEY = "storage"
DEFAULT_ALERT_PERCENT = 85
DAYS_RANGE = (1, 3650)
ALERT_RANGE = (50, 99)


def _bounded(value, default: int, lo: int, hi: int) -> int:
    """Integer dalam rentang → dipakai; rusak/di luar rentang → default + peringatan log."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = None
    if n is None or not lo <= n <= hi:
        logger.warning("storage setting %r di luar rentang %s-%s — memakai %s", value, lo, hi, default)
        return default
    return n


def _stored(db: Session) -> dict:
    row = db.get(Setting, KEY)
    return dict(row.value or {}) if row is not None else {}


def get(db: Session) -> dict:
    v = _stored(db)
    days = settings.retention_days
    return {
        "clip_days": _bounded(v.get("clip_days", days), days, *DAYS_RANGE),
        "snapshot_days": _bounded(v.get("snapshot_days", days), days, *DAYS_RANGE),
        "disk_alert_percent": _bounded(v.get("disk_alert_percent", DEFAULT_ALERT_PERCENT),
                                       DEFAULT_ALERT_PERCENT, *ALERT_RANGE),
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
