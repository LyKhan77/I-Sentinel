# Retention & Storage UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Admin mengatur retensi clip dan snapshot secara terpisah dari UI, membersihkan event behavior per rentang tanggal (attendance selalu aman), dan mendapat peringatan disk hampir penuh lewat banner + Telegram.

**Architecture:** Pengaturan di tabel `setting` (key `storage`, tanpa migrasi) lewat service `storage_settings`; `retention.sweep` memakai cutoff per jenis; `retention.cleanup` menghapus event + media + alert; `disk_alert.check` + thread `DiskAlertMonitor` di lifespan API. Frontend: tab Storage mendapat kartu Pengaturan retensi, kartu Bersihkan event, dan banner disk (juga di Dashboard).

**Tech Stack:** FastAPI + SQLAlchemy 2 + Pydantic v2, pytest; React 19 + TypeScript + Carbon, Vitest.

**Spec:** `docs/superpowers/specs/2026-09-29-retention-storage-ui-design.md`

## Global Constraints

- Branch `feat/retention-storage-ui` (dari `main` @ `5c17cea`; spec `516db9f`).
- **Tanpa AI attribution** di commit/kode/docs (`AGENTS.md` §9).
- Tanpa dependensi baru, **tanpa migrasi DB** (pakai tabel `setting`).
- **Event `attendance` tidak pernah dihapus** oleh cleanup — dalam kondisi apa pun.
- File hanya dihapus bila path hasil `_safe_join` berada di dalam `storage_root`.
- Validasi: retensi **1–3650** hari, ambang disk **50–99** %; cleanup `date_from <= date_to <= hari ini`.
- Telegram: token tidak pernah di log/pesan; tanpa token/grup → tidak mengirim, tanpa error.
- REST hanya lewat `src/api/*`; string UI lewat `i18n.tsx` (`id` + `en`, kunci sama); Carbon + token tema; 390 px
  tanpa overflow horizontal halaman.
- **Jangan** `uv sync` / `uv lock` / membuat ulang venv.
- Setiap task: commit Conventional Commits + bullet `CHANGELOG.md` bagian `### Retention & Storage UI (2026-09-29 – …)`
  (dibuat di Task 1, di atas `### User management (2026-09-28)`).
- Baseline `main` `5c17cea`: backend **450**, vision **223** (3 deselected), frontend **171**, build 0, lint = set rule+file lama.
- **Eksekutor berhenti setelah `git push`.** Deploy (restart API) dan uji lapangan di sesi perencana.

## Deviasi / keputusan teknis dari spec

1. **Kunci yang tidak disimpan tetap mengikuti env**: `put` hanya menyimpan field yang dikirim; mis. hanya
   `clip_days` disimpan → `snapshot_days` tetap = `RETENTION_DAYS`.
2. **Sweep tidak lagi menyaring `media_expired=False`**: dengan retensi terpisah, event yang clip-nya sudah
   kedaluwarsa masih harus diproses saat snapshot-nya kedaluwarsa; path yang sudah `NULL` menjadi penandanya.
3. **Perbandingan waktu dilakukan di SQL**, bukan Python (SQLite di tes mengembalikan datetime naif).
4. **Dry run menghitung file bersama sekali** (set `seen`) — perilaku lama bisa menghitung ganda.
5. `CleanupIn.dry_run` default **`true`** (aman bila klien lupa mengirim).
6. `formatBytes` dipindah ke `features/config/bytes.ts` (dipakai StoragePage + kartu cleanup).
7. Thread `DiskAlertMonitor` menunggu satu interval (600 s) sebelum cek pertama → tidak berjalan selama tes.

## Review Focus

1. **Attendance diminta eksplisit di filter cleanup** → tetap tidak terhapus (0 event bila hanya attendance).
   Tes: Task 3 `test_cleanup_never_deletes_attendance`.
2. **Clip insiden bersama** antara event dalam rentang dan di luar rentang → file tetap ada.
   Tes: Task 3 `test_cleanup_keeps_clip_shared_with_event_outside_range`.
3. **Batas hari di zona lokal** (23:30 vs 00:30) → hanya event di dalam tanggal lokal yang terhapus.
   Tes: Task 3 `test_cleanup_local_day_boundaries`.
4. **Clip kedaluwarsa tapi snapshot belum** → snapshot tetap tampil, sweep berikutnya tetap menghapus snapshot
   saat waktunya. Tes: Task 2 `test_sweep_split_retention_across_two_runs`.
5. **Tombol Hapus setelah filter diubah** → nonaktif sampai pratinjau ulang (tidak menghapus rentang yang belum
   dipratinjau). Tes: Task 6 `hapus nonaktif sampai pratinjau untuk filter yang sama`.

---

### Task 1: Pengaturan storage (service + API + stats)

**Files:**
- Create: `backend/app/services/storage_settings.py`
- Create: `backend/app/schemas/storage.py`
- Modify: `backend/app/api/storage.py`
- Test: `backend/tests/test_storage_api.py`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Produces:
  - `storage_settings.KEY = "storage"`, `DEFAULT_ALERT_PERCENT = 85`
  - `storage_settings.get(db) -> dict` → `{"clip_days": int, "snapshot_days": int, "disk_alert_percent": int}`
  - `storage_settings.put(db, patch: dict) -> dict` (commit; field `None` diabaikan)
  - `schemas.storage.StorageSettingsPatch` (`extra="forbid"`)
  - `GET /api/v1/storage/settings`, `PUT /api/v1/storage/settings` (admin)
  - `GET /storage/stats` + `"settings": {...}`, `"disk_alert": {"threshold": int, "over": bool}`; `retention_days` = `clip_days`

- [ ] **Step 1: Tulis tes (gagal)** — tambahkan di `backend/tests/test_storage_api.py`:

```python
def test_settings_default_from_env_and_partial_put(client, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "retention_days", 30)
    h = admin_headers(client)
    assert client.get("/api/v1/storage/settings", headers=h).json() == \
        {"clip_days": 30, "snapshot_days": 30, "disk_alert_percent": 85}
    r = client.put("/api/v1/storage/settings", json={"clip_days": 7}, headers=h)
    assert r.status_code == 200 and r.json()["clip_days"] == 7
    monkeypatch.setattr(settings, "retention_days", 45)  # yang tidak disimpan tetap ikut env
    assert client.get("/api/v1/storage/settings", headers=h).json() == \
        {"clip_days": 7, "snapshot_days": 45, "disk_alert_percent": 85}


def test_settings_validation_and_admin_only(client):
    h = admin_headers(client)
    for body in ({"clip_days": 0}, {"snapshot_days": 3651}, {"disk_alert_percent": 49},
                 {"disk_alert_percent": 100}, {"foo": 1}, {"clip_days": "tujuh"}):
        assert client.put("/api/v1/storage/settings", json=body, headers=h).status_code == 422, body
    assert client.put("/api/v1/storage/settings", json={"clip_days": 7},
                      headers=viewer_headers(client)).status_code == 403


def test_stats_includes_settings_and_disk_alert(client, tmp_path, monkeypatch):
    from app.services import retention
    monkeypatch.setattr(retention.settings, "storage_root", str(tmp_path))
    monkeypatch.setattr(retention.settings, "retention_days", 30)
    h = admin_headers(client)
    client.put("/api/v1/storage/settings", json={"clip_days": 14, "disk_alert_percent": 85}, headers=h)
    usage = {"total": 100, "used": 90, "free": 10, "percent": 90.0}
    monkeypatch.setattr(retention, "disk_usage", lambda root: usage)
    body = client.get("/api/v1/storage/stats", headers=h).json()
    assert body["settings"] == {"clip_days": 14, "snapshot_days": 30, "disk_alert_percent": 85}
    assert body["retention_days"] == 14
    assert body["disk_alert"] == {"threshold": 85, "over": True}
    usage["percent"] = 80.0
    assert client.get("/api/v1/storage/stats", headers=h).json()["disk_alert"]["over"] is False
```

(`viewer_headers` ada di `tests/conftest.py`; import lewat `from tests.conftest import *` yang sudah ada.)

- [ ] **Step 2: Jalankan, pastikan gagal** — `cd backend && .venv/bin/python -m pytest tests/test_storage_api.py -q`.

- [ ] **Step 3: Implementasi**

`backend/app/schemas/storage.py`:

```python
from pydantic import BaseModel, Field


class StorageSettingsPatch(BaseModel):
    """Perubahan parsial pengaturan storage; field kosong = tidak diubah."""
    model_config = {"extra": "forbid"}
    clip_days: int | None = Field(default=None, ge=1, le=3650)
    snapshot_days: int | None = Field(default=None, ge=1, le=3650)
    disk_alert_percent: int | None = Field(default=None, ge=50, le=99)
```

`backend/app/services/storage_settings.py`:

```python
"""Pengaturan retensi & peringatan disk (tabel setting, key "storage").

Field yang belum pernah disimpan mengikuti env (RETENTION_DAYS) / default, jadi .env tetap berlaku
sampai admin menyimpan nilai lain dari UI.
"""
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.setting import Setting

KEY = "storage"
DEFAULT_ALERT_PERCENT = 85


def _stored(db: Session) -> dict:
    row = db.get(Setting, KEY)
    return dict(row.value or {}) if row is not None else {}


def get(db: Session) -> dict:
    v = _stored(db)
    days = settings.retention_days
    return {
        "clip_days": int(v.get("clip_days", days)),
        "snapshot_days": int(v.get("snapshot_days", days)),
        "disk_alert_percent": int(v.get("disk_alert_percent", DEFAULT_ALERT_PERCENT)),
    }


def put(db: Session, patch: dict) -> dict:
    stored = {**_stored(db), **{k: v for k, v in patch.items() if v is not None}}
    row = db.get(Setting, KEY)
    if row is None:
        db.add(Setting(key=KEY, value=stored))
    else:
        row.value = stored  # dict baru → SQLAlchemy mendeteksi perubahan JSON
    db.commit()
    return get(db)
```

`backend/app/api/storage.py` — import `storage_settings`, `StorageSettingsPatch`; `storage_stats` dan dua endpoint baru:

```python
@router.get("/stats")
def storage_stats(db: Session = Depends(get_db), user=Depends(get_current_user)):
    root = settings.storage_root
    s = storage_settings.get(db)
    disk = retention.disk_usage(root)
    return {
        "retention_days": s["clip_days"],  # kompatibilitas klien lama
        "settings": s,
        "storage_root": root,
        "disk": disk,
        "disk_alert": {"threshold": s["disk_alert_percent"], "over": disk["percent"] >= s["disk_alert_percent"]},
        "kinds": retention.kind_usage(root),
        "last_sweep": _last_sweep(db),
    }


@router.get("/settings")
def get_settings(db: Session = Depends(get_db), user=Depends(get_current_user)):
    return storage_settings.get(db)


@router.put("/settings")
def put_settings(body: StorageSettingsPatch, db: Session = Depends(get_db), admin=Depends(require_admin)):
    return storage_settings.put(db, body.model_dump())
```

- [ ] **Step 4: Jalankan, pastikan lulus** — backend suite penuh:
`cd backend && .venv/bin/python -m pytest tests -q -m "not gpu" > /tmp/be.log 2>&1; grep -oE '[0-9]+ (passed|failed)[^|]*' /tmp/be.log | tail -1`

- [ ] **Step 5: CHANGELOG + commit** — di atas `### User management (2026-09-28)`:

```markdown
### Retention & Storage UI (2026-09-29 – …)

- **Pengaturan storage editable**: setting `storage` (`clip_days`, `snapshot_days`, `disk_alert_percent`; field yang
  belum disimpan ikut `RETENTION_DAYS`/85 %), `GET/PUT /storage/settings` (PUT admin, 1–3650 hari, 50–99 %),
  `/storage/stats` memuat `settings` + `disk_alert`. Backend **<angka> passed**.
```

```bash
git add backend/app/services/storage_settings.py backend/app/schemas/storage.py backend/app/api/storage.py backend/tests/test_storage_api.py CHANGELOG.md
git commit -m "feat(storage): pengaturan retensi dan ambang disk tersimpan di DB"
```

---

### Task 2: Sweep dengan retensi clip vs snapshot

**Files:**
- Modify: `backend/app/services/retention.py` (`sweep`, helper `_expire_field`)
- Test: `backend/tests/test_retention.py`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: `storage_settings.get(db)` (Task 1).
- Produces: hasil `sweep()` + `"clip_days"`, `"snapshot_days"`; `ORPHAN_CUTOFF_KIND = {"clips": "clip", "snapshots": "snapshot", "crops": "snapshot"}`.

- [ ] **Step 1: Tulis tes (gagal)** — tambahkan di `backend/tests/test_retention.py`:

```python
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
    db.refresh(ev)
    assert ev.snapshot_path is None


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
```

- [ ] **Step 2: Jalankan, pastikan gagal** — `cd backend && .venv/bin/python -m pytest tests/test_retention.py -q`.

- [ ] **Step 3: Implementasi** — `backend/app/services/retention.py`: import `from app.services import storage_settings`;
ganti fungsi `sweep` (helper lain tetap) dengan:

```python
ORPHAN_CUTOFF_KIND = {"clips": "clip", "snapshots": "snapshot", "crops": "snapshot"}


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
```

(`scripts/retention_sweep.py` tidak perlu diubah — memanggil `retention.sweep(db)`; perbarui baris log-nya agar
mencetak `result["clip_days"]`/`result["snapshot_days"]` alih-alih `settings.retention_days`.)

- [ ] **Step 4: Jalankan, pastikan lulus** — backend suite penuh (semua tes retensi lama harus tetap hijau).

- [ ] **Step 5: CHANGELOG + commit**

```markdown
- **Sweep retensi terpisah**: clip memakai `clip_days`, snapshot/crops memakai `snapshot_days` (juga orphan);
  event yang clip-nya sudah kedaluwarsa tetap diproses saat snapshot-nya kedaluwarsa; dry run menghitung clip
  bersama sekali; hasil sweep mencatat `clip_days`/`snapshot_days`. Backend **<angka> passed**.
```

```bash
git add backend/app/services/retention.py backend/scripts/retention_sweep.py backend/tests/test_retention.py CHANGELOG.md
git commit -m "feat(storage): sweep retensi terpisah clip dan snapshot"
```

---

### Task 3: Cleanup event per rentang tanggal

**Files:**
- Modify: `backend/app/services/retention.py` (`cleanup`)
- Modify: `backend/app/schemas/storage.py` (`CleanupIn`)
- Modify: `backend/app/api/storage.py` (`POST /cleanup`)
- Test: `backend/tests/test_storage_cleanup.py` (baru)
- Modify: `CHANGELOG.md`

**Interfaces:**
- Produces: `retention.cleanup(db, date_from: date, date_to: date, camera_ids: list[int] | None = None, types: list[str] | None = None, dry_run: bool = True) -> dict` → `{"events", "files", "bytes", "dry_run"}`;
  `POST /api/v1/storage/cleanup` (admin) body `CleanupIn`.

- [ ] **Step 1: Tulis tes (gagal)** — `backend/tests/test_storage_cleanup.py`:

```python
import os
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.db import get_db
from app.models.alert import Alert
from app.models.camera import Camera
from app.models.event import Event
from app.services import retention
from tests.conftest import *  # noqa


def _local(y, m, d, hh=12, mm=0):
    """Waktu lokal server (cleanup memakai tanggal lokal)."""
    return datetime(y, m, d, hh, mm).astimezone()


def _file(root, rel, size=100):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(b"x" * size)
    return path


def _ev(db, ts, type_="intrusion", cam=None, clip=None, snap=None):
    ev = Event(type=type_, ts_event=ts, camera_id=cam, clip_path=clip, snapshot_path=snap)
    db.add(ev); db.commit(); db.refresh(ev)
    return ev


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(retention.settings, "storage_root", str(tmp_path))
    return str(tmp_path)


def test_cleanup_dry_run_changes_nothing(db, root):
    clip = _file(root, "clips/a.mp4", 300)
    ev = _ev(db, _local(2026, 9, 10), clip="clips/a.mp4")
    r = retention.cleanup(db, date(2026, 9, 10), date(2026, 9, 10), dry_run=True)
    assert r == {"events": 1, "files": 1, "bytes": 300, "dry_run": True}
    assert os.path.exists(clip) and db.get(Event, ev.id) is not None


def test_cleanup_deletes_events_media_and_alerts(db, root):
    clip = _file(root, "clips/a.mp4")
    snap = _file(root, "snapshots/a.jpg")
    ev = _ev(db, _local(2026, 9, 10), clip="clips/a.mp4", snap="snapshots/a.jpg")
    db.add(Alert(event_id=ev.id, type="intrusion", status="sent")); db.commit()
    outside = _ev(db, _local(2026, 9, 12))
    r = retention.cleanup(db, date(2026, 9, 10), date(2026, 9, 11), dry_run=False)
    assert (r["events"], r["files"]) == (1, 2)
    assert not os.path.exists(clip) and not os.path.exists(snap)
    assert db.get(Event, ev.id) is None and db.query(Alert).count() == 0
    assert db.get(Event, outside.id) is not None


def test_cleanup_never_deletes_attendance(db, root):
    att = _ev(db, _local(2026, 9, 10), type_="attendance")
    assert retention.cleanup(db, date(2026, 9, 10), date(2026, 9, 10), dry_run=False)["events"] == 0
    r = retention.cleanup(db, date(2026, 9, 10), date(2026, 9, 10), types=["attendance"], dry_run=False)
    assert r["events"] == 0 and db.get(Event, att.id) is not None


def test_cleanup_keeps_clip_shared_with_event_outside_range(db, root):
    clip = _file(root, "clips/shared.mp4")
    _ev(db, _local(2026, 9, 10, 23, 59), clip="clips/shared.mp4")
    keep = _ev(db, _local(2026, 9, 11, 0, 1), clip="clips/shared.mp4")
    r = retention.cleanup(db, date(2026, 9, 10), date(2026, 9, 10), dry_run=False)
    assert (r["events"], r["files"]) == (1, 0)
    assert os.path.exists(clip) and db.get(Event, keep.id).clip_path == "clips/shared.mp4"


def test_cleanup_local_day_boundaries(db, root):
    late = _ev(db, _local(2026, 9, 10, 23, 30))
    early = _ev(db, _local(2026, 9, 11, 0, 30))
    retention.cleanup(db, date(2026, 9, 11), date(2026, 9, 11), dry_run=False)
    assert db.get(Event, late.id) is not None and db.get(Event, early.id) is None


def test_cleanup_filters_camera_and_type(db, root):
    db.add_all([Camera(id=1, name="c1", host="h"), Camera(id=2, name="c2", host="h")]); db.commit()
    a = _ev(db, _local(2026, 9, 10), cam=1, type_="intrusion")
    b = _ev(db, _local(2026, 9, 10), cam=2, type_="intrusion")
    c = _ev(db, _local(2026, 9, 10), cam=1, type_="loitering")
    r = retention.cleanup(db, date(2026, 9, 10), date(2026, 9, 10), camera_ids=[1], types=["loitering"], dry_run=False)
    assert r["events"] == 1
    assert db.get(Event, c.id) is None and db.get(Event, a.id) is not None and db.get(Event, b.id) is not None


@pytest.fixture
def client(db, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "admin_username", "admin")
    monkeypatch.setattr(settings, "admin_password", "boot123")
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_cleanup_api_validation_and_admin_only(client, root):
    h = admin_headers(client)
    today = date.today()
    ok = {"date_from": str(today - timedelta(days=3)), "date_to": str(today), "dry_run": True}
    r = client.post("/api/v1/storage/cleanup", json=ok, headers=h)
    assert r.status_code == 200 and r.json() == {"events": 0, "files": 0, "bytes": 0, "dry_run": True}
    for bad in ({**ok, "date_from": str(today), "date_to": str(today - timedelta(days=1))},
                {**ok, "date_to": str(today + timedelta(days=1))},
                {**ok, "types": ["meteor"]},
                {**ok, "date_from": "kemarin"},
                {**ok, "hapus_semua": True}):
        assert client.post("/api/v1/storage/cleanup", json=bad, headers=h).status_code == 422, bad
    assert client.post("/api/v1/storage/cleanup", json=ok, headers=viewer_headers(client)).status_code == 403
```

- [ ] **Step 2: Jalankan, pastikan gagal** — `cd backend && .venv/bin/python -m pytest tests/test_storage_cleanup.py -q`.

- [ ] **Step 3: Implementasi**

`backend/app/schemas/storage.py` (tambah):

```python
from datetime import date

from pydantic import model_validator

from app.services.ingest import ALLOWED_TYPES


class CleanupIn(BaseModel):
    """Hapus event behavior per rentang tanggal lokal; attendance tidak pernah ikut."""
    model_config = {"extra": "forbid"}
    date_from: date
    date_to: date
    camera_ids: list[int] = []
    types: list[str] = []
    dry_run: bool = True  # aman bila klien lupa mengirim

    @model_validator(mode="after")
    def _check(self):
        if self.date_from > self.date_to:
            raise ValueError("date_from must be <= date_to")
        if self.date_to > date.today():
            raise ValueError("date_to must not be in the future")
        unknown = set(self.types) - ALLOWED_TYPES
        if unknown:
            raise ValueError(f"unknown event types: {sorted(unknown)}")
        return self
```

`backend/app/services/retention.py` (import `date`, `time` dari datetime, `Alert`, `or_`):

```python
from datetime import date, time
from sqlalchemy import or_
from app.models.alert import Alert

PROTECTED_TYPES = ("attendance",)  # sumber hari absensi & export — tidak pernah dihapus cleanup


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
        db.query(Alert).filter(Alert.event_id.in_(ids)).delete(synchronize_session=False)
        db.query(Event).filter(Event.id.in_(ids)).delete(synchronize_session=False)
        db.commit()
    return {"events": len(ids), "files": files, "bytes": freed, "dry_run": dry_run}
```

`backend/app/api/storage.py` (import `logging`, `CleanupIn`):

```python
logger = logging.getLogger(__name__)


@router.post("/cleanup")
def cleanup_events(body: CleanupIn, db: Session = Depends(get_db), admin=Depends(require_admin)):
    result = retention.cleanup(db, body.date_from, body.date_to, body.camera_ids, body.types, dry_run=body.dry_run)
    if not body.dry_run:
        logger.info("event cleanup by %s: %s..%s cameras=%s types=%s → %s events, %s files, %s bytes",
                    admin.username, body.date_from, body.date_to, body.camera_ids or "all",
                    body.types or "all", result["events"], result["files"], result["bytes"])
    return result
```

(Bila import `app.services.ingest` dari schema menimbulkan import melingkar, pindahkan `ALLOWED_TYPES` ke
`app/services/event_types.py` dan impor dari kedua tempat — catat deviasinya.)

- [ ] **Step 4: Jalankan, pastikan lulus** — backend suite penuh.

- [ ] **Step 5: CHANGELOG + commit**

```markdown
- **Cleanup event per tanggal**: `POST /storage/cleanup` (admin, dry run default) menghapus event non-attendance +
  clip/snapshot + alert-nya pada rentang tanggal lokal (filter kamera/jenis opsional); attendance tidak pernah
  dihapus walau diminta; clip bersama dengan event di luar rentang dipertahankan; validasi tanggal/jenis 422;
  cleanup nyata dicatat di log dengan username admin. Backend **<angka> passed**.
```

```bash
git add backend/app/services/retention.py backend/app/schemas/storage.py backend/app/api/storage.py backend/tests/test_storage_cleanup.py CHANGELOG.md
git commit -m "feat(storage): cleanup event per rentang tanggal tanpa menyentuh absensi"
```

---

### Task 4: Peringatan disk hampir penuh (check + thread + Telegram)

**Files:**
- Create: `backend/app/services/disk_alert.py`
- Modify: `backend/app/main.py` (lifespan start/stop)
- Test: `backend/tests/test_disk_alert.py` (baru)
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: `storage_settings.get` (Task 1), `retention.disk_usage`, `telegram.get_token/active_chat/deliver`.
- Produces: `disk_alert.STATE_KEY = "disk_alert_state"`, `RECOVER_MARGIN = 2`, `REPEAT_AFTER = timedelta(hours=24)`,
  `check(db, now=None, percent=None, free_bytes=None, send=None) -> str | None` (`"alert"`/`"recovered"`/`None`),
  `DiskAlertMonitor(interval_s=600, session_factory=SessionLocal)` dengan `start()`/`stop()`, instance `monitor`.

- [ ] **Step 1: Tulis tes (gagal)** — `backend/tests/test_disk_alert.py`:

```python
import time
from datetime import datetime, timedelta, timezone

from app.models.setting import Setting
from app.services import disk_alert, storage_settings

T0 = datetime(2026, 9, 29, 8, 0, tzinfo=timezone.utc)
GB = 1024 ** 3


def test_alert_once_repeat_after_24h_and_recover(db):
    storage_settings.put(db, {"disk_alert_percent": 85})
    sent = []
    send = lambda db, text: sent.append(text) or True
    check = lambda now, pct: disk_alert.check(db, now=now, percent=pct, free_bytes=50 * GB, send=send)
    assert check(T0, 80.0) is None
    assert check(T0, 86.0) == "alert" and "86" in sent[-1] and "85" in sent[-1]
    assert check(T0 + timedelta(hours=23), 90.0) is None               # belum 24 jam
    assert check(T0 + timedelta(hours=24, minutes=1), 90.0) == "alert"  # pengingat harian
    assert check(T0 + timedelta(hours=25), 84.0) is None               # di atas ambang − 2 → belum pulih
    assert check(T0 + timedelta(hours=26), 82.0) == "recovered" and "82" in sent[-1]
    assert len(sent) == 3
    assert check(T0 + timedelta(hours=27), 86.0) == "alert"            # lewat lagi → kirim lagi


def test_without_telegram_state_kept_and_sent_later(db):
    storage_settings.put(db, {"disk_alert_percent": 85})
    assert disk_alert.check(db, now=T0, percent=95.0, free_bytes=GB, send=lambda db, t: False) is None
    state = db.get(Setting, disk_alert.STATE_KEY).value
    assert state["over"] is True and state["last_sent_at"] is None
    got = []
    assert disk_alert.check(db, now=T0 + timedelta(minutes=10), percent=95.0, free_bytes=GB,
                            send=lambda db, t: got.append(t) or True) == "alert"
    assert got


def test_default_send_skips_when_telegram_not_configured(db, monkeypatch):
    from app.services import telegram
    monkeypatch.setattr(telegram, "get_token", lambda: "")
    called = []
    monkeypatch.setattr(telegram, "deliver", lambda *a, **k: called.append(a) or ("sent", None))
    assert disk_alert._send(db, "x") is False and called == []


def test_monitor_runs_check_and_stops(monkeypatch):
    calls = []
    monkeypatch.setattr(disk_alert, "check", lambda db: calls.append(db))

    class FakeSession:
        def close(self):
            pass

    m = disk_alert.DiskAlertMonitor(interval_s=0.01, session_factory=FakeSession)
    m.start()
    time.sleep(0.1)
    m.stop()
    assert calls and not m._thread.is_alive()
```

- [ ] **Step 2: Jalankan, pastikan gagal** — `cd backend && .venv/bin/python -m pytest tests/test_disk_alert.py -q`.

- [ ] **Step 3: Implementasi** — `backend/app/services/disk_alert.py`:

```python
"""Peringatan disk hampir penuh: cek berkala → pesan Telegram + state untuk banner.

State di setting "disk_alert_state" {"over", "last_sent_at"} supaya pengingat 24 jam dan pesan
"pulih" tetap benar setelah API restart. Tanpa token/grup Telegram: tidak mengirim, state tetap.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone

from app.core.config import settings
from app.core.db import SessionLocal
from app.models.setting import Setting
from app.services import retention, storage_settings, telegram

logger = logging.getLogger(__name__)

STATE_KEY = "disk_alert_state"
RECOVER_MARGIN = 2  # % di bawah ambang sebelum dianggap pulih (cegah pesan bolak-balik)
REPEAT_AFTER = timedelta(hours=24)


def _send(db, text: str) -> bool:
    token = telegram.get_token()
    chat = telegram.active_chat(db)
    if not token or chat is None:
        return False
    status, error = telegram.deliver(token, chat.chat_id, text, retries=1)
    if status != "sent":
        logger.warning("disk alert telegram failed: %s", error)  # pesan deliver() sudah bebas token
    return status == "sent"


def _state(db) -> dict:
    row = db.get(Setting, STATE_KEY)
    return dict(row.value or {}) if row is not None else {"over": False, "last_sent_at": None}


def _save(db, state: dict) -> None:
    row = db.get(Setting, STATE_KEY)
    if row is None:
        db.add(Setting(key=STATE_KEY, value=state))
    else:
        row.value = state
    db.commit()


def check(db, now: datetime | None = None, percent: float | None = None,
          free_bytes: int | None = None, send=None) -> str | None:
    """Bandingkan pemakaian disk dengan ambang; kirim peringatan/pulih bila perlu."""
    now = now or datetime.now(timezone.utc)
    send = send or _send
    if percent is None or free_bytes is None:
        usage = retention.disk_usage(settings.storage_root)
        percent, free_bytes = usage["percent"], usage["free"]
    threshold = storage_settings.get(db)["disk_alert_percent"]
    state = _state(db)
    last = datetime.fromisoformat(state["last_sent_at"]) if state.get("last_sent_at") else None
    sent_kind = None
    if percent >= threshold:
        if not state.get("over") or last is None or now - last >= REPEAT_AFTER:
            text = (f"⚠️ Disk hampir penuh: {percent:.0f}% (ambang {threshold}%) — "
                    f"sisa {free_bytes / 1024 ** 3:.1f} GB")
            if send(db, text):
                last, sent_kind = now, "alert"
        state = {"over": True, "last_sent_at": last.isoformat() if last else None}
    elif state.get("over") and percent < threshold - RECOVER_MARGIN:
        if send(db, f"✅ Disk pulih: {percent:.0f}% (ambang {threshold}%)"):
            sent_kind = "recovered"
        state = {"over": False, "last_sent_at": None}
    _save(db, state)
    return sent_kind


class DiskAlertMonitor:
    """Thread latar: check() tiap interval_s; menunggu satu interval sebelum cek pertama."""

    def __init__(self, interval_s: float = 600, session_factory=SessionLocal):
        self.interval_s = interval_s
        self._session_factory = session_factory
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="disk-alert")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def _loop(self) -> None:
        while not self._stop.wait(self.interval_s):
            db = self._session_factory()
            try:
                check(db)
            except Exception:
                logger.warning("disk alert check failed", exc_info=True)
            finally:
                db.close()


monitor = DiskAlertMonitor()
```

(Catatan: tes `check(..., now=T0, percent=86.0)` → state `over` dan `last_sent_at` diisi; kalimat
"not state over" pada cek berikut di bawah ambang−2 → `recovered`. `datetime.fromisoformat` menerima offset
`+00:00`.)

`backend/app/main.py` — di lifespan setelah `dispatcher.start()`:

```python
    from app.services.disk_alert import monitor as disk_monitor
    disk_monitor.start()
    try:
        yield
    finally:
        disk_monitor.stop()
        dispatcher.stop()
        consumer.stop()
```

- [ ] **Step 4: Jalankan, pastikan lulus** — backend suite penuh (pastikan durasi suite tidak naik: thread menunggu
  600 s dan berhenti saat shutdown).

- [ ] **Step 5: CHANGELOG + commit**

```markdown
- **Peringatan disk hampir penuh**: `disk_alert.check` (ambang dari pengaturan; Telegram sekali, ulang ≤ 1×/24 jam,
  "pulih" saat < ambang − 2 %; tanpa Telegram state tetap disimpan) + thread `DiskAlertMonitor` tiap 10 menit di
  lifespan API. Backend **<angka> passed**.
```

```bash
git add backend/app/services/disk_alert.py backend/app/main.py backend/tests/test_disk_alert.py CHANGELOG.md
git commit -m "feat(storage): peringatan disk hampir penuh lewat Telegram"
```

---

### Task 5: Frontend — pengaturan retensi, banner disk, tile retensi

**Files:**
- Modify: `frontend/src/api/storage.ts`
- Create: `frontend/src/features/config/bytes.ts` (pindahan `formatBytes`)
- Create: `frontend/src/features/config/StorageSettingsCard.tsx`
- Create: `frontend/src/components/DiskAlertBanner.tsx`
- Modify: `frontend/src/features/config/StoragePage.tsx`
- Modify: `frontend/src/features/dashboard/DashboardPage.tsx`
- Modify: `frontend/src/app/theme.scss` (`.st-card*`)
- Modify: `frontend/src/app/i18n.tsx`
- Test: `frontend/src/__tests__/storage.test.tsx`, `frontend/src/__tests__/dashboard.test.tsx`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: API Task 1.
- Produces:
  - `api/storage.ts`: `type StorageSettings = { clip_days: number; snapshot_days: number; disk_alert_percent: number }`;
    `StorageStats` + `settings: StorageSettings`, `disk_alert: { threshold: number; over: boolean }`;
    `saveStorageSettings(s: StorageSettings): Promise<StorageSettings>` (422 → `Error('invalid')`).
  - `features/config/bytes.ts`: `formatBytes(n: number, locale: string): string`.
  - `components/DiskAlertBanner.tsx`: `DiskAlertBanner({ stats }: { stats: StorageStats | null })`.
  - `StorageSettingsCard({ value, isAdmin, onSaved }: { value: StorageSettings; isAdmin: boolean; onSaved: (s: StorageSettings) => void })`.

- [ ] **Step 1: Tulis tes (gagal)** — ubah `frontend/src/__tests__/storage.test.tsx`: fixture `STATS` ditambah

```tsx
  settings: { clip_days: 30, snapshot_days: 30, disk_alert_percent: 85 },
  disk_alert: { threshold: 85, over: true },
```

(disk 85 % ≥ 85 → banner). Tambahkan:

```tsx
import { fireEvent, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

const json = (status: number, body: unknown) => ({ ok: status < 400, status, json: () => Promise.resolve(body) })

function stub(role: 'admin' | 'viewer', putStatus = 200) {
  const f = vi.fn(async (url: string, init?: RequestInit) => {
    const u = String(url)
    if (u.endsWith('/auth/me')) return json(200, { id: 1, username: 'u', role })
    if (u.endsWith('/storage/settings') && init?.method === 'PUT') {
      return putStatus === 200 ? json(200, JSON.parse(String(init.body))) : json(putStatus, { detail: [] })
    }
    if (u.endsWith('/storage/stats')) return json(200, STATS)
    if (u.endsWith('/cameras')) return json(200, [])
    return json(404, null)
  })
  vi.stubGlobal('fetch', f)
  return f
}

const renderStorage = () => render(<I18nProvider><StoragePage /></I18nProvider>)

afterEach(() => vi.unstubAllGlobals())

test('banner disk hampir penuh dan tile retensi clip/snapshot', async () => {
  stub('viewer')
  renderStorage()
  expect(await screen.findByTestId('disk-alert')).toHaveTextContent('Disk hampir penuh (85%)')
  expect(screen.getByTestId('storage-retention')).toHaveTextContent('Clip 30 hari · Snapshot 30 hari')
})

test('admin menyimpan pengaturan retensi', async () => {
  const f = stub('admin')
  renderStorage()
  const clip = await screen.findByLabelText('Retensi clip (hari)')
  await waitFor(() => expect(screen.getByTestId('storage-settings-save')).toBeInTheDocument())
  fireEvent.change(clip, { target: { value: '7' } })
  await userEvent.click(screen.getByTestId('storage-settings-save'))
  expect(await screen.findByText('Pengaturan tersimpan')).toBeInTheDocument()
  const put = f.mock.calls.find(([, i]) => (i as RequestInit | undefined)?.method === 'PUT')!
  expect(JSON.parse(String((put[1] as RequestInit).body))).toEqual({ clip_days: 7, snapshot_days: 30, disk_alert_percent: 85 })
  expect(screen.getByTestId('storage-retention')).toHaveTextContent('Clip 7 hari')
})

test('422 dari server tampil sebagai pesan rentang', async () => {
  stub('admin', 422)
  renderStorage()
  await waitFor(() => expect(screen.getByTestId('storage-settings-save')).toBeInTheDocument())
  await userEvent.click(screen.getByTestId('storage-settings-save'))
  expect(await screen.findByText(/Nilai di luar rentang/)).toBeInTheDocument()
})

test('viewer: pengaturan hanya-baca, tanpa tombol simpan dan tanpa kartu cleanup', async () => {
  stub('viewer')
  renderStorage()
  expect(await screen.findByLabelText('Retensi clip (hari)')).toBeDisabled()
  expect(screen.queryByTestId('storage-settings-save')).not.toBeInTheDocument()
  expect(screen.queryByTestId('storage-cleanup')).not.toBeInTheDocument()
})
```

Di `dashboard.test.tsx` — `stubFetch` menjawab `/storage/stats` dengan `{ ...STATS_STORAGE, disk_alert: { threshold: 85, over: true }, disk: { total: 100, used: 91, free: 9, percent: 91 } }` (buat konstanta
`STATS_STORAGE` minimal berisi `retention_days, storage_root, disk, kinds: {}, last_sweep: null, settings, disk_alert`), lalu:

```tsx
test('dashboard menampilkan banner disk hampir penuh', async () => {
  vi.stubGlobal('fetch', stubFetch())
  renderDashboard() // helper render yang sudah ada di file ini
  expect(await screen.findByTestId('disk-alert')).toHaveTextContent('Disk hampir penuh (91%)')
})
```

(Sesuaikan nama helper render dashboard yang ada; tes dashboard lain tidak boleh berubah perilaku.)

- [ ] **Step 2: Jalankan, pastikan gagal** — `cd frontend && npx vitest run src/__tests__/storage.test.tsx src/__tests__/dashboard.test.tsx`.

- [ ] **Step 3: Implementasi**

`frontend/src/api/storage.ts` (tambah):

```ts
export type StorageSettings = { clip_days: number; snapshot_days: number; disk_alert_percent: number }

// StorageStats: tambah dua field
//   settings: StorageSettings
//   disk_alert: { threshold: number; over: boolean }

export async function saveStorageSettings(s: StorageSettings): Promise<StorageSettings> {
  const res = await apiFetch('/storage/settings', { method: 'PUT', body: JSON.stringify(s) })
  if (res.status === 422) throw new Error('invalid')
  if (!res.ok) throw new Error(`save failed: ${res.status}`)
  return res.json()
}
```

`frontend/src/features/config/bytes.ts`: pindahkan fungsi `formatBytes` dari `StoragePage.tsx` apa adanya dan
`export` (StoragePage mengimpornya).

`frontend/src/components/DiskAlertBanner.tsx`:

```tsx
import { InlineNotification } from '@carbon/react'
import { useT } from '../app/i18n'
import type { StorageStats } from '../api/storage'

/** Banner merah saat pemakaian disk ≥ ambang (Storage & Dashboard). */
export default function DiskAlertBanner({ stats }: { stats: StorageStats | null }) {
  const { t } = useT()
  if (!stats?.disk_alert?.over) return null
  return (
    <div data-testid="disk-alert">
      <InlineNotification kind="error" lowContrast hideCloseButton
        title={t('storage.alert.title').replace('{n}', String(Math.round(stats.disk.percent)))}
        subtitle={t('storage.alert.sub').replace('{m}', String(stats.disk_alert.threshold))} />
    </div>
  )
}
```

`frontend/src/features/config/StorageSettingsCard.tsx`:

```tsx
import { useState } from 'react'
import { Button, InlineNotification, NumberInput } from '@carbon/react'
import { useT, type TKey } from '../../app/i18n'
import { saveStorageSettings, type StorageSettings } from '../../api/storage'

const FIELDS: [keyof StorageSettings, TKey, number, number][] = [
  ['clip_days', 'storage.settings.clipDays', 1, 3650],
  ['snapshot_days', 'storage.settings.snapshotDays', 1, 3650],
  ['disk_alert_percent', 'storage.settings.alertPercent', 50, 99],
]

/** Form retensi clip/snapshot + ambang disk; nilai awal diambil sekali saat mount. */
export default function StorageSettingsCard({ value, isAdmin, onSaved }: {
  value: StorageSettings
  isAdmin: boolean
  onSaved: (s: StorageSettings) => void
}) {
  const { t } = useT()
  const [form, setForm] = useState(value)
  const [status, setStatus] = useState<'ok' | 'invalid' | 'error' | null>(null)
  const [busy, setBusy] = useState(false)

  const save = async () => {
    setBusy(true)
    setStatus(null)
    try {
      onSaved(await saveStorageSettings(form))
      setStatus('ok')
    } catch (e) {
      setStatus((e as Error).message === 'invalid' ? 'invalid' : 'error')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="st-card" data-testid="storage-settings">
      <h3 className="st-card__title">{t('storage.settings.title')}</h3>
      <div className="st-card__grid">
        {FIELDS.map(([key, label, min, max]) => (
          <NumberInput key={key} id={`storage-${key}`} label={t(label)} min={min} max={max} step={1}
            value={form[key]} disabled={!isAdmin}
            onChange={(_, state) => {
              const n = Number(state.value)
              if (Number.isInteger(n)) setForm((f) => ({ ...f, [key]: n }))
            }} />
        ))}
      </div>
      <p className="en-muted">{t('storage.settings.schedule')}</p>
      {status === 'ok' && (
        <InlineNotification kind="success" lowContrast title={t('storage.settings.saved')} onCloseButtonClick={() => setStatus(null)} />
      )}
      {status && status !== 'ok' && (
        <InlineNotification kind="error" lowContrast
          title={t(status === 'invalid' ? 'storage.settings.invalid' : 'common.error')}
          onCloseButtonClick={() => setStatus(null)} />
      )}
      {isAdmin && (
        <Button size="sm" data-testid="storage-settings-save" disabled={busy} onClick={save}>{t('common.save')}</Button>
      )}
    </section>
  )
}
```

`StoragePage.tsx`:
- hapus `formatBytes` lokal → `import { formatBytes } from './bytes'`.
- di atas notifikasi error: `<DiskAlertBanner stats={stats} />`.
- Tile retensi: `value={t('storage.retentionValue').replace('{clip}', String(stats.settings.clip_days)).replace('{snap}', String(stats.settings.snapshot_days))}` (testId `storage-retention` tetap).
- Setelah kartu sweep terakhir (masih di dalam `stats && (...)`):

```tsx
          <StorageSettingsCard
            value={stats.settings}
            isAdmin={isAdmin}
            onSaved={(s) => setStats((prev) => (prev ? { ...prev, settings: s, retention_days: s.clip_days } : prev))}
          />
```

(Kartu tidak di-`key` pada nilai: form tidak di-reset saat stats di-refresh, dan notifikasi sukses tetap tampil.)

`DashboardPage.tsx`: state `const [storage, setStorage] = useState<StorageStats | null>(null)`; effect saat mount
`getStorageStats().then(setStorage).catch(() => setStorage(null))`; render `<DiskAlertBanner stats={storage} />`
di bagian atas halaman (setelah judul).

`theme.scss`:

```scss
.st-card {
  background: var(--cds-layer-01);
  border: 1px solid var(--cds-border-subtle);
  padding: 14px 16px;
  margin-top: 14px;
}

.st-card__title {
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 12px;
}

.st-card__grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 12px;
  margin-bottom: 12px;
}

.st-card__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 12px 0;
}
```

`i18n.tsx`:

| Kunci | id | en |
|---|---|---|
| `storage.retentionValue` | Clip {clip} hari · Snapshot {snap} hari | Clips {clip} days · Snapshots {snap} days |
| `storage.settings.title` | Pengaturan retensi | Retention settings |
| `storage.settings.clipDays` | Retensi clip (hari) | Clip retention (days) |
| `storage.settings.snapshotDays` | Retensi snapshot (hari) | Snapshot retention (days) |
| `storage.settings.alertPercent` | Peringatan disk (%) | Disk alert (%) |
| `storage.settings.schedule` | Auto-cleanup berjalan harian (systemd); perubahan berlaku di sweep berikutnya. | Auto-cleanup runs daily (systemd); changes apply at the next sweep. |
| `storage.settings.saved` | Pengaturan tersimpan | Settings saved |
| `storage.settings.invalid` | Nilai di luar rentang (retensi 1–3650 hari, peringatan 50–99%) | Value out of range (retention 1–3650 days, alert 50–99%) |
| `storage.alert.title` | Disk hampir penuh ({n}%) | Disk almost full ({n}%) |
| `storage.alert.sub` | Ambang peringatan {m}%. Kurangi retensi atau bersihkan event di Konfigurasi → Storage. | Alert threshold {m}%. Lower retention or clean up events in Configuration → Storage. |

- [ ] **Step 4: Jalankan, pastikan lulus** — `npx vitest run && npm run build && npm run lint`.

- [ ] **Step 5: CHANGELOG + commit**

```markdown
- **UI pengaturan retensi + banner disk**: kartu Pengaturan retensi (clip/snapshot/ambang, admin simpan, viewer
  hanya-baca, pesan 422), tile "Clip N hari · Snapshot M hari", banner "Disk hampir penuh" di Storage & Dashboard.
  Frontend **<angka> passed**, build 0, lint set sama.
```

```bash
git add frontend/src/api/storage.ts frontend/src/features/config/bytes.ts frontend/src/features/config/StorageSettingsCard.tsx frontend/src/components/DiskAlertBanner.tsx frontend/src/features/config/StoragePage.tsx frontend/src/features/dashboard/DashboardPage.tsx frontend/src/app/theme.scss frontend/src/app/i18n.tsx frontend/src/__tests__/storage.test.tsx frontend/src/__tests__/dashboard.test.tsx CHANGELOG.md
git commit -m "feat(storage): UI pengaturan retensi dan banner disk hampir penuh"
```

---

### Task 6: Frontend — kartu Bersihkan event

**Files:**
- Modify: `frontend/src/api/storage.ts` (`CleanupFilter`, `CleanupResult`, `cleanupEvents`)
- Create: `frontend/src/features/config/EventCleanupCard.tsx`
- Modify: `frontend/src/features/config/StoragePage.tsx`
- Modify: `frontend/src/app/i18n.tsx`
- Test: `frontend/src/__tests__/storage.test.tsx`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: `POST /storage/cleanup` (Task 3), `formatBytes` (Task 5), `listCameras` (`api/cameras.ts`).
- Produces: `type CleanupFilter = { date_from: string; date_to: string; camera_ids: number[]; types: string[] }`,
  `type CleanupResult = { events: number; files: number; bytes: number; dry_run: boolean }`,
  `cleanupEvents(f: CleanupFilter, dryRun: boolean): Promise<CleanupResult>` (422 → `Error('invalid')`);
  `EventCleanupCard({ onDone }: { onDone: () => void })`.

- [ ] **Step 1: Tulis tes (gagal)** — di `storage.test.tsx`, perluas `stub()` agar `POST /storage/cleanup`
  mengembalikan `{ events: 3, files: 4, bytes: 2048, dry_run: <dari body> }`, lalu:

```tsx
async function fillDates(from: string, to: string) {
  fireEvent.change(await screen.findByLabelText('Dari tanggal'), { target: { value: from } })
  fireEvent.change(screen.getByLabelText('Sampai tanggal'), { target: { value: to } })
}

const cleanupCalls = (f: ReturnType<typeof stub>) => f.mock.calls
  .filter(([u]) => String(u).endsWith('/storage/cleanup'))
  .map(([, i]) => JSON.parse(String((i as RequestInit).body)))

test('cleanup: pratinjau lalu konfirmasi hapus', async () => {
  const f = stub('admin')
  renderStorage()
  await fillDates('2026-09-01', '2026-09-10')
  expect(screen.getByTestId('cleanup-delete')).toBeDisabled()
  await userEvent.click(screen.getByTestId('cleanup-preview'))
  expect(await screen.findByTestId('cleanup-preview-result')).toHaveTextContent('3 event · 4 file · 2 kB')
  expect(cleanupCalls(f)[0]).toEqual({ date_from: '2026-09-01', date_to: '2026-09-10', camera_ids: [], types: [], dry_run: true })
  await userEvent.click(screen.getByTestId('cleanup-delete'))
  const dialog = screen.getByRole('dialog')
  expect(dialog).toHaveTextContent('3 event dari 2026-09-01 sampai 2026-09-10')
  await userEvent.click(within(dialog).getByRole('button', { name: 'Hapus 3 event' }))
  expect(await screen.findByText('Event dihapus')).toBeInTheDocument()
  expect(cleanupCalls(f)[1].dry_run).toBe(false)
})

test('hapus nonaktif sampai pratinjau untuk filter yang sama', async () => {
  stub('admin')
  renderStorage()
  await fillDates('2026-09-01', '2026-09-10')
  await userEvent.click(screen.getByTestId('cleanup-preview'))
  await screen.findByTestId('cleanup-preview-result')
  expect(screen.getByTestId('cleanup-delete')).toBeEnabled()
  fireEvent.change(screen.getByLabelText('Sampai tanggal'), { target: { value: '2026-09-20' } })
  expect(screen.getByTestId('cleanup-delete')).toBeDisabled()
  expect(screen.queryByTestId('cleanup-preview-result')).not.toBeInTheDocument()
})

test('rentang terbalik: pratinjau nonaktif', async () => {
  stub('admin')
  renderStorage()
  await fillDates('2026-09-10', '2026-09-01')
  expect(screen.getByTestId('cleanup-preview')).toBeDisabled()
})
```

(import `within` dari `@testing-library/react`.)

- [ ] **Step 2: Jalankan, pastikan gagal** — `npx vitest run src/__tests__/storage.test.tsx`.

- [ ] **Step 3: Implementasi**

`frontend/src/api/storage.ts` (tambah):

```ts
export type CleanupFilter = { date_from: string; date_to: string; camera_ids: number[]; types: string[] }
export type CleanupResult = { events: number; files: number; bytes: number; dry_run: boolean }

export async function cleanupEvents(f: CleanupFilter, dryRun: boolean): Promise<CleanupResult> {
  const res = await apiFetch('/storage/cleanup', { method: 'POST', body: JSON.stringify({ ...f, dry_run: dryRun }) })
  if (res.status === 422) throw new Error('invalid')
  if (!res.ok) throw new Error(`cleanup failed: ${res.status}`)
  return res.json()
}
```

`frontend/src/features/config/EventCleanupCard.tsx`:

```tsx
import { useEffect, useState } from 'react'
import { Button, InlineNotification, Modal, MultiSelect, TextInput } from '@carbon/react'
import { useT, type TKey } from '../../app/i18n'
import { listCameras, type Camera } from '../../api/cameras'
import { cleanupEvents, type CleanupFilter, type CleanupResult } from '../../api/storage'
import { formatBytes } from './bytes'

// jenis yang bisa dipilih; attendance sengaja tidak ada (backend juga selalu mengecualikannya)
const TYPES = ['intrusion', 'loitering', 'running', 'idle_zone', 'crowd'] as const

function today(): string {
  const d = new Date()
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset())
  return d.toISOString().slice(0, 10)
}

/** Hapus event behavior per rentang tanggal: pratinjau wajib sebelum hapus, konfirmasi merah. */
export default function EventCleanupCard({ onDone }: { onDone: () => void }) {
  const { t, locale } = useT()
  const [cams, setCams] = useState<Camera[]>([])
  const [filter, setFilter] = useState<CleanupFilter>({ date_from: '', date_to: '', camera_ids: [], types: [] })
  const [preview, setPreview] = useState<{ key: string; result: CleanupResult } | null>(null)
  const [confirm, setConfirm] = useState(false)
  const [done, setDone] = useState<CleanupResult | null>(null)
  const [error, setError] = useState<TKey | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    listCameras().then(setCams).catch(() => setCams([]))
  }, [])

  const key = JSON.stringify(filter)
  const ready = !!filter.date_from && !!filter.date_to && filter.date_from <= filter.date_to
  const previewed = preview?.key === key ? preview.result : null // filter berubah → pratinjau basi
  const summary = (r: CleanupResult) => t('storage.cleanup.summary')
    .replace('{events}', String(r.events)).replace('{files}', String(r.files)).replace('{size}', formatBytes(r.bytes, locale))

  const run = async (dryRun: boolean) => {
    setBusy(true)
    setError(null)
    try {
      const r = await cleanupEvents(filter, dryRun)
      if (dryRun) {
        setPreview({ key, result: r })
        setDone(null)
      } else {
        setDone(r)
        setPreview(null)
        setConfirm(false)
        onDone()
      }
    } catch (e) {
      setError((e as Error).message === 'invalid' ? 'storage.cleanup.invalid' : 'common.error')
      setConfirm(false)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="st-card" data-testid="storage-cleanup">
      <h3 className="st-card__title">{t('storage.cleanup.title')}</h3>
      <p className="en-muted">{t('storage.cleanup.hint')}</p>
      <div className="st-card__grid">
        <TextInput id="cleanup-from" type="date" labelText={t('storage.cleanup.from')} max={today()}
          value={filter.date_from} onChange={(e) => setFilter({ ...filter, date_from: e.target.value })} />
        <TextInput id="cleanup-to" type="date" labelText={t('storage.cleanup.to')} max={today()}
          value={filter.date_to} onChange={(e) => setFilter({ ...filter, date_to: e.target.value })} />
        <MultiSelect<Camera> id="cleanup-cams" titleText={t('storage.cleanup.cameras')} label={t('storage.cleanup.all')}
          items={cams} itemToString={(c) => c?.name ?? ''}
          onChange={({ selectedItems }) => setFilter((f) => ({ ...f, camera_ids: (selectedItems ?? []).map((c) => c.id) }))} />
        <MultiSelect<string> id="cleanup-types" titleText={t('storage.cleanup.types')} label={t('storage.cleanup.all')}
          items={[...TYPES]} itemToString={(k) => (k ? t(`zones.behavior.${k}` as TKey) : '')}
          onChange={({ selectedItems }) => setFilter((f) => ({ ...f, types: [...(selectedItems ?? [])] }))} />
      </div>
      <div className="st-card__actions">
        <Button kind="secondary" size="sm" data-testid="cleanup-preview" disabled={!ready || busy} onClick={() => run(true)}>
          {t('storage.cleanup.preview')}
        </Button>
        <Button kind="danger" size="sm" data-testid="cleanup-delete" disabled={!previewed || previewed.events === 0 || busy}
          onClick={() => setConfirm(true)}>
          {t('storage.cleanup.delete').replace('{n}', String(previewed?.events ?? 0))}
        </Button>
      </div>
      {previewed && <p data-testid="cleanup-preview-result">{summary(previewed)}</p>}
      {done && (
        <InlineNotification kind="success" lowContrast title={t('storage.cleanup.done')} subtitle={summary(done)}
          onCloseButtonClick={() => setDone(null)} />
      )}
      {error && <InlineNotification kind="error" lowContrast title={t(error)} onCloseButtonClick={() => setError(null)} />}
      {confirm && previewed && (
        <Modal open danger size="sm" modalHeading={t('storage.cleanup.confirmTitle')}
          primaryButtonText={t('storage.cleanup.delete').replace('{n}', String(previewed.events))}
          secondaryButtonText={t('common.cancel')} primaryButtonDisabled={busy}
          onRequestClose={() => setConfirm(false)} onRequestSubmit={() => run(false)}>
          <p>
            {t('storage.cleanup.confirmBody').replace('{n}', String(previewed.events))
              .replace('{from}', filter.date_from).replace('{to}', filter.date_to)}
          </p>
        </Modal>
      )}
    </section>
  )
}
```

(Bila generic `MultiSelect<Camera>` tidak didukung tipe Carbon terpasang, hapus parameter generik dan cast item
di `onChange` — catat deviasinya.)

`StoragePage.tsx`: setelah `StorageSettingsCard`, `{isAdmin && <EventCleanupCard onDone={refresh} />}`.

`i18n.tsx`:

| Kunci | id | en |
|---|---|---|
| `storage.cleanup.title` | Bersihkan event | Clean up events |
| `storage.cleanup.hint` | Menghapus event behavior beserta clip & snapshot-nya secara permanen. Event absensi tidak pernah dihapus. | Permanently deletes behavior events with their clips & snapshots. Attendance events are never deleted. |
| `storage.cleanup.from` | Dari tanggal | From |
| `storage.cleanup.to` | Sampai tanggal | To |
| `storage.cleanup.cameras` | Kamera | Cameras |
| `storage.cleanup.types` | Jenis | Types |
| `storage.cleanup.all` | Semua | All |
| `storage.cleanup.preview` | Pratinjau | Preview |
| `storage.cleanup.delete` | Hapus {n} event | Delete {n} events |
| `storage.cleanup.summary` | {events} event · {files} file · {size} | {events} events · {files} files · {size} |
| `storage.cleanup.confirmTitle` | Hapus event permanen? | Permanently delete events? |
| `storage.cleanup.confirmBody` | {n} event dari {from} sampai {to} beserta medianya akan dihapus dan tidak bisa dipulihkan. | {n} events from {from} to {to} and their media will be deleted and cannot be recovered. |
| `storage.cleanup.done` | Event dihapus | Events deleted |
| `storage.cleanup.invalid` | Rentang tanggal atau filter tidak valid | Invalid date range or filter |

- [ ] **Step 4: Jalankan, pastikan lulus** — `npx vitest run && npm run build && npm run lint`; cek visual tab Storage
  1440 px & 390 px (kartu menumpuk, tanpa overflow halaman).

- [ ] **Step 5: CHANGELOG + commit**

```markdown
- **UI Bersihkan event**: rentang tanggal (maks hari ini), kamera & jenis opsional (tanpa attendance) → Pratinjau
  "N event · M file · X" → Hapus dengan konfirmasi merah; tombol Hapus nonaktif sampai pratinjau untuk filter yang
  sama. Frontend **<angka> passed**, build 0, lint set sama.
```

```bash
git add frontend/src/api/storage.ts frontend/src/features/config/EventCleanupCard.tsx frontend/src/features/config/StoragePage.tsx frontend/src/app/i18n.tsx frontend/src/__tests__/storage.test.tsx CHANGELOG.md
git commit -m "feat(storage): kartu bersihkan event per rentang tanggal"
```

---

### Task 7: Dokumen, suite penuh, push (eksekutor berhenti di sini)

- [ ] **Step 1: Suite penuh**

```bash
cd backend && .venv/bin/python -m pytest tests -q -m "not gpu" > /tmp/be.log 2>&1; grep -oE '[0-9]+ (passed|failed)[^|]*' /tmp/be.log | tail -1; cd ..
backend/.venv/bin/python -m pytest vision/tests -q -m "not gpu" | tail -1
cd frontend && npx vitest run | tail -3 && npm run build > /dev/null; echo build=$?; npm run lint | tail -2; cd ..
```

- [ ] **Step 2: Dokumen**
  - `README.md` bagian storage/retensi: retensi clip & snapshot dari UI (default `RETENTION_DAYS`), cleanup per
    tanggal (attendance aman, tidak bisa dipulihkan), peringatan disk (ambang, Telegram, pulih).
  - `docs/runbooks/` — tambah bagian di runbook yang relevan (atau `docs/runbooks/storage-retention.md` baru):
    cara mengubah retensi, cleanup aman (pratinjau dulu), respons terhadap peringatan disk.
  - `ROADMAP.md` — baris sebelum `| E | Edge Jetson …`:
    `| RS | Retention & Storage UI (retensi clip/snapshot, cleanup per tanggal, alert disk) | [~] lokal selesai, PENDING deploy + verifikasi | — | spec + plan 2026-09-29 | |`
  - `CHANGELOG.md` — bullet dokumen + suite akhir.

```bash
git add README.md docs/runbooks ROADMAP.md CHANGELOG.md
git commit -m "docs(storage): dokumentasi retention & storage UI"
```

- [ ] **Step 3: Push** — `git push -u origin feat/retention-storage-ui` (diizinkan). **Jangan** deploy, ssh, atau
  merge. Catatan untuk sesi perencana: deploy = restart **isentinel-api** (tanpa migrasi); timer retensi systemd
  otomatis memakai pengaturan DB.
