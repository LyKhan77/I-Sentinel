"""Status node vision: satu jalur transisi online ↔ offline (event system + WS + Telegram) dan monitor latar.

Offline terdeteksi dari LWT MQTT (crash/putus) atau heartbeat yang terlambat > HEARTBEAT_TIMEOUT_S (stop rapi,
hang). Hanya perpindahan status yang membuat event dan pesan, jadi LWT + timeout tidak dobel.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import uuid
from datetime import datetime, timedelta, timezone

from app.core.db import SessionLocal
from app.models.node import Node
from app.schemas.event import EventOut
from app.services import telegram
from app.services.ingest import ingest_event
from app.ws.hub import hub

logger = logging.getLogger(__name__)

HEARTBEAT_TIMEOUT_S = 35
CHECK_INTERVAL_S = 15


def _aware(dt: datetime | None) -> datetime | None:
    """SQLite mengembalikan datetime naive (UTC)."""
    return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt


def _emit(db, node: Node, severity: str, reason: str, now: datetime) -> None:
    status, ev = ingest_event(db, {
        "event_id": str(uuid.uuid4()), "type": "system", "node_id": node.id, "severity": severity,
        "ts_event": now.isoformat(), "payload": {"node": node.name, "reason": reason},
    })
    if status == "created" and ev is not None:
        try:
            asyncio.run(hub.broadcast(EventOut.model_validate(ev).model_dump(mode="json")))
        except Exception:
            logger.exception("node event broadcast failed for %s", node.name)


def _duration(delta: timedelta) -> str:
    minutes = int(delta.total_seconds() // 60)
    return f"{minutes} menit" if minutes < 120 else f"{minutes // 60} jam {minutes % 60} menit"


def mark_offline(db, node: Node, reason: str, now: datetime | None = None, send=None) -> bool:
    """online/unknown → offline: event warning + Telegram. False bila sudah offline."""
    if node.status == "offline":
        return False
    now = now or datetime.now(timezone.utc)
    node.status = "offline"
    db.commit()
    _emit(db, node, "warning", reason, now)
    (send or telegram.send_text)(db, f"⚠️ Node {node.name} offline ({reason}) — deteksi AI berhenti")
    return True


def mark_online(db, node: Node, now: datetime | None = None, since: datetime | None = None,
                send=None) -> bool:
    """offline → online: event info + Telegram "pulih". unknown → online tanpa event. False bila tanpa event."""
    was = node.status
    if was == "online":
        return False
    now = now or datetime.now(timezone.utc)
    node.status = "online"
    db.commit()
    if was != "offline":
        return False
    _emit(db, node, "info", "online", now)
    since = _aware(since)
    took = f" — offline {_duration(now - since)}" if since else ""
    (send or telegram.send_text)(db, f"✅ Node {node.name} pulih{took}")
    return True


def check(db, now: datetime | None = None, send=None) -> int:
    """Node online dengan heartbeat lebih tua dari timeout → offline (reason timeout)."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=HEARTBEAT_TIMEOUT_S)
    stale = db.query(Node).filter(Node.status == "online", Node.last_seen < cutoff).all()
    return sum(mark_offline(db, n, "timeout", now=now, send=send) for n in stale)


class NodeHealthMonitor:
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
        self._thread = threading.Thread(target=self._loop, daemon=True, name="node-health")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def _loop(self) -> None:
        while not self._stop.wait(self.interval_s):
            db = None
            try:
                db = self._session_factory()
                check(db)
            except Exception:
                logger.warning("node health check failed", exc_info=True)
            finally:
                if db is not None:
                    try:
                        db.close()
                    except Exception:
                        logger.warning("node health session close failed", exc_info=True)


monitor = NodeHealthMonitor()
