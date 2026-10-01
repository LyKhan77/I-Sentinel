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
from app.services.monitoring_history import _dict, _minute, _num, minute_samples
from app.ws.hub import hub

logger = logging.getLogger(__name__)

HEARTBEAT_TIMEOUT_S = 35
CHECK_INTERVAL_S = 15


def _aware(dt: datetime | None) -> datetime | None:
    """SQLite mengembalikan datetime naive (UTC)."""
    return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt


def _emit(db, node: Node, severity: str, reason: str, now: datetime,
          extra: dict | None = None) -> None:
    payload = {"node": node.name, "reason": reason, **(extra or {})}
    status, ev = ingest_event(db, {
        "event_id": str(uuid.uuid4()), "type": "system", "node_id": node.id, "severity": severity,
        "ts_event": now.isoformat(), "payload": payload,
    })
    if status == "created" and ev is not None:
        try:
            asyncio.run(hub.broadcast(EventOut.model_validate(ev).model_dump(mode="json")))
        except Exception:
            logger.exception("node event broadcast failed for %s", node.name)


def _duration(delta: timedelta) -> str:
    minutes = int(delta.total_seconds() // 60)
    return f"{minutes} menit" if minutes < 120 else f"{minutes // 60} jam {minutes % 60} menit"


def _node_evidence(db, node_id: int, now: datetime) -> dict | None:
    """Build the last 30 completed minute averages for CPU and inference FPS."""
    end = _minute(now)
    start = end - timedelta(minutes=30)
    samples = minute_samples(db, node_id, start, end)
    if not samples:
        return None
    cpu_values, fps_values = [], []
    for offset in range(30):
        data = _dict(samples.get(start + timedelta(minutes=offset)))
        cpu = _num(_dict(data.get("cpu_pct")).get("avg"))
        fps = _num(_dict(data.get("infer_fps")).get("avg"))
        cpu_values.append(round(cpu, 1) if cpu is not None else None)
        fps_values.append(round(fps, 1) if fps is not None else None)
    return {"v": 1, "from": start.isoformat().replace("+00:00", "Z"), "step_s": 60,
            "series": {"cpu_pct": cpu_values, "infer_fps": fps_values}}


def mark_offline(db, node: Node, reason: str, now: datetime | None = None, send=None) -> bool:
    """online/unknown → offline: event warning + Telegram. False bila sudah offline."""
    if node.status == "offline":
        return False
    now = now or datetime.now(timezone.utc)
    extra = {}
    last_seen = _aware(node.last_seen)
    if last_seen is not None:
        extra["last_seen"] = last_seen.isoformat().replace("+00:00", "Z")
    try:
        evidence = _node_evidence(db, node.id, now)
        if evidence is not None:
            extra["evidence"] = evidence
    except Exception:
        logger.exception("node evidence build failed for %s", node.name)
        db.rollback()
    node.status = "offline"
    db.commit()
    _emit(db, node, "warning", reason, now, extra)
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
    since = _aware(since)
    extra = {}
    if since is not None and now > since:
        extra["down_s"] = round((now - since).total_seconds())
    _emit(db, node, "info", "online", now, extra)
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
