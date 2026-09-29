import os
from datetime import datetime, timedelta, timezone

from app.models.event import Event
from app.services import retention


def _mkfile(root, rel, age_days, size=1024):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(b"x" * size)
    old = datetime.now(timezone.utc).timestamp() - age_days * 86400
    os.utime(path, (old, old))
    return path


def _event(db, ts, clip=None, snap=None):
    ev = Event(type="intrusion", ts_event=ts, clip_path=clip, snapshot_path=snap)
    db.add(ev)
    db.commit()
    db.refresh(ev)
    return ev


def test_event_defaults_media_expired_false(db):
    ev = Event(type="intrusion", ts_event=datetime.now(timezone.utc))
    db.add(ev)
    db.commit()
    db.refresh(ev)
    assert ev.media_expired is False


def test_cutoff_for():
    now = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)
    assert retention.cutoff_for(now, 30) == datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)


def test_sweep_deletes_expired_files_and_marks_event(db, tmp_path, monkeypatch):
    monkeypatch.setattr(retention.settings, "storage_root", str(tmp_path))
    monkeypatch.setattr(retention.settings, "retention_days", 30)
    now = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)

    old_clip = _mkfile(str(tmp_path), "clips/2026/07/01/a.mp4", age_days=76)
    fresh_clip = _mkfile(str(tmp_path), "clips/2026/09/14/b.mp4", age_days=1)
    ev_old = _event(db, now - timedelta(days=76), clip="clips/2026/07/01/a.mp4")
    ev_fresh = _event(db, now - timedelta(days=1), clip="clips/2026/09/14/b.mp4")

    result = retention.sweep(db, now=now)

    assert result["files_deleted"] == 1
    assert result["events_marked"] == 1
    assert not os.path.exists(old_clip)
    assert os.path.exists(fresh_clip)

    # media terakhir event lama habis → event (card Events) ikut dihapus
    assert result["events_deleted"] == 1 and db.get(Event, ev_old.id) is None
    db.refresh(ev_fresh)
    assert ev_fresh.media_expired is False
    assert ev_fresh.clip_path == "clips/2026/09/14/b.mp4"


def test_sweep_keeps_clip_shared_with_unexpired_event(db, tmp_path, monkeypatch):
    # clip insiden dipakai beberapa event; cutoff jatuh di tengah insiden
    monkeypatch.setattr(retention.settings, "storage_root", str(tmp_path))
    monkeypatch.setattr(retention.settings, "retention_days", 30)
    now = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)
    cutoff = now - timedelta(days=30)

    shared = _mkfile(str(tmp_path), "clips/2026/08/16/inc.mp4", age_days=30)
    ev_old = _event(db, cutoff - timedelta(seconds=10), clip="clips/2026/08/16/inc.mp4")
    ev_new = _event(db, cutoff + timedelta(seconds=50), clip="clips/2026/08/16/inc.mp4")

    result = retention.sweep(db, now=now)

    assert os.path.exists(shared)
    assert result["files_deleted"] == 0
    assert db.get(Event, ev_old.id) is None  # medianya habis (path di-null-kan) → event dihapus
    db.refresh(ev_new)
    assert ev_new.clip_path == "clips/2026/08/16/inc.mp4"


def test_sweep_dry_run_touches_nothing(db, tmp_path, monkeypatch):
    monkeypatch.setattr(retention.settings, "storage_root", str(tmp_path))
    monkeypatch.setattr(retention.settings, "retention_days", 30)
    now = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)
    path = _mkfile(str(tmp_path), "snapshots/2026/07/01/a.jpg", age_days=76)
    ev = _event(db, now - timedelta(days=76), snap="snapshots/2026/07/01/a.jpg")

    result = retention.sweep(db, now=now, dry_run=True)

    assert result["dry_run"] is True
    assert result["files_deleted"] == 1  # dilaporkan, tidak dihapus
    assert result["events_deleted"] == 1  # prediksi, event tetap ada
    assert os.path.exists(path)
    db.refresh(ev)
    assert ev.media_expired is False
    assert ev.snapshot_path == "snapshots/2026/07/01/a.jpg"


def test_sweep_removes_old_orphan_files(db, tmp_path, monkeypatch):
    """File tanpa baris event (mis. upload gagal) tetap harus dibersihkan."""
    monkeypatch.setattr(retention.settings, "storage_root", str(tmp_path))
    monkeypatch.setattr(retention.settings, "retention_days", 30)
    now = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)
    orphan = _mkfile(str(tmp_path), "crops/2026/07/01/orphan.jpg", age_days=76)

    result = retention.sweep(db, now=now)

    assert result["orphans_deleted"] == 1
    assert not os.path.exists(orphan)


def test_sweep_keeps_file_whose_db_path_escapes_root(db, tmp_path, monkeypatch):
    """Path di DB tidak boleh dipakai untuk menghapus file di luar storage_root."""
    monkeypatch.setattr(retention.settings, "storage_root", str(tmp_path / "root"))
    monkeypatch.setattr(retention.settings, "retention_days", 30)
    now = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)
    outside = _mkfile(str(tmp_path), "outside/secret.txt", age_days=76)
    _event(db, now - timedelta(days=76), clip="../outside/secret.txt")

    retention.sweep(db, now=now)

    assert os.path.exists(outside)


def test_kind_usage_counts_files_and_bytes(tmp_path):
    _mkfile(str(tmp_path), "clips/a/b.mp4", age_days=0, size=2048)
    _mkfile(str(tmp_path), "snapshots/a/b.jpg", age_days=0, size=1024)
    usage = retention.kind_usage(str(tmp_path))
    assert usage["clips"]["files"] == 1
    assert usage["clips"]["bytes"] == 2048
    assert usage["snapshots"]["bytes"] == 1024
    assert usage["crops"]["files"] == 0


def _split(db, clip_days, snap_days):
    from app.services import storage_settings
    storage_settings.put(db, {"clip_days": clip_days, "snapshot_days": snap_days})


def test_sweep_split_retention_across_two_runs(db, tmp_path, monkeypatch):
    monkeypatch.setattr(retention.settings, "storage_root", str(tmp_path))
    _split(db, 7, 30)
    now = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)
    clip = _mkfile(str(tmp_path), "clips/2026/09/05/a.mp4", age_days=10)
    snap = _mkfile(str(tmp_path), "snapshots/2026/09/05/a.jpg", age_days=10)
    ev = _event(db, now - timedelta(days=10), clip="clips/2026/09/05/a.mp4", snap="snapshots/2026/09/05/a.jpg")

    r = retention.sweep(db, now=now)
    assert (r["files_deleted"], r["clip_days"], r["snapshot_days"]) == (1, 7, 30)
    assert not os.path.exists(clip) and os.path.exists(snap)
    db.refresh(ev)
    assert ev.clip_path is None and ev.snapshot_path == "snapshots/2026/09/05/a.jpg" and ev.media_expired is True

    later = now + timedelta(days=25)  # event kini 35 hari → snapshot kedaluwarsa juga
    r = retention.sweep(db, now=later)
    assert r["files_deleted"] == 1 and not os.path.exists(snap)
    assert r["events_deleted"] == 1 and db.get(Event, ev.id) is None  # media terakhir habis


def test_orphans_use_per_kind_cutoff(db, tmp_path, monkeypatch):
    monkeypatch.setattr(retention.settings, "storage_root", str(tmp_path))
    _split(db, 7, 30)
    now = datetime.now(timezone.utc)
    clip = _mkfile(str(tmp_path), "clips/x/orphan.mp4", age_days=10)
    snap = _mkfile(str(tmp_path), "snapshots/x/orphan.jpg", age_days=10)
    crop = _mkfile(str(tmp_path), "crops/x/orphan.jpg", age_days=40)
    r = retention.sweep(db, now=now)
    assert r["orphans_deleted"] == 2
    assert not os.path.exists(clip) and os.path.exists(snap) and not os.path.exists(crop)


def test_dry_run_counts_shared_clip_once(db, tmp_path, monkeypatch):
    monkeypatch.setattr(retention.settings, "storage_root", str(tmp_path))
    _split(db, 7, 30)
    now = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)
    clip = _mkfile(str(tmp_path), "clips/2026/09/01/shared.mp4", age_days=14, size=2048)
    _event(db, now - timedelta(days=14), clip="clips/2026/09/01/shared.mp4")
    _event(db, now - timedelta(days=14), clip="clips/2026/09/01/shared.mp4")
    r = retention.sweep(db, now=now, dry_run=True)
    assert (r["files_deleted"], r["bytes_freed"], r["events_marked"]) == (1, 2048, 2)
    assert os.path.exists(clip)


def test_crops_follow_attendance_cutoff(db, tmp_path, monkeypatch):
    """Crop 10 hari dengan attendance_days=30 harus bertahan (cutoff crop = absensi, bukan clip)."""
    monkeypatch.setattr(retention.settings, "storage_root", str(tmp_path))
    _split(db, 7, 30)
    from app.services import storage_settings
    storage_settings.put(db, {"attendance_days": 30})
    crop = _mkfile(str(tmp_path), "crops/x/fresh.jpg", age_days=10)
    snap = _mkfile(str(tmp_path), "snapshots/x/fresh.jpg", age_days=10)
    r = retention.sweep(db, now=datetime.now(timezone.utc))
    assert r["orphans_deleted"] == 0
    assert os.path.exists(crop) and os.path.exists(snap)


def _attendance(db, ts, snap=None, crop=None):
    ev = Event(type="attendance", ts_event=ts, snapshot_path=snap,
               payload={"direction": "entry", "crop_path": crop} if crop else {"direction": "entry"})
    db.add(ev)
    db.commit()
    db.refresh(ev)
    return ev


def test_attendance_media_uses_own_retention(db, tmp_path, monkeypatch):
    """Snapshot + crop wajah absensi mengikuti attendance_days; snapshot behavior tetap snapshot_days."""
    from app.services import storage_settings
    monkeypatch.setattr(retention.settings, "storage_root", str(tmp_path))
    storage_settings.put(db, {"clip_days": 30, "snapshot_days": 30, "attendance_days": 7})
    now = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)
    root = str(tmp_path)
    a_snap = _mkfile(root, "snapshots/2026/09/05/att.jpg", age_days=10)
    a_crop = _mkfile(root, "crops/2026/09/05/att.jpg", age_days=10)
    b_snap = _mkfile(root, "snapshots/2026/09/05/beh.jpg", age_days=10)
    att = _attendance(db, now - timedelta(days=10), snap="snapshots/2026/09/05/att.jpg",
                      crop="crops/2026/09/05/att.jpg")
    beh = _event(db, now - timedelta(days=10), snap="snapshots/2026/09/05/beh.jpg")

    r = retention.sweep(db, now=now)
    assert (r["files_deleted"], r["attendance_days"]) == (2, 7)
    assert not os.path.exists(a_snap) and not os.path.exists(a_crop) and os.path.exists(b_snap)
    assert db.get(Event, att.id) is None  # foto + crop habis → entri Inbox absensi dihapus
    db.refresh(beh)
    assert beh.snapshot_path == "snapshots/2026/09/05/beh.jpg" and beh.media_expired is False


def test_attendance_retention_longer_than_behavior_snapshots(db, tmp_path, monkeypatch):
    from app.services import storage_settings
    monkeypatch.setattr(retention.settings, "storage_root", str(tmp_path))
    storage_settings.put(db, {"snapshot_days": 7, "attendance_days": 90})
    now = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)
    a_snap = _mkfile(str(tmp_path), "snapshots/a.jpg", age_days=10)
    b_snap = _mkfile(str(tmp_path), "snapshots/b.jpg", age_days=10)
    _attendance(db, now - timedelta(days=10), snap="snapshots/a.jpg")
    _event(db, now - timedelta(days=10), snap="snapshots/b.jpg")
    retention.sweep(db, now=now)
    assert os.path.exists(a_snap) and not os.path.exists(b_snap)


def test_referenced_crop_not_swept_as_orphan(db, tmp_path, monkeypatch):
    """Crop yang masih dirujuk payload absensi (dalam retensi) bukan orphan walau mtime-nya tua."""
    from app.services import storage_settings
    monkeypatch.setattr(retention.settings, "storage_root", str(tmp_path))
    storage_settings.put(db, {"attendance_days": 30})
    now = datetime.now(timezone.utc)
    crop = _mkfile(str(tmp_path), "crops/x/kept.jpg", age_days=60)  # file tua, event masih baru
    orphan = _mkfile(str(tmp_path), "crops/x/orphan.jpg", age_days=60)
    _attendance(db, now - timedelta(days=2), crop="crops/x/kept.jpg")
    r = retention.sweep(db, now=now)
    assert r["orphans_deleted"] == 1
    assert os.path.exists(crop) and not os.path.exists(orphan)


def test_attendance_dry_run_changes_nothing(db, tmp_path, monkeypatch):
    from app.services import storage_settings
    monkeypatch.setattr(retention.settings, "storage_root", str(tmp_path))
    storage_settings.put(db, {"attendance_days": 7})
    now = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)
    crop = _mkfile(str(tmp_path), "crops/d.jpg", age_days=10, size=500)
    att = _attendance(db, now - timedelta(days=10), crop="crops/d.jpg")
    r = retention.sweep(db, now=now, dry_run=True)
    assert (r["files_deleted"], r["bytes_freed"]) == (1, 500)
    db.refresh(att)
    assert os.path.exists(crop) and att.payload["crop_path"] == "crops/d.jpg" and att.media_expired is False


def test_sweep_nulls_attendance_event_copy_of_crop(db, tmp_path, monkeypatch):
    """attendance_event.snapshot_path menyimpan salinan path crop → ikut di-null-kan saat crop dihapus."""
    from app.models.attendance import AttendanceEvent
    from app.models.employee import Employee
    from app.services import storage_settings
    monkeypatch.setattr(retention.settings, "storage_root", str(tmp_path))
    storage_settings.put(db, {"attendance_days": 7})
    now = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)
    from app.models.camera import Camera
    db.add(Camera(id=1, name="c1", host="h"))
    emp = Employee(name="Uji", employee_code="UJI-9")
    db.add(emp); db.commit(); db.refresh(emp)
    _mkfile(str(tmp_path), "crops/z.jpg", age_days=10)
    ev = _attendance(db, now - timedelta(days=10), crop="crops/z.jpg")
    row = AttendanceEvent(employee_id=emp.id, camera_id=1, direction="entry", ts_event=ev.ts_event,
                          snapshot_path="crops/z.jpg", event_id=ev.event_id)
    db.add(row); db.commit()
    retention.sweep(db, now=now)
    db.refresh(row)
    assert row.snapshot_path is None and db.get(AttendanceEvent, row.id) is not None  # riwayat tetap


def test_event_with_remaining_media_kept_and_system_logs_untouched(db, tmp_path, monkeypatch):
    from app.services import storage_settings
    monkeypatch.setattr(retention.settings, "storage_root", str(tmp_path))
    storage_settings.put(db, {"clip_days": 7, "snapshot_days": 30})
    now = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)
    _mkfile(str(tmp_path), "clips/k.mp4", age_days=10)
    _mkfile(str(tmp_path), "snapshots/k.jpg", age_days=10)
    kept = _event(db, now - timedelta(days=10), clip="clips/k.mp4", snap="snapshots/k.jpg")
    sys_ev = Event(type="system", ts_event=now - timedelta(days=90), media_expired=True, payload={"node": "n"})
    db.add(sys_ev); db.commit()
    r = retention.sweep(db, now=now)
    assert r["events_deleted"] == 0
    db.refresh(kept)
    assert kept.clip_path is None and kept.snapshot_path == "snapshots/k.jpg"
    assert db.get(Event, sys_ev.id) is not None


def test_new_event_waiting_for_media_is_never_purged(db, tmp_path, monkeypatch):
    """Event baru belum punya media (upload menyusul) → bukan kedaluwarsa, tidak boleh terhapus."""
    monkeypatch.setattr(retention.settings, "storage_root", str(tmp_path))
    now = datetime.now(timezone.utc)
    waiting = _event(db, now - timedelta(seconds=5))
    old_no_media = _event(db, now - timedelta(days=90))  # tanpa media sejak awal, tapi bukan hasil retensi
    r = retention.sweep(db, now=now)
    assert r["events_deleted"] == 0
    assert db.get(Event, waiting.id) is not None and db.get(Event, old_no_media.id) is not None


def test_legacy_expired_events_without_media_purged_with_alerts(db, tmp_path, monkeypatch):
    """Event lama yang medianya sudah dihapus retensi versi sebelumnya ikut dibersihkan (+ alert)."""
    from app.models.alert import Alert
    monkeypatch.setattr(retention.settings, "storage_root", str(tmp_path))
    now = datetime.now(timezone.utc)
    ev = _event(db, now - timedelta(days=60))
    ev.media_expired = True
    db.add(Alert(event_id=ev.id, type="intrusion", status="sent"))
    db.commit()
    dry = retention.sweep(db, now=now, dry_run=True)
    assert dry["events_deleted"] == 1 and db.get(Event, ev.id) is not None
    r = retention.sweep(db, now=now)
    assert r["events_deleted"] == 1 and db.get(Event, ev.id) is None and db.query(Alert).count() == 0
