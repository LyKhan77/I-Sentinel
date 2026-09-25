"""Node settings (pydantic-settings, env prefix VISION_)."""
from __future__ import annotations

import json

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class CameraCfg(BaseModel):
    camera_id: int
    source_url: str
    ai_fps: float = 5.0
    confidence: float | None = None        # override detector conf (None = env/model)
    analyzers: list | None = None          # deprecated: diabaikan (zona = satu-satunya aturan)
    motion: dict = {}                      # {enabled,threshold,min_area,force_interval_s}
    meters_per_pixel: float | None = None  # calibration for speed (m/s)
    zones: list = []  # zones w/ polygon + behaviors (from config apply)


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
    emit_person_detect: bool = False  # debug-only: zones are the real signal
    go2rtc_url: str = "http://localhost:1984"
    clip_pre_s: float = 10.0     # clip starts this long before the first incident event
    clip_post_s: float = 8.0     # ...and ends this long after its tracks were last seen
    clip_max_s: float = 120.0    # hard cap on one incident clip (pre included)
    clip_ring_dir: str = "/dev/shm/isentinel"  # tmpfs for mainstream segments
    log_level: str = "INFO"
    detector_device: str = ""  # ""=auto; "cuda:N" pin (Task 9, fail-fast if invalid)
    face_embed: bool = True   # Opsi B: embed wajah di node; False = kirim crop saja
    face_device: str = ""     # ""=auto, "cpu", "cuda:N"
    face_model_dir: str = ""  # default: <data_dir>/faces_models
    cameras_json: str = ""  # JSON: [{"camera_id": int, "source_url": str, "ai_fps": float}]

    model_config = SettingsConfigDict(env_prefix="VISION_", env_file=".env", extra="ignore")

    def cameras(self) -> list[CameraCfg]:
        return [CameraCfg(**c) for c in json.loads(self.cameras_json)] if self.cameras_json else []
