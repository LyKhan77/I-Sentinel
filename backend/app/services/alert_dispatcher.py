"""Antrean alert Telegram: dipisah dari thread konsumen MQTT (ingest tidak boleh tertahan Telegram)."""
from __future__ import annotations

import logging
import queue

logger = logging.getLogger(__name__)
QUEUE_MAX = 200


class AlertDispatcher:
    def __init__(self, maxsize: int = QUEUE_MAX):
        self._q: queue.Queue = queue.Queue(maxsize=maxsize)

    def enqueue(self, alert_id: int) -> bool:
        try:
            self._q.put_nowait(alert_id)
            return True
        except queue.Full:
            logger.warning("alert queue full, alert %s dropped", alert_id)
            return False


dispatcher = AlertDispatcher()
