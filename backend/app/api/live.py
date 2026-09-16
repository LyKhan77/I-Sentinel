from urllib.parse import urlsplit, urlunsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response

from app.api.deps import get_current_user
from app.core.config import settings
from app.models.camera import Camera
from app.core.db import get_db

router = APIRouter(prefix="/api/v1/cameras", tags=["cameras"])


def _public_host(request: Request) -> str:
    """Host go2rtc yang dipakai browser.

    Prioritas: `GO2RTC_PUBLIC_HOST` (eksplisit, tahan reverse proxy) → host dari
    request. Header Host tidak bisa dipercaya begitu ada proxy di depan: proxy
    Vite dev menggantinya jadi `localhost:8000`, sehingga klien LAN menerima
    `localhost:1984` yang menunjuk ke mesin klien sendiri dan live view mati.
    """
    return settings.go2rtc_public_host.strip() or request.url.hostname or "localhost"


def _rewrite_host(url: str, host: str) -> str:
    """go2rtc URL host → host yang bisa dijangkau browser, port go2rtc tetap."""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, f"{host}:{parts.port}", parts.path, parts.query, ""))


@router.get("/{camera_id}/snapshot")
def camera_snapshot(camera_id: int, user=Depends(get_current_user), db=Depends(get_db)):
    """Proxy frame JPEG go2rtc lewat API.

    Klien LAN tidak bisa menjangkau port go2rtc (1984): firewall server hanya
    membuka 8000/5173/1883, dan go2rtc tidak punya autentikasi sendiri. Karena
    itu snapshot diambil dari sisi server dan diteruskan lewat port API yang
    sudah terbuka DAN sudah di belakang `get_current_user`.

    Efek samping yang tidak diinginkan: tanpa proxy ini URL `snapshot` yang
    dikirim ke browser menunjuk ke host yang tak terjangkau, dan tiap tile
    menunggu sampai timeout (5 detik per kamera).
    """
    cam = db.get(Camera, camera_id)
    if not cam:
        raise HTTPException(404, "camera not found")
    url = f"{settings.go2rtc_url.rstrip('/')}/api/frame.jpeg"
    try:
        upstream = httpx.get(url, params={"src": f"cam_{cam.id}"}, timeout=5.0)
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"go2rtc unreachable: {type(exc).__name__}") from exc
    if upstream.status_code != 200:
        raise HTTPException(502, f"go2rtc returned {upstream.status_code}")
    return Response(
        content=upstream.content,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/{camera_id}/live")
def live_urls(camera_id: int, request: Request, user=Depends(get_current_user), db=Depends(get_db)):
    cam = db.get(Camera, camera_id)
    if not cam:
        raise HTTPException(404, "camera not found")
    base = settings.go2rtc_url.rstrip("/")
    sub = f"cam_{cam.id}"
    main = f"{sub}_main"
    host = _public_host(request)
    return {
        "camera_id": cam.id,
        "streams": {"sub": sub, "main": main},
        # playback = MAINSTREAM; substream milik AI (vision pull RTSP lokal) + snapshot fallback
        "webrtc": _rewrite_host(f"{base}/api/ws?src={main}", host),
        "mse": _rewrite_host(f"{base}/api/stream.mse?src={main}", host),
        "hls": _rewrite_host(f"{base}/api/stream.m3u8?src={main}", host),
        # same-origin + di belakang auth: satu-satunya bentuk yang jalan dari LAN
        "snapshot": f"/api/v1/cameras/{cam.id}/snapshot",
    }
