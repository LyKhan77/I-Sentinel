import logging
from urllib.parse import quote

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


def _client() -> httpx.Client:
    return httpx.Client(base_url=settings.go2rtc_url, timeout=5.0)


def add_stream(name: str, src: str) -> bool:
    try:
        with _client() as c:
            r = c.put("/api/streams", params={"name": name, "src": src})
        if r.is_success:
            return True
        logger.warning("go2rtc add_stream %s -> HTTP %s", name, r.status_code)
    except Exception:
        logger.warning("go2rtc add_stream %s failed (go2rtc down?)", name, exc_info=True)
    return False


def remove_stream(name: str) -> bool:
    try:
        with _client() as c:
            r = c.delete("/api/streams", params={"src": name})
        if r.is_success:
            return True
        logger.warning("go2rtc remove_stream %s -> HTTP %s", name, r.status_code)
    except Exception:
        logger.warning("go2rtc remove_stream %s failed (go2rtc down?)", name, exc_info=True)
    return False


def stream_info(name: str) -> dict | None:
    try:
        with _client() as c:
            r = c.get("/api/streams", params={"src": name})
        if r.is_success:
            return r.json()
        logger.warning("go2rtc stream_info %s -> HTTP %s", name, r.status_code)
    except Exception:
        logger.warning("go2rtc stream_info %s failed (go2rtc down?)", name, exc_info=True)
    return None


def build_rtsp_url(camera, field: str = "rtsp_sub") -> str | None:
    path = getattr(camera, field, None)
    if not path:
        return None
    u = quote(settings.cam_username or "", safe="")
    p = quote(settings.cam_password or "", safe="")
    auth = f"{u}:{p}@" if (u or p) else ""
    return f"rtsp://{auth}{camera.host}{path}"


def sync_camera(camera, delete: bool = False) -> None:
    """Add/remove cam_{id} (sub) & cam_{id}_main on go2rtc. Tolerant-down: never raises."""
    for field, suffix in (("rtsp_sub", ""), ("rtsp_main", "_main")):
        name = f"cam_{camera.id}{suffix}"
        try:
            if delete:
                remove_stream(name)
            else:
                src = build_rtsp_url(camera, field)
                if src:
                    add_stream(name, src)
        except Exception:
            logger.warning("go2rtc sync_camera %s failed", name, exc_info=True)
