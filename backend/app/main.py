import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.auth import router as auth_router
from app.api.users import router as users_router
from app.core.config import settings
from app.core.db import Base, get_db, SessionLocal
from app.core.security import hash_password
from app.models import user as _u, node as _n, camera as _c, setting as _s  # noqa: F401 — register tables
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
    # honor dependency_overrides so tests (SQLite) bootstrap against the test DB
    gen = app.dependency_overrides.get(get_db, get_db)()
    db = next(gen) if hasattr(gen, "__next__") else gen
    try:
        _bootstrap(db)
    finally:
        db.close()
        if hasattr(gen, "__next__"): gen.close()
    yield


app = FastAPI(title="I-Sentinel API", version="0.1.0", lifespan=lifespan)
app.include_router(auth_router)
app.include_router(users_router)
from app.api.nodes import router as nodes_router
from app.api.cameras import router as cameras_router
app.include_router(nodes_router)
app.include_router(cameras_router)


@app.get("/api/v1/health")
def health(): return {"status": "ok"}
