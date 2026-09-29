"""Kontrak response GET /api/v1/monitoring (kondisi saat ini; S1 tanpa riwayat)."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class HostOut(BaseModel):
    cpu_pct: float | None = None
    ram_used_mb: int | None = None
    ram_total_mb: int | None = None
    disk_used_pct: float | None = None
    disk_free_gb: float | None = None


class GpuOut(BaseModel):
    idx: int | None = None
    name: str | None = None
    util_pct: float | None = None
    vram_used_mb: float | None = None
    vram_total_mb: float | None = None
    temp_c: float | None = None
    power_w: float | None = None


class DetectorOut(BaseModel):
    model: str | None = None
    device: str | None = None
    ms_avg: float | None = None
    ms_max: float | None = None
    infer_fps: float | None = None


class FaceOut(BaseModel):
    loaded: bool | None = None
    queue: int | None = None


class InferenceOut(BaseModel):
    detector: DetectorOut
    face: FaceOut
    mqtt_backlog: int | None = None


class NodeHealthOut(BaseModel):
    id: int
    name: str
    status: str
    last_seen: str | None = None
    age_s: float | None = None
    health: str
    issues: list[str]
    host: HostOut
    gpus: list[GpuOut]
    inference: InferenceOut


class CameraAiOut(BaseModel):
    state: str | None = None
    fps: float | None = None
    target_fps: float | None = None
    last_frame_age_s: float | None = None
    reconnects_1h: int = 0
    motion_skip_pct: float | None = None


class CameraStreamOut(BaseModel):
    registered: bool | None = None


class CameraHealthOut(BaseModel):
    id: int
    name: str
    location: str | None = None
    node_id: int | None = None
    node_name: str | None = None
    enabled: bool
    health: str
    issues: list[str]
    ai: CameraAiOut | None = None
    stream: CameraStreamOut


class ServiceOut(BaseModel):
    key: str
    health: str
    detail: str | None = None
    latency_ms: float | None = None


class SummaryOut(BaseModel):
    health: str
    cameras: dict[str, int]
    nodes: dict[str, int]
    services: dict[str, int]


class MonitoringOut(BaseModel):
    generated_at: datetime
    summary: SummaryOut
    server: HostOut
    nodes: list[NodeHealthOut]
    cameras: list[CameraHealthOut]
    services: list[ServiceOut]
