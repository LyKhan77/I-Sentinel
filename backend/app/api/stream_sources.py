import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin
from app.core.db import get_db
from app.models.camera import Camera
from app.models.credential_profile import CredentialProfile
from app.models.stream_source import StreamSource
from app.schemas.stream_source import StreamSourceIn, StreamSourceOut, StreamSourcePatch
from app.services.go2rtc import sync_camera


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/stream-sources", tags=["stream-sources"])


def _credential(db: Session, credential_id: int | None) -> None:
    if credential_id is not None:
        profile = db.get(CredentialProfile, credential_id)
        if profile is None:
            raise HTTPException(422, "credential profile not found")
        if not profile.enabled:
            raise HTTPException(422, "credential profile is disabled")


def _duplicate_name(db: Session, name: str, source_id: int | None = None) -> bool:
    query = db.query(StreamSource).filter(StreamSource.name == name)
    if source_id is not None:
        query = query.filter(StreamSource.id != source_id)
    return query.first() is not None


def _legacy_host(source: StreamSource) -> str:
    return source.host if source.port == 554 else f"{source.host}:{source.port}"


def _refresh_cameras(db: Session, source_id: int) -> None:
    from app.services.config_push import publish_node_config_for_camera

    for camera in db.query(Camera).filter(Camera.source_id == source_id).all():
        try:
            sync_camera(camera, delete=not camera.enabled)
        except Exception:
            logger.warning("go2rtc sync after source mutation failed", exc_info=True)
        try:
            publish_node_config_for_camera(db, camera.id)
        except Exception:
            logger.warning("config push after source mutation failed", exc_info=True)


@router.get("", response_model=list[StreamSourceOut])
def list_sources(user=Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(StreamSource).order_by(StreamSource.name).all()


@router.post("", response_model=StreamSourceOut)
def create_source(
    body: StreamSourceIn,
    admin=Depends(require_admin),
    db: Session = Depends(get_db),
):
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "stream source name is required")
    if _duplicate_name(db, name):
        raise HTTPException(409, "stream source name already exists")
    _credential(db, body.default_credential_id)
    source = StreamSource(**body.model_dump(exclude={"name"}), name=name)
    source.host = source.host.strip()
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


@router.patch("/{source_id}", response_model=StreamSourceOut)
def update_source(
    source_id: int,
    body: StreamSourcePatch,
    admin=Depends(require_admin),
    db: Session = Depends(get_db),
):
    source = db.get(StreamSource, source_id)
    if source is None:
        raise HTTPException(404, "stream source not found")
    data = body.model_dump(exclude_unset=True)
    if "name" in data:
        data["name"] = data["name"].strip()
        if not data["name"]:
            raise HTTPException(422, "stream source name is required")
        if _duplicate_name(db, data["name"], source.id):
            raise HTTPException(409, "stream source name already exists")
    if "host" in data:
        data["host"] = data["host"].strip()
    if "default_credential_id" in data:
        _credential(db, data["default_credential_id"])
    if data.get("enabled") is False and db.query(Camera).filter(
        Camera.source_id == source.id, Camera.enabled.is_(True)
    ).first():
        raise HTTPException(409, "source has enabled cameras; disable cameras first")
    runtime_changed = bool({"host", "port", "default_credential_id", "enabled"} & data.keys())
    for key, value in data.items():
        setattr(source, key, value)
    if runtime_changed and ("host" in data or "port" in data):
        for camera in db.query(Camera).filter(Camera.source_id == source.id).all():
            camera.host = _legacy_host(source)
    db.commit()
    db.refresh(source)
    if runtime_changed:
        _refresh_cameras(db, source.id)
    return source


@router.delete("/{source_id}")
def delete_source(source_id: int, admin=Depends(require_admin), db: Session = Depends(get_db)):
    source = db.get(StreamSource, source_id)
    if source is None:
        raise HTTPException(404, "stream source not found")
    if db.query(Camera).filter(Camera.source_id == source.id).first():
        raise HTTPException(409, "stream source has cameras; disable or move them first")
    db.delete(source)
    db.commit()
    return {"ok": True}
