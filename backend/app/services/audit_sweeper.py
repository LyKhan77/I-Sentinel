"""Penyapu retensi audit log: hapus entri lebih tua dari settings.audit_retention_days.

Thread latar pola sama dengan disk_alert/attendance_closer: sesi segar per iterasi,
penghapusan batch agar tidak memblokir lama. Hash chain baris yang tersisa tidak rusak:
setiap baris menyimpan hash-nya sendiri; verifikasi berjalan maju dari baris tertua
di window retensi (genesis window, lihat services/audit.py verify()).
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import SessionLocal
from app.models.audit_log import AuditLog

logger = logging.getLogger(__name__)

BATCH = 5000
INTERVAL_S = 24 * 3600


def sweep_once(db: Session, now: datetime | None = None) -> int:
    """Hapus entri audit lebih tua dari retensi; return jumlah terhapus."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=settings.audit_retention_days)
    total = 0
    while True:
        ids = [
            r[0]
            for r in db.query(AuditLog.id).filter(AuditLog.ts < cutoff)
            .order_by(AuditLog.id).limit(BATCH).all()
        ]
        if not ids:
            break
        db.query(AuditLog).filter(AuditLog.id.in_(ids)).delete(synchronize_session=False)
        total += len(ids)
    db.commit()
    return total


class AuditSweeper:
    """Thread latar: sweep_once() tiap interval_s; tanpa run_on_start (sweep pertama setelah 1 interval)."""

    def __init__(self, interval_s: float = INTERVAL_S, session_factory=SessionLocal,
                 run_on_start: bool = False):
        self.interval_s = interval_s
        self.run_on_start = run_on_start
        self._session_factory = session_factory
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            logger.warning("audit sweeper sudah berjalan — start() diabaikan")
            return
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="audit-sweeper")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def _loop(self) -> None:
        if self.run_on_start:
            self._sweep_safe()
        while not self._stop.wait(self.interval_s):
            self._sweep_safe()

    def _sweep_safe(self) -> None:
        db = self._session_factory()
        try:
            removed = sweep_once(db)
            if removed:
                logger.info("audit sweeper removed %s entries", removed)
        except Exception:
            logger.warning("audit sweep failed", exc_info=True)
        finally:
            db.close()


sweeper = AuditSweeper()
