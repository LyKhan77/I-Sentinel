import asyncio
import json
import logging
import threading
from datetime import datetime, timezone
import time

import paho.mqtt.client as mqtt

from app.core.config import settings
from app.models import Event, Node
from app.schemas.event import EventIn, EventOut
from app.services import alerting, attendance, monitoring_history, node_health
from app.services.ingest import ingest_event
from app.ws.hub import hub

logger = logging.getLogger(__name__)

EVENTS_TOPIC = "isentinel/events"
MEDIA_TOPIC = "isentinel/events/media"
FACE_TOPIC = "isentinel/events/face"
DETECTIONS_PREFIX = "isentinel/detections/"
LWT_TOPIC = "isentinel/nodes/+/lwt"
HEARTBEAT_TOPIC = "isentinel/nodes/+/heartbeat"

connected = threading.Event()  # status koneksi consumer ke broker (monitoring)


def _cameras(raw) -> list[dict]:
    """Heartbeat baru: [{id, worker, state, ...}]; lama: [id] → [{"id": id}] (tanpa statistik)."""
    if not isinstance(raw, list):
        return []
    out = []
    for c in raw:
        if isinstance(c, dict) and isinstance(c.get("id"), int):
            out.append(c)
        elif isinstance(c, int) and not isinstance(c, bool):
            out.append({"id": c})
    return out


def handle_message(db, topic: str, payload: bytes) -> None:
    """Parse one MQTT message and ingest it. Never raises."""
    try:
        try:
            data = json.loads(payload)
        except (ValueError, UnicodeDecodeError):
            logger.warning("Malformed JSON on %s", topic)
            return

        if topic.startswith(DETECTIONS_PREFIX):
            try:
                asyncio.run(hub.broadcast({"type": "detections", **data}))
            except Exception:
                logger.exception("detections broadcast failed")
            return

        if topic == EVENTS_TOPIC:
            try:
                event = EventIn.model_validate(data)
            except Exception:
                logger.warning("Invalid event payload on %s", topic)
                return
            data["ts_event"] = event.ts_event
            # embedding biometrik tidak pernah masuk tabel event/WS: dipisah sebelum ingest
            # commit, diteruskan langsung ke matcher (jalur error pun tak menyisakannya)
            embedding = None
            if isinstance(data.get("payload"), dict):
                data["payload"] = dict(data["payload"])
                embedding = data["payload"].pop("embedding", None)
            status, ev = ingest_event(db, data)
            if status == "created" and ev is not None:
                # attendance dulu: keputusan alert absensi butuh match_reason
                try:
                    attendance.handle_face_event(db, ev, embedding=embedding)
                except Exception:
                    db.rollback()
                    logger.exception("attendance failed for event %s", ev.event_id)
                try:
                    alerting.handle(db, ev)
                except Exception:
                    db.rollback()
                    logger.exception("alerting failed for event %s", ev.event_id)
                try:
                    from app.services.ai_worker import worker
                    worker.maybe_enqueue_caption(db, ev)
                except Exception:
                    db.rollback()
                    logger.exception("AI caption hook failed for event %s", ev.event_id)
                try:
                    from app.services import intrusion_face
                    if intrusion_face.wants_identity(db, ev):
                        intrusion_face.schedule_unverified(ev.event_id)
                except Exception:
                    db.rollback()
                    logger.exception("identity fallback schedule failed for event %s", ev.event_id)
                asyncio.run(hub.broadcast(EventOut.model_validate(ev).model_dump(mode="json")))
        elif topic == MEDIA_TOPIC:
            event_id = data.get("event_id")
            ev = db.query(Event).filter_by(event_id=event_id).first() if event_id else None
            if ev is None:
                logger.warning("media update for unknown event %r", event_id)
                return
            for col in ("clip_path", "snapshot_path"):
                if data.get(col):
                    setattr(ev, col, data[col])
            # detik mulai event ini di dalam klip insiden bersama (UI: #t=offset)
            offset = data.get("clip_offset_s")
            if isinstance(offset, (int, float)) and not isinstance(offset, bool) and offset >= 0:
                ev.payload = {**(ev.payload or {}), "clip_offset_s": offset}
            db.commit()
            if data.get("snapshot_path"):
                try:
                    from app.services.ai_worker import worker
                    worker.maybe_enqueue_caption(db, ev)
                except Exception:
                    db.rollback()
                    logger.exception("AI caption media hook failed for event %s", ev.event_id)
            # F5: snapshot absensi bisa datang belakangan (handle_face_event sudah jalan
            # saat snapshot masih None) — label ulang dari payload yang tersimpan.
            if data.get("snapshot_path") and ev.type == "attendance":
                attendance.annotate_event_snapshot(ev)
        elif topic == FACE_TOPIC:
            from app.services import intrusion_face
            intrusion_face.handle_face_result(db, data if isinstance(data, dict) else {})
        elif topic.startswith("isentinel/nodes/") and topic.endswith("/heartbeat"):
            name = topic.split("/")[2]
            node = db.query(Node).filter_by(name=name).first()
            if node is None:
                logger.warning("heartbeat for unknown node %r", name)
                return
            since = node.last_seen
            node.last_seen = datetime.now(timezone.utc)
            if isinstance(data.get("hw"), dict):
                node.hw = data["hw"]
            modules = None
            if isinstance(data.get("modules"), dict):
                modules = dict(data["modules"])
                if "cameras" in data:
                    modules["cameras"] = _cameras(data.get("cameras"))
                if isinstance(data.get("mqtt_backlog"), int):
                    modules["mqtt_backlog"] = data["mqtt_backlog"]
                node.modules = modules
            db.commit()
            # riwayat S2: nilai heartbeat ini ke bucket menit (modules gabungan: cameras + mqtt_backlog)
            monitoring_history.record(node.id, data.get("hw") if isinstance(data.get("hw"), dict) else None, modules)
            node_health.mark_online(db, node, since=since)
        elif topic.startswith("isentinel/nodes/") and topic.endswith("/lwt"):
            if data.get("status") != "offline":
                return  # "online" dari node (menimpa retained) / payload kosong
            name = topic.split("/")[2]
            node = db.query(Node).filter_by(name=name).first()
            if node is None:
                logger.warning("LWT for unknown node %r", name)
                return
            node_health.mark_offline(db, node, "lwt")
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
                client.on_disconnect = self._on_disconnect
                host, _, port = settings.mqtt_url.rpartition(":")
                client.connect(host or settings.mqtt_url, int(port) if port else 1883)
                client.reconnect_delay_set(min_delay=1, max_delay=30)
                client.loop_forever()
                return  # loop_forever returns only after disconnect()
            except Exception:
                logger.exception("MQTT connect failed — retrying in 5s")
                time.sleep(5)

    def _subscriptions(self):
        return [(EVENTS_TOPIC, 1), (MEDIA_TOPIC, 1), (FACE_TOPIC, 1),
                ("isentinel/detections/+", 0), (LWT_TOPIC, 1), (HEARTBEAT_TOPIC, 0)]

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        connected.set()
        client.subscribe(self._subscriptions())

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        connected.clear()

    def _on_message(self, client, userdata, msg):
        from app.core.db import SessionLocal  # local import: avoid engine at module import in tests
        db = SessionLocal()
        try:
            handle_message(db, msg.topic, msg.payload)
        finally:
            db.close()
