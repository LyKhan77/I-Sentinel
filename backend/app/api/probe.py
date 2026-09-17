from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.core.db import get_db
from app.models.camera import Camera
from app.models.credential_profile import CredentialProfile
from app.models.stream_source import StreamSource
from app.services.probe import probe_camera, probe_exact
from app.services.stream_endpoint import (
    StreamEndpointError,
    resolve_source_stream,
    resolve_stream,
)


router = APIRouter(prefix="/api/v1/cameras", tags=["cameras"])


class ProbeIn(BaseModel):
    host: str | None = None
    camera_id: int | None = None
    source_id: int | None = None
    credential_override_id: int | None = None
    main_path: str | None = None
    sub_path: str | None = None


def _source(db: Session, source_id: int | None) -> StreamSource | None:
    if source_id is None:
        return None
    source = db.get(StreamSource, source_id)
    if source is None:
        raise HTTPException(422, "stream source not found")
    if not source.enabled:
        raise HTTPException(422, "stream source is disabled")
    return source


def _credential(db: Session, credential_id: int | None) -> CredentialProfile | None:
    if credential_id is None:
        return None
    profile = db.get(CredentialProfile, credential_id)
    if profile is None:
        raise HTTPException(422, "credential profile not found")
    if not profile.enabled:
        raise HTTPException(422, "credential profile is disabled")
    return profile


def _source_host(source: StreamSource) -> str:
    return source.host if source.port == 554 else f"{source.host}:{source.port}"


@router.post("/probe")
def probe(body: ProbeIn, admin=Depends(require_admin), db: Session = Depends(get_db)):
    cam = db.get(Camera, body.camera_id) if body.camera_id is not None else None
    if body.camera_id is not None and cam is None:
        raise HTTPException(404, "camera not found")

    source = _source(db, body.source_id)
    credential = _credential(db, body.credential_override_id)
    if cam is not None:
        source = source if body.source_id is not None else cam.source
        credential = (
            credential
            if body.credential_override_id is not None
            else cam.credential_override
        )
    if source is None and credential is not None:
        raise HTTPException(422, "credential override requires a stream source")

    main_path = body.main_path if body.main_path is not None else (
        cam.rtsp_main if cam is not None else None
    )
    sub_path = body.sub_path if body.sub_path is not None else (
        cam.rtsp_sub if cam is not None else None
    )
    host = body.host or (cam.host if cam is not None else None)
    exact = main_path is not None or sub_path is not None
    try:
        if exact:
            if source is not None:
                stream = resolve_source_stream(source, credential, main_path, sub_path)
            else:
                stream = resolve_stream(
                    credential_override=credential,
                    legacy_host=host,
                    main_path=main_path,
                    sub_path=sub_path,
                )
            result = probe_exact(stream)
        else:
            if source is not None:
                stream = resolve_source_stream(source, credential)
                host = _source_host(source)
                result = probe_camera(host, stream.username, stream.password)
            else:
                if not host:
                    raise HTTPException(422, "camera host or exact source endpoint is required")
                result = probe_camera(host)
    except StreamEndpointError as exc:
        raise HTTPException(422, str(exc)) from exc

    if cam is not None:
        cam.probe_main = result["main"]
        cam.probe_sub = result["sub"]
        cam.status = "online" if result["main"] or result["sub"] else "offline"
        db.commit()
        db.refresh(cam)
    return result
