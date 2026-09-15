"""Node settings (pydantic-settings, env prefix VISION_)."""
from __future__ import annotations

import json

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class CameraCfg(BaseModel):
    camera_id: int
    source_url: str
    ai_fps: float = 5.0


class NodeSettings(BaseSettings):
    node_id: str = "server"
    mqtt_url: str = "localhost:1883"
    mqtt_username: str = ""
    mqtt_password: str = ""
    api_url: str = "http://localhost:8000"
    api_key: str = ""
    data_dir: str = "~/.isentinel"
    detector_model: str = "yolo26s.pt"
    detector_nms: bool = False
    detector_conf: float = 0.4
    detector_imgsz: int = 640
    heartbeat_s: float = 10.0
    log_level: str = "INFO"
    cameras_json: str = ""  # JSON: [{"camera_id": int, "source_url": str, "ai_fps": float}]

    model_config = SettingsConfigDict(env_prefix="VISION_", env_file=".env", extra="ignore")

    def cameras(self) -> list[CameraCfg]:
        return [CameraCfg(**c) for c in json.loads(self.cameras_json)] if self.cameras_json else []
