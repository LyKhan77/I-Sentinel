# I-Sentinel — Fase 5: Hardening & Load Test Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) atau superpowers:executing-plans untuk mengerjakan plan ini task-by-task.
> Langkah memakai checkbox (`- [ ]`) untuk tracking.

**Goal:** Sistem siap produksi — retensi media berjalan otomatis, celah keamanan tertutup,
resiliensi terbukti, dan 32 stream sintetis stabil di GPU tanpa memory leak.

**Architecture:** Retensi sebagai sweeper dua-lapis (berdasarkan `ts_event` di DB + sapuan
orphan berdasarkan mtime file) yang dijalankan systemd timer harian dan bisa dipicu manual
dari UI admin. Load test memakai ffmpeg yang mem-publish video loop ke go2rtc sebagai RTSP
loopback, didaftarkan sebagai kamera biasa lewat API sehingga seluruh pipeline
(MQTT → ingest → DB → alerting) ikut teruji, bukan hanya detektor.

**Tech Stack:** Python 3.11 / FastAPI / SQLAlchemy 2 + Alembic / pytest / systemd
(service + timer) / ffmpeg / React + TS + @carbon/react / vitest.

**Spec:** `docs/plans/2026-09-08-isentinel-design.md` (brief asal milestone ini:
`docs/plans/06-fase-5-hardening.md` sebelum file ini menggantikannya).

## Global Constraints

Disalin dari `docs/plans/00-master.md` — berlaku untuk **setiap** task:

- Semua keputusan requirement terkunci di spec §1; perubahan = update spec dulu.
- UI: IBM Carbon Gray-100 dark, Plex Sans, corner 0px, **tanpa emoji** (ikon dari
  `@carbon/icons-react`), sidebar collapsible, bahasa ID/EN lengkap.
- Logic inti backend & vision HARUS testable tanpa GPU/RTSP (model & stream di-mock).
- Vision-node tidak boleh depend ke FastAPI/SQLAlchemy — kontrak hanya MQTT + HTTP upload.
- **Zero-secret**: kredensial kamera/Telegram hanya via env/config file; tidak pernah di commit
  atau di DB plaintext.
- Conventional Commits; setiap task berakhir dengan commit; test harus pass sebelum commit.
- Workflow dev: device coding = Windows ini (smoke test CPU saja); test GPU/RTSP di `gspe-ai3`
  via SSH. GitHub = source of truth.
- Marker pytest `@pytest.mark.gpu` untuk test yang butuh CUDA; default run = CPU-only.
- Aturan file rahasia (temuan sesi 2026-09-15): file runtime yang memuat kredensial **tidak boleh
  se-nama dengan template-nya dan tidak boleh ter-track git**. `.env`/`.env.example`,
  `vision.env`/`vision.env.example`, `go2rtc.yaml`/`go2rtc.example.yaml`.

---

## Prasyarat — fakta lingkungan (hasil audit 2026-09-15 di `gspe-ai3`)

Bagian ini **bukan** opsional; beberapa task tidak bisa dikerjakan tanpa ini.

| # | Fakta | Konsekuensi |
|---|---|---|
| P1 | **`ffmpeg` TIDAK terpasang** (hanya `/usr/bin/ffprobe`) | Generator stream sintetis (Task 10) butuh `sudo apt install -y ffmpeg`. **Tindakan user.** |
| P2 | **GPU0 = RTX 4090, 23 644 / 24 564 MiB terpakai** (beban lain: llamacpp/litellm, 6+ proses). GPU1 & GPU2 = RTX 5080 16 GB (13.2/16.3 dan 15.0/16.3) | Soak 32 kamera di GPU0 kemungkinan gagal OOM. Lihat **Keputusan D1**. |
| P3 | `STORAGE_ROOT` sebenarnya `/home/gspe-ai3/isentinel-data` (bukan default config `/data/isentinel`) | Semua path di plan ini relatif ke `settings.storage_root`, jangan hardcode. |
| P4 | Media saat ini: clips 214 MB, snapshots 77 MB, crops 6.7 MB, **1 673 file**, semua dari 2026-09-15. Disk `/` **85% (sisa 133 GB)** | Retensi belum urgent hari ini, tapi ~300 MB/hari akan menumpuk. |
| P5 | **Unit systemd di repo ≠ yang jalan.** Repo: `WorkingDirectory=/opt/isentinel`, `User=isentinel`. Aktual: `/home/gspe-ai3/project_cv/I-Sentinel`, `User=gspe-ai3`. Repo `vision-node.service` → `isentinel-venv/bin/vision-node`; aktual → `vision-venv/bin/isentinel-vision` | Task 12 wajib merekonsiliasi, kalau tidak dokumentasi operasional akan menyesatkan. |
| P6 | `sudo` tanpa password TIDAK tersedia di `gspe-ai3` (kecuali `llamacpp.service`) | Service I-Sentinel di-restart lewat: `kill $(cat /sys/fs/cgroup/system.slice/<unit>.service/cgroup.procs)` karena unit memakai `Restart=always` dan jalan sebagai user SSH. Pemasangan unit systemd baru (Task 4) **butuh user**. |
| P7 | `vision/vision/config.py` `NodeSettings` **tidak punya field device**; `PersonDetector.predict()` tidak meneruskan `device=` | Task 9 menambahkannya — tanpa itu tidak bisa memilih GPU untuk soak. |
| P8 | Tidak ada rate-limit di `/api/v1/auth/login` | Task 6. |
| P9 | Tidak ada middleware CORS sama sekali | Task 7 — ini **keputusan sadar** (app same-origin via proxy), bukan gap. Dokumentasikan, jangan tambahkan. |

### Keputusan yang dibutuhkan user sebelum eksekusi

**D1 — GPU dan durasi soak.** Brief mengizinkan dua bentuk bukti:
- **(a) soak penuh 24 jam** — butuh GPU dengan memori lega dan jendela 24 jam tanpa gangguan.
- **(b) 2 jam soak + uji churn** — sesuai bunyi brief *"32 stream sintetis 24 jam (atau 2 jam +
  uji churn)"*. Uji churn = tambah/hapus kamera berulang selama soak untuk memicu
  start/stop pipeline berulang (justru bagian yang paling rawan leak).

**Rekomendasi:** jalankan (b) dengan `VISION_DETECTOR_DEVICE=cuda:1` (RTX 5080) karena GPU0
sudah 96% terisi beban lain. Naikkan ke (a) hanya kalau ada jendela GPU0 lega.

**D2 — izin memasang ffmpeg** di `gspe-ai3` (`sudo apt install -y ffmpeg`).

---

## File Structure

**Dibuat:**

| File | Tanggung jawab |
|---|---|
| `backend/alembic/versions/0006_retention.py` | tambah kolom `event.media_expired` |
| `backend/app/services/retention.py` | logika sweeper: hapus file + tandai event + sapu orphan |
| `backend/app/api/storage.py` | `GET /api/v1/storage/stats`, `POST /api/v1/storage/sweep` |
| `backend/scripts/retention_sweep.py` | entrypoint CLI untuk systemd timer |
| `backend/tests/test_retention.py` | unit test sweeper (CPU, tanpa GPU) |
| `backend/tests/test_storage_api.py` | test API storage |
| `backend/tests/test_auth_ratelimit.py` | test rate-limit login |
| `deploy/systemd/isentinel-retention.service` | unit oneshot |
| `deploy/systemd/isentinel-retention.timer` | jadwal harian 03:00 |
| `frontend/src/features/config/StoragePage.tsx` | halaman Retensi & Storage |
| `frontend/src/__tests__/storage.test.tsx` | test halaman |
| `deploy/loadtest/make-streams.sh` | generator stream sintetis ffmpeg |
| `deploy/loadtest/register-cams.py` | daftar/hapus kamera sintetis lewat API |
| `deploy/loadtest/soak.sh` | runner soak + sampler metrik |
| `deploy/loadtest/resilience.sh` | harness uji resiliensi |
| `docs/RUNBOOK.md` | start/stop, backup, add camera, troubleshooting, alert |

**Dimodifikasi:**

| File | Perubahan |
|---|---|
| `backend/app/models/event.py` | `media_expired` |
| `backend/app/main.py` | daftarkan router storage |
| `backend/app/core/config.py` | `login_max_attempts`, `login_lockout_min`, `sweep_batch_size` |
| `backend/app/api/auth.py` | rate-limit login |
| `vision/vision/config.py` | `detector_device` |
| `vision/vision/pipeline/detector.py` | teruskan `device=` ke `predict()` |
| `frontend/src/main.tsx` | route `/config/storage` |
| `frontend/src/app/AppShell.tsx` | item nav "Retensi & Storage" |
| `frontend/src/app/i18n.tsx` | key halaman storage (ID + EN) |
| `deploy/systemd/isentinel-api.service`, `vision-node.service` | rekonsiliasi dengan yang aktual (P5) |
| `README.md` | bagian operasional menunjuk `docs/RUNBOOK.md` |
| `docs/plans/00-master.md` | baris milestone Fase 5 → DONE + bukti |

**Urutan dependensi:** Task 1 → 2 → 3 → 4 → 5 (rantai retensi, berurutan ketat).
Task 6, 7, 9 independen. Task 8 butuh 9 kalau dijalankan dengan vision nyata.
Task 10 → 11. Task 12 terakhir.

---

### Task 1: Kolom `media_expired` + migrasi

**Files:**
- Modify: `backend/app/models/event.py`
- Create: `backend/alembic/versions/0006_retention.py`
- Test: `backend/tests/test_retention.py` (bagian pertama)

**Interfaces:**
- Produces: `Event.media_expired: bool` (default `False`, `nullable=False`) — dipakai Task 2
  (sweeper menandai) dan Task 5 (UI membedakan "clip dihapus retensi" vs "belum ada clip").

- [ ] **Step 1: Tambah kolom ke model**

Di `backend/app/models/event.py`, tambah `Boolean` ke import dan satu baris kolom setelah
`snapshot_path`:

```python
from sqlalchemy import String, Integer, DateTime, JSON, ForeignKey, Boolean
```

```python
    clip_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    snapshot_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # media sudah dihapus sweeper retensi (file lama) — beda dari "belum pernah ada"
    media_expired: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
```

- [ ] **Step 2: Tulis migrasi**

Buat `backend/alembic/versions/0006_retention.py` mengikuti pola `0005_attendance.py`:

```python
"""retention

Revision ID: 0006
Revises: 0005
Create Date: 2026-01-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0006'
down_revision: Union[str, Sequence[str], None] = '0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'event',
        sa.Column('media_expired', sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('event', 'media_expired')
```

- [ ] **Step 3: Test bahwa kolom ada dan default-nya False**

Buat `backend/tests/test_retention.py`:

```python
from datetime import datetime, timezone

from app.models.event import Event


def test_event_defaults_media_expired_false(db):
    ev = Event(type="intrusion", ts_event=datetime.now(timezone.utc))
    db.add(ev)
    db.commit()
    db.refresh(ev)
    assert ev.media_expired is False
```

- [ ] **Step 4: Jalankan test**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_retention.py -v`
Expected: PASS 1 test.

- [ ] **Step 5: Verifikasi migrasi naik-turun di SQLite**

Run:
```bash
cd backend && DATABASE_URL="sqlite:///./test_mig.db" .venv/Scripts/python.exe -m alembic upgrade head
cd backend && DATABASE_URL="sqlite:///./test_mig.db" .venv/Scripts/python.exe -m alembic downgrade 0005
cd backend && DATABASE_URL="sqlite:///./test_mig.db" .venv/Scripts/python.exe -m alembic upgrade head
rm -f backend/test_mig.db
```
Expected: ketiganya sukses tanpa error. (Jangan jalankan di server dulu — Task 4 yang urus itu.)

- [ ] **Step 6: Commit**

```bash
git add backend/app/models/event.py backend/alembic/versions/0006_retention.py backend/tests/test_retention.py
git commit -m "feat: event.media_expired column + migration 0006"
```

---

### Task 2: Sweeper retensi

**Files:**
- Create: `backend/app/services/retention.py`
- Test: `backend/tests/test_retention.py`

**Interfaces:**
- Consumes: `Event.media_expired` dari Task 1, `settings.storage_root`, `settings.retention_days`.
- Produces:
  - `sweep(db, now: datetime | None = None, dry_run: bool = False) -> dict`
    mengembalikan `{"files_deleted": int, "bytes_freed": int, "events_marked": int, "orphans_deleted": int, "dry_run": bool}`
  - `cutoff_for(now: datetime, days: int) -> datetime`
  - `disk_usage(root: str) -> dict` → `{"total": int, "used": int, "free": int, "percent": float}`
  - `kind_usage(root: str) -> dict[str, dict]` → `{"clips": {"files": int, "bytes": int}, ...}`

- [ ] **Step 1: Tulis test yang gagal**

Tambahkan ke `backend/tests/test_retention.py`:

```python
import os
from datetime import datetime, timedelta, timezone

import pytest

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
```

- [ ] **Step 2: Jalankan test, pastikan gagal**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_retention.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.retention'`

- [ ] **Step 3: Implementasi sweeper**

Buat `backend/app/services/retention.py`:

```python
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
    for ev in expired:
        for field in ("clip_path", "snapshot_path"):
            rel = getattr(ev, field)
            if not rel:
                continue
            full = _safe_join(root, rel)
            if full and os.path.isfile(full):
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
```

- [ ] **Step 4: Jalankan test, pastikan lolos**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_retention.py -v`
Expected: PASS 8 test.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/retention.py backend/tests/test_retention.py
git commit -m "feat: retention sweeper (event expired + orphan sweep) with path-escape guard"
```

---

### Task 3: API storage

**Files:**
- Create: `backend/app/api/storage.py`
- Modify: `backend/app/main.py`, `backend/app/core/config.py`
- Test: `backend/tests/test_storage_api.py`

**Interfaces:**
- Consumes: `retention.sweep`, `retention.disk_usage`, `retention.kind_usage` (Task 2);
  `Setting` model (`key`/`value` JSON) untuk menyimpan hasil sweep terakhir.
- Produces:
  - `GET /api/v1/storage/stats` → `{retention_days, storage_root, disk, kinds, last_sweep}`
  - `POST /api/v1/storage/sweep?dry_run=false` (admin) → hasil `sweep()` + tercatat
  - Key `Setting`: `"retention_last_sweep"`

- [ ] **Step 1: Tulis test yang gagal**

Buat `backend/tests/test_storage_api.py`:

```python
from datetime import datetime, timedelta, timezone

from app.models.event import Event
from app.models.setting import Setting


def test_stats_shape(client, db, tmp_path, monkeypatch):
    from app.services import retention

    monkeypatch.setattr(retention.settings, "storage_root", str(tmp_path))
    monkeypatch.setattr(retention.settings, "retention_days", 30)
    h = client.get("/api/v1/cameras").status_code  # pastikan app jalan
    r = client.get("/api/v1/storage/stats", headers=_admin_headers(client))
    assert r.status_code == 200
    body = r.json()
    assert body["retention_days"] == 30
    assert body["storage_root"] == str(tmp_path)
    assert set(body["kinds"].keys()) == {"clips", "snapshots", "crops"}
    assert body["disk"]["total"] > 0
    assert body["last_sweep"] is None


def test_sweep_requires_admin(client, db, tmp_path, monkeypatch):
    from app.services import retention

    monkeypatch.setattr(retention.settings, "storage_root", str(tmp_path))
    assert client.post("/api/v1/storage/sweep").status_code == 401
    viewer = _viewer_headers(client)
    assert client.post("/api/v1/storage/sweep", headers=viewer).status_code == 403


def test_sweep_records_last_run(client, db, tmp_path, monkeypatch):
    from app.services import retention

    monkeypatch.setattr(retention.settings, "storage_root", str(tmp_path))
    monkeypatch.setattr(retention.settings, "retention_days", 30)
    now = datetime.now(timezone.utc)
    ev = Event(
        type="intrusion",
        ts_event=now - timedelta(days=90),
        clip_path="clips/old.mp4",
    )
    db.add(ev)
    db.commit()

    r = client.post("/api/v1/storage/sweep?dry_run=true", headers=_admin_headers(client))
    assert r.status_code == 200
    assert r.json()["events_marked"] == 1

    row = db.get(Setting, "retention_last_sweep")
    assert row is not None
    assert row.value["events_marked"] == 1
    assert "at" in row.value

    stats = client.get("/api/v1/storage/stats", headers=_admin_headers(client)).json()
    assert stats["last_sweep"]["events_marked"] == 1
```

Tambahkan dua helper ke **`backend/tests/conftest.py`** (bukan ke file test ini) supaya Task 3 dan
Task 7 memakai definisi yang sama — jangan diduplikasi. `from tests.conftest import *` sudah ada
di semua file test, jadi helper langsung tersedia. File test lama yang punya salinan lokal
(`test_go2rtc.py`) tetap jalan karena definisi lokal men-shadow.

```python
# backend/tests/conftest.py — tambahkan setelah import yang ada

def admin_headers(client):
    tok = client.post("/api/v1/auth/login", json={"username": "admin", "password": "boot123"}).json()["token"]
    return {"Authorization": f"Bearer {tok}"}


def viewer_headers(client):
    """Buat user viewer lewat API admin, lalu login sebagai dia.

    Lewat API (bukan langsung ke DB) supaya helper ini tidak perlu tahu soal
    fixture db. Tiap test punya DB in-memory sendiri, jadi user 'vw' selalu baru.
    """
    client.post(
        "/api/v1/users",
        json={"username": "vw", "password": "pw12345", "role": "viewer"},
        headers=admin_headers(client),
    )
    tok = client.post("/api/v1/auth/login", json={"username": "vw", "password": "pw12345"}).json()["token"]
    return {"Authorization": f"Bearer {tok}"}
```

Di `test_storage_api.py`, ganti seluruh `admin_headers(client)` → `admin_headers(client)` dan
`viewer_headers(client)` → `viewer_headers(client)` (tanpa garis bawah, sesuai nama di conftest).

- [ ] **Step 2: Jalankan test, pastikan gagal**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_storage_api.py -v`
Expected: FAIL — 404 pada `/api/v1/storage/stats`.

- [ ] **Step 3: Implementasi router**

Buat `backend/app/api/storage.py`:

```python
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin
from app.core.config import settings
from app.core.db import get_db
from app.models.setting import Setting
from app.services import retention

router = APIRouter(prefix="/api/v1/storage", tags=["storage"])

LAST_SWEEP_KEY = "retention_last_sweep"


def _last_sweep(db: Session) -> dict | None:
    row = db.get(Setting, LAST_SWEEP_KEY)
    return row.value if row else None


def _record_sweep(db: Session, result: dict) -> dict:
    payload = {**result, "at": datetime.now(timezone.utc).isoformat()}
    row = db.get(Setting, LAST_SWEEP_KEY)
    if row is None:
        row = Setting(key=LAST_SWEEP_KEY, value=payload)
        db.add(row)
    else:
        row.value = payload
    db.commit()
    return payload


@router.get("/stats")
def storage_stats(db: Session = Depends(get_db), user=Depends(get_current_user)):
    root = settings.storage_root
    return {
        "retention_days": settings.retention_days,
        "storage_root": root,
        "disk": retention.disk_usage(root),
        "kinds": retention.kind_usage(root),
        "last_sweep": _last_sweep(db),
    }


@router.post("/sweep")
def run_sweep(
    dry_run: bool = Query(False),
    db: Session = Depends(get_db),
    admin=Depends(require_admin),
):
    result = retention.sweep(db, dry_run=dry_run)
    return _record_sweep(db, result)
```

- [ ] **Step 4: Daftarkan router**

Di `backend/app/main.py`, setelah baris `app.include_router(telegram_router)`:

```python
from app.api.storage import router as storage_router
app.include_router(storage_router)
```

- [ ] **Step 5: Tambah setting rate-limit & batch (dipakai Task 6)**

Di `backend/app/core/config.py`, setelah `retention_days: int = 30`:

```python
    login_max_attempts: int = 5      # percobaan login gagal per (username, ip) sebelum dikunci
    login_lockout_min: int = 15      # lama kunci, menit
```

- [ ] **Step 6: Jalankan test**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_storage_api.py -v`
Expected: PASS 3 test.

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/storage.py backend/app/main.py backend/app/core/config.py \
  backend/tests/conftest.py backend/tests/test_storage_api.py
git commit -m "feat: storage stats + manual sweep API (admin-gated)"
```

---

### Task 4: Entrypoint + systemd timer

**Files:**
- Create: `backend/scripts/retention_sweep.py`,
  `deploy/systemd/isentinel-retention.service`, `deploy/systemd/isentinel-retention.timer`
- Test: verifikasi manual di server (bukan pytest — butuh systemd)

**Interfaces:**
- Consumes: `retention.sweep` (Task 2), `Setting` (Task 3).
- Produces: perintah `python scripts/retention_sweep.py` yang bisa dipanggil systemd; exit code
  0 sukses / 1 gagal.

- [ ] **Step 1: Tulis entrypoint**

Buat `backend/scripts/retention_sweep.py`:

```python
"""Sweep retensi sekali jalan — dipanggil isentinel-retention.service.

Sengaja tidak lewat HTTP API supaya tidak perlu kredensial admin di unit systemd
dan tidak ikut gagal saat API sedang restart.
"""
import logging
import sys

from app.core.config import settings
from app.core.db import SessionLocal
from app.models.setting import Setting
from app.services import retention

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("retention")


def main() -> int:
    db = SessionLocal()
    try:
        result = retention.sweep(db)
        from datetime import datetime, timezone

        payload = {**result, "at": datetime.now(timezone.utc).isoformat()}
        row = db.get(Setting, "retention_last_sweep")
        if row is None:
            db.add(Setting(key="retention_last_sweep", value=payload))
        else:
            row.value = payload
        db.commit()
        logger.info(
            "sweep selesai: %s file, %s byte, %s event, %s orphan (retention=%s hari)",
            result["files_deleted"], result["bytes_freed"], result["events_marked"],
            result["orphans_deleted"], settings.retention_days,
        )
        return 0
    except Exception:
        logger.exception("sweep gagal")
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Tulis unit + timer**

`deploy/systemd/isentinel-retention.service` — pakai path aktual (lihat P5), bukan `/opt`:

```ini
[Unit]
Description=I-Sentinel Retention Sweep
After=network.target postgresql.service

[Service]
Type=oneshot
User=gspe-ai3
WorkingDirectory=/home/gspe-ai3/project_cv/I-Sentinel/backend
EnvironmentFile=/home/gspe-ai3/project_cv/I-Sentinel/.env
ExecStart=/home/gspe-ai3/isentinel-venv/bin/python scripts/retention_sweep.py
```

`deploy/systemd/isentinel-retention.timer`:

```ini
[Unit]
Description=Jalankan sweep retensi I-Sentinel tiap hari 03:00

[Timer]
OnCalendar=*-*-* 03:00:00
Persistent=true
RandomizedDelaySec=300

[Install]
WantedBy=timers.target
```

- [ ] **Step 3: Uji entrypoint lokal (tanpa systemd)**

Run: `cd backend && DATABASE_URL="sqlite:///./test_sweep.db" .venv/Scripts/python.exe -m alembic upgrade head && STORAGE_ROOT=./tmp_storage DATABASE_URL="sqlite:///./test_sweep.db" .venv/Scripts/python.exe scripts/retention_sweep.py; echo "exit=$?"`
Expected: baris log `sweep selesai: 0 file, 0 byte, 0 event, 0 orphan ...` dan `exit=0`.
Lalu bersihkan: `rm -f backend/test_sweep.db && rm -rf backend/tmp_storage`

- [ ] **Step 4: Pasang di server (BUTUH USER — sudo)**

```bash
ssh gspe-ai3 'sudo cp /home/gspe-ai3/project_cv/I-Sentinel/deploy/systemd/isentinel-retention.{service,timer} /etc/systemd/system/ \
  && sudo systemctl daemon-reload \
  && sudo systemctl enable --now isentinel-retention.timer'
```

- [ ] **Step 5: Verifikasi di server**

```bash
ssh gspe-ai3 'systemctl list-timers isentinel-retention.timer --no-pager | head -3'
ssh gspe-ai3 'sudo systemctl start isentinel-retention.service && journalctl -u isentinel-retention --no-pager -n 5'
```
Expected: timer muncul dengan NEXT 03:00; journal memuat `sweep selesai: ...`; exit sukses.

- [ ] **Step 6: Commit**

```bash
git add backend/scripts/retention_sweep.py deploy/systemd/isentinel-retention.service deploy/systemd/isentinel-retention.timer
git commit -m "feat: retention sweep entrypoint + daily systemd timer"
```

---

### Task 5: Halaman Retensi & Storage

**Files:**
- Create: `frontend/src/features/config/StoragePage.tsx`,
  `frontend/src/__tests__/storage.test.tsx`
- Modify: `frontend/src/main.tsx`, `frontend/src/app/AppShell.tsx`,
  `frontend/src/app/i18n.tsx`, `frontend/src/api/events.ts` atau file api baru

**Interfaces:**
- Consumes: `GET /api/v1/storage/stats`, `POST /api/v1/storage/sweep` (Task 3).
- Produces: route `/config/storage`, item nav admin-only.

- [ ] **Step 1: Tulis test yang gagal**

Buat `frontend/src/__tests__/storage.test.tsx`:

```tsx
import { render, screen, waitFor } from '@testing-library/react'
import '@testing-library/jest-dom/vitest'
import { I18nProvider } from '../app/i18n'
import StoragePage from '../features/config/StoragePage'

const STATS = {
  retention_days: 30,
  storage_root: '/data/isentinel',
  disk: { total: 1000, used: 850, free: 150, percent: 85.0 },
  kinds: {
    clips: { files: 10, bytes: 2048 },
    snapshots: { files: 5, bytes: 1024 },
    crops: { files: 0, bytes: 0 },
  },
  last_sweep: { at: '2026-09-15T03:00:00+00:00', files_deleted: 3, bytes_freed: 4096, events_marked: 2, orphans_deleted: 1, dry_run: false },
}

test('menampilkan retensi, disk, per-jenis, dan sweep terakhir', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, status: 200, json: () => Promise.resolve(STATS) })))
  render(
    <I18nProvider>
      <StoragePage />
    </I18nProvider>,
  )
  expect(await screen.findByTestId('storage-disk-percent')).toHaveTextContent('85')
  expect(screen.getByTestId('storage-retention')).toHaveTextContent('30')
  expect(screen.getByTestId('kind-clips')).toHaveTextContent('2,0 kB'.replace('2,0', '2.0')) // locale id
  expect(screen.getByTestId('storage-last-sweep')).toBeInTheDocument()
})
```

Catatan: sesuaikan assertion format byte dengan helper `formatBytes` yang kamu tulis di Step 3 —
kalau helper memakai locale `id-ID` hasilnya `2,0 kB`. **Jalankan test dulu, lihat output
sebenarnya, lalu samakan assertion** (jangan menebak format).

- [ ] **Step 2: Jalankan test, pastikan gagal**

Run: `cd frontend && npx vitest run src/__tests__/storage.test.tsx`
Expected: FAIL — `Failed to resolve import "../features/config/StoragePage"`

- [ ] **Step 3: Implementasi halaman**

Buat `frontend/src/features/config/StoragePage.tsx`. Struktur mengikuti pola `CamerasPage`
(`apiFetch`, `app-page`, admin-gating, error notification `lowContrast`):

- ambil `GET /api/v1/storage/stats` saat mount
- kartu ringkas: Retensi (hari), Path storage, Disk terpakai % dengan bar
- tabel per jenis: clips / snapshots / crops → jumlah file + ukuran
- kartu "Sweep terakhir": waktu, file terhapus, byte dibebaskan, event tertandai
- tombol admin: **Dry run** dan **Jalankan sekarang** → `POST /api/v1/storage/sweep?dry_run=…`,
  setelah sukses reload stats dan tampilkan `InlineNotification` hasilnya
- helper `formatBytes(n)` pakai `Intl.NumberFormat('id-ID'|'en', { maximumFractionDigits: 1 })`

- [ ] **Step 4: Daftarkan route + nav + i18n**

- `frontend/src/main.tsx`: `{ path: 'config/storage', element: <StoragePage /> }`
- `frontend/src/app/AppShell.tsx`: item di grup `management`, `adminOnly: true`,
  icon `DataBase` dari `@carbon/icons-react`, key `'storage.title'`
- `frontend/src/app/i18n.tsx`: tambah key `storage.*` **di blok `id` DAN `en`** — tanpa emoji.

- [ ] **Step 5: Jalankan test + build**

Run: `cd frontend && npx vitest run && npm run build`
Expected: seluruh suite PASS, build sukses.

- [ ] **Step 6: Verifikasi visual di server**

```bash
ssh gspe-ai3 "cd ~/project_cv/I-Sentinel && git pull --quiet origin main"
```
Lalu buka `http://192.168.2.133:5173/config/storage` dengan Playwright, screenshot ke
`docs/evidence/fase-5/storage-page.png`. Cek: nilai disk cocok dengan `df -h` di server,
dan tombol **Dry run** tidak menghapus apa pun (bandingkan jumlah file sebelum/sesudah).

- [ ] **Step 7: Commit**

```bash
git add frontend/src/features/config/StoragePage.tsx frontend/src/__tests__/storage.test.tsx \
  frontend/src/main.tsx frontend/src/app/AppShell.tsx frontend/src/app/i18n.tsx
git commit -m "feat: Retensi & Storage page (disk usage, per-kind, manual sweep)"
```

---

### Task 6: Rate-limit login

**Files:**
- Modify: `backend/app/api/auth.py`
- Test: `backend/tests/test_auth_ratelimit.py`

**Interfaces:**
- Consumes: `settings.login_max_attempts`, `settings.login_lockout_min` (Task 3 Step 5).
- Produces: `/api/v1/auth/login` mengembalikan **429** saat terkunci.

- [ ] **Step 1: Tulis test yang gagal**

Buat `backend/tests/test_auth_ratelimit.py`:

```python
def test_login_locks_after_max_attempts(client, monkeypatch):
    from app.api import auth as auth_mod

    auth_mod._FAILURES.clear()
    monkeypatch.setattr(auth_mod.settings, "login_max_attempts", 3)
    monkeypatch.setattr(auth_mod.settings, "login_lockout_min", 15)

    body = {"username": "admin", "password": "salah"}
    for _ in range(3):
        assert client.post("/api/v1/auth/login", json=body).status_code == 401

    r = client.post("/api/v1/auth/login", json=body)
    assert r.status_code == 429
    assert "Retry-After" in r.headers


def test_successful_login_resets_failures(client, monkeypatch):
    from app.api import auth as auth_mod

    auth_mod._FAILURES.clear()
    monkeypatch.setattr(auth_mod.settings, "login_max_attempts", 3)
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "salah"})
    client.post("/api/v1/auth/login", json={"username": "admin", "password": "salah"})
    assert client.post("/api/v1/auth/login", json={"username": "admin", "password": "boot123"}).status_code == 200
    assert client.post("/api/v1/auth/login", json={"username": "admin", "password": "salah"}).status_code == 401
```

- [ ] **Step 1b: Isolasi state antar-test (WAJIB — kalau tidak, suite jadi flaky)**

`_FAILURES` adalah state level-modul yang **hidup sepanjang proses pytest**. Satu test yang
membuat banyak login gagal akan membuat test lain di file berbeda mendapat 429 padahal tidak
terkait. Tambahkan fixture autouse di `backend/tests/conftest.py`:

```python
@pytest.fixture(autouse=True)
def _reset_login_ratelimit():
    """Penghitung rate-limit login bersifat level-modul; bersihkan tiap test."""
    from app.api import auth as auth_mod
    auth_mod._FAILURES.clear()
    yield
    auth_mod._FAILURES.clear()
```

Terapkan Step 1 di atas dengan password `boot123` — nilai itu yang dipakai fixture `client` di
`backend/tests/test_auth_api.py` (`monkeypatch.setattr(settings, "admin_password", "boot123")`).

- [ ] **Step 2: Jalankan test, pastikan gagal**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_auth_ratelimit.py -v`
Expected: FAIL — percobaan ke-4 masih 401, bukan 429.

- [ ] **Step 3: Implementasi**

Di `backend/app/api/auth.py` — tambah modul-level state + guard di handler login:

```python
import time
from fastapi import HTTPException, Request

# ponytail: penghitung in-memory per proses. Cukup karena deployment ini satu
# worker uvicorn. Kalau nanti dijalankan multi-worker, pindah ke tabel DB atau
# Redis (sudah ada di host) — jangan pakai dict lagi.
_FAILURES: dict[tuple[str, str], list[float]] = {}


def _client_key(username: str, request: Request) -> tuple[str, str]:
    ip = request.client.host if request.client else "?"
    return (username.strip().lower(), ip)


def _check_lock(key: tuple[str, str]) -> None:
    window = settings.login_lockout_min * 60
    now = time.monotonic()
    hits = [t for t in _FAILURES.get(key, []) if now - t < window]
    _FAILURES[key] = hits
    if len(hits) >= settings.login_max_attempts:
        retry = int(window - (now - hits[0])) + 1
        raise HTTPException(
            status_code=429,
            detail="too many failed login attempts",
            headers={"Retry-After": str(retry)},
        )
```

Panggil `_check_lock(key)` **sebelum** verifikasi password; catat kegagalan dengan
`_FAILURES.setdefault(key, []).append(time.monotonic())`; dan `_FAILURES.pop(key, None)`
saat login sukses.

Handler login perlu menerima `request: Request` sebagai parameter.

- [ ] **Step 4: Jalankan test**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_auth_ratelimit.py backend/tests/test_auth_api.py -v`
Expected: PASS keduanya (test auth lama tidak boleh regresi — fixture autouse dari Step 1b
mencegah 429 bocor ke test lain).

- [ ] **Step 4b: Jalankan SELURUH suite untuk membuktikan tidak ada 429 yang bocor**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests -q`
Expected: jumlah passed sama seperti sebelum Task 6 (+3 test baru). Kalau ada test lama yang
tiba-tiba 429, Step 1b belum benar dipasang.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/auth.py backend/tests/conftest.py backend/tests/test_auth_ratelimit.py
git commit -m "feat: rate-limit login attempts (429 + Retry-After) + test isolation"
```

---

### Task 7: Sisa keamanan pass

**Files:**
- Modify: `docs/RUNBOOK.md` (dibuat di Task 12 — task ini menulis draf bagian keamanan di
  `docs/plans/00-master.md` dulu, lalu dipindah)
- Test: `backend/tests/test_security.py` (tambah)

**Interfaces:** tidak ada kode baru; ini verifikasi + dokumentasi keputusan.

- [ ] **Step 1: Test — PATCH absensi hanya admin, dan note wajib**

Tambahkan ke `backend/tests/test_security.py`:

```python
def test_attendance_override_requires_admin(client, db):
    """Override absensi mengubah data kehadiran — harus admin."""
    viewer = viewer_headers(client)  # helper dari conftest.py (Task 3 Step 1)
    r = client.patch("/api/v1/attendance/1", json={"status": "ontime", "note": "x"}, headers=viewer)
    assert r.status_code != 200


def test_attendance_patch_route_uses_require_admin():
    """Memastikan guard-nya memang require_admin, bukan kebetulan 404."""
    import inspect
    from app.api import attendance as att_mod

    src = inspect.getsource(att_mod)
    assert "require_admin" in src, "PATCH /attendance harus admin-gated"
```

Kalau `PATCH /api/v1/attendance/{id}` ternyata memang sudah memakai `require_admin`, kedua test
langsung hijau. Kalau belum, **itu temuan keamanan nyata** — tambahkan `Depends(require_admin)`
pada handler-nya di task ini, lalu commit terpisah dengan pesan `fix:` (bukan `test:`).

- [ ] **Step 2: Jalankan test**

Run: `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_security.py -v`
Expected: PASS.

- [ ] **Step 3: Catat tiga keputusan (tanpa kode)**

1. **CORS sengaja tidak ada.** App diakses same-origin (Vite proxy `/api` → 8000). Menambah
   `allow_origins` justru melebarkan permukaan serangan. Tulis satu paragraf alasannya di
   `docs/plans/00-master.md` bagian Global Constraints supaya tidak "diperbaiki" orang lain.
2. **Rotasi JWT secret** = prosedur operasional, bukan kode: ganti `JWT_SECRET` di `.env`,
   restart API. Efek: semua sesi login mati, user login ulang. Masukkan ke RUNBOOK (Task 12).
3. **Verifikasi tidak ada rahasia ter-track** — jalankan dan tempel hasilnya sebagai bukti:
   ```bash
   git grep -nEi 'ghp_|github_pat_|password\s*=\s*["'"'"'][^"'"'"']+@' -- . | head
   git log --all --oneline -S 'gspe123456' | head
   ```

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_security.py docs/plans/00-master.md
git commit -m "test: attendance override admin-gated + catat keputusan CORS/JWT"
```

---

### Task 8: Harness resiliensi

**Files:**
- Create: `deploy/loadtest/resilience.sh`
- Test: skrip itu sendiri (dijalankan di server, output dibandingkan dengan ekspektasi)

**Interfaces:**
- Consumes: `VISION_*` env di `vision.env`, MQTT 1883, API 8000, `GET /api/v1/nodes`.
- Produces: skrip yang mencetak `PASS`/`FAIL` per skenario.

- [ ] **Step 1: Tulis harness**

Buat `deploy/loadtest/resilience.sh`:

```bash
#!/usr/bin/env bash
# Uji resiliensi I-Sentinel. Jalankan DI SERVER (gspe-ai3), bukan dari laptop.
# Semua restart memakai kill-cgroup karena sudo tanpa password tidak tersedia.
set -uo pipefail

ROOT="${ISENTINEL_ROOT:-/home/gspe-ai3/project_cv/I-Sentinel}"
API="${ISENTINEL_API:-http://127.0.0.1:8000}"
USER_NAME="${ISENTINEL_USER:-admin}"
USER_PASS="${ISENTINEL_PASS:?set ISENTINEL_PASS}"
JAR="$(mktemp)"
PASS=0; FAIL=0

ok()   { echo "  PASS  $1"; PASS=$((PASS+1)); }
bad()  { echo "  FAIL  $1"; FAIL=$((FAIL+1)); }
login() { curl -s -c "$JAR" -X POST "$API/api/v1/auth/login" -H 'Content-Type: application/json' \
            -d "{\"username\":\"$USER_NAME\",\"password\":\"$USER_PASS\"}" -o /dev/null; }
nodes() { curl -s -b "$JAR" "$API/api/v1/nodes"; }
restart_unit() { local u=$1
  kill "$(cat /sys/fs/cgroup/system.slice/$u/cgroup.procs 2>/dev/null)" 2>/dev/null || true
  for _ in $(seq 1 30); do sleep 1; systemctl is-active --quiet "$u" && return 0; done
  return 1; }

login
trap 'rm -f "$JAR"' EXIT

echo "== 1. API restart saat jalan =="
restart_unit isentinel-api.service && ok "API kembali aktif" || bad "API tidak kembali"
sleep 3; login
[ "$(curl -s -o /dev/null -w '%{http_code}' "$API/api/v1/health")" = "200" ] \
  && ok "health 200 setelah restart" || bad "health bukan 200"

echo "== 2. kill -9 vision → LWT → node offline =="
VPID=$(systemctl show -p MainPID --value vision-node.service)
kill -9 "$VPID" 2>/dev/null
sleep 20   # LWT broker + staleness di backend
STATE=$(nodes | grep -o '"status":"[a-z]*"' | head -1)
[ "$STATE" = '"status":"offline"' ] && ok "node terlihat offline ($STATE)" \
  || bad "node belum offline setelah 20 s ($STATE)"

echo "== 3. vision pulih + antrean ter-flush =="
restart_unit vision-node.service && ok "vision-node aktif lagi" || bad "vision-node gagal start"
sleep 30
STATE=$(nodes | grep -o '"status":"[a-z]*"' | head -1)
[ "$STATE" = '"status":"online"' ] && ok "node online lagi" || bad "node masih $STATE"

echo "== 4. kamera mati → status offline + event system =="
echo "  (manual: cabut/putus salah satu kamera, lalu jalankan ulang skrip ini)"
echo "  ekspektasi: /api/v1/cameras menunjukkan status != online dan muncul event type=system"

echo
echo "ringkasan: $PASS PASS, $FAIL FAIL"
[ "$FAIL" -eq 0 ]
```

- [ ] **Step 2: Jalankan di server**

```bash
ssh gspe-ai3 "cd ~/project_cv/I-Sentinel && chmod +x deploy/loadtest/resilience.sh"
ssh gspe-ai3 "cd ~/project_cv/I-Sentinel && ISENTINEL_PASS='<password-admin>' ./deploy/loadtest/resilience.sh"
```
Expected: `ringkasan: 4 PASS, 0 FAIL` (skenario 4 manual, tidak dihitung).

- [ ] **Step 3: Simpan bukti + commit**

Simpan output ke `docs/evidence/fase-5/resilience.txt`.

```bash
git add deploy/loadtest/resilience.sh docs/evidence/fase-5/resilience.txt
git commit -m "test: resilience harness (API restart, kill -9 LWT, vision recovery)"
```

---

### Task 9: Pilih GPU untuk detektor

**Files:**
- Modify: `vision/vision/config.py`, `vision/vision/pipeline/detector.py`
- Test: `vision/tests/test_detector.py`

**Interfaces:**
- Produces: `NodeSettings.detector_device: str = ""` (env `VISION_DETECTOR_DEVICE`), diteruskan
  ke `YOLO.predict(device=...)`. Kosong = perilaku lama (Ultralytics pilih sendiri).

- [ ] **Step 1: Tulis test yang gagal**

Tambahkan ke `vision/tests/test_detector.py`:

```python
def test_detector_passes_device_to_predict(monkeypatch):
    """Tanpa ini, soak test tidak bisa dipindah dari GPU0 yang sudah penuh."""
    from vision.pipeline.detector import PersonDetector

    seen = {}

    class FakeModel:
        def predict(self, frame, **kw):
            seen.update(kw)
            return []

    det = PersonDetector("x.engine", device="cuda:1")
    det._model = FakeModel()
    det.detect(object())

    assert seen["device"] == "cuda:1"


def test_detector_device_empty_omits_kwarg(monkeypatch):
    from vision.pipeline.detector import PersonDetector

    seen = {}

    class FakeModel:
        def predict(self, frame, **kw):
            seen.update(kw)
            return []

    det = PersonDetector("x.engine")
    det._model = FakeModel()
    det.detect(object())

    assert "device" not in seen
```

- [ ] **Step 2: Jalankan test, pastikan gagal**

Run: `cd vision && ./.venv/Scripts/python.exe -m pytest tests/test_detector.py -v`
Expected: FAIL — `PersonDetector.__init__() got an unexpected keyword argument 'device'`

- [ ] **Step 3: Implementasi**

`vision/vision/pipeline/detector.py`:

```python
    def __init__(self, model_path: str, nms: bool = False, conf: float = 0.4, imgsz: int = 640,
                 device: str = ""):
        self.model_path = model_path
        self.nms = nms
        self.conf = conf
        self.imgsz = imgsz
        self.device = device
        self._model = None
```

```python
        kwargs = {"conf": self.conf, "iou": 0.7 if self.nms else 0.0, "imgsz": self.imgsz,
                  "verbose": False}
        if self.device:
            kwargs["device"] = self.device
        results = self._model.predict(frame, **kwargs)
```

`vision/vision/config.py` — di `NodeSettings`, setelah `detector_imgsz`:

```python
    detector_device: str = ""  # "" = biarkan Ultralytics; mis. "cuda:1" untuk pin GPU
```

Lalu di tempat `PersonDetector(...)` dibuat (cari `detector_model` di `vision/vision/node.py`),
tambahkan `device=settings.detector_device`.

- [ ] **Step 4: Jalankan test**

Run: `cd vision && ./.venv/Scripts/python.exe -m pytest tests -q`
Expected: PASS seluruh suite vision (tidak ada regresi).

- [ ] **Step 5: Commit**

```bash
git add vision/vision/config.py vision/vision/pipeline/detector.py vision/tests/test_detector.py
git commit -m "feat: VISION_DETECTOR_DEVICE untuk pin GPU detektor"
```

---

### Task 10: Generator stream sintetis

**Files:**
- Create: `deploy/loadtest/make-streams.sh`, `deploy/loadtest/register-cams.py`

**Interfaces:**
- Consumes: `ffmpeg` (P1), go2rtc RTSP `:8554`, API `/api/v1/cameras`.
- Produces: N stream `synth_1..synth_N` di go2rtc + N kamera terdaftar di DB dengan pola nama
  `SYNTH-01..N` supaya mudah dihapus (`DELETE /api/v1/cameras/{id}`).

- [ ] **Step 1: Siapkan video sumber**

```bash
ssh gspe-ai3 'mkdir -p ~/isentinel-data/loadtest'
ssh gspe-ai3 'ffmpeg -f lavfi -i testsrc2=size=640x360:rate=15 -f lavfi -i sine=frequency=440 \
  -t 60 -c:v libx264 -preset ultrafast -pix_fmt yuv420p -c:a aac \
  ~/isentinel-data/loadtest/sample.mp4'
```
Expected: file ~1–2 MB. Video ini punya pola bergerak (memicu tracker), tapi belum ada "orang" —
itu cukup untuk menguji beban decode/deteksi; detektor akan mengembalikan 0 orang.

**Catatan jujur:** brief meminta video dengan "orang" bergerak. Kalau perlu deteksi benar-benar
menghasilkan `person_detect`/event, rekam 60 detik dari salah satu kamera nyata lalu pakai itu
sebagai sumber — perintahnya sama, hanya `-i` yang diganti:
```bash
ssh gspe-ai3 'ffmpeg -rtsp_transport tcp -i "rtsp://127.0.0.1:8554/cam_5" -t 60 -c copy \
  ~/isentinel-data/loadtest/sample.mp4'
```
Pilih ini kalau kriteria bukti menuntut event benar-benar terbentuk.

- [ ] **Step 2: Tulis skrip publisher**

`deploy/loadtest/make-streams.sh`:

```bash
#!/usr/bin/env bash
# Publish N video loop ke go2rtc sebagai stream synth_<i>. Jalankan DI SERVER.
#   ./make-streams.sh start 32      # nyalakan 32 stream
#   ./make-streams.sh stop          # matikan semua
#   ./make-streams.sh status
set -uo pipefail

N="${2:-32}"
SRC="${SYNTH_SRC:-$HOME/isentinel-data/loadtest/sample.mp4}"
RTSP="${SYNTH_RTSP:-rtsp://127.0.0.1:8554}"
PIDDIR="${SYNTH_PIDDIR:-/tmp/isentinel-synth}"
mkdir -p "$PIDDIR"

start() {
  [ -f "$SRC" ] || { echo "video sumber tidak ada: $SRC"; exit 1; }
  for i in $(seq 1 "$N"); do
    if [ -f "$PIDDIR/$i.pid" ] && kill -0 "$(cat "$PIDDIR/$i.pid")" 2>/dev/null; then continue; fi
    ffmpeg -nostdin -loglevel error -re -stream_loop -1 -i "$SRC" \
      -c:v libx264 -preset ultrafast -tune zerolatency -g 15 -f rtsp -rtsp_transport tcp \
      "$RTSP/synth_$i" >/dev/null 2>&1 &
    echo $! > "$PIDDIR/$i.pid"
  done
  echo "started: $(ls "$PIDDIR" | wc -l) publisher"
}

stop() {
  for f in "$PIDDIR"/*.pid; do [ -e "$f" ] || continue; kill "$(cat "$f")" 2>/dev/null; rm -f "$f"; done
  echo "semua publisher dimatikan"
}

status() {
  local live=0
  for f in "$PIDDIR"/*.pid; do [ -e "$f" ] || continue
    kill -0 "$(cat "$f")" 2>/dev/null && live=$((live+1)); done
  echo "publisher hidup: $live / $(ls "$PIDDIR"/*.pid 2>/dev/null | wc -l)"
  free -m | awk 'NR==2{printf "RAM: %s MB terpakai dari %s MB\n", $3, $2}'
  nvidia-smi --query-gpu=index,utilization.gpu,memory.used --format=csv,noheader
}

case "${1:-}" in
  start) start ;;
  stop) stop ;;
  status) status ;;
  *) echo "pakai: $0 {start N|stop|status}"; exit 2 ;;
esac
```

- [ ] **Step 3: Tulis skrip registrasi kamera**

`deploy/loadtest/register-cams.py` — daftarkan/hapus kamera sintetis lewat API supaya seluruh
pipeline ikut jalan:

```python
"""Daftarkan kamera sintetis ke I-Sentinel lewat API.

    python register-cams.py add 32
    python register-cams.py remove
"""
import json
import os
import sys
import urllib.request

API = os.environ.get("ISENTINEL_API", "http://127.0.0.1:8000")
USER = os.environ.get("ISENTINEL_USER", "admin")
PASS = os.environ.get("ISENTINEL_PASS")
PREFIX = "SYNTH-"


def _req(path, method="GET", body=None, cookie=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{API}{path}", data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    if cookie:
        req.add_header("Cookie", cookie)
    with urllib.request.urlopen(req) as res:
        raw = res.read()
        return res.headers.get("Set-Cookie"), (json.loads(raw) if raw else None)


def _login():
    cookie, _ = _req("/api/v1/auth/login", "POST", {"username": USER, "password": PASS})
    return cookie.split(";")[0]


def _cameras(cookie):
    _, rows = _req("/api/v1/cameras", cookie=cookie)
    return rows


def add(n):
    cookie = _login()
    node_id = next((n_["id"] for n_ in _req("/api/v1/nodes", cookie=cookie)[1]
                    if n_["type"] == "server"), None)
    created = 0
    for i in range(1, n + 1):
        name = f"{PREFIX}{i:02d}"
        if any(c["name"] == name for c in _cameras(cookie)):
            continue
        _req("/api/v1/cameras", "POST", {
            "name": name,
            "location": "LOADTEST",
            "host": "127.0.0.1",
            "rtsp_sub": f"/synth_{i}",
            "node_id": node_id,
        }, cookie=cookie)
        created += 1
    print(f"dibuat: {created}")


def remove():
    cookie = _login()
    removed = 0
    for c in _cameras(cookie):
        if str(c["name"]).startswith(PREFIX):
            _req(f"/api/v1/cameras/{c['id']}", "DELETE", cookie=cookie)
            removed += 1
    print(f"dihapus: {removed}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "add":
        add(int(sys.argv[2]) if len(sys.argv) > 2 else 32)
    elif cmd == "remove":
        remove()
    else:
        print(__doc__)
        sys.exit(2)
```

- [ ] **Step 4: Uji dengan 2 stream dulu, bukan 32**

```bash
ssh gspe-ai3 "cd ~/project_cv/I-Sentinel && chmod +x deploy/loadtest/make-streams.sh"
ssh gspe-ai3 "cd ~/project_cv/I-Sentinel && ./deploy/loadtest/make-streams.sh start 2 && sleep 5 && ./deploy/loadtest/make-streams.sh status"
ssh gspe-ai3 "cd ~/project_cv/I-Sentinel && curl -s -o /dev/null -w 'synth_1 http %{http_code}\n' 'http://127.0.0.1:1984/api/frame.jpeg?src=synth_1'"
ssh gspe-ai3 "cd ~/project_cv/I-Sentinel && ISENTINEL_PASS='<password-admin>' python3 deploy/loadtest/register-cams.py add 2"
```
Expected: `publisher hidup: 2 / 2`, `synth_1 http 200`, `dibuat: 2`.

- [ ] **Step 5: Bersihkan + commit**

```bash
ssh gspe-ai3 "cd ~/project_cv/I-Sentinel && ISENTINEL_PASS='<password-admin>' python3 deploy/loadtest/register-cams.py remove && ./deploy/loadtest/make-streams.sh stop"
git add deploy/loadtest/make-streams.sh deploy/loadtest/register-cams.py
git commit -m "feat: synthetic stream generator + camera registration for load test"
```

---

### Task 11: Soak + laporan

**Files:**
- Create: `deploy/loadtest/soak.sh`, `docs/evidence/fase-5/soak.md`

**Interfaces:**
- Consumes: `make-streams.sh`, `register-cams.py` (Task 10), `VISION_DETECTOR_DEVICE` (Task 9).
- Produces: CSV metrik + laporan dengan angka nyata.

- [ ] **Step 1: Tulis sampler**

`deploy/loadtest/soak.sh`:

```bash
#!/usr/bin/env bash
# Soak: jalankan N stream sintetis, sampel metrik tiap 30 s, tulis CSV.
#   ./soak.sh 120 32        # 120 menit, 32 stream
set -uo pipefail
MINUTES="${1:-120}"; N="${2:-32}"
OUT="${SOAK_OUT:-$HOME/isentinel-data/loadtest/soak-$(date +%Y%m%d-%H%M).csv}"
mkdir -p "$(dirname "$OUT")"
echo "ts,gpu0_util,gpu0_mem_mb,vision_rss_kb,api_rss_kb,events_total" > "$OUT"

./deploy/loadtest/make-streams.sh start "$N"
ISENTINEL_PASS="${ISENTINEL_PASS:?}" python3 deploy/loadtest/register-cams.py add "$N" || true

END=$(( $(date +%s) + MINUTES * 60 ))
while [ "$(date +%s)" -lt "$END" ]; do
  TS=$(date +%s)
  GPU=$(nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv,noheader,nounits -i 0 | tr -d ' ')
  VRSS=$(ps -o rss= -p "$(systemctl show -p MainPID --value vision-node.service)")
  ARSS=$(ps -o rss= -p "$(systemctl show -p MainPID --value isentinel-api.service)")
  EV=$(curl -s -b /dev/null "http://127.0.0.1:8000/api/v1/events/stats/today" 2>/dev/null | grep -o '"total":[0-9]*' | cut -d: -f2)
  echo "$TS,$GPU,${VRSS// /},${ARSS// /},${EV:-0}" >> "$OUT"
  sleep 30
done

echo "CSV: $OUT"
awk -F, 'NR>1{u+=$2;m+=$3;r+=$4;if($4>max)max=$4} END{printf "gpu util rata2 %.1f%% | gpu mem rata2 %d MB | vision RSS rata2 %d MB puncak %d MB\n", u/(NR-1), m/(NR-1), r/(NR-1)/1024, max/1024}' "$OUT"
```

- [ ] **Step 2: Jalankan sesuai keputusan D1**

Untuk pilihan (b) — 2 jam + churn:
```bash
ssh gspe-ai3 'export VISION_DETECTOR_DEVICE=cuda:1   # sudah harus ada di vision.env sebelum start'
ssh gspe-ai3 "cd ~/project_cv/I-Sentinel && ISENTINEL_PASS='<password-admin>' SOAK_OUT=~/isentinel-data/loadtest/soak.csv ./deploy/loadtest/soak.sh 120 32"
```
Selama soak berjalan, jalankan churn di terminal lain:
```bash
for i in 1 2 3 4 5; do
  ssh gspe-ai3 "cd ~/project_cv/I-Sentinel && ISENTINEL_PASS='<password-admin>' python3 deploy/loadtest/register-cams.py remove"
  ssh gspe-ai3 "cd ~/project_cv/I-Sentinel && ISENTINEL_PASS='<password-admin>' python3 deploy/loadtest/register-cams.py add 32"
  sleep 300
done
```

- [ ] **Step 3: Ambil kesimpulan dari CSV, bukan dari ingatan**

```bash
ssh gspe-ai3 'awk -F, "NR>1{if(\$4>max)max=\$4; n++; s+=\$4} END{printf \"sampel=%d vision RSS rata2=%.0f MB puncak=%.0f MB\n\", n, s/n/1024, max/1024}" ~/isentinel-data/loadtest/soak.csv'
```
Expected sesuai kriteria brief: RAM **naik lalu plateau** (bandingkan 30 menit pertama vs 30
menit terakhir — selisih RSS < 10%). Kalau terus naik monoton, itu leak: **jangan di-commit
sebagai sukses.**

- [ ] **Step 4: Tulis laporan dengan angka nyata**

`docs/evidence/fase-5/soak.md`: durasi, N stream, GPU dipakai, tabel ringkas dari CSV, p95
latensi event (ukur dari `ts_event` vs `created_at` event terakhir), dan **apa yang tidak
tercapai** kalau ada.

- [ ] **Step 5: Bersihkan + commit**

```bash
ssh gspe-ai3 "cd ~/project_cv/I-Sentinel && ISENTINEL_PASS='<password-admin>' python3 deploy/loadtest/register-cams.py remove && ./deploy/loadtest/make-streams.sh stop"
git add deploy/loadtest/soak.sh docs/evidence/fase-5/soak.md
git commit -m "test: 32-stream soak harness + laporan metrik"
```

---

### Task 12: Dokumentasi operasional + rekonsiliasi unit

**Files:**
- Create: `docs/RUNBOOK.md`
- Modify: `deploy/systemd/isentinel-api.service`, `deploy/systemd/vision-node.service`,
  `README.md`, `docs/plans/00-master.md`, `ROADMAP.md`, `CHANGELOG.md`

**Interfaces:** tidak ada kode; ini yang membuat sistem bisa dioperasikan orang lain.

- [ ] **Step 1: Rekonsiliasi unit systemd dengan yang AKTUAL**

Repo dan server berbeda (P5). Samakan ke yang aktual supaya `deploy/` bisa dipakai ulang:

```bash
ssh gspe-ai3 'systemctl cat isentinel-api isentinel-web vision-node | grep -E "^(# |WorkingDirectory|ExecStart|User|EnvironmentFile)"'
```
Lalu ubah file di `deploy/systemd/` agar cocok — termasuk mengganti `User=isentinel` →
`User=gspe-ai3`, `/opt/isentinel` → `/home/gspe-ai3/project_cv/I-Sentinel`, dan
`isentinel-venv/bin/vision-node` → `vision-venv/bin/isentinel-vision`.

- [ ] **Step 2: Tulis RUNBOOK**

`docs/RUNBOOK.md` wajib memuat, dengan perintah yang **sudah diverifikasi jalan**:

1. **Start/stop/restart** — termasuk trik kill-cgroup karena sudo tanpa password terbatas.
2. **Backup DB** — `pg_dump` + restore, dan backup `.env` (ingat mode 600).
3. **Tambah kamera** — playbook wizard probe → node → zona, plus catatan bahwa
   `go2rtc.yaml` ditulis otomatis oleh go2rtc saat kamera ditambah/dinonaktifkan.
4. **Troubleshooting** — live view 502 (cek go2rtc + stream), node offline (cek LWT/heartbeat),
   login 401 setelah restart, disk penuh (jalankan sweep manual).
5. **Alert runbook** — Telegram belum dikonfigurasi artinya apa, dan bagaimana memverifikasi
   alert tercatat (`/api/v1/alerts`).
6. **Rotasi JWT secret** — prosedur + efek (semua sesi mati).
7. **Retensi** — jadwal timer, cara menjalankan manual, cara membaca hasil sweep.

- [ ] **Step 3: Diagram arsitektur final**

Tambahkan diagram ASCII ke `README.md`: browser → Vite :5173 → API :8000 → Postgres,
go2rtc :1984/:8554 (tertutup firewall, snapshot lewat proxy API), Mosquitto :1883,
vision-node → MQTT + HTTP upload. Sebutkan **port** dan mana yang terbuka.

- [ ] **Step 4: Tandai milestone selesai**

`docs/plans/00-master.md`: baris Fase 5 → **DONE** + hash range.
`ROADMAP.md`: baris Fase 5 → `[x]` + tabel bukti.
`CHANGELOG.md`: entri versi baru (0.6.0) dengan semua commit fase ini.

- [ ] **Step 5: Verifikasi seluruh gerbang**

```bash
cd backend && .venv/Scripts/python.exe -m pytest tests -q
cd vision && .venv/Scripts/python.exe -m pytest tests -q
cd frontend && npx vitest run && npm run build && npx oxlint
```
Expected: semua hijau. Kalau ada yang merah, **jangan tandai Fase 5 selesai.**

- [ ] **Step 6: Commit + push + tag**

```bash
git add -A
git commit -m "docs: RUNBOOK operasional, diagram, rekonsiliasi unit systemd + Fase 5 selesai"
git tag -a v0.6.0 -m "v0.6.0 - Fase 5 hardening: retensi, keamanan, resiliensi, soak"
git push origin main --follow-tags
```
Lalu `ssh gspe-ai3 "cd ~/project_cv/I-Sentinel && git pull"`.

---

## Fase 5 — Definition of Done

Semua harus tercentang, dengan bukti tertempel (bukan "seharusnya jalan"):

- [ ] **Retensi**: `pytest backend/tests/test_retention.py` hijau; timer terpasang
      (`systemctl list-timers`); sweep manual dari UI mengubah angka di halaman Retensi & Storage;
      file uji kadaluarsa benar-benar hilang dari disk dan `event.media_expired = true`.
- [ ] **Tidak ada file orphan** setelah sweep — dijalankan pada storage nyata, jumlah file
      yang lebih tua dari 30 hari = 0.
- [ ] **Keamanan**: `/auth/login` mengembalikan 429 setelah N gagal (`test_auth_ratelimit.py`);
      `git grep` kredensial = kosong; tidak ada file runtime berisi kredensial yang ter-track;
      keputusan CORS + prosedur rotasi JWT tercatat di RUNBOOK.
- [ ] **Resiliensi**: `resilience.sh` → 4 PASS / 0 FAIL, output tersimpan di
      `docs/evidence/fase-5/resilience.txt`.
- [ ] **Soak**: CSV metrik dengan ≥ 2 jam data; RSS vision **plateau** (bukan naik monoton);
      GPU util & mem tercatat; laporan `docs/evidence/fase-5/soak.md` memuat angka nyata dan
      secara eksplisit menyebut apa yang tidak tercapai.
- [ ] **Dokumentasi**: `docs/RUNBOOK.md` lengkap; `deploy/systemd/` cocok dengan unit yang benar-benar
      jalan; diagram + daftar port di README.
- [ ] **Gerbang**: pytest backend + vision + vitest + build + oxlint semuanya hijau.
- [ ] **Rekonsiliasi rencana**: `docs/plans/00-master.md` baris Fase 5 = DONE, ROADMAP + CHANGELOG
      terisi, tag `v0.6.0` di-push, server sudah `git pull`.

**Tidak termasuk Fase 5** (jangan dikerjakan diam-diam di sini): Telegram chat CRUD + sendPhoto,
halaman User/Notifikasi/Deteksi&Model, WebRTC video live, recorder nyata, probe massal, alerts
acknowledge, Edge Jetson. Semua itu dicatat sebagai kandidat setelah Fase 5 di `ROADMAP.md`.
