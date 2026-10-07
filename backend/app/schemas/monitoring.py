"""Kontrak response GET /api/v1/monitoring (kondisi saat ini; S1 tanpa riwayat)."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


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
    funnel: dict | None = None


class CameraStreamOut(BaseModel):
    registered: bool | None = None


class CameraHealthOut(BaseModel):
    id: int
    name: str
    location: str | None = None
    node_id: int | None = None
    node_name: str | None = None
    enabled: bool
    analyzed: bool = False  # punya zona aktif ber-behavior → worker vision diharapkan jalan
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


class PointOut(BaseModel):
    t: str
    avg: float | None = None
    max: float | None = None
    min: float | None = None


class GpuSeriesOut(BaseModel):
    util_pct: list[PointOut] = []
    vram_pct: list[PointOut] = []
    temp_c: list[PointOut] = []


class NodeSeriesOut(BaseModel):
    cpu_pct: list[PointOut]
    ram_pct: list[PointOut]
    ms_avg: list[PointOut]
    ms_max: list[PointOut]
    infer_fps: list[PointOut]
    mqtt_backlog: list[PointOut]
    gpus: dict[str, GpuSeriesOut]


class CameraSeriesOut(BaseModel):
    id: int
    name: str
    fps: list[PointOut]
    frame_age_s: list[PointOut]
    target_fps: float | None = None


class OfflineOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    from_: str = Field(alias="from")
    to: str | None = None


class NodeHistoryOut(BaseModel):
    id: int
    name: str
    series: NodeSeriesOut
    cameras: list[CameraSeriesOut]
    offline: list[OfflineOut]


class MonitoringHistoryOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    range: str
    bucket_s: int
    from_: str = Field(alias="from")
    to: str
    nodes: list[NodeHistoryOut]


from typing import Literal


class HealthRuleOut(BaseModel):
    rule: str
    enabled: bool
    threshold: float
    duration_min: int
    severity: str
    telegram: bool
    unit: str
    min: float
    max: float
    target: str


class HealthRulePatch(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    enabled: bool | None = None
    threshold: float | None = None
    duration_min: int | None = None
    severity: Literal["warning", "critical"] | None = None
    telegram: bool | None = None


class HealthAlertOut(BaseModel):
    id: int
    rule: str
    target: str
    label: str
    node_id: int
    camera_id: int | None = None
    severity: str
    value: float | None = None
    threshold: float
    unit: str
    started_at: datetime
    resolved_at: datetime | None = None


class HealthAlertsOut(BaseModel):
    active: list[HealthAlertOut]
    recent: list[HealthAlertOut]
