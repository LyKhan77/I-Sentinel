# Spec — Zona UX: satu tempat untuk aturan deteksi

Status: **DISETUJUI di chat (2026-09-25)**, menunggu review spec tertulis.
Branch: `feat/zone-config-ux` (dari `main` @ `2ddd209`).
Checkpoint: `.cooper/context/next-features.md`.
Asal: arah disepakati di `docs/superpowers/specs/2026-09-24-event-clip-prebuffer-design.md` §10, direvisi di chat.

---

## 1. Latar

Permintaan user: *"perlu adjustment flow UX pada Detection Zones agar tidak redundan … ada 2 fungsi, halaman
Detection Zones untuk mengaktifkan zona, halaman Detection & Model untuk mengaktifkan analyzers … saya bingung"*,
ditambah *"detector behavior juga memiliki opsi untuk activate/deactivate Snapshot dan Clip"* dan *"apakah akan lebih
murah jika halaman Attendance Gates yang dihapus? … semua konfigurasi zona berada di satu halaman Detection Zones"*.

### Kondisi kode (`main` @ `2ddd209`)

Sebuah behavior hanya jalan bila **empat** saklar ON: kamera `enabled` · chip analyzer kamera
(`camera.analyzers`, *mask* di `vision/vision/node.py` `_make_analyzers`) · behavior dicentang di zona · zona
`active` (diatur di Zona Deteksi **dan** Gate Absensi).

| # | Temuan | Lokasi |
|---|---|---|
| 1 | Mask `camera.analyzers` membuat behavior zona mati tanpa peringatan. | `node.py` `_make_analyzers` |
| 2 | Kamera tanpa zona tetap menjalankan YOLO (overlay live saja) — GPU terpakai tanpa event. | `node.py` `_start_workers` (`if analyzers or not gates`) |
| 3 | Snapshot/Clip hanya per zona, berlaku untuk semua behavior di zona itu. | `node.py` `_make_analyzers` (`media`) |
| 4 | Gate Absensi: kolom SNAPSHOT **dan** CLIP no-op — `FaceGateWorker` selalu unggah crop+snapshot (`face_worker.py:243`) dan `clip_path: None` (`:284`). | `GatesPage.tsx` |
| 5 | Gate Absensi hanya daftar + pintasan; menggambar/mengedit zona attendance sudah ada di Zona Deteksi (tipe attendance/behavior `ZonesPage.tsx:155/282`, arah `:302`). | `GatesPage.tsx` `addGate` → `navigate('/configuration?tab=zones')` |
| 6 | Validasi konflik arah (satu kamera, arah berbeda) hanya peringatan di Gates, tidak di backend. | `GatesPage.tsx:86-95`, `api/zones.py` |
| 7 | Kartu tracker "buffer 30 frame" basi; sejak R5b track dilepas setelah `max_age_s = 3.0`. | `DetectionPage.tsx`, `vision/vision/pipeline/tracker.py:31` |

### Data server (gspe-ai3, 2026-09-25, baca-saja)

- Zona 15 cam 363 (Lorong Server) **aktif** intrusion, chip kamera `['attendance']` → intrusion ter-mask (terulang).
- Cam 358, 362, 366 tanpa zona, `analyzers = null` → YOLO jalan untuk overlay saja.
- Zona attendance 12 (cam 364, masuk) dan 14 (cam 365, keluar) nonaktif; zona 6 cam 357 nonaktif.

## 2. Keputusan user

| # | Keputusan |
|---|---|
| K1 | **Zona aktif = AI aktif** (pendekatan A): chip analyzer kamera dihapus; deteksi hanya di kamera dengan ≥ 1 zona aktif; tanpa zona = live view saja. |
| K2 | **Snapshot/Clip per behavior** (bukan per zona). |
| K3 | **Halaman Gate Absensi dihapus**; semua zona (behavior + absensi) di **Zona Deteksi**. |
| K4 | Validasi konflik arah absensi pindah ke **backend** (422). |
| K5 | **Deteksi & Model = parameter model saja**: tanpa chip, + kolom **Status AI** hanya-baca, + kartu model wajah, teks tracker diperbaiki. |
| K6 | Pipeline wajah R5b (FaceGateWorker, crop+snapshot selalu, tanpa clip) tidak diubah. |

Pembagian akhir: **Kamera** = sumber stream · **Zona Deteksi** = aturan (apa, di mana, kapan, media) ·
**Deteksi & Model** = parameter model.

## 3. Desain

### 3.1 Vision (`vision/vision/node.py`)

- `_make_analyzers`: hapus mask `if cam.analyzers is not None and kind not in cam.analyzers: continue`.
  Media per behavior: `{"snapshot": b.get("snapshot", z.get("snapshot", True)), "clip": b.get("clip",
  z.get("clip", True))}` — zona lama (tanpa key per behavior) berperilaku sama.
- `_start_workers`: `CameraWorker` dibuat **hanya** bila `analyzers` tidak kosong **atau**
  `cfg.emit_person_detect`; `FaceGateWorker` bila ada gate aktif dan `self.face` tersedia (tetap). Kamera tanpa
  keduanya → **tidak ada worker, stream tidak dibuka, recorder/ring tidak dibuat**.
- `CameraCfg.analyzers` dibiarkan (diabaikan) agar config push lama tetap ter-parse; komentar "deprecated".
- Ring clip: tetap `_wants_clip(analyzers)` (sudah membaca `media["clip"]`).

### 3.2 Backend

- `schemas/zone.py` `_validate_behaviors`: item boleh memuat `snapshot` dan `clip` (opsional, wajib `bool` bila
  ada); key lain tetap seperti sekarang.
- `api/zones.py` `create_zone` + `update_zone`: setelah nilai gabungan terbentuk, bila zona attendance **aktif**,
  tolak 422 `"camera already has an active attendance zone with another direction"` jika ada zona attendance
  aktif lain di kamera yang sama dengan `direction` berbeda. Zona dengan arah sama boleh lebih dari satu (sama
  dengan perilaku Gates sekarang: konflik = set arah > 1).
- `services/config_push.py`: berhenti mengirim `analyzers` (baris 88).
- `models/camera.py` `analyzers`: kolom dibiarkan, komentar deprecated. **Tanpa migrasi**; API kamera tetap
  menerima/mengembalikan field ini (kompatibel) tetapi tidak ada yang membacanya.

### 3.3 Frontend

**Konfigurasi (`ConfigurationPage.tsx`)**: tab `gates` dihapus → Kamera · Zona Deteksi · Deteksi & Model ·
Penyimpanan · Node. URL lama `?tab=gates` jatuh ke tab default (perilaku `TABS` yang ada).

**Zona Deteksi (`ZonesPage.tsx`)**
- Pilihan tipe **Behavior / Absensi** tetap.
- Toggle `zone-snapshot` / `zone-clip` level zona **dihapus**.
- Zona Behavior: baris per behavior — checkbox aktif, parameter (trigger / batas kecepatan), toggle **Snapshot**
  dan **Clip** (nonaktif bila behavior tidak dicentang). Default saat dicentang: nilai `zone.snapshot/clip`
  (true untuk zona baru). Disimpan sebagai key `snapshot`/`clip` di item `behaviors`.
- Zona Absensi: Arah (Masuk/Keluar), petunjuk area wajah (`zones.attendanceHint`), Aktif — tanpa Snapshot/Clip.
- Daftar zona per kamera: badge tipe (Behavior / Absensi) + status aktif.
- 422 konflik arah → pesan inline "Kamera ini sudah punya zona absensi aktif dengan arah lain."
- Label `zones.sub` diperbarui: zona behavior dan absensi per kamera.

**Gate Absensi**: `GatesPage.tsx`, `__tests__/gates.test.tsx`, dan key i18n `gates.*` yang tidak lagi dipakai
dihapus.

**Deteksi & Model (`DetectionPage.tsx`)**
- Kartu: Model orang (YOLO26s · TensorRT FP16 · 640px), FPS default, Confidence default, Tracker (ByteTrack ·
  "lepas track setelah 3 s"), **Model wajah (InsightFace buffalo_l)**.
- Tabel per kamera: Kamera · AI FPS · Confidence · **Status AI** · Reset. Kolom chip analyzer dihapus; Reset tidak
  lagi mengirim `analyzers`.
- **Status AI** (hanya baca, dari `listZones()`): "Aktif · N zona" bila kamera punya N zona aktif (behavior +
  absensi), selain itu "Tidak jalan (tanpa zona aktif)". Kamera `enabled=false` → "Kamera nonaktif".
- Hint: "Deteksi hanya berjalan di kamera yang punya zona aktif. Atur zona di tab Zona Deteksi."
- Bagian motion gate dan setelan wajah absensi tetap.

## 4. Penanganan error

| Kondisi | Perilaku |
|---|---|
| Item behavior dengan `snapshot`/`clip` bukan bool | 422 dari validator |
| Konflik arah absensi aktif | 422 + pesan inline di form zona |
| Node lama menerima config tanpa `analyzers` | `CameraCfg.analyzers` default `None` → aman |
| Kamera tanpa zona aktif | tanpa worker; Live View tetap lewat go2rtc; overlay deteksi kosong |

## 5. Pengujian

- Vision (`vision/tests/test_config_apply.py` / `test_node.py`): kamera tanpa zona aktif → tidak ada worker
  dan `source_factory` tidak dipanggil; kamera dengan `analyzers=['attendance']` + zona intrusion aktif → analyzer
  intrusion tetap dibuat (mask tidak berlaku); media per behavior (snapshot off pada loitering, clip off pada
  intrusion) terbawa ke event; fallback ke flag zona bila key per behavior tidak ada.
- Backend: validator behaviors (bool OK, non-bool 422); konflik arah → 422 pada create dan patch (termasuk
  mengaktifkan zona yang tadinya nonaktif); arah sama → OK; zona nonaktif tidak dihitung; config push tanpa
  `analyzers`.
- Frontend: Zona Deteksi (baris behavior + toggle, simpan mengirim key per behavior, zona absensi tanpa
  Snapshot/Clip, pesan konflik), Konfigurasi tanpa tab Gate, Deteksi & Model (tanpa chip, Status AI dari zona,
  kartu wajah, teks tracker). 390 px tanpa overflow.
- Baseline `main` `2ddd209`: backend 363, vision 200 (3 deselected), frontend 129, build 0, lint set sama.

## 6. Verifikasi lapangan (butuh izin user)

Deploy (API + vision-node restart, frontend Vite otomatis). Cek: `vision-node` log "started N worker(s)" turun
(kamera tanpa zona tidak lagi punya worker), `nvidia-smi`/CPU sebelum-sesudah; zona 15 cam 363 menghasilkan event
intrusion tanpa menyentuh chip; toggle Clip off pada satu behavior → event tanpa clip; tab Gate hilang.

## 7. Di luar scope

Telegram per behavior (masih placeholder); migrasi drop kolom `camera.analyzers`; perubahan pipeline wajah;
tabel ringkasan gate lintas kamera; User management; Retention UI.

## 8. Rollback

`git revert` + restart API dan vision-node. Tanpa migrasi DB. Key `snapshot`/`clip` per behavior yang sudah
tersimpan diabaikan oleh kode lama (flag zona dipakai). Kamera dengan chip lama kembali ter-mask setelah revert.
