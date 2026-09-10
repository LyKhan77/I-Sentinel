import asyncio
import json
import logging
import threading
import time
import uuid

import paho.mqtt.client as mqtt

from app.core.config import settings
from app.models import Event, Node
from app.schemas.event import EventIn, EventOut
from app.services.ingest import ingest_event
from app.ws.hub import hub

logger = logging.getLogger(__name__)

EVENTS_TOPIC = "isentinel/events"
LWT_TOPIC = "isentinel/nodes/+/lwt"


def handle_message(db, topic: str, payload: bytes) -> None:
    """Parse one MQTT message and ingest it. Never raises."""
    try:
        try:
            data = json.loads(payload)
        except (ValueError, UnicodeDecodeError):
            logger.warning("Malformed JSON on %s", topic)
            return

        if topic == EVENTS_TOPIC:
            try:
                event = EventIn.model_validate(data)
            except Exception:
                logger.warning("Invalid event payload on %s", topic)
                return
            data["ts_event"] = event.ts_event
            status, ev = ingest_event(db, data)
            if status == "created" and ev is not None:
                asyncio.run(hub.broadcast(EventOut.model_validate(ev).model_dump(mode="json")))
        elif topic.startswith("isentinel/nodes/") and topic.endswith("/lwt"):
            name = topic.split("/")[2]
            node = db.query(Node).filter_by(name=name).first()
            if node is None:
                logger.warning("LWT for unknown node %r", name)
                return
            node.status = "offline"
            db.commit()
            ingest_event(db, {
                "event_id": str(uuid.uuid4()),
                "type": "system",
                "node_id": node.id,
                "severity": "warning",
                "payload": {"node": name, "reason": "lwt"},
            })
    except Exception:
        logger.exception("Error handling MQTT message on %s", topic)


class EventConsumer:
    def __init__(self):
        self._client: mqtt.Client | None = None
        self._thread: threading.Thread | None = None

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True, name="mqtt-consumer")
        self._thread.start()

    def stop(self):
        if self._client is not None:
            try:
                self._client.disconnect()
            except Exception:
                pass

    def _run(self):
        # ponytail: connect-retry loop in a plain thread; paho loop_forever only
        # covers reconnects after the first successful connect. Swap to
        # aiomqtt/async client if thread-count or QoS ever matters.
        while True:
            try:
                client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
                self._client = client
                if settings.mqtt_username:
                    client.username_pw_set(settings.mqtt_username, settings.mqtt_password or None)
                client.on_connect = self._on_connect
                client.on_message = self._on_message
                host, _, port = settings.mqtt_url.rpartition(":")
                client.connect(host or settings.mqtt_url, int(port) if port else 1883)
                client.reconnect_delay_set(min_delay=1, max_delay=30)
                client.loop_forever()
                return  # loop_forever returns only after disconnect()
            except Exception:
                logger.exception("MQTT connect failed — retrying in 5s")
                time.sleep(5)

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        client.subscribe([(EVENTS_TOPIC, 1), (LWT_TOPIC, 1)])

    def _on_message(self, client, userdata, msg):
        from app.core.db import SessionLocal  # local import: avoid engine at module import in tests
        db = SessionLocal()
        try:
            handle_message(db, msg.topic, msg.payload)
        finally:
            db.close()
