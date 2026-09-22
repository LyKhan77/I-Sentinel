from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator


def _path_only(value: str | None) -> str | None:
    if not value:
        return None
    raw = value.strip()
    if "://" in raw:
        parsed = urlsplit(raw)
        raw = parsed.path + (f"?{parsed.query}" if parsed.query else "")
    return raw if raw.startswith("/") else f"/{raw}"


def _host_only(value: str | None) -> str | None:
    if not value:
        return value
    raw = value.strip()
    parsed = urlsplit(raw if "://" in raw else f"//{raw}")
    if not parsed.hostname:
        return raw
    host = parsed.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    try:
        port = parsed.port
    except ValueError:
        port = None
    return f"{host}:{port}" if port is not None else host




class NodeOut(BaseModel):
    id: int
    name: str
    type: str
    status: str
    hw: dict | None = None
    modules: dict | None = None
    detector_device: str | None = None
    face_device: str | None = None

    model_config = {"from_attributes": True}


class StreamSourceSummary(BaseModel):
    id: int
    name: str
    kind: str
    host: str
    port: int
    vendor: str | None
    enabled: bool

    model_config = {"from_attributes": True}

    @field_validator("host", mode="before")
    @classmethod
    def hosts_are_credential_free(cls, value: str) -> str:
        return _host_only(value) or ""


class LocationGroupSummary(BaseModel):
    id: int
    name: str
    sort_order: int
    enabled: bool

    model_config = {"from_attributes": True}


class CredentialProfileSummary(BaseModel):
    id: int
    name: str
    username: str
    enabled: bool

    model_config = {"from_attributes": True}


class CameraOut(BaseModel):
    id: int
    name: str
    location: str | None
    host: str
    rtsp_main: str | None
    rtsp_sub: str | None
    main_path: str | None = None
    sub_path: str | None = None
    node_id: int | None
    source_id: int | None
    location_group_id: int | None
    credential_override_id: int | None
    source: StreamSourceSummary | None = None
    location_group: LocationGroupSummary | None = None
    credential_override: CredentialProfileSummary | None = None
    enabled: bool
    status: str
    probe_main: dict | None
    probe_sub: dict | None
    meters_per_pixel: float | None
    ai_fps: float | None
    confidence: float | None
    analyzers: list[str] | None
    motion_enabled: bool | None

    model_config = {"from_attributes": True}

    @field_validator("host", mode="before")
    @classmethod
    def hosts_are_credential_free(cls, value: str) -> str:
        return _host_only(value) or ""

    @field_validator("rtsp_main", "rtsp_sub", "main_path", "sub_path", mode="before")
    @classmethod
    def paths_are_credential_free(cls, value: str | None) -> str | None:
        return _path_only(value)


class CameraIn(BaseModel):
    name: str
    location: str | None = None
    host: str | None = None
    rtsp_main: str | None = None
    rtsp_sub: str | None = None
    main_path: str | None = None
    sub_path: str | None = None
    node_id: int | None = None
    source_id: int | None = None
    location_group_id: int | None = None
    credential_override_id: int | None = None
    probe_main: dict | None = None
    probe_sub: dict | None = None
    status: str | None = None


class CameraPatch(BaseModel):
    name: str | None = None
    location: str | None = None
    host: str | None = None
    rtsp_main: str | None = None
    rtsp_sub: str | None = None
    main_path: str | None = None
    sub_path: str | None = None
    node_id: int | None = None
    source_id: int | None = None
    location_group_id: int | None = None
    credential_override_id: int | None = None
    enabled: bool | None = None
    probe_main: dict | None = None
    probe_sub: dict | None = None
    status: str | None = None
    meters_per_pixel: float | None = Field(default=None, gt=0)
    ai_fps: float | None = Field(default=None, ge=0.5, le=25)
    confidence: float | None = Field(default=None, ge=0.05, le=0.95)
    analyzers: list[str] | None = None
    motion_enabled: bool | None = None

    @field_validator("analyzers")
    @classmethod
    def valid_analyzers(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and not set(value) <= {"intrusion", "loitering", "running", "attendance"}:
            raise ValueError("invalid analyzer")
        return value


class CameraImportEntry(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    location: str | None = Field(default=None, max_length=128)
    host: str | None = Field(default=None, min_length=1, max_length=255)
    rtsp_main: str | None = Field(default=None, max_length=255)
    rtsp_sub: str | None = Field(default=None, max_length=255)
    main_path: str | None = Field(default=None, max_length=255)
    sub_path: str | None = Field(default=None, max_length=255)
    camera_id: int | None = None
    source_id: int | None = None
    source: str | None = Field(default=None, max_length=64)
    location_group_id: int | None = None
    location_group: str | None = Field(default=None, max_length=128)
    credential_override_id: int | None = None
    credential_profile: str | None = Field(default=None, max_length=64)


class CameraImportIn(BaseModel):
    entries: list[CameraImportEntry] = Field(min_length=1, max_length=100)
