# Spec — Retention & Storage UI (retensi editable, clip vs snapshot, cleanup per tanggal, alert disk)

Status: **DISETUJUI di chat (2026-09-29)**, menunggu review spec tertulis.
Branch: `feat/retention-storage-ui` (dari `main` @ `5c17cea`).
Checkpoint: `.cooper/context/next-features.md`.

---

## 1. Latar

Usulan user (awal): *"Retention & Storage, belum editable via UI. bisa manage data event untuk cleanup per date
range."* Mockup yang disetujui (`mockup-ui/06-configuration.html`, panel Retensi): input retensi (hari), info
auto-cleanup harian, estimasi pemakaian, tombol Simpan.

### Kondisi kode (`main` @ `5c17cea`)

| # | Fakta | Lokasi |
|---|---|---|
| 1 | Tab **Storage** (Konfigurasi) hanya-baca: retensi, path, disk, pemakaian per jenis (clips/snapshots/crops), sweep terakhir; admin: tombol Dry run / Jalankan sekarang. | `frontend/src/features/config/StoragePage.tsx`, `src/api/storage.ts` |
| 2 | `GET /api/v1/storage/stats` (semua user), `POST /storage/sweep?dry_run=` (admin); sweep terakhir di `setting` key `retention_last_sweep`. | `backend/app/api/storage.py` |
| 3 | Retensi = **satu angka** `RETENTION_DAYS` (env, default 30) untuk clip + snapshot; ubah = edit `.env` + restart. | `core/config.py:39` |
| 4 | Sweep 2 lapis: (a) event `ts_event < cutoff` → file clip/snapshot dihapus (clip bersama yang masih dirujuk event belum kedaluwarsa dipertahankan), path di-null-kan, `media_expired=True`; (b) orphan per mtime di `clips/`, `snapshots/`, `crops/`. **Baris event tidak pernah dihapus.** | `backend/app/services/retention.py` |
| 5 | Sweep harian lewat systemd (`isentinel-retention.timer` → `scripts/retention_sweep.py`, memanggil `retention.sweep(db)` langsung). | `backend/scripts/retention_sweep.py`, `deploy/systemd/` |
| 6 | `alert.event_id` FK ke `event.id` (unique, tanpa cascade) → hapus event harus menghapus alert-nya dulu. | `backend/app/models/alert.py:11` |
| 7 | Telegram: `deliver(token, chat_id, text)` kirim teks (tidak pernah raise), `get_token()`, `active_chat(db)`. | `backend/app/services/telegram.py` |
| 8 | Event `attendance` = sumber hari absensi & export CSV. | `services/attendance.py` |

## 2. Keputusan user

| # | Keputusan |
|---|---|
| K1 | Cakupan: retensi editable di UI, retensi terpisah clip vs snapshot, cleanup event per rentang tanggal, peringatan disk hampir penuh. |
| K2 | Cleanup menghapus **baris event + media**, **attendance dikecualikan** (rekap absensi aman). |
| K3 | Peringatan disk: **banner UI + Telegram**, ambang editable (default 85 %). |

## 3. Desain

### 3.1 Pengaturan storage (tanpa migrasi)

- Disimpan di `setting` key **`storage`**: `{"clip_days": int, "snapshot_days": int, "disk_alert_percent": int}`.
- Default bila belum ada / field hilang: `clip_days = snapshot_days = settings.retention_days`,
  `disk_alert_percent = 85`.
- Validasi: hari **1–3650**, ambang **50–99** (422 di luar rentang / bukan int).
- Service `app/services/storage_settings.py`: `get(db) -> dict` (efektif), `put(db, patch) -> dict`.
- API: `GET /api/v1/storage/settings` (semua user), `PUT /api/v1/storage/settings` (admin; body parsial,
  `extra="forbid"`). `GET /storage/stats` mengembalikan `settings` efektif (field `retention_days` lama tetap =
  `clip_days` untuk kompatibilitas) dan `disk_alert: {threshold, over}`.

### 3.2 Sweep dengan retensi terpisah

- `retention.sweep(db, now=None, dry_run=False)` membaca `storage_settings.get(db)`:
  - lapis 1: `clip_cutoff = now - clip_days`, `snapshot_cutoff = now - snapshot_days`. Event dengan
    `ts_event < clip_cutoff` → clip dihapus (aturan clip bersama tetap, dihitung terhadap event dengan
    `ts_event >= clip_cutoff`); `ts_event < snapshot_cutoff` → snapshot dihapus. `media_expired=True` saat media
    apa pun dihapus retensi (perilaku sekarang).
  - lapis 2 (orphan): `clips/` memakai `clip_cutoff`; `snapshots/`, `crops/` memakai `snapshot_cutoff`.
- Hasil sweep ditambah `clip_days`, `snapshot_days` (dicatat di `retention_last_sweep`).
- Sweep harian (systemd) & manual otomatis memakai nilai DB; tanpa restart.

### 3.3 Cleanup event per rentang tanggal

- `POST /api/v1/storage/cleanup` (admin), body `{"date_from": "YYYY-MM-DD", "date_to": "YYYY-MM-DD",
  "camera_ids": [int]?, "types": [str]?, "dry_run": bool}`.
- Rentang dalam zona waktu lokal server: `[date_from 00:00, date_to + 1 hari 00:00)` pada `ts_event`.
- **`attendance` selalu dikecualikan** (juga bila diminta di `types` → diabaikan). `types` lain harus anggota
  `ALLOWED_TYPES` ingest (422 bila tidak).
- Validasi: `date_from <= date_to`, `date_to <= hari ini`, rentang tidak kosong → 422 bila salah.
- Eksekusi (service `retention.cleanup(db, date_from, date_to, camera_ids, types, dry_run)`):
  1. pilih event cocok; kumpulkan path clip/snapshot;
  2. file dihapus kecuali dirujuk event **di luar** himpunan yang dihapus (clip insiden bersama);
     path keluar `storage_root` diabaikan (`_safe_join`);
  3. hapus baris `alert` untuk event tersebut, lalu baris event; satu commit.
- Response `{"events": n, "files": n, "bytes": n, "dry_run": bool}`; `dry_run` tidak mengubah apa pun.
- Setiap cleanup non-dry-run dicatat `logger.info` dengan username admin + rentang + jumlah (tanpa data pribadi).

### 3.4 Peringatan disk hampir penuh

- Service `app/services/disk_alert.py`: `check(db, now=None, percent=None) -> str | None` — membandingkan
  `disk_usage(storage_root).percent` dengan `disk_alert_percent`; state di `setting` key **`disk_alert_state`**
  `{"over": bool, "last_sent_at": iso | null}`:
  - `percent >= threshold` dan (belum `over` atau `last_sent_at` > 24 jam) → kirim pesan "⚠️ Disk hampir penuh:
    N % (ambang M %) — sisa X GB", `over=True`, `last_sent_at=now`;
  - `over` dan `percent < threshold - 2` → kirim "✅ Disk pulih: N %", `over=False`;
  - kirim hanya bila token + grup aktif ada; bila tidak, state tetap diperbarui (banner tetap jalan).
  - mengembalikan jenis pesan yang dikirim (`"alert"`/`"recovered"`/`None`) untuk tes.
- Thread latar di lifespan API (pola `alert_dispatcher`): tiap **600 s**, sesi DB sendiri, exception dicatat tanpa
  mematikan thread; berhenti rapi saat shutdown. Tes memanggil `check()` langsung.
- `GET /storage/stats` → `disk_alert.over = percent >= threshold` (dihitung langsung, bukan dari state).

### 3.5 Frontend — tab Storage

- **Banner** merah (InlineNotification error) "Disk hampir penuh (N %) — ambang M %" bila `disk_alert.over`, di tab
  Storage dan **Dashboard** (Dashboard memanggil `getStorageStats`; gagal → tanpa banner).
- Bagian atas (disk, per jenis, sweep terakhir) tetap; tile "Retensi" menampilkan "Clip N hari · Snapshot M hari".
- **Kartu "Pengaturan retensi"** (admin; viewer read-only): NumberInput clip (hari), snapshot (hari), ambang disk
  (%), teks "Auto-cleanup harian (systemd)", tombol **Simpan** → toast sukses / error 422.
- **Kartu "Bersihkan event"** (admin saja): tanggal dari/sampai (`TextInput type="date"`, max = hari ini), kamera
  (MultiSelect, opsional), jenis (MultiSelect tanpa attendance, opsional) → **Pratinjau** (dry run) menampilkan
  "N event · M file · X" → **Hapus N event** (danger) → modal konfirmasi menyebut jumlah & rentang → eksekusi →
  hasil + refresh stats. Tombol Hapus nonaktif sampai pratinjau untuk filter yang sama sudah ada.
- REST lewat `src/api/storage.ts`; string lewat `i18n.tsx`; 390 px tanpa overflow.

## 4. Penanganan error

| Kondisi | Perilaku |
|---|---|
| Hari retensi < 1 / > 3650, ambang < 50 / > 99, field liar | 422 |
| Cleanup: tanggal terbalik / masa depan / format salah / jenis tak dikenal | 422 |
| Cleanup meminta `attendance` | diabaikan (tidak pernah dihapus) |
| File cleanup tidak ada / di luar storage_root | dilewati, baris event tetap dihapus |
| Telegram belum dikonfigurasi / gagal kirim | state diperbarui, banner tetap; error dicatat tanpa token |
| Viewer memanggil PUT settings / cleanup | 403 |

## 5. Pengujian

- Backend:
  - settings: default dari env, PUT parsial + validasi, 403 viewer, stats memuat settings & `disk_alert`;
  - sweep: clip 7 hari vs snapshot 30 hari (event 10 hari → clip hilang, snapshot tetap), orphan per jenis,
    clip bersama tetap aman;
  - cleanup: dry run tanpa perubahan, attendance aman (juga bila diminta), clip bersama dengan event di luar rentang
    tetap, alert ikut terhapus, filter kamera/jenis, validasi tanggal, 403 viewer, batas zona waktu;
  - disk alert: di bawah ambang → tidak kirim; lewat → kirim sekali; < 24 jam → tidak ulang; > 24 jam → ulang;
    turun < ambang−2 → pulih; tanpa Telegram → tidak kirim tapi state `over`.
- Frontend: form pengaturan (simpan, 422, viewer read-only), cleanup (pratinjau → konfirmasi → hapus, tombol nonaktif
  sebelum pratinjau / setelah filter berubah), banner disk (Storage & Dashboard), 390 px.
- Baseline `main` `5c17cea`: backend 450, vision 223 (3 deselected), frontend 171, build 0, lint set sama.

## 6. Verifikasi lapangan (butuh izin user)

Deploy (restart API; frontend HMR; tanpa migrasi). Uji: ubah retensi clip → dry run menunjukkan clip yang akan
dihapus; cleanup rentang uji kecil (pratinjau → hapus) dan pastikan absensi tidak berubah; set ambang disk di bawah
pemakaian sekarang → banner + pesan Telegram → kembalikan ambang → pesan pulih.

## 7. Di luar scope

Jadwal sweep editable (tetap harian systemd), pindah path storage (tetap env), retensi otomatis baris event,
penghapusan data attendance, kuota per kamera.

## 8. Rollback

`git revert` + restart API. Setting `storage` / `disk_alert_state` di DB diabaikan kode lama (retensi kembali ke
`RETENTION_DAYS`). Event yang sudah dihapus cleanup **tidak bisa dipulihkan** — itulah alasan pratinjau + konfirmasi.
