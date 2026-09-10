from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user
from app.core.config import settings
from app.models.camera import Camera
from app.core.db import get_db

router = APIRouter(prefix="/api/v1/cameras", tags=["cameras"])

@router.get("/{camera_id}/live")
def live_urls(camera_id: int, user=Depends(get_current_user), db=Depends(get_db)):
    cam = db.get(Camera, camera_id)
    if not cam:
        raise HTTPException(404, "camera not found")
    base = settings.go2rtc_url.rstrip("/")
    sub = f"cam_{cam.id}"
    main = f"{sub}_main"
    return {
        "camera_id": cam.id,
        "streams": {"sub": sub, "main": main},
        "webrtc": f"{base}/api/ws?src={sub}",
        "mse": f"{base}/api/stream.mse?src={sub}",
        "hls": f"{base}/api/stream.m3u8?src={sub}",
        "snapshot": f"{base}/api/frame.jpeg?src={sub}",
    }
