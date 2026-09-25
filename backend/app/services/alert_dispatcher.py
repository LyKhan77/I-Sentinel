"""Dispatcher alert Telegram: dipisah dari thread konsumen MQTT (ingest tidak boleh tertahan Telegram).

Per alert: tunggu snapshot event (media datang ±0,5 s setelah event) maksimal ~5 s, lalu
sendPhoto (file dari storage_root) atau sendMessage teks. Hasil ditulis ke baris alert.
Satu worker → worst-case satu alert menahan antrean ±5 s polling + retry kirim (~48 s); cukup untuk
LAN skala kecil karena `alerting.should_alert` sudah rate-limit per (kamera, zona, tipe). Baris `queued`
hanya terkirim selama dispatcher berjalan (antrean in-memory, tanpa pemulihan saat restart).
"""
from __future__ import annotations

import logging
import os
import queue
import threading
import time

from app.core.config import settings
from app.core.db import SessionLocal
from app.models.alert import Alert
from app.models.camera import Camera
from app.models.zone import Zone
from app.services import telegram

logger = logging.getLogger(__name__)
QUEUE_MAX = 200


class AlertDispatcher:
    def __init__(self, maxsize: int = QUEUE_MAX, *, snapshot_polls: int = 10, poll_s: float = 0.5,
                 sleep=time.sleep, session_factory=SessionLocal):
        self._q: queue.Queue = queue.Queue(maxsize=maxsize)
        self._snapshot_polls = snapshot_polls
        self._poll_s = poll_s
        self._sleep = sleep
        self._session_factory = session_factory
        self._thread: threading.Thread | None = None
        self._stopped = threading.Event()

    def enqueue(self, alert_id: int) -> bool:
        try:
            self._q.put_nowait(alert_id)
            return True
        except queue.Full:
            logger.warning("alert queue full, alert %s not dispatched", alert_id)
            return False

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stopped.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="alert-dispatcher")
        self._thread.start()

    def stop(self) -> None:
        self._stopped.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def join_queue(self, timeout: float) -> None:
        """Tes: tunggu antrean kosong dan item terakhir selesai diproses."""
        deadline = time.monotonic() + timeout
        while self._q.unfinished_tasks and time.monotonic() < deadline:
            time.sleep(0.01)

    def _loop(self) -> None:
        # Loop tidak boleh mati: tiap item dipisah sehingga error sesi/DB apa pun tertangkap.
        while not self._stopped.is_set():
            try:
                alert_id = self._q.get(timeout=0.5)
            except queue.Empty:
                continue
            self._pump(alert_id)

    def _pump(self, alert_id: int) -> None:
        db = None
        try:
            db = self._session_factory()
            self.process(alert_id, db)
        except Exception:
            logger.exception("alert %s dispatch failed", alert_id)
            self._reconcile(db, alert_id)
        finally:
            if db is not None:
                try:
                    db.close()
                except Exception:
                    logger.exception("close session failed for alert %s", alert_id)
            self._q.task_done()

    def _reconcile(self, db, alert_id: int) -> None:
        """Jangan tinggalkan alert menggantung 'queued' bila dispatch gagal total."""
        if db is None:
            return
        try:
            db.rollback()
            alert = db.get(Alert, alert_id)
            if alert is not None and alert.status == "queued":
                alert.status, alert.error = "failed", "dispatcher error"
                db.commit()
        except Exception:
            logger.exception("could not reconcile alert %s", alert_id)

    def _snapshot(self, db, event) -> bytes | None:
        for attempt in range(self._snapshot_polls):
            db.refresh(event)
            if event.snapshot_path:
                root = os.path.realpath(settings.storage_root)
                full = os.path.realpath(os.path.join(root, event.snapshot_path))
                if full.startswith(root + os.sep) and os.path.isfile(full):
                    try:
                        with open(full, "rb") as f:
                            return f.read()
                    except OSError:  # hilang/ditolak saat dibaca (mis. sapu retensi) → fallback teks
                        return None
                return None  # path ada tapi file hilang/di luar root → kirim teks
            if attempt < self._snapshot_polls - 1:
                self._sleep(self._poll_s)
        return None

    def process(self, alert_id: int, db) -> None:
        alert = db.get(Alert, alert_id)
        if alert is None:
            return
        token = telegram.get_token()
        chat = telegram.active_chat(db)
        if not token or chat is None:
            alert.status, alert.error = "not_configured", None
            db.commit()
            return
        event = alert.event
        camera = db.get(Camera, alert.camera_id) if alert.camera_id else None
        zone = db.get(Zone, alert.zone_id) if alert.zone_id else None
        caption = telegram.format_caption(
            event, camera.name if camera else f"cam {alert.camera_id}",
            zone.name if zone else None, telegram.app_url(db))
        photo = self._snapshot(db, event)
        db.commit()  # tutup transaksi baca sebelum I/O jaringan; token tidak tersimpan di objek alert
        status, error = telegram.deliver(token, chat.chat_id, caption, photo)
        alert.status, alert.error, alert.chat_id = status, error, chat.chat_id
        db.commit()


dispatcher = AlertDispatcher()
