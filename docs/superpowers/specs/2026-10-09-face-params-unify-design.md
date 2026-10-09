# Spec — Keselarasan dan pemusatan parameter pengenalan wajah

Status: **Draft, desain disetujui di chat 2026-10-09**, menunggu review spec tertulis.
Branch: `feat/face-params-unify` (dari `main`, merge `feat/intrusion-face-progressive`).
Konteks: `docs/superpowers/specs/2026-10-08-intrusion-face-id-design.md`, `docs/superpowers/specs/2026-10-07-face-gate-refine-design.md`, `docs/runbooks/intrusion-face-id.md`, `docs/runbooks/attendance.md`.

---

## 1. Latar

Parameter pengenalan wajah tersebar di empat tempat dan dua algoritma memperlakukan wajah yang sama dengan angka berbeda.

| Tempat | Isi | Cara ubah |
|---|---|---|
| DB `detector_setting` (tab Deteksi & Model) | lebar 80, skor 0,6, yaw 0,35, blur 120, min frame 3 | UI, dipush ke node |
| Env API `Settings` | `face_match_threshold` 0,40, `face_min_quality` 0,5, `face_dup_warn` 0,6, `attendance_cooldown_min` 5 | env + recreate; compose tidak meneruskannya |
| Env API + compose | `FACE_ID_THRESHOLD` / `FACE_ID_MARGIN` (repo 0,50 / 0,10; server `.env` 0,35 / 0,15) | `docker/.env` + recreate `api` |
| Konstanta kode `vision/vision/intrusion_face.py` | lebar 60, pitch 0,30, K=5, jendela 8 dtk, pembaruan 10 dtk, maks 6 pembaruan, lacak 90 dtk | ubah kode + deploy |

Bukti bahwa algoritma intrusion (tanpa gerbang blur/quality absolut, peringkat relatif `det × ketajaman`, 5 terbaik, lebar ≥ 60 px, aturan margin top-2) lebih baik (`CHANGELOG.md`, entri face ID 2026-10-08):
- Kamera 357 pada 1080p: tidak ada frame yang lolos gerbang absensi lama (lebar ≥ 80, blur ≥ 120); tanpa gerbang blur karyawan 0,427–0,483 (margin 0,26–0,29), non-karyawan 0,243 (margin 0,01).
- Kamera 357 pada 2K: lima percobaan, semua karyawan `recognized` (skor 0,444–0,639; margin ≥ 0,25), non-karyawan `unknown` (0,222).
- Variansi Laplacian bergantung pada ukuran wajah asli dan kamera, sehingga gerbang blur absolut menolak wajah yang justru skornya baik.

**Belum terbukti:** algoritma ini di jalur absensi (cepat ≤ 2 dtk, pintu, tanpa jendela 8 dtk), tingkat salah-orang (baru dua non-karyawan), dan karyawan mirip (`ambiguous`).

## 2. Keputusan user

| Topik | Keputusan |
|---|---|
| Cakupan | Pusatkan parameter, lalu samakan algoritma absensi, bertahap (saklar `legacy`/`unified`) |
| Kecepatan absensi | Tetap ≤ 2 detik |
| Ambang bersama | 0,40, margin 0,15 |
| Urutan | Merge branch intrusion ke `main` dulu (selesai, main di-push); keselarasan dari branch baru |

## 3. Tujuan, kriteria sukses, non-tujuan

**Kriteria sukses** (diuji):
1. Semua parameter pengenalan wajah yang memengaruhi akurasi dapat dilihat dan diubah di satu kartu UI "Pengenalan wajah" tanpa deploy, tanpa env, tanpa kode.
2. Node dan API membaca parameter dari baris `detector_setting` yang sama; env hanya cadangan saat baris tidak ada.
3. Tahap 1 tidak mengubah keputusan absensi untuk masukan yang sama (diuji dengan masukan identik sebelum dan sesudah).
4. Perubahan nilai di UI berlaku di node setelah config push dan di API pada event berikutnya, tanpa restart.
5. Tahap 2: mode `unified` mengenali ≥ 95% karyawan dalam median ≤ 2 dtk (p95 ≤ 3 dtk; diukur dari `face_stats.zone_s`: wajah pertama di zona sampai event dikirim), 0 salah-orang, 0 non-karyawan tercatat (bukti di §7).

**Non-tujuan:** foto enrollment (`face_min_quality`, `face_dup_warn`), `attendance_cooldown_min`, interval pembaruan / maks pembaruan / batas lacak / `UNVERIFIED_AFTER_S` (batas operasional, tetap konstanta kode), deteksi wajah pada ROI kepala, hardening GPU container, Jetson.

## 4. Desain tahap 1 — pemusatan (perilaku absensi tidak berubah)

**DB (`0024_face_policy`)**, kolom baru di `detector_setting` (semua `NOT NULL` dengan `server_default`):

| Kolom | Nilai awal | Dipakai oleh |
|---|---|---|
| `face_match_threshold` | 0,40 | absensi dan intrusion (menggantikan env `face_match_threshold` dan `FACE_ID_THRESHOLD`) |
| `face_match_margin` | 0,15 | intrusion (menggantikan `FACE_ID_MARGIN`) |
| `face_max_pitch` | 0,30 | intrusion (konstanta `MAX_PITCH`) |
| `face_best_k` | 5 | intrusion (`BEST_K`) |
| `face_ident_min_width_px` | 60 | intrusion (`IDENT_MIN_WIDTH_PX`) |
| `face_ident_window_s` | 8 | intrusion (`IDENT_WINDOW_S`) |

`face_min_det_score` dan `face_max_yaw` yang sudah ada tetap dipakai bersama oleh absensi dan intrusion (seperti sekarang). `face_min_width_px`, `face_blur_min`, `face_min_frames` tetap milik absensi lama.

**Backend:**
- `backend/app/services/face_policy.py` (baru): dataclass beku `FacePolicy(match_threshold, match_margin)` dan `load(db) -> FacePolicy` yang membaca baris `id=1`; bila baris tidak ada, nilai dari `Settings` (env). `Settings` memberi nilai awal `face_match_threshold = 0.40` dan `face_id_margin = 0.15`; `face_id_threshold` dihapus.
- `FaceGallery.match(vector, threshold)`, `match_vector(vector, quality, policy)`, `match_strict(vector, quality, policy)` dan `match_crop(db, path)` memakai ambang dari `policy`; parameter `policy` opsional (bawaan: dari `Settings`) agar pemanggil lama dan tes tidak pecah. `handle_face_event` dan `intrusion_face._identify_with_name` memanggil `face_policy.load(db)`.
- `schemas/detector_setting.py`, `api/detector_settings.py` (`_effective`, `PUT`), `config_push.py` menambah kolom baru. Blok `face` di config push mendapat sub-blok `ident: {min_width_px, max_pitch, best_k, window_s}`.
- Validasi: `match_threshold` 0,1–0,99, `match_margin` 0–0,5, `max_pitch` 0,05–1, `best_k` 1–10, `ident_min_width_px` 16–1000, `ident_window_s` 1–10 (jendela + unggah crop ≤ 6 dtk + antrean MQTT harus muat di bawah `UNVERIFIED_AFTER_S` = 20 dtk; dengan 15 dtk status `unverified` bisa mendahului hasil nyata. Batas awal 1–15 dikoreksi saat review 2026-10-09).
- `docker/compose.yml` dan `.env.example`: `FACE_ID_THRESHOLD` dihapus; `FACE_ID_MARGIN` dan `FACE_MATCH_THRESHOLD` ditandai sebagai cadangan.

**Vision:**
- `vision/vision/face_quality.py`: dataclass beku `IdentSettings(min_width_px=60.0, max_pitch=0.30, best_k=5, window_s=8.0)` dengan `from_config(ident: dict | None)` (key hilang memakai nilai awal), tertanam sebagai `FaceSettings.ident` dan dibaca `FaceSettings.from_config` dari `face["ident"]`. Nilai awalnya adalah konstanta `IDENT_MIN_WIDTH_PX`, `MAX_PITCH`, `BEST_K`, `IDENT_WINDOW_S` yang dipindah ke `face_quality.py` dan tetap dapat diimpor dari `vision.intrusion_face`. `IdentCollector` membaca `settings.ident` (parameter `settings: FaceSettings` yang sudah diterimanya).
- Muat ulang worker sudah tercakup: `Node.apply_config` membandingkan `FaceSettings` lama dan baru (`node.py:445-448`) dan merestart worker wajah kamera terkait bila berbeda; karena `ident` bagian dari `FaceSettings`, perubahan nilai identitas ikut terdeteksi tanpa kode tambahan.

**Frontend (`DetectionPage.tsx`, `api/detection.ts`, `i18n.tsx`):** kartu "Pengenalan wajah" dengan tiga grup: **Bersama** (skor deteksi, yaw, ambang kecocokan), **Identitas** (lebar min identitas, pitch, K, margin, jendela), **Absensi (lama)** (lebar, blur, jumlah frame). Teks lewat i18n (`id` dan `en`). Tanpa CSS baru selain token Carbon yang ada; 390 px tanpa overflow.

**Migrasi nilai server:** `docker/.env` server memakai 0,35 / 0,15; setelah migrasi nilai DB 0,40 / 0,15 berlaku (data terukur: karyawan agregat terendah 0,444). Perubahan nilai ini sah dan bisa diubah di UI.

## 5. Desain tahap 2 — keselarasan absensi (saklar)

Migrasi `0025`: `face_attendance_mode` (`'legacy'` | `'unified'`, awal `legacy`) dan `face_attendance_window_s` (awal **1,5**, rentang 0,5–3,0; koreksi dari 2,0 agar `zone_s` median ≤ 2 dtk masih tercapai).

**Node (`FaceGateWorker`, mode `unified`):**
- Gerbang per wajah: di dalam poligon zona (tetap), lebar ≥ `face_ident_min_width_px`, skor ≥ `face_min_det_score`, yaw ≤ `face_max_yaw`, pitch ≤ `face_max_pitch`. Tanpa gerbang blur absolut.
- Per track: simpan `face_best_k` kandidat terbaik berperingkat `det × ketajaman` (logika peringkat yang sama dengan `IdentCollector`, dipakai bersama, bukan salinan).
- Kirim event pada yang lebih dulu: `face_attendance_window_s` berlalu sejak kandidat pertama, atau track hilang dengan ≥ 1 kandidat. **K kandidat terkumpul tidak memicu pengiriman** (koreksi 2026-10-09 atas rancangan awal): itu akan mengambil K frame pertama dan meniadakan pemilihan frame terbaik; pelajaran siklus intrusion ialah jendela pengamatan yang terlalu pendek merugikan. Embedding = `aggregate` berbobot (sama seperti sekarang). Payload mendapat `policy: "unified"` (tanpa field = `legacy`) dan `face_stats.collect_s` (kandidat pertama → kirim) serta `face_stats.zone_s` (wajah pertama di zona → kirim, dasar ukuran kecepatan).

**API:** event dengan `policy == "unified"` dicocokkan lewat `match_strict(embedding, None, policy)` (ambang + margin, tanpa gerbang `low_quality`); `ambiguous` diperlakukan seperti `no_match` (tidak tercatat, `match_reason="ambiguous"`, label snapshot "Unknown", UI menampilkannya sebagai tidak dikenal); `payload.face_margin` disimpan untuk pemantauan. Event `legacy` tetap lewat `match_vector`. Memilih berdasarkan payload event menjamin keputusan konsisten per event walau saklar dibalik saat event di perjalanan. Jalur crop-saja (`match_crop`) tidak berubah.

**UI:** saklar `face_attendance_mode` dan jendela absensi di kartu yang sama. Grup "Absensi (lama)" hanya berlaku di mode `legacy`; dihapus pada siklus pembersihan terpisah setelah `unified` stabil.

## 6. Tes

Mengikuti berkas yang ada. Tiap tes harus gagal pada bug yang masuk akal; rincian di plan.
- Backend: `test_face_policy.py` (baris DB menimpa env; baris tidak ada memakai env; vektor cosine 0,38 cocok di ambang 0,35 dan tidak di 0,40; margin dari DB), `test_detector_settings_api.py` (kolom baru bulat-balik, batas validasi), `test_config_push` (blok `face.ident`), `test_intrusion_face_api.py` dan `test_attendance_api.py` (keputusan tidak berubah pada tahap 1; tahap 2: event `unified` dengan top-2 berselisih < margin → `ambiguous` tanpa catatan).
- Vision: `IdentSettings.from_config` (nilai awal saat key hilang, nilai dipakai oleh kolektor: K, lebar, pitch, jendela), tahap 2: worker `unified` mengirim pada K kandidat / jendela / track hilang dan tidak pernah dua kali per track.
- Frontend: `detection.test.tsx` — nilai kartu terkirim di `PUT`, grup tampil, label i18n `id`/`en`.
- Tahap 1 menjalankan suite penuh berurutan (backend `-m "not gpu"`, vision, vitest, `npm run build`, lint).

## 7. Bukti tahap 2 sebelum saklar dibalik ke `unified`

1. **Replay offline** (di `api` container, `nice -n 19 taskset -c 0-3`, satu klip/crop per proses, diumumkan dulu ke user — lihat memori `limit-cpu-for-server-diagnostics`): crop event absensi ≥ 14 hari terakhir. Syarat: ≥ 98% crop yang dikenali `legacy` tetap ke karyawan yang sama di 0,40 / 0,15; 0 berpindah ke karyawan lain; daftar `ambiguous` dan pasangan karyawannya dilaporkan; crop `no_match` lama yang kini cocok dilaporkan untuk dinilai manual. Replay hanya menguji aturan ambang/margin pada satu crop, bukan waktu jendela.
2. **Uji lapangan** di kamera profil C (2K, 15 fps, Max. 8192 kbps). Angka dilaporkan per kategori, karena satu angka gabungan menyembunyikan batas fisik:
   - **A. Berjalan normal menuju kamera, tanpa berhenti** (kategori penentu): ≥ 5 karyawan × 10 lintasan → ≥ 95% tercatat, median ≤ 2 dtk, p95 ≤ 3 dtk, 0 salah-orang.
   - **B. Berhenti sebentar di titik absensi**: kriteria sama dengan A.
   - **C. Menyamping atau menunduk (melihat ponsel)**: 5 lintasan per karyawan; hasil dicatat sebagai batas sistem (bukan kegagalan) dan dipakai untuk saran penempatan kamera. Syarat tetap: 0 salah-orang.
   - **D. Non-karyawan**: ≥ 10 lintasan (≥ 3 orang), berjalan dan berhenti → 0 tercatat.
3. Hasil ditempel di `CHANGELOG.md` dan `ROADMAP.md`; keputusan balik saklar ada di tangan user.
4. **Pemantauan setelah `unified`:** runbook memuat query siap pakai untuk distribusi `match_score` dan rasio `match_reason` (`matched`, `no_match`, `ambiguous`) per kamera per hari dari tabel event; tanpa fitur atau tabel baru. Ambang dan galeri diuji ulang bila jumlah karyawan terdaftar berlipat.

## 8. Risiko dan rollback

| Risiko | Mitigasi |
|---|---|
| Ambang intrusion naik 0,35 → 0,40; kelonggaran genuine hanya 0,044 (agregat terendah 0,444) dan baru dua non-karyawan teruji | Dapat diubah di UI tanpa deploy; baris `IFI` di ROADMAP tetap `[~]` sampai ≥ 3 non-karyawan teruji (kategori D di §7) |
| Margin menolak karyawan kembar/mirip (`ambiguous`) → absensi terlewat | Daftar `ambiguous` di replay; koreksi admin tetap tersedia; saklar `legacy` |
| Ketidaksesuaian versi: node baru dengan backend lama (atau sebaliknya) | Key hilang memakai nilai awal di kedua sisi; kontrak diuji |
| Row `detector_setting` belum ada di instalasi baru | Fallback ke `Settings`, diuji |
| Replay tidak menguji waktu jendela | Uji lapangan §7.2 wajib |

**Rollback:** tahap 1 — `git revert` merge dan `alembic downgrade -1` (kolom dihapus; nilai env kembali jadi sumber); tahap 2 — balik `face_attendance_mode` ke `legacy` di UI (instan, tanpa deploy).

## 9. Dokumen

`ARCHITECTURE.md` (kontrak blok `face` dan `FacePolicy`), `WORKFLOW.md` (alur absensi dan identitas), `README.md`, `docs/runbooks/intrusion-face-id.md` dan `docs/runbooks/attendance.md` (letak parameter, cara tuning), `.env.example`, `ROADMAP.md` (baris baru `FPU`), `CHANGELOG.md` per commit.
