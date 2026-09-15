from urllib.parse import urlsplit, urlunsplit

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.deps import get_current_user
from app.core.config import settings
from app.models.camera import Camera
from app.core.db import get_db

router = APIRouter(prefix="/api/v1/cameras", tags=["cameras"])


def _rewrite_host(url: str, host: str) -> str:
    """go2rtc URL host → host dari request (browser LAN), port go2rtc tetap."""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, f"{host}:{parts.port}", parts.path, parts.query, ""))


@router.get("/{camera_id}/live")
def live_urls(camera_id: int, request: Request, user=Depends(get_current_user), db=Depends(get_db)):
    cam = db.get(Camera, camera_id)
    if not cam:
        raise HTTPException(404, "camera not found")
    base = settings.go2rtc_url.rstrip("/")
    sub = f"cam_{cam.id}"
    main = f"{sub}_main"
    host = request.url.hostname or "localhost"
    return {
        "camera_id": cam.id,
        "streams": {"sub": sub, "main": main},
        "webrtc": _rewrite_host(f"{base}/api/ws?src={sub}", host),
        "mse": _rewrite_host(f"{base}/api/stream.mse?src={sub}", host),
        "hls": _rewrite_host(f"{base}/api/stream.m3u8?src={sub}", host),
        "snapshot": _rewrite_host(f"{base}/api/frame.jpeg?src={sub}", host),
    }
