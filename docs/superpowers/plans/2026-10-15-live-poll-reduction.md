# Live Polling & DB Pool Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Kurangi polling `/live` dan `/events` di jendela TV dan buat pool DB API tahan lonjakan.

**Architecture:** Hook frontend menerima himpunan kamera yang tampil; provider notifikasi membagikan satu poller event; backend memakai pool dapat diatur dan melepas koneksi sebelum menunggu go2rtc.

**Tech Stack:** FastAPI + SQLAlchemy 2, React 19 + TypeScript, Vitest, pytest.

**Spec:** `docs/superpowers/specs/2026-10-15-live-poll-reduction-design.md` (disetujui 2026-10-15).

## Global Constraints

- Respons API, tampilan, dan perilaku kiosk tidak berubah. Tidak ada dependensi, endpoint, atau migrasi baru.
- Pool: `db_pool_size=20`, `db_max_overflow=20`, `db_pool_timeout=10.0`, dapat ditimpa env (`DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_TIMEOUT`); tidak diterapkan pada SQLite (tes).
- Tile tidak boleh kosong menunggu refresh 30 detik setelah himpunan kamera berubah.
- Commit Conventional Commits, tanpa atribusi AI, satu per perubahan fungsional; tanpa push kecuali user mengizinkan; suite berurutan (pytest lalu vitest/build/lint), `env -u NODE_ENV`; dilarang `uv sync`/`uv lock`.
- Production tidak bisa membangun image: bangun di dev, kirim; tiap deploy butuh izin eksplisit.

## Review Focus

1. Pilihan kamera berubah saat berjalan → ID baru langsung diambil, ID lama tidak diambil ulang (Task 3).
2. Kamera nonaktif tidak pernah diambil walau ada di `cameras=` (Task 3).
3. `cameras=` berisi ID tak dikenal → tidak ada permintaan untuknya (Task 3).
4. Dua pemanggil langganan event (provider dan `LiveWall`) → tepat satu poller `/events` per jendela, dan `LiveWall` tetap menerima event (Task 4).
5. Snapshot: 404 untuk kamera tak ada, 502 bila go2rtc gagal, tetap benar setelah sesi ditutup lebih awal (Task 2).

## Tasks

### Task 1: Pool DB dapat diatur (B1)
**Files:** `backend/app/core/config.py`, `backend/app/core/db.py`; tes `backend/tests/test_db_pool.py` (baru).
**Interfaces:** `Settings.db_pool_size: int = 20`, `db_max_overflow: int = 20`, `db_pool_timeout: float = 10.0`; `app.core.db.engine_kwargs(url: str) -> dict` (kosong untuk URL `sqlite`, selain itu `pool_pre_ping=True, pool_size, max_overflow, pool_timeout`).
- [ ] Tes gagal: default 20/20/10.0; env `DB_POOL_SIZE=7` menimpa; `engine_kwargs("sqlite://")` == `{}`; `engine_kwargs("postgresql+psycopg://x")` memuat tiga nilai pool dan `pool_pre_ping=True`.
- [ ] Implementasi `engine_kwargs` dan `create_engine(settings.database_url, **engine_kwargs(settings.database_url))`; pertahankan `pool_pre_ping=True` untuk semua dialek.
- [ ] `pytest tests/test_db_pool.py` lulus; commit `feat(db): pool koneksi dapat diatur lewat env (bawaan 20+20, timeout 10 detik)`.

### Task 2: Snapshot melepas sesi DB sebelum menunggu go2rtc (B2)
**Files:** `backend/app/api/live.py` (`camera_snapshot`); tes `backend/tests/test_live_snapshot.py` (baru).
- [ ] Tes gagal: override `get_db` dengan sesi pelacak; ganti `app.api.live.httpx.get` dengan palsu yang mencatat apakah sesi sudah ditutup saat dipanggil; assert sudah ditutup. Tes lain: kamera tak ada → 404 (go2rtc tidak dipanggil); `httpx.HTTPError` → 502 `go2rtc unreachable`; status upstream ≠ 200 → 502; sukses → 200 `image/jpeg` dengan `Cache-Control: no-store`.
- [ ] Implementasi: baca `cam.id` lalu `db.close()` sebelum `httpx.get`.
- [ ] Lulus; commit `fix(live): snapshot melepas koneksi DB sebelum menunggu go2rtc`.

### Task 3: `useLiveCameras(wanted)` hanya kamera tampil (A1)
**Files:** `frontend/src/features/live/useLiveCameras.ts`, `LiveTvPage.tsx`, `LiveViewPage.tsx`; tes `frontend/src/__tests__/live-cameras-hook.test.tsx` (baru), `live-tv.test.tsx`, `liveview.test.tsx`.
**Interfaces:** `useLiveCameras(wanted?: number[] | null)`; himpunan = kamera `enabled` yang ID-nya di `wanted` (semua aktif bila `wanted == null`); mengembalikan bentuk yang sama seperti sekarang.
- [ ] Tes gagal (hook, `fetch` palsu menghitung `/cameras/N/live`): `wanted=[1,2]` dari 5 kamera (3 nonaktif ikut di daftar) → hanya `1` dan `2`; kamera nonaktif di `wanted` tidak diambil; ID tak dikenal tidak diambil; `wanted` berubah ke `[1,2,3]` → hanya `3` diambil segera; timer 30 detik hanya himpunan saat ini; `wanted=null` → semua aktif (bukan nonaktif). Tes halaman: `/live/tv?cameras=2,1` memanggil `/live` hanya untuk 2 dan 1.
- [ ] Implementasi: simpan `wanted` di ref; `fetchLives(ids)` mengisi `lives` secara inkremental; efek pada kunci himpunan mengambil ID yang belum ada; `refresh` mengambil himpunan saat ini. `LiveTvPage`: mengoper ID tampil (URL `cameras=` bila ada, kalau tidak ID dari pilihan tersimpan atau `null` bila `all`); `LiveViewPage`: idem dari pilihan layar `default`.
- [ ] Lulus; commit `feat(live): info /live hanya untuk kamera yang tampil dan aktif`.

### Task 4: Satu langganan event per jendela (A2)
**Files:** `frontend/src/features/notifications/EventAlertsProvider.tsx`, `frontend/src/features/live/LiveWall.tsx`; tes `frontend/src/__tests__/live-events-subscription.test.tsx` (baru) dan tes yang ada.
**Interfaces:** `useEventAlerts()` menambah `subscribeEvents(cb: (e: unknown) => void): () => void`; `LiveWall` memakainya menggantikan `useLiveEvents`.
- [ ] Tes gagal: render `/live/tv` dengan provider; timer palsu 5 detik; `fetch` ke `/events` dipanggil sekali per tick (bukan dua kali); event yang masuk lewat provider tetap menyalakan outline tile di `LiveWall`.
- [ ] Implementasi: provider meneruskan event dari `useLiveEvents`-nya ke daftar pelanggan; `LiveWall` berlangganan di efek dan membatalkan saat unmount; pesan sebelum jendela riwayat tetap diperlakukan seperti sekarang.
- [ ] Lulus; commit `refactor(live): satu poller event per jendela, LiveWall berlangganan lewat provider`.

### Task 5: Dokumentasi
- [ ] README/WORKFLOW/ARCHITECTURE (angka polling dan pool), runbook TV (catatan beban), `.env.example` (variabel pool), CHANGELOG, ROADMAP. Commit `docs(live): pengurangan polling dan pool DB`.

### Task 6: Verifikasi penuh dan deploy dev
- [ ] `pytest tests -q -m "not gpu and not llm"` (baseline `1112 passed, 1 deselected`), lalu `npx vitest run` (baseline 39 berkas / 579 tes; `--maxWorkers=2` bila mesin ber-load), `npm run build`, `npm run lint` (24 warning, set identik).
- [ ] Izin user → push, deploy dev (`./docker/setup.sh`), verifikasi: nginx `web` 2 menit, `/live` hanya kamera tampil; log `api` tanpa `QueuePool`; uji user.

### Task 7: Deploy production
- [ ] Izin user → tag cadangan `*:prev-<tanggal>`, kirim image `web` dan `api` dari dev (sha256), `run-setup.sh`, verifikasi (health, subnet `172.16.200.0/24`, tanpa rute `192.168.x`); ukur nginx 2 menit (`/live` ≈76 dari 528; total ≈ separuh) dan 0 `QueuePool` dalam 1 jam setelah memuat ulang Chromium di ketiga Pi bersamaan.
