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

import logging
import os
import shutil
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.alert import Alert
from app.models.attendance import AttendanceDay, AttendanceEvent
from app.models.employee import Employee
from app.models.event import Event
from app.models.event_ai import EventAi
from app.services import storage_settings

logger = logging.getLogger(__name__)

KINDS = ("clips", "snapshots", "crops")
# crops/ = crop wajah absensi (payload.crop_path) → ikut retensi media absensi
ORPHAN_CUTOFF_KIND = {"clips": "clip", "snapshots": "snapshot", "crops": "attendance"}
# absensi = sumber rekap → tidak pernah dihapus cleanup
PROTECTED_TYPES = ("attendance",)
# log sistem (node offline/LWT) hanya terhapus bila dipilih eksplisit di filter Jenis
OPT_IN_TYPES = ("system",)
CLEANUP_BATCH = 5000  # batas placeholder IN (...) untuk rentang tanggal besar
# event memang tanpa media sejak awal → tidak pernah dihapus karena "media habis"
MEDIA_FREE_EXEMPT = ("system",)


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


def _by_attendance(q, attendance: bool | None):
    """None = semua jenis; True = hanya absensi; False = selain absensi."""
    if attendance is None:
        return q
    return q.filter(Event.type == "attendance") if attendance else q.filter(Event.type != "attendance")


def _expire_field(db: Session, root: str, field: str, cutoff: datetime, dry_run: bool,
                  attendance: bool | None = None) -> tuple[int, int, list]:
    """Hapus file `field` (clip_path/snapshot_path) milik event lebih tua dari cutoff.

    File yang masih dirujuk event lebih baru (clip insiden bersama) dipertahankan; path event
    kedaluwarsa tetap di-null-kan. Perbandingan waktu di SQL (SQLite tes = datetime naif).
    """
    col = getattr(Event, field)
    expired = _by_attendance(db.query(Event).filter(Event.ts_event < cutoff, col.isnot(None)), attendance).all()
    if not expired:
        return 0, 0, []
    live = {p for (p,) in _by_attendance(db.query(col).filter(Event.ts_event >= cutoff, col.isnot(None)),
                                         attendance)}
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


def _expire_crops(db: Session, root: str, cutoff: datetime, dry_run: bool,
                  event_type: str = "attendance") -> tuple[int, int, list]:
    """Crop wajah (payload.crop_path) jenis event tertentu lebih tua dari cutoff.

    attendance mengikuti attendance_days; intrusion mengikuti snapshot_days (bukti manual).
    ponytail: memindai payload event lama di Python (JSON filter beda per dialek); pindah ke
    filter JSON SQL bila baris mencapai ratusan ribu.
    """
    rows = db.query(Event).filter(Event.type == event_type, Event.ts_event < cutoff).all()
    expired = [ev for ev in rows if (ev.payload or {}).get("crop_path")]
    files = freed = 0
    seen: set[str] = set()
    for ev in expired:
        rel = ev.payload["crop_path"]
        full = _safe_join(root, rel)
        if rel not in seen and full and os.path.isfile(full):
            seen.add(rel)
            files += 1
            freed += _size(full)
            if not dry_run:
                os.remove(full)
        if not dry_run:
            ev.payload = {**ev.payload, "crop_path": None}  # dict baru → perubahan JSON terdeteksi
            ev.media_expired = True
    if not dry_run and expired and event_type == "attendance":
        _null_attendance_copies(db, [ev.event_id for ev in expired])
    return files, freed, expired


def _media_fields(ev: Event) -> set[str]:
    """Media yang masih dirujuk event: clip, snapshot, crop wajah (payload absensi)."""
    out = set()
    if ev.clip_path:
        out.add("clip")
    if ev.snapshot_path:
        out.add("snapshot")
    if (ev.payload or {}).get("crop_path"):
        out.add("crop")
    return out


def _delete_events(db: Session, ids: list[int]) -> None:
    """Hapus hasil AI, alert, lalu event sesuai urutan FK, per batch; tanpa commit."""
    for chunk in _chunks(ids):
        db.query(EventAi).filter(EventAi.event_id.in_(chunk)).delete(synchronize_session="fetch")
        db.query(Alert).filter(Alert.event_id.in_(chunk)).delete(synchronize_session="fetch")
        db.query(Event).filter(Event.id.in_(chunk)).delete(synchronize_session="fetch")


def _media_free_after(db: Session, parts: list, names: tuple[str, ...]) -> set[int]:
    """Event yang seluruh medianya habis oleh retensi (sweep ini atau versi sebelumnya).

    Tujuan event = bukti visual; tanpa media card Events tidak berguna. Hanya event yang medianya
    dihapus retensi (bukan event baru yang upload medianya masih menyusul). Log system dikecualikan.
    """
    expired: dict[int, set[str]] = {}
    touched: dict[int, Event] = {}
    for (_files, _bytes, evs), name in zip(parts, names):
        for ev in evs:
            expired.setdefault(ev.id, set()).add(name)
            touched[ev.id] = ev
    # dry run: field belum di-null-kan → semua media yang ada harus termasuk yang kedaluwarsa;
    # eksekusi: field sudah di-null-kan → yang tersisa hanya media yang belum kedaluwarsa
    purge = {eid for eid, ev in touched.items()
             if ev.type not in MEDIA_FREE_EXEMPT and _media_fields(ev) <= expired[eid]}
    legacy = db.query(Event).filter(Event.media_expired.is_(True), Event.clip_path.is_(None),
                                    Event.snapshot_path.is_(None), Event.type.notin_(MEDIA_FREE_EXEMPT))
    purge |= {ev.id for ev in legacy if ev.id not in touched and not _media_fields(ev)}
    return purge


def sweep(db: Session, now: datetime | None = None, dry_run: bool = False) -> dict:
    now = now or datetime.now(timezone.utc)
    root = settings.storage_root
    s = storage_settings.get(db)
    cutoffs = {"clip": cutoff_for(now, s["clip_days"]), "snapshot": cutoff_for(now, s["snapshot_days"]),
               "attendance": cutoff_for(now, s["attendance_days"])}

    # --- lapis 1: media event kedaluwarsa, per jenis (absensi punya retensi sendiri) ---
    parts = [
        _expire_field(db, root, "clip_path", cutoffs["clip"], dry_run, attendance=False),
        # clip absensi = data lama (pipeline sebelum face worker), ikut retensi media absensi
        _expire_field(db, root, "clip_path", cutoffs["attendance"], dry_run, attendance=True),
        _expire_field(db, root, "snapshot_path", cutoffs["snapshot"], dry_run, attendance=False),
        _expire_field(db, root, "snapshot_path", cutoffs["attendance"], dry_run, attendance=True),
        _expire_crops(db, root, cutoffs["attendance"], dry_run),
        # crop wajah intrusion = bukti manual critical, mengikuti retensi snapshot
        _expire_crops(db, root, cutoffs["snapshot"], dry_run, event_type="intrusion"),
    ]
    files_deleted = sum(p[0] for p in parts)
    bytes_freed = sum(p[1] for p in parts)
    events_marked = len({ev.id for p in parts for ev in p[2]})
    purge = _media_free_after(db, parts, ("clip", "clip", "snapshot", "snapshot", "crop", "crop"))
    if not dry_run:
        _delete_events(db, sorted(purge))  # card Events tanpa media ikut hilang (+ alert-nya)
        db.commit()

    # --- lapis 2: sapuan orphan berdasarkan mtime, cutoff per jenis ---
    referenced = set()
    for (clip, snap) in db.query(Event.clip_path, Event.snapshot_path).all():
        if clip:
            referenced.add(clip)
        if snap:
            referenced.add(snap)
    # crop yang masih dirujuk payload event (attendance atau intrusion) bukan orphan —
    # umurninya diatur lapis 1; tanpa ini sapuan orphan menghapus crop intrusion.
    for (payload,) in db.query(Event.payload).filter(Event.type.in_(("attendance", "intrusion"))):
        crop = (payload or {}).get("crop_path")
        if crop:
            referenced.add(crop)

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
        "events_deleted": len(purge),
        "clip_days": s["clip_days"],
        "snapshot_days": s["snapshot_days"],
        "attendance_days": s["attendance_days"],
    }


def _chunks(items: list, size: int = CLEANUP_BATCH) -> list[list]:
    return [items[i:i + size] for i in range(0, len(items), size)]


def _null_attendance_copies(db: Session, event_ids: list[str]) -> None:
    """attendance_event.snapshot_path menyimpan salinan path crop → ikut di-null-kan (tanpa commit)."""
    for chunk in _chunks([e for e in event_ids if e]):
        db.query(AttendanceEvent).filter(AttendanceEvent.event_id.in_(chunk)).update(
            {"snapshot_path": None}, synchronize_session=False)


def _local_range(date_from: date, date_to: date) -> tuple[datetime, datetime]:
    """Batas hari lokal server `[dari 00:00, sampai+1 hari 00:00)` — dipakai semua mode cleanup."""
    tz = datetime.now().astimezone().tzinfo
    start = datetime.combine(date_from, time.min, tzinfo=tz)
    end = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=tz)
    return start, end


def _range_query(db: Session, date_from: date, date_to: date, camera_ids: list[int] | None):
    """Event pada rentang tanggal lokal server (+ filter kamera)."""
    start, end = _local_range(date_from, date_to)
    q = db.query(Event).filter(Event.ts_event >= start, Event.ts_event < end)
    return q.filter(Event.camera_id.in_(camera_ids)) if camera_ids else q


def _remove_files(root: str, rels: list[str]) -> tuple[int, int]:
    files = freed = 0
    for rel in rels:
        full = _safe_join(root, rel)
        size = _size(full)
        try:
            os.remove(full)
        except OSError:
            logger.warning("cleanup: gagal menghapus %s", rel, exc_info=True)
            continue
        files += 1
        freed += size
    return files, freed


def cleanup_attendance_media(db: Session, date_from: date, date_to: date,
                             camera_ids: list[int] | None = None, dry_run: bool = True) -> dict:
    """Hapus semua media event absensi di rentang (foto, crop wajah, clip lama) + entri Inbox-nya.

    Riwayat masuk/keluar (attendance_event) dan rekap (attendance_day) tetap.
    """
    events = [ev for ev in _range_query(db, date_from, date_to, camera_ids).filter(Event.type == "attendance")
              if _media_fields(ev)]
    if not events:
        return {"events": 0, "files": 0, "bytes": 0, "dry_run": dry_run}
    id_set = {ev.id for ev in events}
    eid_set = {ev.event_id for ev in events}
    paths = {p for ev in events for p in (ev.clip_path, ev.snapshot_path, (ev.payload or {}).get("crop_path")) if p}
    # file yang juga dirujuk event/riwayat di luar rentang dipertahankan
    kept: set[str] = set()
    for chunk in _chunks(sorted(paths)):
        rows = db.query(Event.id, Event.clip_path, Event.snapshot_path).filter(
            or_(Event.clip_path.in_(chunk), Event.snapshot_path.in_(chunk)))
        kept |= {p for (eid, clip, snap) in rows if eid not in id_set for p in (clip, snap) if p}
        copies = db.query(AttendanceEvent.event_id, AttendanceEvent.snapshot_path).filter(
            AttendanceEvent.snapshot_path.in_(chunk))
        kept |= {p for (eid, p) in copies if eid not in eid_set}
    root = settings.storage_root
    doomed = [rel for rel in sorted(paths - kept) if (full := _safe_join(root, rel)) and os.path.isfile(full)]
    if dry_run:
        return {"events": len(events), "files": len(doomed),
                "bytes": sum(_size(_safe_join(root, rel)) for rel in doomed), "dry_run": True}
    _null_attendance_copies(db, list(eid_set))
    # media habis → entri Inbox absensi ikut dihapus; rekap (attendance_day) & riwayat (attendance_event) tetap
    _delete_events(db, sorted(id_set))
    db.commit()  # baris dulu, file sesudahnya (sisa file gagal hapus → orphan sweep)
    files, freed = _remove_files(root, doomed)
    return {"events": len(events), "files": files, "bytes": freed, "dry_run": False}


def cleanup_attendance_data(db: Session, date_from: date, date_to: date,
                            employee_ids: list[int] | None = None, dry_run: bool = True) -> dict:
    """Hapus PERMANEN riwayat (attendance_event), rekap (attendance_day, termasuk override_note),
    entri Inbox absensi terkait, dan medianya untuk karyawan terpilih (`employee_ids=None` = semua
    karyawan, termasuk event wajah tak dikenal) pada rentang tanggal lokal server.

    Tindakan admin eksplisit, bukan retensi otomatis — tidak bisa dipulihkan. Beda dengan
    cleanup_attendance_media: mode ini juga menghapus baris riwayat & rekap, bukan cuma media.
    """
    start, end = _local_range(date_from, date_to)
    att_q = db.query(AttendanceEvent).filter(AttendanceEvent.ts_event >= start, AttendanceEvent.ts_event < end)
    day_q = db.query(AttendanceDay).filter(AttendanceDay.date >= date_from, AttendanceDay.date <= date_to)
    if employee_ids is not None:
        att_q = att_q.filter(AttendanceEvent.employee_id.in_(employee_ids))
        day_q = day_q.filter(AttendanceDay.employee_id.in_(employee_ids))
    att_rows, day_rows = att_q.all(), day_q.all()
    eid_set = {row.event_id for row in att_rows if row.event_id}

    events_q = db.query(Event).filter(Event.type == "attendance", Event.ts_event >= start, Event.ts_event < end)
    if employee_ids is not None:
        # dengan filter karyawan, wajah tak dikenal (tanpa baris riwayat) tidak ikut
        inbox_events = events_q.filter(Event.event_id.in_(eid_set)).all() if eid_set else []
    else:
        inbox_events = events_q.all()

    emp_ids = {row.employee_id for row in att_rows} | {row.employee_id for row in day_rows}
    names = dict(db.query(Employee.id, Employee.name).filter(Employee.id.in_(emp_ids))) if emp_ids else {}
    att_count: dict[int, int] = {}
    day_count: dict[int, int] = {}
    for row in att_rows:
        att_count[row.employee_id] = att_count.get(row.employee_id, 0) + 1
    for row in day_rows:
        day_count[row.employee_id] = day_count.get(row.employee_id, 0) + 1
    # karyawan terhapus dari DB sementara itu → tampilkan sebagai #id, bukan gagal
    employees = sorted(
        ({"id": eid, "name": names.get(eid, f"#{eid}"),
          "attendance_events": att_count.get(eid, 0), "days": day_count.get(eid, 0)} for eid in emp_ids),
        key=lambda e: e["name"])

    id_set = {ev.id for ev in inbox_events}
    att_id_set = {row.id for row in att_rows}
    paths = {p for ev in inbox_events for p in (ev.clip_path, ev.snapshot_path, (ev.payload or {}).get("crop_path")) if p}
    paths |= {row.snapshot_path for row in att_rows if row.snapshot_path}
    # file yang juga dirujuk baris di luar seleksi (event lain / attendance_event lain) dipertahankan
    kept: set[str] = set()
    for chunk in _chunks(sorted(paths)):
        rows = db.query(Event.id, Event.clip_path, Event.snapshot_path).filter(
            or_(Event.clip_path.in_(chunk), Event.snapshot_path.in_(chunk)))
        kept |= {p for (eid, clip, snap) in rows if eid not in id_set for p in (clip, snap) if p}
        copies = db.query(AttendanceEvent.id, AttendanceEvent.snapshot_path).filter(
            AttendanceEvent.snapshot_path.in_(chunk))
        kept |= {p for (aid, p) in copies if aid not in att_id_set}
    root = settings.storage_root
    doomed = [rel for rel in sorted(paths - kept) if (full := _safe_join(root, rel)) and os.path.isfile(full)]

    if dry_run:
        return {"events": len(inbox_events), "attendance_events": len(att_rows), "days": len(day_rows),
                "files": len(doomed), "bytes": sum(_size(_safe_join(root, rel)) for rel in doomed),
                "dry_run": True, "employees": employees}

    # baris dulu dalam satu transaksi (alert → event → riwayat → rekap), file sesudahnya
    _delete_events(db, sorted(id_set))
    for chunk in _chunks(sorted(att_id_set)):
        db.query(AttendanceEvent).filter(AttendanceEvent.id.in_(chunk)).delete(synchronize_session="fetch")
    for chunk in _chunks(sorted(row.id for row in day_rows)):
        db.query(AttendanceDay).filter(AttendanceDay.id.in_(chunk)).delete(synchronize_session="fetch")
    db.commit()
    files, freed = _remove_files(root, doomed)
    return {"events": len(inbox_events), "attendance_events": len(att_rows), "days": len(day_rows),
            "files": files, "bytes": freed, "dry_run": False, "employees": employees}


def cleanup(db: Session, date_from: date, date_to: date, camera_ids: list[int] | None = None,
            types: list[str] | None = None, dry_run: bool = True, mode: str = "events",
            employee_ids: list[int] | None = None) -> dict:
    """Hapus event (non-attendance/system) + clip/snapshot + alert-nya pada rentang tanggal lokal server.

    mode="attendance_media": hanya media absensi (lihat cleanup_attendance_media).
    mode="attendance_data": riwayat + rekap + Inbox + media absensi karyawan terpilih (lihat
    cleanup_attendance_data) — permanen, bukan retensi.
    """
    if mode == "attendance_media":
        return cleanup_attendance_media(db, date_from, date_to, camera_ids, dry_run=dry_run)
    if mode == "attendance_data":
        return cleanup_attendance_data(db, date_from, date_to, employee_ids, dry_run=dry_run)
    q = _range_query(db, date_from, date_to, camera_ids).filter(Event.type.notin_(PROTECTED_TYPES))
    if not types:
        q = q.filter(Event.type.notin_(OPT_IN_TYPES))
    if types is not None and len(types) > 0:
        q = q.filter(Event.type.in_([t for t in types if t not in PROTECTED_TYPES]))
    events = q.all()
    if not events:
        return {"events": 0, "files": 0, "bytes": 0, "dry_run": dry_run}
    ids = [ev.id for ev in events]
    id_set = set(ids)
    paths = {p for ev in events for p in (ev.clip_path, ev.snapshot_path) if p}
    # clip/snapshot bersama: jangan hapus file yang masih dirujuk event yang TIDAK ikut dihapus
    kept: set[str] = set()
    for chunk in _chunks(sorted(paths)):
        rows = db.query(Event.id, Event.clip_path, Event.snapshot_path).filter(
            or_(Event.clip_path.in_(chunk), Event.snapshot_path.in_(chunk)))
        kept |= {p for (eid, clip, snap) in rows if eid not in id_set for p in (clip, snap) if p}
    root = settings.storage_root
    doomed = []
    for rel in sorted(paths - kept):
        full = _safe_join(root, rel)
        if full and os.path.isfile(full):
            doomed.append(rel)
    if dry_run:
        return {"events": len(ids), "files": len(doomed),
                "bytes": sum(_size(_safe_join(root, rel)) for rel in doomed), "dry_run": True}
    # Baris dulu (satu transaksi), file sesudahnya: kalau penghapusan file gagal, sisa file disapu
    # orphan sweep — tidak ada baris event yang menunjuk ke file yang sudah hilang.
    _delete_events(db, ids)
    db.commit()
    files, freed = _remove_files(root, doomed)
    return {"events": len(ids), "files": files, "bytes": freed, "dry_run": False}
