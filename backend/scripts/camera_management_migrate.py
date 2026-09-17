"""Preview and apply the source-aware camera backfill."""

from __future__ import annotations

import argparse
import json
import re

from app.core.config import settings
from app.core.db import SessionLocal
from app.models.camera import Camera
from app.models.credential_profile import CredentialProfile
from app.models.location_group import LocationGroup
from app.models.stream_source import StreamSource
from app.services.stream_endpoint import StreamEndpointError, path_only, split_host_port


LEGACY_PROFILE_NAME = "legacy-global"
LEGACY_SECRET_REF = "env:CAM_PASSWORD"


def _source_key(camera: Camera) -> tuple[str, int]:
    try:
        return split_host_port(camera.host)
    except StreamEndpointError as exc:
        raise ValueError(f"camera {camera.id} has invalid host") from exc


def _source_name(host: str, port: int) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", host).strip("-").lower() or "source"
    suffix = "" if port == 554 else f"-{port}"
    return f"legacy-{slug}{suffix}"[:64]


def _preview_items(db) -> tuple[list[dict], list[dict]]:
    items: list[dict] = []
    duplicates: dict[tuple[str, str], list[int]] = {}
    for camera in db.query(Camera).order_by(Camera.id).all():
        host, port = _source_key(camera)
        path = path_only(camera.rtsp_main) or ""
        duplicates.setdefault((f"{host}:{port}", path), []).append(camera.id)
        items.append(
            {
                "camera_id": camera.id,
                "source": {"host": host, "port": port, "name": _source_name(host, port)},
                "location_group": camera.location.strip() if camera.location and camera.location.strip() else None,
                "legacy_reference": {
                    "source_id": camera.source_id,
                    "location_group_id": camera.location_group_id,
                    "credential_override_id": camera.credential_override_id,
                },
            }
        )
    ambiguous = [
        {"host_port": key[0], "rtsp_main": key[1], "camera_ids": ids}
        for key, ids in duplicates.items()
        if len(ids) > 1 and key[1]
    ]
    return items, ambiguous


def preview_backfill(db) -> dict:
    items, ambiguous = _preview_items(db)
    sources = {(item["source"]["host"], item["source"]["port"]) for item in items}
    groups = {item["location_group"] for item in items if item["location_group"]}
    has_global_credentials = bool(settings.cam_username or settings.cam_password)
    return {
        "applied": False,
        "camera_count": len(items),
        "source_count": len(sources),
        "location_group_count": len(groups),
        "credential_profile_count": 1 if has_global_credentials else 0,
        "ambiguous": ambiguous,
        "items": items,
    }


def _unique_source_name(db, base: str, host: str, port: int) -> str:
    candidate = base
    index = 2
    while True:
        existing = db.query(StreamSource).filter_by(name=candidate).first()
        if existing is None or (existing.host == host and existing.port == port):
            return candidate
        suffix = f"-{index}"
        candidate = f"{base[:64 - len(suffix)]}{suffix}"
        index += 1


def _get_or_create_profile(db) -> tuple[CredentialProfile | None, int]:
    if not (settings.cam_username or settings.cam_password):
        return None, 0
    profile = db.query(CredentialProfile).filter_by(name=LEGACY_PROFILE_NAME).first()
    if profile:
        return profile, 0
    profile = CredentialProfile(
        name=LEGACY_PROFILE_NAME,
        username=settings.cam_username,
        secret_ref=LEGACY_SECRET_REF,
        enabled=True,
    )
    db.add(profile)
    db.flush()
    return profile, 1


def apply_backfill(db) -> dict:
    preview = preview_backfill(db)
    if preview["ambiguous"]:
        raise ValueError("backfill has ambiguous camera identities; resolve them first")

    created_sources = 0
    created_groups = 0
    profile, created_profiles = _get_or_create_profile(db)
    source_cache: dict[tuple[str, int], StreamSource] = {}
    group_cache: dict[str, LocationGroup] = {}
    try:
        for camera in db.query(Camera).order_by(Camera.id).all():
            host, port = _source_key(camera)
            if camera.source_id is not None:
                source = db.get(StreamSource, camera.source_id)
                if source is None:
                    raise ValueError(f"camera {camera.id} references a missing source")
            else:
                key = (host, port)
                source = source_cache.get(key)
                if source is None:
                    matches = db.query(StreamSource).filter_by(host=host, port=port).all()
                    if len(matches) > 1:
                        raise ValueError(f"multiple sources already use {host}:{port}")
                    source = matches[0] if matches else None
                    if source is None:
                        source = StreamSource(
                            name=_unique_source_name(db, _source_name(host, port), host, port),
                            kind="unknown",
                            host=host,
                            port=port,
                            default_credential=profile,
                            enabled=True,
                        )
                        db.add(source)
                        db.flush()
                        created_sources += 1
                    source_cache[key] = source
                camera.source_id = source.id

            location = camera.location.strip() if camera.location and camera.location.strip() else None
            if camera.location_group_id is None and location:
                group = group_cache.get(location)
                if group is None:
                    group = db.query(LocationGroup).filter_by(name=location).first()
                    if group is None:
                        group = LocationGroup(name=location, sort_order=0, enabled=True)
                        db.add(group)
                        db.flush()
                        created_groups += 1
                    group_cache[location] = group
                camera.location_group_id = group.id
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {
        "applied": True,
        "camera_count": preview["camera_count"],
        "created_sources": created_sources,
        "created_location_groups": created_groups,
        "created_credential_profiles": created_profiles,
        "ambiguous": [],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preview", action="store_true", help="show the plan without writing")
    parser.add_argument("--apply", action="store_true", help="apply the plan")
    args = parser.parse_args()
    if args.preview and args.apply:
        parser.error("choose only --preview or --apply")
    db = SessionLocal()
    try:
        result = apply_backfill(db) if args.apply else preview_backfill(db)
        print(json.dumps(result, sort_keys=True))
    finally:
        db.close()


if __name__ == "__main__":
    main()
