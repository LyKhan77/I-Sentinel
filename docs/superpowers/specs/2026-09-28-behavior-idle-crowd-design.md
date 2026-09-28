# Spec — Behavior baru: Idle Zone + Crowd (+ jadwal zona ikut Shift)

Status: **DISETUJUI di chat (2026-09-28)**, menunggu review spec tertulis.
Branch: `feat/behavior-idle-crowd` (dari `main` @ `b9fdc55`).
Checkpoint: `.cooper/context/next-features.md`.

---

## 1. Latar

Usulan user: *"menambah behavior baru … alerting jika tidak ada orang di dalam zona selama threshold waktu yang ditentukan
(Idle Zone), Crowd Detection (alerting jika terlalu banyak jumlah orang terdeteksi dalam suatu zona)"*, lalu *"apakah
bisa assign [jadwal] dari Shift saja?"*. Kandidat lain yang dibahas (Lone worker, Line crossing, Man-down, APD) **di luar
siklus ini**. Referensi `roboflow/supervision` dipakai sebagai referensi algoritma (PolygonZone/time-in-zone), **bukan**
dependensi vision (aturan minimal-deps).

### Kondisi kode (`main` @ `b9fdc55`)

| # | Fakta | Lokasi |
|---|---|---|
| 1 | Detektor hanya kelas orang (YOLO class 0) → behavior = aturan atas track orang. | `vision/vision/pipeline/detector.py:60` |
| 2 | Analyzer: `on_frame(ts, tracks, frame_w, frame_h) -> list[partial]`; registry `ANALYZERS`; titik kaki `ground_point`. | `vision/vision/analyzers/base.py`, `__init__.py`, `intrusion.py` |
| 3 | Motion gate melewatkan inferensi saat sepi; frame paksa tiap `force_interval_s` (default 2 s) tetap memanggil analyzer. | `vision/vision/node.py` `CameraWorker.run` |
| 4 | Jadwal zona `{days, start, end}` hanya dipakai intrusion (`_schedule_active`). | `intrusion.py` |
| 5 | **Bug**: frame live membawa `ts` **monotonic** (`pipeline/source.py`, `_latest` = `time.monotonic()`), tetapi `_schedule_active` memakai `datetime.fromtimestamp(ts)` → hari/jam dihitung dari 1970 + uptime → jadwal intrusion salah di produksi. Tes lama lolos karena memakai ts wall-clock. Server saat ini tanpa zona berjadwal (belum berdampak). | `intrusion.py:_schedule_active` |
| 6 | Shift: `start_time`, `end_time` (`HH:MM`), `workdays` (ISO 1–7) — setara `{start, end, days}`. Hapus shift → 409 bila dipakai karyawan. | `models/shift.py`, `api/shifts.py:56` |
| 7 | Toggle Snapshot/Clip/Telegram per behavior, caption `TYPE_TITLE`, rate-limit per (kamera, zona, tipe, track) sudah generik. | `ZonesPage.tsx`, `services/telegram.py`, `alerting.py` |

## 2. Keputusan user

| # | Keputusan |
|---|---|
| K1 | Scope: **Idle Zone** + **Crowd**. |
| K2 | Kondisi berkelanjutan: **alert pertama + pengingat berkala** tiap `reminder_minutes` (per behavior; 0 = tanpa pengingat); siaga lagi setelah kondisi pulih. |
| K3 | Jadwal zona bisa **ikut satu Shift** (`{"shift_id": N}`), selain 24/7 dan jam manual. |
| K4 | Dua analyzer terpisah + helper bersama (bukan satu analyzer multi-mode). |

## 3. Desain

### 3.1 Vision

**Helper bersama** (`vision/vision/analyzers/base.py`):
- `wall_time(ts) -> float`: ts monotonic (< 1_700_000_000) → `ts + (time.time() - time.monotonic())`; ts wall-clock dikembalikan apa adanya. `node._iso` memakai helper ini (perilaku sama).
- `schedule_active(schedule, ts) -> bool`: pindahan `_schedule_active` dari `intrusion.py`, memakai `wall_time(ts)` (**fix bug #5**). Tanpa jadwal → True. Jadwal tetap `start <= HH:MM <= end` (tanpa lintas tengah malam — sama dengan Shift saat ini).
- `persons_in_zone(tracks, polygon, frame_w, frame_h) -> list[track]`: track yang `ground_point`-nya di dalam poligon (sama dengan intrusion).

**`IdleZoneAnalyzer`** (`analyzers/idle_zone.py`, `kind: "idle_zone"`):
- Parameter: `trigger_seconds` (kosong minimal, default 300), `reminder_minutes` (default 15, 0 = off), `schedule` zona.
- Di luar jadwal: state di-reset (timer kosong tidak berjalan, tidak alert).
- Dalam jadwal: `empty_since` = ts pertama zona kosong (atau ts start worker bila sudah kosong). Orang masuk → reset + siaga.
- Kosong ≥ `trigger_seconds` → event `idle_zone` (`reminder: 0`); selama tetap kosong, event lagi tiap `reminder_minutes` (`reminder: 1, 2, …`).
- Payload: `{"idle_s": int, "reminder": int, "zone_polygon": [[x,y],…]}` (tanpa `track_id`).

**`CrowdAnalyzer`** (`analyzers/crowd.py`, `kind: "crowd"`):
- Parameter: `min_count` (≥ 1, default 5), `trigger_seconds` (default 30), `reminder_minutes` (default 15, 0 = off), `schedule` zona.
- Jumlah = `len(persons_in_zone(...))`. `crowd_since` = ts pertama jumlah ≥ `min_count`. Jumlah turun di bawah ambang **≤ 2 s** (track berkedip/oklusi) tidak me-reset; > 2 s → reset + siaga.
- Jumlah ≥ `min_count` selama ≥ `trigger_seconds` → event `crowd` (`reminder: 0`), lalu pengingat tiap `reminder_minutes`.
- Payload: `{"count": int, "min_count": int, "duration_s": int, "reminder": int, "bboxes": [[x1,y1,x2,y2],…]}`.

**Wiring** (`node._make_analyzers`): kind `idle_zone` → `IdleZoneAnalyzer(spec)`, `crowd` → `CrowdAnalyzer(spec)` dengan media per behavior yang sudah ada. `IntrusionAnalyzer` memakai `schedule_active` dari `base.py`.

**Snapshot** (`recorder._draw_track_box` diperluas; `TYPE_LABEL` + `IDLE_ZONE`, `CROWD`):
- `payload.bboxes` → gambar semua kotak, label `CROWD (n)` di kotak pertama.
- `payload.zone_polygon` → gambar garis poligon zona + label `IDLE ZONE` di titik pertama.
- selain itu → perilaku sekarang (satu `bbox_norm`).

### 3.2 Backend

- `schemas/zone.py`: `VALID_BEHAVIOR_KINDS` + `idle_zone`, `crowd`. Validator item: `min_count` int ≥ 1 (**wajib** untuk `crowd`), `reminder_minutes` int ≥ 0 (opsional).
- **Jadwal ikut shift**: `_validate_schedule` menerima `{"days","start","end"}` **atau** `{"shift_id": int}`. Create/patch zona dengan `shift_id` yang tidak ada → 422.
- `services/config_push.py`: sebelum mengirim, `schedule` berbentuk `{"shift_id": N}` di-resolve ke `{"days": shift.workdays, "start": shift.start_time, "end": shift.end_time}`; shift hilang → `schedule: null` + log warning (tidak mematikan zona diam-diam — tercatat).
- `api/shifts.py`: PATCH shift → config push ulang untuk kamera yang punya zona dengan `schedule.shift_id == id` (filter di Python atas zona); DELETE → 409 `"shift in use by zones: <nama zona>, …"` bila dipakai zona (selain cek karyawan yang sudah ada).
- `services/telegram.py`: `TYPE_TITLE` + `"idle_zone": "IDLE ZONE"`, `"crowd": "CROWD"`; baris tambahan: idle → `<b>Kosong</b>: 12 menit`; crowd → `<b>Jumlah</b>: 7 orang (min 5)`; `reminder > 0` → judul diberi `(pengingat ke-n)`.
- Rate-limit: event tanpa `track_id` → kunci per zona+tipe (perilaku yang ada); warning 2 menit < interval pengingat → tidak bentrok.
- Tanpa migrasi DB.

### 3.3 Frontend

- **Zona Deteksi** — dua baris behavior baru (toggle Snapshot/Clip/Telegram seperti yang lain):
  - `Zona kosong (Idle)`: "Kosong selama (detik)" = `trigger_seconds` (default 300), "Pengingat tiap (menit, 0 = tidak)" = `reminder_minutes` (default 15). Clip **default off** saat dicentang.
  - `Kerumunan (Crowd)`: "Minimal orang" = `min_count` (default 5), "Selama (detik)" = `trigger_seconds` (default 30), "Pengingat tiap (menit)" (default 15).
  - Jadwal: `24/7 · Jam tertentu · Ikut shift [dropdown shift]`; shift dimuat dari `/api/v1/shifts`.
- Inbox, Status AI, deep-link: tidak berubah (tipe baru tampil generik; label i18n untuk `idle_zone`/`crowd` ditambahkan bila Inbox memetakan label tipe).
- i18n `id` + `en`.

## 4. Penanganan error

| Kondisi | Perilaku |
|---|---|
| Crowd tanpa `min_count` / `min_count < 1` | 422 |
| `schedule.shift_id` tidak ada | 422 saat simpan; saat push (shift terhapus di luar API) → `schedule: null` + warning |
| Hapus shift yang dipakai zona | 409 dengan nama zona |
| Node restart saat zona kosong | timer mulai dari start worker → alert setelah `trigger_seconds` bila tetap kosong |
| Track berkedip ≤ 2 s (crowd) | tidak me-reset |
| Motion gate aktif (sepi) | evaluasi lewat frame paksa (`force_interval_s`), akurasi ±2 s |

## 5. Pengujian

- Vision (`vision/tests/`): `wall_time` (monotonic vs wall), `schedule_active` dengan ts **monotonic** (regresi bug #5), Idle (timer, reset saat orang masuk, di luar jadwal, pengingat berjarak `reminder_minutes`, reminder 0 = sekali), Crowd (ambang, toleransi 2 s, reset > 2 s, pengingat, bboxes), wiring `_make_analyzers`, gambar snapshot (poligon + label, banyak kotak + label jumlah).
- Backend: validator kinds + `min_count`/`reminder_minutes`, schedule `shift_id` (valid / tidak ada → 422), resolve di config push, PATCH shift → push, DELETE shift dipakai zona → 409, caption idle/crowd + pengingat.
- Frontend: baris Idle/Crowd + default, clip idle off, jadwal ikut shift, 390 px.
- Baseline `main` `b9fdc55`: backend 423, vision 205 (3 deselected), frontend 140, build 0, lint set sama.

## 6. Verifikasi lapangan (butuh izin user)

Deploy (restart API + vision-node). Zona uji: Idle `trigger_seconds=60`, pengingat 2 menit, jadwal ikut shift aktif → kosongkan zona → alert ±60 s, pengingat 2 menit kemudian, orang masuk → siaga. Crowd `min_count=2`, 10 s → dua orang berdiri → alert; satu keluar → siaga. Telegram: judul `IDLE ZONE`/`CROWD`, baris jumlah/kosong, `(pengingat ke-1)`. Intrusion berjadwal kini mengikuti jam lokal yang benar.

## 7. Di luar scope

Lone worker, Line crossing/arah terlarang, Man-down, APD/forklift/api, jadwal multi-shift atau lintas tengah malam, heatmap/analitik okupansi.

## 8. Rollback

`git revert` + restart API dan vision-node. Tanpa migrasi DB. Zona dengan behavior `idle_zone`/`crowd` atau `schedule.shift_id`
perlu dihapus/diubah dulu (kode lama menolak kind/format itu).
