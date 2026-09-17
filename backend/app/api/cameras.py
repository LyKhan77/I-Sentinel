import logging
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin
from app.core.db import get_db
from app.models.attendance import AttendanceEvent
from app.models.camera import Camera
from app.models.credential_profile import CredentialProfile
from app.models.location_group import LocationGroup
from app.models.node import Node
from app.models.stream_source import StreamSource
from app.schemas.camera import CameraImportIn, CameraOut, CameraIn, CameraPatch
from app.services.go2rtc import remove_stream, sync_camera
from app.services.stream_endpoint import path_only, split_host_port


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/cameras", tags=["cameras"])


def _config_push(db: Session, camera_id: int, node_name: str | None = None) -> None:
    try:
        from app.services.config_push import publish_node_config
        if node_name is None:
            from app.services.config_push import publish_node_config_for_camera
            publish_node_config_for_camera(db, camera_id)
        else:
            publish_node_config(None, db, node_name)
    except Exception:
        logger.warning("config push after camera mutation failed", exc_info=True)


def _check_node(db: Session, node_id: int | None) -> None:
    if node_id is not None and not db.query(Node).filter_by(id=node_id).first():
        raise HTTPException(422, "node not found")


def _dup_name(db: Session, name: str, node_id: int | None, exclude_id: int | None = None) -> bool:
    query = db.query(Camera).filter_by(name=name, node_id=node_id)
    if exclude_id is not None:
        query = query.filter(Camera.id != exclude_id)
    return query.first() is not None


def _source(db: Session, source_id: int | None, *, allow_disabled: bool = False) -> StreamSource | None:
    if source_id is None:
        return None
    source = db.get(StreamSource, source_id)
    if source is None:
        raise HTTPException(422, "stream source not found")
    if not allow_disabled and not source.enabled:
        raise HTTPException(422, "stream source is disabled")
    return source


def _group(db: Session, group_id: int | None, *, allow_disabled: bool = False) -> LocationGroup | None:
    if group_id is None:
        return None
    group = db.get(LocationGroup, group_id)
    if group is None:
        raise HTTPException(422, "location group not found")
    if not allow_disabled and not group.enabled:
        raise HTTPException(422, "location group is disabled")
    return group


def _credential(
    db: Session,
    credential_id: int | None,
    *,
    allow_disabled: bool = False,
) -> CredentialProfile | None:
    if credential_id is None:
        return None
    profile = db.get(CredentialProfile, credential_id)
    if profile is None:
        raise HTTPException(422, "credential profile not found")
    if not allow_disabled and not profile.enabled:
        raise HTTPException(422, "credential profile is disabled")
    return profile

 


def _legacy_host(source: StreamSource) -> str:
    return source.host if source.port == 554 else f"{source.host}:{source.port}"


def _canonical_path(value: str | None) -> str | None:
    return path_only(value)


def _import_host(value: str) -> str:
    raw = value.strip().lower()
    parsed = urlsplit(raw if "://" in raw else f"//{raw}")
    host = parsed.hostname or raw
    try:
        port = parsed.port
    except ValueError:
        return raw
    return f"{host}:{port}" if port and port != 554 else host


def _import_path(value: str | None) -> str | None:
    return _canonical_path(value)


def _import_key(host: str, path: str) -> tuple[str, str]:
    return _import_host(host), _import_path(path) or "/"


def _source_key(source_id: int, path: str) -> tuple[int, str]:
    return source_id, _import_path(path) or "/"




def _entry_source(db: Session, entry) -> tuple[StreamSource | None, str | None]:
    if entry.source_id is not None:
        source = db.get(StreamSource, entry.source_id)
        if source is None:
            return None, "NEW SOURCE"
        if entry.source and source.name != entry.source.strip():
            return source, "stream source references differ"
        if not source.enabled:
            return source, "stream source is disabled"
        return source, None
    if entry.source:
        source = db.query(StreamSource).filter_by(name=entry.source.strip()).first()
        if source is None:
            return None, "NEW SOURCE"
        if not source.enabled:
            return source, "stream source is disabled"
        return source, None
    return None, None


def _entry_group(db: Session, entry) -> tuple[LocationGroup | None, str | None]:
    if entry.location_group_id is not None:
        group = db.get(LocationGroup, entry.location_group_id)
        if group is None:
            return None, "location group not found"
        if entry.location_group and group.name != entry.location_group.strip():
            return group, "location group references differ"
        if not group.enabled:
            return group, "location group is disabled"
        return group, None
    if entry.location_group:
        group = db.query(LocationGroup).filter_by(name=entry.location_group.strip()).first()
        if group is None:
            return None, "location group not found"
        if not group.enabled:
            return group, "location group is disabled"
        return group, None
    return None, None


def _entry_credential(db: Session, entry) -> tuple[CredentialProfile | None, str | None]:
    if entry.credential_override_id is not None:
        profile = db.get(CredentialProfile, entry.credential_override_id)
        if profile is None:
            return None, "CREDENTIAL"
        if entry.credential_profile and profile.name != entry.credential_profile.strip():
            return profile, "credential profile references differ"
        if not profile.enabled:
            return profile, "credential profile is disabled"
        return profile, None
    if entry.credential_profile:
        profile = db.query(CredentialProfile).filter_by(name=entry.credential_profile.strip()).first()
        if profile is None:
            return None, "CREDENTIAL"
        if not profile.enabled:
            return profile, "credential profile is disabled"
        return profile, None
    return None, None


def _identity_duplicate(
    db: Session,
    source_id: int | None,
    main_path: str | None,
    exclude_id: int | None = None,
) -> bool:
    if source_id is None or main_path is None:
        return False
    query = db.query(Camera).filter(Camera.source_id == source_id)
    if exclude_id is not None:
        query = query.filter(Camera.id != exclude_id)
    return any(_canonical_path(camera.rtsp_main) == main_path for camera in query)


def _prepare_camera_data(
    db: Session,
    raw: dict,
    current: Camera | None = None,
) -> dict:
    data = dict(raw)
    source_id = data.get("source_id", current.source_id if current else None)
    source = _source(
        db,
        source_id,
        allow_disabled=current is not None and source_id == current.source_id,
    )
    group_id = data.get("location_group_id", current.location_group_id if current else None)
    group = _group(
        db,
        group_id,
        allow_disabled=current is not None and group_id == current.location_group_id,
    )
    if "source_id" in data and data["source_id"] is None and "credential_override_id" not in data:
        credential_id = None
    else:
        credential_id = data.get(
            "credential_override_id",
            current.credential_override_id if current else None,
        )
    credential = _credential(
        db,
        credential_id,
        allow_disabled=current is not None and credential_id == current.credential_override_id,
    )
    if source is None and credential is not None:
        raise HTTPException(422, "credential override requires a stream source")

    if "name" in data or current is None:
        data["name"] = str(data.get("name", "")).strip()
        if not data["name"]:
            raise HTTPException(422, "camera name is required")
    if "main_path" in data and "rtsp_main" in data and (
        _canonical_path(data["main_path"]) != _canonical_path(data["rtsp_main"])
    ):
        raise HTTPException(422, "main_path and rtsp_main differ")
    if "sub_path" in data and "rtsp_sub" in data and (
        _canonical_path(data["sub_path"]) != _canonical_path(data["rtsp_sub"])
    ):
        raise HTTPException(422, "sub_path and rtsp_sub differ")
    if "main_path" in data:
        data["rtsp_main"] = _canonical_path(data.pop("main_path"))
    elif "rtsp_main" in data:
        data["rtsp_main"] = _canonical_path(data["rtsp_main"])
    main_path = _canonical_path(
        data.get("rtsp_main", current.rtsp_main if current else None)
    )
    if "sub_path" in data:
        data["rtsp_sub"] = _canonical_path(data.pop("sub_path"))
    elif "rtsp_sub" in data:
        data["rtsp_sub"] = _canonical_path(data["rtsp_sub"])

    if source is not None:
        if main_path is None:
            raise HTTPException(422, "source cameras require an exact main path")
        data["host"] = _legacy_host(source)
        if "source_id" in raw or current is None:
            data["source_id"] = source.id
    elif "host" in data:
        if not data["host"] or not str(data["host"]).strip():
            raise HTTPException(422, "camera host is required")
        data["host"] = _import_host(str(data["host"]))
    elif current is None:
        raise HTTPException(422, "camera host or stream source is required")

    if "source_id" in raw and source is None:
        data["source_id"] = None
        data["credential_override_id"] = None
    elif credential is not None or "credential_override_id" in raw:
        data["credential_override_id"] = credential.id if credential else None

    if "location_group_id" in raw or current is None:
        data["location_group_id"] = group.id if group else None
    if group is not None and (
        current is None
        or ("location_group_id" in raw and group.id != current.location_group_id)
    ) and "location" not in raw:
        data["location"] = group.name

    return data


def _camera_after(
    name: str,
    location: str | None,
    host: str | None,
    main_path: str | None,
    sub_path: str | None,
    source: StreamSource | None,
    group: LocationGroup | None,
    credential: CredentialProfile | None,
) -> dict:
    return {
        "name": name,
        "location": location,
        "host": host,
        "rtsp_main": main_path,
        "rtsp_sub": sub_path,
        "main_path": main_path,
        "sub_path": sub_path,
        "source_id": source.id if source else None,
        "source": source.name if source else None,
        "location_group_id": group.id if group else None,
        "location_group": group.name if group else None,
        "credential_override_id": credential.id if credential else None,
        "credential_profile": credential.name if credential else None,
    }


def _import_snapshot(cam: Camera) -> dict:
    source = cam.source
    group = cam.location_group
    credential = cam.credential_override
    return _camera_after(
        cam.name,
        cam.location,
        _import_host(cam.host),
        _import_path(cam.rtsp_main),
        _import_path(cam.rtsp_sub),
        source,
        group,
        credential,
    )


def _import_fields(item: dict) -> dict:
    after = item["after"]
    return {
        "name": after["name"],
        "location": after["location"],
        "host": after["host"],
        "rtsp_main": after["rtsp_main"],
        "rtsp_sub": after["rtsp_sub"],
        "source_id": after["source_id"],
        "location_group_id": after["location_group_id"],
        "credential_override_id": after["credential_override_id"],
    }


@router.post("", response_model=CameraOut)
def create_camera(body: CameraIn, admin=Depends(require_admin), db: Session = Depends(get_db)):
    data = _prepare_camera_data(db, body.model_dump(exclude_none=True))
    _check_node(db, data.get("node_id"))
    if _dup_name(db, data["name"], data.get("node_id")):
        raise HTTPException(409, "camera name already exists on this node")
    if _identity_duplicate(db, data.get("source_id"), _canonical_path(data.get("rtsp_main"))):
        raise HTTPException(409, "camera stream identity already exists")
    cam = Camera(**data)
    db.add(cam)
    db.commit()
    db.refresh(cam)
    if cam.enabled:
        try:
            sync_camera(cam)
        except Exception:
            logger.warning("go2rtc sync after create failed", exc_info=True)
    _config_push(db, cam.id)
    return cam


@router.get("", response_model=list[CameraOut])
def list_cameras(user=Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(Camera).order_by(Camera.id).all()


@router.get("/{camera_id}", response_model=CameraOut)
def get_camera(camera_id: int, user=Depends(get_current_user), db: Session = Depends(get_db)):
    cam = db.get(Camera, camera_id)
    if not cam:
        raise HTTPException(404, "camera not found")
    return cam


@router.patch("/{camera_id}", response_model=CameraOut)
def update_camera(camera_id: int, body: CameraPatch, admin=Depends(require_admin), db: Session = Depends(get_db)):
    cam = db.get(Camera, camera_id)
    if not cam:
        raise HTTPException(404, "camera not found")
    raw = body.model_dump(exclude_unset=True)
    data = _prepare_camera_data(db, raw, current=cam)
    node_id = data.get("node_id", cam.node_id)
    _check_node(db, node_id)
    if _dup_name(db, data.get("name", cam.name), node_id, exclude_id=cam.id):
        raise HTTPException(409, "camera name already exists on this node")
    if _identity_duplicate(
        db,
        data.get("source_id", cam.source_id),
        _canonical_path(data.get("rtsp_main", cam.rtsp_main)),
        exclude_id=cam.id,
    ):
        raise HTTPException(409, "camera stream identity already exists")
    for key, value in data.items():
        setattr(cam, key, value)
    db.commit()
    db.refresh(cam)
    try:
        sync_camera(cam, delete=not cam.enabled)
    except Exception:
        logger.warning("go2rtc sync after update failed", exc_info=True)
    _config_push(db, cam.id)
    return cam


@router.post("/import")
def import_cameras(
    body: CameraImportIn,
    apply_changes: bool = Query(False, alias="apply"),
    allow_create: bool = Query(False, alias="allow_create"),
    admin=Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Preview or apply a source-aware, idempotent camera inventory update."""
    cameras = db.query(Camera).all()
    by_id = {camera.id: camera for camera in cameras}
    legacy_candidates: dict[tuple[str, str], list[Camera]] = {}
    source_candidates: dict[tuple[int, str], list[Camera]] = {}
    for camera in cameras:
        main_path = _import_path(camera.rtsp_main)
        if not main_path:
            continue
        legacy_candidates.setdefault(_import_key(camera.host, main_path), []).append(camera)
        if camera.source_id is not None:
            source_candidates.setdefault(_source_key(camera.source_id, main_path), []).append(camera)

    errors: list[str] = []
    items: list[dict] = []
    seen_keys: set[tuple] = set()
    seen_names: set[str] = set()
    matched_ids: set[int] = set()

    for entry in body.entries:
        name = entry.name.strip()
        location = entry.location.strip() if entry.location else None
        source_specified = entry.source_id is not None or bool(entry.source and entry.source.strip())
        group_specified = entry.location_group_id is not None or bool(
            entry.location_group and entry.location_group.strip()
        )
        credential_specified = entry.credential_override_id is not None or bool(
            entry.credential_profile and entry.credential_profile.strip()
        )
        source, source_error = _entry_source(db, entry)
        group, group_error = _entry_group(db, entry)
        credential, credential_error = _entry_credential(db, entry)
        entry_errors = [error for error in (source_error, group_error, credential_error) if error]

        main_input = entry.main_path if entry.main_path is not None else entry.rtsp_main
        sub_input = entry.sub_path if entry.sub_path is not None else entry.rtsp_sub
        if entry.main_path is not None and entry.rtsp_main is not None and (
            _import_path(entry.main_path) != _import_path(entry.rtsp_main)
        ):
            entry_errors.append("main_path and rtsp_main differ")
        if entry.sub_path is not None and entry.rtsp_sub is not None and (
            _import_path(entry.sub_path) != _import_path(entry.rtsp_sub)
        ):
            entry_errors.append("sub_path and rtsp_sub differ")
        main_path = _import_path(main_input)
        sub_path = _import_path(sub_input) if sub_input else None
        if not name:
            entry_errors.append("camera name is required")
        if not main_path:
            entry_errors.append("exact main path is required")

        host = _import_host(entry.host) if entry.host else None
        if source is not None:
            source_host = _legacy_host(source)
            if host is not None and host != _import_host(source_host):
                entry_errors.append("source host does not match host")
            host = source_host
        elif host is None:
            entry_errors.append("camera host or stream source is required")

        identity_key = None
        if main_path and source is not None:
            identity_key = _source_key(source.id, main_path)
        elif main_path and host is not None:
            identity_key = _import_key(host, main_path)
        duplicate_input = identity_key is not None and identity_key in seen_keys
        if identity_key is not None:
            seen_keys.add(identity_key)
        duplicate_name = name in seen_names
        if duplicate_name:
            entry_errors.append(f"duplicate input name: {name}")
        seen_names.add(name)
        if duplicate_input:
            entry_errors.append("duplicate input stream")

        cam = None
        if entry.camera_id is not None:
            cam = by_id.get(entry.camera_id)
            if cam is None:
                entry_errors.append("camera id not found")
        elif not source_error and main_path:
            candidates = (
                source_candidates.get(_source_key(source.id, main_path), [])
                if source is not None
                else legacy_candidates.get(_import_key(host, main_path), [])
            )
            if len(candidates) == 1:
                cam = candidates[0]
            elif len(candidates) > 1:
                entry_errors.append("ambiguous camera identity")

        candidate_source = source if source_specified else (cam.source if cam else None)
        candidate_group = group if group_specified else (cam.location_group if cam else None)
        candidate_credential = (
            credential if credential_specified else (cam.credential_override if cam else None)
        )
        if candidate_source is None and candidate_credential is not None:
            entry_errors.append("credential override requires a stream source")
        if candidate_source is not None:
            host = _legacy_host(candidate_source)
        elif host is None and cam is not None:
            host = _import_host(cam.host)

        after = _camera_after(
            name,
            location,
            host,
            main_path,
            sub_path,
            candidate_source,
            candidate_group,
            candidate_credential,
        )
        before = _import_snapshot(cam) if cam else None
        identity_duplicate = cam is not None and _identity_duplicate(
            db,
            candidate_source.id if candidate_source else None,
            main_path,
            exclude_id=cam.id,
        )
        if identity_duplicate:
            entry_errors.append("camera stream identity already exists")

        name_conflict = False
        if cam is not None:
            name_conflict = _dup_name(db, name, cam.node_id, exclude_id=cam.id)
        elif name:
            name_conflict = db.query(Camera).filter(Camera.name == name).first() is not None
        if name_conflict:
            entry_errors.append(f"camera name already exists on node: {name}")

        changed = cam is not None and before != after
        duplicate_decision = (
            duplicate_input
            or identity_duplicate
            or name_conflict
            or "ambiguous camera identity" in entry_errors
        )
        if duplicate_decision:
            classification = "DUPLICATE"
        elif source_error == "NEW SOURCE":
            classification = "NEW SOURCE"
        elif credential_error or (
            credential_specified
            and cam is not None
            and before
            and before["credential_override_id"] != after["credential_override_id"]
        ):
            classification = "CREDENTIAL"
        elif cam is None:
            classification = "CREATE"
        elif changed:
            classification = "UPDATE"
        else:
            classification = "MATCHED"

        if entry_errors:
            errors.extend(f"{name}: {error}" for error in entry_errors)
        item = {
            "classification": classification,
            "camera_id": cam.id if cam else entry.camera_id,
            "matched": cam is not None,
            "changed": changed,
            "before": before,
            "after": after,
        }
        items.append(item)
        if cam is not None:
            matched_ids.add(cam.id)

    orphans = [
        {
            "classification": "ORPHAN",
            "camera_id": camera.id,
            "matched": False,
            "changed": False,
            "before": _import_snapshot(camera),
            "after": _import_snapshot(camera),
        }
        for camera in cameras
        if camera.id not in matched_ids
    ]
    unresolved = [
        item
        for item in items
        if not item["matched"] and not (allow_create and item["classification"] == "CREATE")
    ]
    changed = [item for item in items if item["matched"] and item["changed"]]
    result = {
        "applied": False,
        "total": len(body.entries),
        "matched": sum(item["matched"] for item in items),
        "updated": len(changed),
        "created": 0,
        "unmatched": unresolved,
        "orphans": orphans,
        "errors": errors,
        "items": items + orphans,
    }
    if not apply_changes or errors or unresolved:
        return result

    created_cameras: list[Camera] = []
    try:
        for item in changed:
            cam = db.get(Camera, item["camera_id"])
            for field, value in _import_fields(item).items():
                setattr(cam, field, value)
        for item in items:
            if item["classification"] != "CREATE":
                continue
            data = _import_fields(item)
            cam = Camera(**data)
            db.add(cam)
            created_cameras.append(cam)
        db.commit()
    except Exception:
        db.rollback()
        raise

    for item in changed:
        cam = db.get(Camera, item["camera_id"])
        try:
            sync_camera(cam, delete=not cam.enabled)
        except Exception:
            logger.warning("go2rtc sync after import failed", exc_info=True)
        _config_push(db, cam.id)
    for cam in created_cameras:
        try:
            if cam.enabled:
                sync_camera(cam)
        except Exception:
            logger.warning("go2rtc sync after import create failed", exc_info=True)
        _config_push(db, cam.id)
    created = sum(1 for item in items if item["classification"] == "CREATE")
    result["created"] = created
    result["applied"] = True
    return result


@router.delete("/{camera_id}")
def delete_camera(camera_id: int, admin=Depends(require_admin), db: Session = Depends(get_db)):
    cam = db.get(Camera, camera_id)
    if not cam:
        raise HTTPException(404, "camera not found")
    if db.query(AttendanceEvent).filter(AttendanceEvent.camera_id == camera_id).first():
        raise HTTPException(409, "camera has attendance records; deactivate instead")
    node_name = db.get(Node, cam.node_id).name if cam.node_id else None
    db.delete(cam)
    db.commit()
    try:
        remove_stream(f"cam_{camera_id}")
        remove_stream(f"cam_{camera_id}_main")
    except Exception:
        logger.warning("go2rtc sync after delete failed", exc_info=True)
    if node_name:
        _config_push(db, camera_id, node_name)
    return {"ok": True}
