"""In-process caption queue; ingest never performs media decoding or LLM requests."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import logging
import queue
import threading
import time

from app.core.config import settings
from app.core.db import SessionLocal
from app.models import Camera, Event, EventAi, Zone
from app.services import ai_media, ai_prompts, llm_client
from app.ws.hub import hub

logger = logging.getLogger(__name__)


class AiWorker:
    """Single caption thread with bounded admission and per-zone monotonic throttle.

    Admission is serialized within the single API process. Only pending row ids cross
    threads; each queued operation owns its database session.
    """

    def __init__(self, maxsize: int | None = None, *, session_factory=SessionLocal, clock=time.monotonic):
        self._q = queue.Queue(maxsize=settings.ai_queue_max if maxsize is None else maxsize)
        self._session_factory = session_factory
        self._clock = clock
        self._lock = threading.Lock()
        self._last_zone: dict[int, float] = {}
        self._stopped = threading.Event()
        self._thread: threading.Thread | None = None

    def maybe_enqueue_caption(self, db, ev: Event) -> bool:
        """Admit eligible events once; reject full queues without retaining a row."""
        if not settings.llm_enabled or ev.type not in ai_prompts.AI_TYPES or not ev.zone_id or not ev.snapshot_path or ev.media_expired:
            return False
        zone = db.get(Zone, ev.zone_id)
        if not zone or not zone.ai_caption:
            return False
        with self._lock:
            if db.query(EventAi).filter_by(event_id=ev.id, kind="caption").first():
                return False
            now = self._clock()
            last = self._last_zone.get(zone.id)
            if last is not None and now - last < settings.llm_caption_min_interval_s:
                return False
            row = EventAi(event_id=ev.id, kind="caption", channel="auto")
            db.add(row)
            db.commit()
            if not self.enqueue(row.id):
                db.delete(row)
                db.commit()
                return False
            self._last_zone[zone.id] = now
            return True

    def enqueue(self, ai_id: int) -> bool:
        """Offer an existing pending id without blocking the ingest thread."""
        try:
            self._q.put_nowait(ai_id)
            return True
        except queue.Full:
            logger.warning("AI caption queue full; dropping record %s", ai_id)
            return False

    def process(self, ai_id: int, db) -> None:
        """Persist a terminal result and broadcast best-effort, including LLM failures."""
        row = db.get(EventAi, ai_id)
        if row is None or row.kind != "caption" or row.status != "pending":
            return
        started = time.monotonic()
        try:
            ev = db.get(Event, row.event_id)
            if not settings.llm_enabled:
                raise llm_client.LlmError("AI nonaktif")
            if ev is None or ev.media_expired or not ev.snapshot_path:
                raise ai_media.AiMediaError("Snapshot tidak tersedia")
            zone = db.get(Zone, ev.zone_id) if ev.zone_id else None
            if zone is None or not zone.ai_caption or ev.type not in ai_prompts.AI_TYPES:
                raise llm_client.LlmError("Caption zona nonaktif")
            camera = db.get(Camera, ev.camera_id) if ev.camera_id else None
            content = [llm_client.text_part(ai_prompts.build_caption_prompt(
                zone, ev, camera.name if camera else None, zone.name)),
                llm_client.image_part(ai_media.snapshot_jpeg(ev.snapshot_path))]
            # worker thread khusus: menunggu selama Tanya AI boleh memegang slot, bukan 5 detik
            # (timeout pendek membuat caption gagal permanen karena baris caption sudah ada)
            with llm_client.slot(timeout=settings.llm_timeout_ask_s):
                result = llm_client.chat([
                    {"role": "system", "content": ai_prompts.SYSTEM_PROMPT},
                    {"role": "user", "content": content},
                ], timeout=settings.llm_timeout_caption_s)
            row.status = "ok"
            row.answer = llm_client.clean_error(result.text)
            row.model = llm_client.clean_error(result.model)[:64]
        except (llm_client.LlmError, ai_media.AiMediaError) as exc:
            row.status = "failed"
            row.error = llm_client.clean_error(str(exc))[:255]
        row.latency_ms = int((time.monotonic() - started) * 1000)
        db.commit()
        try:
            asyncio.run(hub.broadcast({"kind": "ai", "event_id": row.event_id, "status": row.status}))
        except Exception:
            logger.warning("AI status broadcast failed for event %s", row.event_id)

    def recover(self, db, now: datetime | None = None) -> int:
        """Requeue pending captions at most ten minutes old; fail stale attempts."""
        now = now or datetime.now(timezone.utc)
        count = 0
        for row in db.query(EventAi).filter_by(kind="caption", status="pending").all():
            created = row.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            if now - created > timedelta(minutes=10):
                row.status, row.error = "failed", "interrupted by restart"
            elif self.enqueue(row.id):
                count += 1
        db.commit()
        return count

    def start(self) -> None:
        """Start at most one thread; an empty queue never opens a DB session."""
        if self._thread and self._thread.is_alive():
            return
        self._stopped.clear()
        self._thread = threading.Thread(target=self._loop, name="ai-caption", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop accepting background work and wait for the bounded in-flight request."""
        self._stopped.set()
        if self._thread:
            self._thread.join(timeout=settings.llm_timeout_caption_s + 10)
            if not self._thread.is_alive():
                self._thread = None

    def join_queue(self, timeout: float) -> None:
        """Wait up to a finite deadline for queued and in-flight work to finish."""
        end = time.monotonic() + timeout
        while self._q.unfinished_tasks and time.monotonic() < end:
            time.sleep(0.01)

    def _loop(self) -> None:
        """Keep database or protocol failures isolated to a single queue item."""
        while not self._stopped.is_set():
            try:
                ai_id = self._q.get(timeout=0.05)
            except queue.Empty:
                continue
            db = None
            try:
                db = self._session_factory()
                self.process(ai_id, db)
            except Exception:
                if db is not None:
                    db.rollback()
                    try:
                        row = db.get(EventAi, ai_id)
                        if row is not None and row.status == "pending":
                            row.status, row.error = "failed", "Caption processing failed"
                            db.commit()
                    except Exception:
                        db.rollback()
                logger.warning("AI caption processing failed for record %s", ai_id)
            finally:
                if db is not None:
                    db.close()
                self._q.task_done()


worker = AiWorker()
