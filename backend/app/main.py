import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.auth import router as auth_router
from app.api.users import router as users_router
from app.api.stream_sources import router as stream_sources_router
from app.api.location_groups import router as location_groups_router
from app.api.credential_profiles import router as credential_profiles_router
from app.core.config import settings
from app.core.db import Base, get_db, SessionLocal
from app.core.security import hash_password
from app.models import user as _u, node as _n, camera as _c, setting as _s  # noqa: F401 — register tables
from app.services.events_consumer import EventConsumer
from app.models.user import User
from app.models.node import Node

logger = logging.getLogger(__name__)


def _bootstrap(db) -> None:
    if db.query(User).count() == 0:
        if not settings.admin_password:
            logger.error("ADMIN_PASSWORD empty — skipping admin bootstrap; set it in .env")
        else:
            db.add(User(
                username=settings.admin_username,
                password_hash=hash_password(settings.admin_password),
                role="admin",
            ))
            db.commit()
            logger.info("Bootstrapped admin user %r", settings.admin_username)
    if db.query(Node).count() == 0:
        db.add(Node(name="server", type="server"))
        db.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.jwt_secret == "CHANGE_ME" or len(settings.jwt_secret) < 32:
        logger.warning("JWT secret default/short — set JWT_SECRET in production")
    # honor dependency_overrides so tests (SQLite) bootstrap against the test DB
    gen = app.dependency_overrides.get(get_db, get_db)()
    db = next(gen) if hasattr(gen, "__next__") else gen
    try:
        _bootstrap(db)
        from app.services.config_push import republish_all
        republish_all(db)
        try:
            from app.services.face import refresh_gallery
            refresh_gallery(db)
        except Exception:
            logger.warning("gallery refresh at startup failed", exc_info=True)
        # Rekonsiliasi stream go2rtc (kamera enabled vs cam_* yang terdaftar).
        # Best-effort: go2rtc belum tentu siap saat API start.
        try:
            from app.services.go2rtc import sync_all
            logger.info("go2rtc sync at startup: %s", sync_all(db))
        except Exception:
            logger.warning("go2rtc sync at startup failed", exc_info=True)
    except Exception:
        logger.warning("republish_all at startup failed", exc_info=True)
    finally:
        db.close()
        if hasattr(gen, "__next__"): gen.close()
    consumer = EventConsumer()
    consumer.start()
    try:
        yield
    finally:
        consumer.stop()


app = FastAPI(title="I-Sentinel API", version="0.1.0", lifespan=lifespan)
app.include_router(auth_router)
app.include_router(users_router)
app.include_router(stream_sources_router)
app.include_router(location_groups_router)
app.include_router(credential_profiles_router)
from app.api.nodes import router as nodes_router
from app.api.cameras import router as cameras_router
from app.api.probe import router as probe_router
app.include_router(nodes_router)
app.include_router(cameras_router)
from app.api.live import router as live_router
app.include_router(live_router)
app.include_router(probe_router)


@app.get("/api/v1/health")
def health(): return {"status": "ok"}
from app.api.events import router as events_router
from app.models import event as _e  # noqa: F401 — register table
app.include_router(events_router)
from app.api.zones import router as zones_router
app.include_router(zones_router)
from app.api.alerts import router as alerts_router
from app.api.telegram import router as telegram_router
app.include_router(alerts_router)
app.include_router(telegram_router)

from app.api.storage import router as storage_router
app.include_router(storage_router)
from app.api.employees import router as employees_router
from app.api.shifts import router as shifts_router
from app.api.enrollment import router as enrollment_router
from app.api.attendance import router as attendance_router
app.include_router(employees_router)
app.include_router(shifts_router)
app.include_router(enrollment_router)
app.include_router(attendance_router)
