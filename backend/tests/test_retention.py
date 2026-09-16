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

    db.refresh(ev_old)
    db.refresh(ev_fresh)
    assert ev_old.media_expired is True
    assert ev_old.clip_path is None
    assert ev_fresh.media_expired is False
    assert ev_fresh.clip_path == "clips/2026/09/14/b.mp4"


def test_sweep_dry_run_touches_nothing(db, tmp_path, monkeypatch):
    monkeypatch.setattr(retention.settings, "storage_root", str(tmp_path))
    monkeypatch.setattr(retention.settings, "retention_days", 30)
    now = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)
    path = _mkfile(str(tmp_path), "snapshots/2026/07/01/a.jpg", age_days=76)
    ev = _event(db, now - timedelta(days=76), snap="snapshots/2026/07/01/a.jpg")

    result = retention.sweep(db, now=now, dry_run=True)

    assert result["dry_run"] is True
    assert result["files_deleted"] == 1  # dilaporkan, tidak dihapus
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
