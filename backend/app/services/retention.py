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
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.alert import Alert
from app.models.event import Event
from app.services import storage_settings

KINDS = ("clips", "snapshots", "crops")
ORPHAN_CUTOFF_KIND = {"clips": "clip", "snapshots": "snapshot", "crops": "snapshot"}
PROTECTED_TYPES = ("attendance",)  # sumber hari absensi & export — tidak pernah dihapus cleanup


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


def _expire_field(db: Session, root: str, field: str, cutoff: datetime, dry_run: bool) -> tuple[int, int, list]:
    """Hapus file `field` (clip_path/snapshot_path) milik event lebih tua dari cutoff.

    File yang masih dirujuk event lebih baru (clip insiden bersama) dipertahankan; path event
    kedaluwarsa tetap di-null-kan. Perbandingan waktu di SQL (SQLite tes = datetime naif).
    """
    col = getattr(Event, field)
    expired = db.query(Event).filter(Event.ts_event < cutoff, col.isnot(None)).all()
    if not expired:
        return 0, 0, []
    live = {p for (p,) in db.query(col).filter(Event.ts_event >= cutoff, col.isnot(None))}
    files = freed = 0
    seen: set[str] = set()
    for ev in expired:
        rel = getattr(ev, field)
        full = _safe_join(root, rel)
        if rel not in seen and rel not in live and full and os.path.isfile(full):
            seen.add(rel)
            files += 1
            freed += _size(full)
            if not dry_run:
                os.remove(full)
        if not dry_run:
            setattr(ev, field, None)
            ev.media_expired = True
    return files, freed, expired


def sweep(db: Session, now: datetime | None = None, dry_run: bool = False) -> dict:
    now = now or datetime.now(timezone.utc)
    root = settings.storage_root
    s = storage_settings.get(db)
    cutoffs = {"clip": cutoff_for(now, s["clip_days"]), "snapshot": cutoff_for(now, s["snapshot_days"])}

    # --- lapis 1: media event kedaluwarsa, per jenis ---
    c_files, c_bytes, c_events = _expire_field(db, root, "clip_path", cutoffs["clip"], dry_run)
    s_files, s_bytes, s_events = _expire_field(db, root, "snapshot_path", cutoffs["snapshot"], dry_run)
    files_deleted, bytes_freed = c_files + s_files, c_bytes + s_bytes
    events_marked = len({ev.id for ev in c_events + s_events})
    if not dry_run:
        db.commit()

    # --- lapis 2: sapuan orphan berdasarkan mtime, cutoff per jenis ---
    referenced = set()
    for (clip, snap) in db.query(Event.clip_path, Event.snapshot_path).all():
        if clip:
            referenced.add(clip)
        if snap:
            referenced.add(snap)

    orphans_deleted = 0
    for kind in KINDS:
        base = os.path.join(root, kind)
        if not os.path.isdir(base):
            continue
        cutoff_ts = cutoffs[ORPHAN_CUTOFF_KIND[kind]].timestamp()
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
        "clip_days": s["clip_days"],
        "snapshot_days": s["snapshot_days"],
    }


def cleanup(db: Session, date_from: date, date_to: date, camera_ids: list[int] | None = None,
            types: list[str] | None = None, dry_run: bool = True) -> dict:
    """Hapus event (non-attendance) + clip/snapshot + alert-nya pada rentang tanggal lokal server."""
    tz = datetime.now().astimezone().tzinfo
    start = datetime.combine(date_from, time.min, tzinfo=tz)
    end = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=tz)
    q = db.query(Event).filter(Event.ts_event >= start, Event.ts_event < end,
                               Event.type.notin_(PROTECTED_TYPES))
    if camera_ids:
        q = q.filter(Event.camera_id.in_(camera_ids))
    if types is not None and len(types) > 0:
        q = q.filter(Event.type.in_([t for t in types if t not in PROTECTED_TYPES]))
    events = q.all()
    if not events:
        return {"events": 0, "files": 0, "bytes": 0, "dry_run": dry_run}
    # ponytail: IN (...) dengan id event; cukup untuk puluhan ribu baris — pecah per batch bila lebih
    ids = [ev.id for ev in events]
    paths = {p for ev in events for p in (ev.clip_path, ev.snapshot_path) if p}
    kept = set()
    if paths:
        rows = db.query(Event.clip_path, Event.snapshot_path).filter(
            Event.id.notin_(ids), or_(Event.clip_path.in_(paths), Event.snapshot_path.in_(paths)))
        kept = {p for row in rows for p in row if p}  # clip insiden bersama dengan event di luar rentang
    root = settings.storage_root
    files = freed = 0
    for rel in sorted(paths - kept):
        full = _safe_join(root, rel)
        if full and os.path.isfile(full):
            files += 1
            freed += _size(full)
            if not dry_run:
                os.remove(full)
    if not dry_run:
        db.query(Alert).filter(Alert.event_id.in_(ids)).delete(synchronize_session="fetch")
        db.query(Event).filter(Event.id.in_(ids)).delete(synchronize_session="fetch")
        db.commit()
    return {"events": len(ids), "files": files, "bytes": freed, "dry_run": dry_run}
