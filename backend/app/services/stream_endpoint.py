import os
import re
from dataclasses import dataclass
from urllib.parse import quote, urlsplit

from app.core.config import settings
from app.services import secret_store


class StreamEndpointError(ValueError):
    """Raised when a camera endpoint cannot be resolved safely."""


@dataclass(frozen=True)
class EffectiveStream:
    host: str
    port: int
    username: str | None
    password: str | None
    main_path: str | None
    sub_path: str | None


def split_host_port(value: str) -> tuple[str, int]:
    raw = value.strip()
    parsed = urlsplit(raw if "://" in raw else f"//{raw}")
    host = parsed.hostname or raw
    try:
        port = parsed.port or 554
    except ValueError as exc:
        raise StreamEndpointError("invalid camera host port") from exc
    if not host:
        raise StreamEndpointError("camera host is empty")
    return host, port


def path_only(value: str | None) -> str | None:
    if not value:
        return None
    raw = value.strip()
    if "://" in raw:
        parsed = urlsplit(raw)
        raw = parsed.path + (f"?{parsed.query}" if parsed.query else "")
    return raw if raw.startswith("/") else f"/{raw}"


def _secret(secret_ref: str) -> str:
    if secret_ref.startswith("store:"):
        try:
            value = secret_store.get(secret_ref[len("store:"):])
        except secret_store.SecretStoreError as exc:
            raise StreamEndpointError("credential reference is unavailable") from exc
        if value is None:
            raise StreamEndpointError("credential reference is unavailable")
        return value
    if not secret_ref.startswith("env:"):
        raise StreamEndpointError("unsupported credential reference")
    name = secret_ref[4:]
    if not re.fullmatch(r"[A-Z][A-Z0-9_]*", name):
        raise StreamEndpointError("invalid credential reference")
    value = os.environ.get(name)
    if value is None and name == "CAM_USERNAME":
        value = settings.cam_username
    elif value is None and name == "CAM_PASSWORD":
        value = settings.cam_password
    if value is None:
        raise StreamEndpointError("credential reference is unavailable")
    return value


def _profile_credentials(profile) -> tuple[str | None, str | None]:
    if not profile.enabled:
        raise StreamEndpointError("credential profile is disabled")
    return profile.username or None, _secret(profile.secret_ref)


def resolve_stream(
    source=None,
    credential_override=None,
    legacy_host: str | None = None,
    main_path: str | None = None,
    sub_path: str | None = None,
) -> EffectiveStream:
    if source is None:
        if not legacy_host:
            raise StreamEndpointError("camera host is empty")
        host, port = split_host_port(legacy_host)
        username = settings.cam_username or None
        password = settings.cam_password or None
    else:
        if not source.enabled:
            raise StreamEndpointError("stream source is disabled")
        host, port = source.host, source.port or 554
        profile = credential_override or getattr(source, "default_credential", None)
        if profile is None:
            username = settings.cam_username or None
            password = settings.cam_password or None
        else:
            username, password = _profile_credentials(profile)

    return EffectiveStream(
        host=host,
        port=port,
        username=username,
        password=password,
        main_path=path_only(main_path),
        sub_path=path_only(sub_path),
    )


def resolve_source_stream(
    source,
    credential_override=None,
    main_path: str | None = None,
    sub_path: str | None = None,
) -> EffectiveStream:
    return resolve_stream(source, credential_override, main_path=main_path, sub_path=sub_path)


def resolve_camera_stream(camera) -> EffectiveStream:
    source = getattr(camera, "source", None)
    return resolve_stream(
        source=source,
        credential_override=getattr(camera, "credential_override", None),
        legacy_host=getattr(camera, "host", None),
        main_path=getattr(camera, "rtsp_main", None),
        sub_path=getattr(camera, "rtsp_sub", None),
    )


def build_rtsp_url(stream: EffectiveStream, path: str | None) -> str | None:
    path = path_only(path)
    if not path:
        return None
    user = quote(stream.username or "", safe="")
    password = quote(stream.password or "", safe="")
    auth = f"{user}:{password}@" if (user or password) else ""
    authority = stream.host if stream.port == 554 else f"{stream.host}:{stream.port}"
    return f"rtsp://{auth}{authority}{path}"
