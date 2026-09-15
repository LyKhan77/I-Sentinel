"""MQTT transport: QoS1 event publish, disk queue on failure, flush on reconnect."""
from __future__ import annotations

import json
import logging
import os

import paho.mqtt.client as mqtt

from .queue import DiskQueue

log = logging.getLogger(__name__)

EVENTS_TOPIC = "isentinel/events"
MEDIA_TOPIC = "isentinel/events/media"


class MqttTransport:
    def __init__(self, cfg, on_config=None):
        self.cfg = cfg
        self._on_config = on_config  # callable(cfg_dict), fired on config topic message
        self._queue = DiskQueue(os.path.join(os.path.expanduser(cfg.data_dir), "queue"))
        self._client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2, client_id=f"vision-{cfg.node_id}-{os.getpid()}"
        )
        if cfg.mqtt_username:
            self._client.username_pw_set(cfg.mqtt_username, cfg.mqtt_password or None)
        self._client.will_set(
            f"isentinel/nodes/{cfg.node_id}/lwt", '{"status":"offline"}', qos=1, retain=True
        )
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._config_topic = f"isentinel/config/{cfg.node_id}"
        host, _, port = cfg.mqtt_url.rpartition(":")
        self._client.connect(host or cfg.mqtt_url, int(port) if port else 1883)
        self._client.loop_start()  # network thread + auto-reconnect

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        client.subscribe(self._config_topic, qos=1)
        self._flush(client)

    def _on_message(self, client, userdata, msg):
        if msg.topic != self._config_topic or self._on_config is None:
            return
        try:
            self._on_config(json.loads(msg.payload.decode("utf-8")))
        except (ValueError, UnicodeDecodeError):
            log.exception("invalid config payload on %s", self._config_topic)

    def _flush(self, client) -> None:
        while True:
            item = self._queue.pop()
            if item is None:
                return
            seq, payload = item
            info = client.publish(payload["_topic"], json.dumps(payload["data"]), qos=1)
            if info.rc != 0:
                log.warning("queue flush stopped: publish rc=%s (payload stays queued)", info.rc)
                return
            self._queue.remove(seq)

    def _publish(self, topic: str, payload_dict: dict) -> None:
        if not self._client.is_connected():
            self._queue.put({"_topic": topic, "data": payload_dict})
            return
        info = self._client.publish(topic, json.dumps(payload_dict), qos=1)
        if info.rc != 0:
            self._queue.put({"_topic": topic, "data": payload_dict})

    def publish_event(self, event: dict) -> None:
        self._publish(EVENTS_TOPIC, event)

    def publish_media(self, payload: dict) -> None:
        self._publish(MEDIA_TOPIC, payload)

    def publish_heartbeat(self, hb: dict) -> None:
        self._client.publish(
            f"isentinel/nodes/{self.cfg.node_id}/heartbeat", json.dumps(hb), qos=0, retain=False
        )

    def close(self) -> None:
        # graceful: just disconnect. LWT only fires on ungraceful drop; backend
        # marks node offline via heartbeat timeout later.
        self._client.loop_stop()
        self._client.disconnect()
