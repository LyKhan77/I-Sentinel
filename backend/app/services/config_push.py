import json
import logging

import paho.mqtt.client as mqtt
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.camera import Camera
from app.models.node import Node
from app.models.zone import Zone
from app.services.stream_endpoint import StreamEndpointError, build_rtsp_url, resolve_camera_stream

logger = logging.getLogger(__name__)


DEFAULT_FPS = 5.0


def build_node_config(db: Session, node: Node) -> dict:
    detector = {
        "model": settings.detector_model,
        "nms": settings.detector_nms,
        "conf": settings.detector_conf,
        "imgsz": settings.detector_imgsz,
    }
    cameras = []
    for cam in (
        db.query(Camera)
        .filter(Camera.node_id == node.id, Camera.enabled.is_(True))
        .order_by(Camera.id)
    ):
        zones = [
            {
                "id": z.id,
                "name": z.name,
                "type": z.type,
                "direction": z.direction,
                "polygon": z.polygon,
                "schedule": z.schedule,
                "severity": z.severity,
                "rate_limit_min": z.rate_limit_min,
                "loiter_seconds": z.loiter_seconds,
                "speed_limit_mps": z.speed_limit_mps,
                "snapshot": z.snapshot,
                "telegram": z.telegram,
            }
            for z in db.query(Zone)
            .filter(Zone.camera_id == cam.id, Zone.active.is_(True))
            .order_by(Zone.id)
        ]
        if node.type == "server":
            source_url = f"rtsp://localhost:8554/cam_{cam.id}"
        else:
            try:
                stream = resolve_camera_stream(cam)
                source_url = build_rtsp_url(stream, stream.sub_path)
            except StreamEndpointError:
                logger.warning("node config camera %s endpoint unavailable", cam.id)
                continue
            if source_url is None:
                logger.warning("node config camera %s has no substream", cam.id)
                continue
        cameras.append({
            "camera_id": cam.id,
            "source_url": source_url,
            "ai_fps": DEFAULT_FPS,
            "meters_per_pixel": cam.meters_per_pixel,
        } | {"zones": zones})
    return {"node_id": node.name, "detector": detector, "cameras": cameras}


def publish_node_config(client_or_none, db: Session, node_name: str) -> bool:
    """Build + publish node config JSON to isentinel/config/{node_name}. Never raises."""
    try:
        node = db.query(Node).filter_by(name=node_name).first()
        if node is None:
            logger.warning("config push: unknown node %r", node_name)
            return False
        payload = json.dumps(build_node_config(db, node)).encode()
        topic = f"isentinel/config/{node_name}"

        client = client_or_none
        owned = client is None
        if owned:
            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
            if settings.mqtt_username:
                client.username_pw_set(settings.mqtt_username, settings.mqtt_password or None)
            host, _, port = settings.mqtt_url.rpartition(":")
            client.connect(host or settings.mqtt_url, int(port) if port else 1883)
            client.loop_start()
        try:
            info = client.publish(topic, payload, qos=1, retain=True)
            if getattr(info, "rc", 0) != 0:
                raise RuntimeError(f"publish rc={info.rc}")
        finally:
            if owned:
                client.loop_stop()
                client.disconnect()
        return True
    except Exception:
        logger.warning("config push for %r failed", node_name, exc_info=True)
        return False


def publish_node_config_for_camera(db: Session, camera_id: int) -> bool:
    cam = db.get(Camera, camera_id)
    if cam is None or cam.node_id is None:
        return False
    node = db.get(Node, cam.node_id)
    if node is None:
        return False
    return publish_node_config(None, db, node.name)


def republish_all(db: Session) -> bool:
    nodes = db.query(Node).order_by(Node.id).all()
    return all(publish_node_config(None, db, n.name) for n in nodes)
