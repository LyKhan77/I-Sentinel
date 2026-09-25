import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin
from app.core.db import get_db
from app.models.camera import Camera
from app.models.credential_profile import CredentialProfile
from app.models.stream_source import StreamSource
from app.schemas.credential_profile import (
    CredentialProfileIn,
    CredentialProfileOut,
    CredentialProfilePatch,
)
from app.services import secret_store
from app.services.go2rtc import sync_camera


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/credential-profiles", tags=["credential-profiles"])


def _duplicate_name(db: Session, name: str, profile_id: int | None = None) -> bool:
    query = db.query(CredentialProfile).filter(CredentialProfile.name == name)
    if profile_id is not None:
        query = query.filter(CredentialProfile.id != profile_id)
    return query.first() is not None


def _in_use(db: Session, profile_id: int) -> bool:
    if db.query(Camera).filter(Camera.credential_override_id == profile_id, Camera.enabled.is_(True)).first():
        return True
    return db.query(StreamSource).filter(StreamSource.default_credential_id == profile_id).first() is not None


def _refresh_cameras(db: Session, profile_id: int) -> None:
    from app.services.config_push import publish_node_config_for_camera

    cameras = (
        db.query(Camera)
        .outerjoin(StreamSource, Camera.source_id == StreamSource.id)
        .filter(
            or_(
                Camera.credential_override_id == profile_id,
                StreamSource.default_credential_id == profile_id,
            )
        )
        .all()
    )
    for camera in cameras:
        try:
            sync_camera(camera, delete=not camera.enabled)
        except Exception:
            logger.warning("go2rtc sync after credential mutation failed", exc_info=True)
        try:
            publish_node_config_for_camera(db, camera.id)
        except Exception:
            logger.warning("config push after credential mutation failed", exc_info=True)


def _store_password(key: str, password: str) -> None:
    """Tulis password ke secret store; gagal → 500, profil tidak tersimpan."""
    try:
        secret_store.put(key, password)
    except secret_store.SecretStoreError as exc:
        logger.error("credential store write failed: %s", exc)
        raise HTTPException(500, "failed to store credential") from exc


@router.get("", response_model=list[CredentialProfileOut])
def list_profiles(user=Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(CredentialProfile).order_by(CredentialProfile.name).all()


@router.post("", response_model=CredentialProfileOut)
def create_profile(
    body: CredentialProfileIn,
    admin=Depends(require_admin),
    db: Session = Depends(get_db),
):
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "credential profile name is required")
    if _duplicate_name(db, name):
        raise HTTPException(409, "credential profile name already exists")
    profile = CredentialProfile(
        **body.model_dump(exclude={"name", "username", "secret_ref", "password"}),
        name=name,
        username=body.username.strip(),
        secret_ref=body.secret_ref or "store:pending",
    )
    db.add(profile)
    db.flush()  # butuh id untuk key store
    if body.password is not None:
        key = f"cred_{profile.id}"
        try:
            _store_password(key, body.password)
        except HTTPException:
            db.rollback()
            raise
        profile.secret_ref = f"store:{key}"
    db.commit()
    db.refresh(profile)
    return profile


@router.patch("/{profile_id}", response_model=CredentialProfileOut)
def update_profile(
    profile_id: int,
    body: CredentialProfilePatch,
    admin=Depends(require_admin),
    db: Session = Depends(get_db),
):
    profile = db.get(CredentialProfile, profile_id)
    if profile is None:
        raise HTTPException(404, "credential profile not found")
    data = body.model_dump(exclude_unset=True)
    password = data.pop("password", None)
    if password is not None:
        ref = profile.secret_ref or ""
        key = ref[len("store:"):] if ref.startswith("store:") else f"cred_{profile.id}"
        _store_password(key, password)
        data["secret_ref"] = f"store:{key}"
    if "name" in data:
        data["name"] = data["name"].strip()
        if not data["name"]:
            raise HTTPException(422, "credential profile name is required")
        if _duplicate_name(db, data["name"], profile.id):
            raise HTTPException(409, "credential profile name already exists")
    if "username" in data and data["username"] is not None:
        data["username"] = data["username"].strip()
    if data.get("enabled") is False and _in_use(db, profile.id):
        raise HTTPException(409, "credential profile is used by an enabled camera or source")
    runtime_changed = bool({"username", "secret_ref", "enabled"} & data.keys())
    for key, value in data.items():
        setattr(profile, key, value)
    db.commit()
    db.refresh(profile)
    if runtime_changed:
        _refresh_cameras(db, profile.id)
    return profile
