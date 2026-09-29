"""Peringatan disk hampir penuh: cek berkala → pesan Telegram + state untuk banner.

State di setting "disk_alert_state" {"over", "last_sent_at"} supaya pengingat 24 jam dan pesan
"pulih" tetap benar setelah API restart. Tanpa token/grup Telegram: tidak mengirim, state tetap.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone

from app.core.config import settings
from app.core.db import SessionLocal
from app.models.setting import Setting
from app.services import retention, storage_settings, telegram

logger = logging.getLogger(__name__)

STATE_KEY = "disk_alert_state"
RECOVER_MARGIN = 2  # % di bawah ambang sebelum dianggap pulih (cegah pesan bolak-balik)
REPEAT_AFTER = timedelta(hours=24)
CHECK_INTERVAL_S = 600


def _send(db, text: str) -> bool:
    token = telegram.get_token()
    chat = telegram.active_chat(db)
    if not token or chat is None:
        return False
    status, error = telegram.deliver(token, chat.chat_id, text, retries=1)
    if status != "sent":
        logger.warning("disk alert telegram failed: %s", error)  # pesan deliver() sudah bebas token
    return status == "sent"


def _state(db) -> dict:
    row = db.get(Setting, STATE_KEY)
    return dict(row.value or {}) if row is not None else {"over": False, "last_sent_at": None}


def _save(db, state: dict) -> None:
    row = db.get(Setting, STATE_KEY)
    if row is None:
        db.add(Setting(key=STATE_KEY, value=state))
    else:
        row.value = state
    db.commit()


def check(db, now: datetime | None = None, percent: float | None = None,
          free_bytes: int | None = None, send=None) -> str | None:
    """Bandingkan pemakaian disk dengan ambang; kirim peringatan/pulih bila perlu."""
    now = now or datetime.now(timezone.utc)
    send = send or _send
    if percent is None or free_bytes is None:
        usage = retention.disk_usage(settings.storage_root)
        percent, free_bytes = usage["percent"], usage["free"]
    threshold = storage_settings.get(db)["disk_alert_percent"]
    state = _state(db)
    last = datetime.fromisoformat(state["last_sent_at"]) if state.get("last_sent_at") else None
    sent_kind = None
    if percent >= threshold:
        if not state.get("over") or last is None or now - last >= REPEAT_AFTER:
            text = (f"⚠️ Disk hampir penuh: {percent:.0f}% (ambang {threshold}%) — "
                    f"sisa {free_bytes / 1024 ** 3:.1f} GB")
            if send(db, text):
                last, sent_kind = now, "alert"
        state = {"over": True, "last_sent_at": last.isoformat() if last else None}
    elif state.get("over") and percent < threshold - RECOVER_MARGIN:
        if send(db, f"✅ Disk pulih: {percent:.0f}% (ambang {threshold}%)"):
            sent_kind = "recovered"
        state = {"over": False, "last_sent_at": None}
    _save(db, state)
    return sent_kind


class DiskAlertMonitor:
    """Thread latar: check() tiap interval_s; menunggu satu interval sebelum cek pertama."""

    def __init__(self, interval_s: float = CHECK_INTERVAL_S, session_factory=SessionLocal):
        self.interval_s = interval_s
        self._session_factory = session_factory
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="disk-alert")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def _loop(self) -> None:
        while not self._stop.wait(self.interval_s):
            db = self._session_factory()
            try:
                check(db)
            except Exception:
                logger.warning("disk alert check failed", exc_info=True)
            finally:
                db.close()


monitor = DiskAlertMonitor()
