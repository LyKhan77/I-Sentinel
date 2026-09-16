"""Sweep retensi sekali jalan — dipanggil isentinel-retention.service.

Sengaja tidak lewat HTTP API supaya tidak perlu kredensial admin di unit systemd
dan tidak ikut gagal saat API sedang restart.
"""
import logging
import sys

# Dipanggil sebagai `python scripts/retention_sweep.py` → sys.path[0] = scripts/,
# bukan backend/. Tambahkan root proyek supaya `app` importable di mana pun
# script ini dijalankan (termasuk unit systemd).
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import settings
from app.core.db import SessionLocal
from app.models.setting import Setting
from app.services import retention

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("retention")


def main() -> int:
    db = SessionLocal()
    try:
        result = retention.sweep(db)
        from datetime import datetime, timezone

        payload = {**result, "at": datetime.now(timezone.utc).isoformat()}
        row = db.get(Setting, "retention_last_sweep")
        if row is None:
            db.add(Setting(key="retention_last_sweep", value=payload))
        else:
            row.value = payload
        db.commit()
        logger.info(
            "sweep selesai: %s file, %s byte, %s event, %s orphan (retention=%s hari)",
            result["files_deleted"], result["bytes_freed"], result["events_marked"],
            result["orphans_deleted"], settings.retention_days,
        )
        return 0
    except Exception:
        logger.exception("sweep gagal")
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
