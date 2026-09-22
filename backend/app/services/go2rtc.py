import logging

import httpx

from app.core.config import settings
from app.services.stream_endpoint import (
    build_rtsp_url as build_endpoint_url,
    resolve_camera_stream,
)

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
    """Build one URL through the shared endpoint resolver."""
    stream = resolve_camera_stream(camera)
    return build_endpoint_url(stream, getattr(camera, field, None))


def stream_names() -> set[str]:
    """Nama semua stream yang terdaftar di go2rtc (set kosong bila go2rtc mati)."""
    try:
        with _client() as c:
            r = c.get("/api/streams")
        if r.is_success:
            return set(r.json().keys())
        logger.warning("go2rtc stream_names -> HTTP %s", r.status_code)
    except Exception:
        logger.warning("go2rtc stream_names failed (go2rtc down?)", exc_info=True)
    return set()


def _targets(camera) -> list[tuple[str, str]]:
    """[(nama_stream, src_url)] untuk `cam_<id>` dan `cam_<id>_main`.

    Kamera single-stream (mis. ZKteco: hanya rtsp_main) tetap mendapat `cam_<id>`
    dengan URL main — konsumen (source vision, klip, snapshot) selalu memakai
    `cam_<id>`, sementara crop wajah butuh `cam_<id>_main`. Berlaku sebaliknya
    bila kamera hanya punya substream.
    """
    stream = resolve_camera_stream(camera)
    sub_src = build_endpoint_url(stream, stream.sub_path)
    main_src = build_endpoint_url(stream, stream.main_path)
    return [
        (f"cam_{camera.id}", sub_src or main_src or ""),
        (f"cam_{camera.id}_main", main_src or sub_src or ""),
    ]


def sync_camera(camera, delete: bool = False) -> None:
    """Add/remove cam_{id} (sub) & cam_{id}_main on go2rtc. Tolerant-down: never raises."""
    for name, src in _targets(camera):
        try:
            if delete:
                remove_stream(name)
            elif src:
                add_stream(name, src)
        except Exception:
            logger.warning("go2rtc sync_camera %s failed", name, exc_info=True)


def sync_all(db) -> dict:
    """Rekonsiliasi stream `cam_*` go2rtc dengan kamera enabled di DB.

    Idempotent: menambah stream yang hilang, menghapus `cam_*` yang tidak lagi
    dimiliki kamera enabled, dan PUT ulang yang sudah ada (agar URL/kredensial
    terbaru terpakai). Stream di luar pola `cam_*` (mis. buatan tangan di
    go2rtc.yaml) tidak pernah disentuh. Tolerant-down: go2rtc mati -> 0 aksi.
    """
    from app.models.camera import Camera  # local: hindari import cycle saat startup

    wanted: dict[str, str] = {}
    for camera in db.query(Camera).filter(Camera.enabled.is_(True)).all():
        for name, src in _targets(camera):
            if src:
                wanted[name] = src

    existing = stream_names()
    added, removed = [], []
    for name, src in wanted.items():
        if add_stream(name, src) and name not in existing:
            added.append(name)
    for name in sorted(existing):
        if name.startswith("cam_") and name not in wanted and remove_stream(name):
            removed.append(name)
    return {"added": added, "removed": removed, "kept": len(wanted) - len(added)}
