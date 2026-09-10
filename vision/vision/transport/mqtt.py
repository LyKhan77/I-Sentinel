"""MQTT transport: QoS1 event publish, disk queue on failure, flush on reconnect."""
from __future__ import annotations

import json
import logging
import os

import paho.mqtt.client as mqtt

from .queue import DiskQueue

log = logging.getLogger(__name__)

EVENTS_TOPIC = "isentinel/events"


class MqttTransport:
    def __init__(self, cfg):
        self.cfg = cfg
        self._queue = DiskQueue(os.path.join(os.path.expanduser(cfg.data_dir), "queue"))
        self._client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2, client_id=f"vision-{cfg.node_id}-{os.getpid()}"
        )
        if cfg.mqtt_username:
            self._client.username_pw_set(cfg.mqtt_username, cfg.mqtt_password or None)
        self._client.will_set(
            f"isentinel/nodes/{cfg.node_id}/lwt", '{"status":"offline"}', retained=True, qos=1
        )
        self._client.on_connect = self._on_connect
        host, _, port = cfg.mqtt_url.rpartition(":")
        self._client.connect(host or cfg.mqtt_url, int(port) if port else 1883)
        self._client.loop_start()  # network thread + auto-reconnect

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        self._flush(client)

    def _flush(self, client) -> None:
        while True:
            item = self._queue.pop()
            if item is None:
                return
            seq, event = item
            info = client.publish(EVENTS_TOPIC, json.dumps(event), qos=1)
            if info.rc != 0:
                log.warning("queue flush stopped: publish rc=%s (event stays queued)", info.rc)
                return
            self._queue.remove(seq)

    def publish_event(self, event: dict) -> None:
        if not self._client.is_connected():
            self._queue.put(event)
            return
        info = self._client.publish(EVENTS_TOPIC, json.dumps(event), qos=1)
        if info.rc != 0:
            self._queue.put(event)

    def publish_heartbeat(self, hb: dict) -> None:
        self._client.publish(
            f"isentinel/nodes/{self.cfg.node_id}/heartbeat", json.dumps(hb), qos=0, retain=False
        )

    def close(self) -> None:
        # graceful: just disconnect. LWT only fires on ungraceful drop; backend
        # marks node offline via heartbeat timeout later.
        self._client.loop_stop()
        self._client.disconnect()
