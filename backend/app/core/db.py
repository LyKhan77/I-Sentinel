from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from app.core.config import settings

class Base(DeclarativeBase): pass

def engine_kwargs(url: str, cfg=settings) -> dict:
    """Argumen `create_engine`: pool dapat diatur untuk Postgres; SQLite (tes) memakai pool bawaannya."""
    kwargs: dict = {"pool_pre_ping": True}
    if not url.startswith("sqlite"):
        kwargs.update(pool_size=cfg.db_pool_size, max_overflow=cfg.db_max_overflow, pool_timeout=cfg.db_pool_timeout)
    return kwargs


engine = create_engine(settings.database_url, **engine_kwargs(settings.database_url))
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()
