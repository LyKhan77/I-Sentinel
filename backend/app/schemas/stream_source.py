from urllib.parse import urlsplit

from typing import Literal

from pydantic import BaseModel, Field, field_validator

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



SourceKind = Literal["nvr", "ip_camera", "unknown"]


class StreamSourceOut(BaseModel):
    id: int
    name: str
    kind: str
    host: str
    port: int
    vendor: str | None
    default_credential_id: int | None
    enabled: bool

    model_config = {"from_attributes": True}
    @field_validator("host", mode="before")
    @classmethod
    def output_host_is_credential_free(cls, value: str) -> str:
        return _host_only(value) or ""



class StreamSourceIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    kind: SourceKind = "unknown"
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(default=554, ge=1, le=65535)
    vendor: str | None = Field(default=None, max_length=64)
    default_credential_id: int | None = None
    enabled: bool = True

    @field_validator("host")
    @classmethod
    def host_is_plain(cls, value: str) -> str:
        value = value.strip()
        if not value or any(char.isspace() for char in value) or "@" in value or "://" in value or "/" in value:
            raise ValueError("host must be a plain hostname or IP address")
        return value


class StreamSourcePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    kind: SourceKind | None = None
    host: str | None = Field(default=None, min_length=1, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    vendor: str | None = Field(default=None, max_length=64)
    default_credential_id: int | None = None
    enabled: bool | None = None

    @field_validator("host")
    @classmethod
    def host_is_plain(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not value or any(char.isspace() for char in value) or "@" in value or "://" in value or "/" in value:
            raise ValueError("host must be a plain hostname or IP address")
        return value
