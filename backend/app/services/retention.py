"""Sweeper retensi media.

Dua lapis, karena keduanya menangkap kasus berbeda:

1. Berdasarkan DB — event yang `ts_event`-nya lebih tua dari RETENTION_DAYS. File
   dihapus, `media_expired` ditandai, path di-null-kan supaya UI tahu medianya
   memang dihapus retensi (bukan "belum ada clip").
2. Berdasarkan file — sapuan orphan untuk file yang tidak punya baris event
   (upload gagal / event dihapus manual). Tanpa lapis ini file itu tidak akan
   pernah tersentuh dan disk bocor perlahan.
"""
from __future__ import annotations

import os
import shutil
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.event import Event

KINDS = ("clips", "snapshots", "crops")


def cutoff_for(now: datetime, days: int) -> datetime:
    return now - timedelta(days=days)


def _safe_join(root: str, rel: str) -> str | None:
    """Path relatif dari DB → path absolut, atau None kalau keluar dari root.

    Path di DB berasal dari upload vision; jangan pernah dipakai untuk menghapus
    file di luar storage_root.
    """
    full = os.path.realpath(os.path.join(root, rel))
    root_real = os.path.realpath(root)
    if full != root_real and not full.startswith(root_real + os.sep):
        return None
    return full


def _size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def disk_usage(root: str) -> dict:
    usage = shutil.disk_usage(root if os.path.isdir(root) else os.path.dirname(root) or ".")
    return {
        "total": usage.total,
        "used": usage.used,
        "free": usage.free,
        "percent": round(usage.used / usage.total * 100, 1) if usage.total else 0.0,
    }


def kind_usage(root: str) -> dict[str, dict]:
    out: dict[str, dict] = {k: {"files": 0, "bytes": 0} for k in KINDS}
    for kind in KINDS:
        base = os.path.join(root, kind)
        if not os.path.isdir(base):
            continue
        for dirpath, _dirnames, filenames in os.walk(base):
            for name in filenames:
                out[kind]["files"] += 1
                out[kind]["bytes"] += _size(os.path.join(dirpath, name))
    return out


def _prune_empty_dirs(base: str) -> None:
    """Rapikan direktori tanggal yang sudah kosong, dari dalam ke luar."""
    if not os.path.isdir(base):
        return
    for dirpath, _dirnames, _filenames in os.walk(base, topdown=False):
        if dirpath == base:
            continue
        try:
            os.rmdir(dirpath)  # gagal kalau masih ada isi — itu benar
        except OSError:
            pass


def sweep(db: Session, now: datetime | None = None, dry_run: bool = False) -> dict:
    now = now or datetime.now(timezone.utc)
    root = settings.storage_root
    cutoff = cutoff_for(now, settings.retention_days)

    files_deleted = 0
    bytes_freed = 0
    events_marked = 0

    # --- lapis 1: event kedaluwarsa menurut ts_event ---
    expired = (
        db.query(Event)
        .filter(Event.ts_event < cutoff)
        .filter(Event.media_expired.is_(False))
        .filter((Event.clip_path.isnot(None)) | (Event.snapshot_path.isnot(None)))
        .all()
    )
    # clip insiden dipakai bersama beberapa event; jangan hapus selama masih
    # dirujuk event yang belum kedaluwarsa (null-kan path saja)
    live = {
        path
        for row in db.query(Event.clip_path, Event.snapshot_path)
        .filter(Event.ts_event >= cutoff)
        for path in row
        if path
    } if expired else set()
    for ev in expired:
        for field in ("clip_path", "snapshot_path"):
            rel = getattr(ev, field)
            if not rel:
                continue
            full = _safe_join(root, rel)
            if full and rel not in live and os.path.isfile(full):
                bytes_freed += _size(full)
                files_deleted += 1
                if not dry_run:
                    os.remove(full)
            if not dry_run:
                setattr(ev, field, None)
        events_marked += 1
    if not dry_run and events_marked:
        for ev in expired:
            ev.media_expired = True
        db.commit()
    elif not dry_run:
        db.commit()

    # --- lapis 2: sapuan orphan berdasarkan mtime ---
    referenced = set()
    for (clip, snap) in db.query(Event.clip_path, Event.snapshot_path).all():
        if clip:
            referenced.add(clip)
        if snap:
            referenced.add(snap)

    orphans_deleted = 0
    cutoff_ts = cutoff.timestamp()
    for kind in KINDS:
        base = os.path.join(root, kind)
        if not os.path.isdir(base):
            continue
        for dirpath, _dirnames, filenames in os.walk(base):
            for name in filenames:
                full = os.path.join(dirpath, name)
                try:
                    if os.path.getmtime(full) >= cutoff_ts:
                        continue
                except OSError:
                    continue
                rel = os.path.relpath(full, root).replace(os.sep, "/")
                if rel in referenced:
                    continue
                orphans_deleted += 1
                bytes_freed += _size(full)
                if not dry_run:
                    os.remove(full)
        if not dry_run:
            _prune_empty_dirs(base)

    return {
        "files_deleted": files_deleted,
        "bytes_freed": bytes_freed,
        "events_marked": events_marked,
        "orphans_deleted": orphans_deleted,
        "dry_run": dry_run,
    }
