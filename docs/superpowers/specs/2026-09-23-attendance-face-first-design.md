# Spec — R5b Attendance face-first

Status: **DISETUJUI per bagian di chat (2026-09-23)**, menunggu review spec tertulis.
Branch: `feat/attendance-face-first` (dari `feat/detection-model` @ `613f3a2`).
Induk: `docs/superpowers/specs/2026-09-22-detection-model-redesign.md` §3.3 dan §4 no.5
(attendance face-first di substream, tanpa person tracking, tanpa clip, `unknown` tetap
terbit). Spec ini **mengubah satu hal** dari induknya: stream attendance = **main stream
1080p**, bukan substream (bukti di §1).
Referensi: Frigate `/Users/leekhan/project/frigate` @ `af0ba1919`.

---

## 1. Latar dan bukti (tes user 2026-09-23)

User masuk ke zona 9 cam 363 sambil memantau debugger. Hasil: overlay sangat lambat,
dan seluruh event attendance hari itu `match_reason: no_face` (2 di cam 363, 6 di
cam 364), `attendance_event` kosong. Diukur, bukan diduga:

| # | Temuan | Bukti | Status |
|---|---|---|---|
| 1 | `FrameSource` membaca 1 frame per `1/ai_fps` dari stream lebih cepat → antrean basi | cam 363 (15 fps dibaca 5 fps): lag +19,8 s setelah 30 s, terus naik | **Diperbaiki** `ddf8599` (reader thread frame-terbaru); selisih konstan 30 s di stream nyata |
| 2 | Pin `cuda:2` model wajah tak berlaku (insightface abaikan `ctx_id ≥ 0`) | proses vision memakai GPU 0 (RTX 4090 bersama vLLM) | **Diperbaiki** `7127f94` (`device_id` di provider) |
| 3 | Wajah hanya terlihat bila orang berjalan **menuju** kamera | snapshot event 4678: user terlihat dari belakang saat kaki masuk zona 9 | desain (§3.1) |
| 4 | Wajah di substream terlalu kecil | kepala ~45 px di 640×480 → wajah ~35 px; rekomendasi identifikasi ≥ 80 px | desain (§3.2) |
| 5 | Snapshot/crop berbasis bbox person, crop main stream diambil terpisah (fetch live) | crop 4670 = lantai kosong, crop 4678 = kepala terpotong | desain (§4) |

Resolusi stream kamera attendance (diukur): cam 358 sub 640×480@10 / main 1080p@25;
cam 363 sub 640×480@15 / main 1080p@25; cam 362 dan 364 tanpa substream nyata
(`cam_<id>` = 1080p@25). Relay overlay MQTT → backend → WebSocket terukur median
**44 ms** (25/25 pesan tiba) — bukan bottleneck.

## 2. Tujuan dan kriteria sukses

Saat karyawan berjalan melewati kamera attendance, sistem mencatat **siapa dan kapan**
dalam **satu** event dengan crop wajah jelas sebagai bukti. Overlay debugger hanya
menampilkan kotak wajah, hampir real-time. Gate absensi tidak bergantung pada YOLO.

Sukses (diuji di lapangan, §11):
- Berjalan menuju kamera → 1 event `attendance` ≤ 2 s setelah wajah masuk zona, crop
  wajah ≥ 80 px, cocok ke karyawan, `attendance_event` tercatat, file ada di disk.
  (Batas 2 s berlaku bila lintasan menghasilkan ≥ K frame bagus; lintasan yang lebih
  singkat terbit saat track kedaluwarsa, ≤ `max_age_s` setelah wajah terakhir terlihat
  pada jaringan sehat. Ruling Task 5 review: bila upload media lambat, percobaan
  dibatasi dan event tetap terbit tanpa media; batas ini dapat lewat ~1,1 s
  ditambah jitter polling ≤0,1 s. Jangan klaim deadline keras saat API terganggu.)
- Membelakangi kamera → tidak ada event.
- Wajah tak ter-enroll → event berlabel tidak dikenal + crop.
- Lewat dua kali dalam 5 menit → satu `attendance_event`.
- Kotak wajah mengikuti wajah di debugger (target latensi kotak ~100–150 ms).

## 3. Keputusan terkunci (Q&A 2026-09-23)

1. **Arah per zona** — zona attendance tetap membawa `direction` entry/exit. Kamera
   yang menghadap orang datang = entry; pulang butuh zona/kamera yang menghadap orang
   keluar. Logika hari absensi backend (`first_entry`/`last_exit`) tidak berubah.
2. **Main stream 1080p** untuk pipeline wajah: deteksi di frame diperkecil, embedding
   dari crop resolusi penuh di **frame yang sama** (tanpa fetch terpisah).
3. **Matching di backend, 1× per orang** — node melacak wajah, menggabungkan beberapa
   frame bagus, kirim **satu** event; galeri wajah tetap hanya di backend. Overlay
   tanpa nama live.
4. **Zona = area wajah + ukuran minimum** — wajah dihitung bila titik tengahnya di
   poligon **dan** lebar ≥ minimum. `trigger_seconds` tidak dipakai untuk attendance;
   digantikan K frame bagus (global).
5. **Pendekatan A** — `FaceGateWorker` terpisah per kamera attendance; `CameraWorker`
   (substream + YOLO) hanya untuk zona behavior. Kamera yang hanya punya zona
   attendance **tidak menjalankan YOLO**.
6. Overlay diperbarui per frame yang dianalisis (≤ AI FPS kamera), kotak dikirim
   **sebelum** embedding; frontend menghaluskan dan membuang kotak basi.

## 4. Arsitektur dan alur data

```
config push ─► VisionNode: pisah zona per kamera
   ├─ zona behavior   ─► CameraWorker   (substream, YOLO)            [tetap]
   └─ zona attendance ─► FaceGateWorker (cam_<id>_main, FrameSource frame-terbaru,
                                          fps = ai_fps kamera)       [baru]
        motion gate ─► SCRFD (det_size 640) ─► wajah + 5 landmark + det_score
        ─► ByteTracker di kotak wajah (reuse, max_age berbasis waktu §8)
        ─► overlay kind="face" (semua track wajah; label §5.4)
        ─► per track: gerbang kualitas §5.2 ─► ArcFace dari crop 1080p ter-align
        ─► K frame bagus, ATAU track berakhir dengan ≥ 1 frame bagus
           ─► SATU event attendance (embedding gabungan, crop terbaik, snapshot
              frame yang sama + kotak wajah, tanpa clip)
backend ─► match_vector ─► cocok: cooldown? ─► attendance_event + recompute_day
                         └► tidak cocok: event employee_id=null, match_reason=no_match
```

- Satu `Recorder` per kamera dipakai bersama bila kamera punya kedua worker.
- URL main stream diturunkan dari `source_url` memakai `main_stream_name()` yang sudah
  ada (`rtsp://host:8554/cam_363` → `.../cam_363_main`). go2rtc sudah memiliki
  `cam_<id>_main` untuk keempat kamera attendance (diukur).
- **Dihapus** (digantikan, bukan disimpan berdampingan): `FaceGateAnalyzer` berbasis
  person, `CameraWorker._attach_crop` / `_mainstream_crop` / `_frame_crop` /
  `_draw_face_box`, dan `CameraWorker._publish_faces` (overlay wajah sementara dari
  `e508a97`). Format config pra-R5 (`behaviors_of`) tetap didukung: zona
  `absensi`/`attendance` lama ikut diarahkan ke `FaceGateWorker`.

## 5. Node — `FaceGateWorker`

### 5.1 Deteksi

`FaceEmbedder` dimuat dengan `allowed_modules=["detection", "recognition"]` (tanpa
age/gender/landmark 3D) di device pin (`device_id`). SCRFD dijalankan pada frame yang
lolos motion gate (`FrameMotionGate` yang sama, setelan kamera). Wajah 80 px di 1080p
≈ 27 px di input 640 — rentang kuat SCRFD. Semua wajah dengan skor ≥ 0,5 (default
insightface) masuk tracker dan overlay.

### 5.2 Gerbang kualitas (semua harus lolos agar frame dipakai untuk embedding)

| Gerbang | Default | Setelan | Dasar |
|---|---|---|---|
| Titik tengah wajah di poligon zona | — | poligon zona | keputusan §3.4 |
| Lebar wajah (px, frame 1080p) | ≥ 80 | `face_min_width_px` | Axis: 80 px untuk identifikasi; input ArcFace 112 |
| Skor deteksi | ≥ 0,6 | `face_min_det_score` | sedikit di atas default insightface 0,5 |
| Frontal: \|x_hidung − x_tengah_mata\| ÷ jarak_mata | ≤ 0,35 (≈ yaw 30°) | `face_max_yaw` | akurasi ArcFace turun pada wajah menyamping |
| Tajam: variansi Laplacian crop ter-align 112×112 | ≥ 120 | `face_blur_min` | Frigate: < 120 = sangat blur. **Wajib dikalibrasi** di lapangan (§11) |

Skor kualitas per frame: `q = det_score × min(1, lebar/112) × (1 − yaw)`.

### 5.3 Embedding dan penggabungan per track

- Hanya frame yang lolos §5.2: `norm_crop(frame_1080p, landmark_1080p)` → 112×112 →
  ArcFace → vektor ternormalisasi.
- **Emit** saat track punya `face_min_frames` (K, default 3) frame bagus, **atau** saat
  track kedaluwarsa (tidak terlihat > `max_age_s`) dengan 1..K−1 frame bagus. Track
  tanpa frame bagus tidak menerbitkan apa pun.
- Setelah emit, track ditandai selesai: tidak di-embed lagi, tidak emit lagi.
- Gabungan: rata-rata berbobot `q` dari embedding, dinormalisasi ulang. Sebelumnya,
  embedding dengan cosine < 0,5 terhadap rata-rata awal dibuang (melindungi dari
  tracker yang tertukar orang; pola `build_class_mean` Frigate). Bila semua terbuang,
  pakai embedding dengan `q` tertinggi.

### 5.4 Overlay

- Dikirim tiap frame yang dianalisis, **sebelum** embedding/upload: `kind="face"`,
  `id` = id track wajah, `bbox_norm` = kotak wajah relatif frame.
- `label` = `q` (dua desimal) bila lolos gerbang, atau kode gerbang yang gagal
  (`zone` | `small` | `score` | `yaw` | `blur`) — frontend menerjemahkan kode lewat
  i18n. Tujuannya kalibrasi: user melihat kenapa wajah tidak dihitung.
- Satu pesan kosong saat tidak ada track wajah lagi.

### 5.5 Event dan media

Payload event `attendance` (field lama dipertahankan agar backend/UI tetap jalan):
`direction`, `track_id` (id track wajah), `bbox_norm` (kotak wajah frame terbaik),
`embedding` (gabungan), `face_quality` (`q` terbaik), `face_bbox` (kotak wajah di
koordinat crop, dipakai `annotate_face_crop`), `crop_path`, dan baru `face_stats` =
`{width_px, det_score, yaw, blur, frames}` dari frame terbaik + jumlah frame dipakai.

- **Crop** = kotak wajah frame terbaik + padding 30%, resolusi penuh, diunggah node.
- **Snapshot** = frame terbaik yang **sama**, diperkecil (lebar 1280), dengan kotak
  wajah; bukan dari ring buffer substream.
- **Clip** = tidak ada (`clip=False`).
- Gagal upload crop → event tetap terkirim dengan embedding (bukti gambar hilang).
  Upload crop/snapshot independen: satu percobaan socket 0,5 s per gambar;
  thread finalisasi event menunggu maksimal 1,1 s lalu menerbitkan event tanpa
  media bila masih tertahan; pembacaan frame dan overlay tetap berjalan. Hanya
  satu upload media tertahan per kamera; event wajah lain selama media pertama
  antre/tertahan dikirim segera tanpa media sehingga urutan terima bisa berbeda
  dari `ts_event`. Blob yang berhasil sesudah batas waktu tidak diasosiasikan
  ke event (tanpa kontrak update backend baru).

### 5.6 Heartbeat

`modules.face = {device, loaded, detect_n, embed_n}` (pola `modules.detector`).

## 6. Backend

- **Matching tidak berubah**: `face.match_vector(embedding, face_quality)`, ambang
  `FACE_MATCH_THRESHOLD`.
- **Event embedding tanpa `crop_path` tetap dicocokkan** (sekarang di-skip). Anotasi
  crop hanya bila crop ada.
- **Cooldown per karyawan + arah**: bila sudah ada `attendance_event` untuk
  `(employee_id, direction)` dalam `ATTENDANCE_COOLDOWN_MIN` (env, default 5) menit
  dari `ts_event` ke kedua arah waktu (karena event media dapat tiba tidak urut),
  tidak dibuat baris baru; payload event diberi `employee_id` dan
  `match_reason: "cooldown"`. Kamera tidak ikut kunci (dua kamera entry dalam 5 menit =
  satu entry).
- **Embedding dibuang dari `event.payload`** di akhir `handle_face_event` pada semua
  jalur (cocok, tidak cocok, cooldown, skip). Migration 0016 juga membuang `embedding`
  dari payload event lama (data biometrik tidak disimpan di tabel event).
- **Setelan wajah global** (migration 0016, tabel `detector_setting`, non-null dengan
  default §5.2): `face_min_width_px`, `face_min_det_score`, `face_max_yaw`,
  `face_blur_min`, `face_min_frames`. API `detector-settings` menerima dan memvalidasi
  kolom ini. Config push mengirimnya di key `face` bersama `device` yang sudah ada.

## 7. Frontend

- **Editor zona attendance** (Zona Deteksi dan Gate Absensi): input `trigger_seconds`
  disembunyikan untuk zona attendance; arah entry/exit tetap; petunjuk baru "gambar
  poligon di area tempat wajah terlihat, bukan lantai".
- **Blok Advanced** tab Deteksi & Model: grup baru "Wajah attendance" dengan lima
  setelan §5.2 (pola yang sama dengan setelan motion gate).
- **Overlay**: kotak bergerak halus antar pembaruan (transisi CSS ~150 ms); kotak yang
  tidak diperbarui 1 s dihapus (juga menyelesaikan kotak person yang sekarang bisa
  menempel selamanya); label kode gerbang diterjemahkan lewat i18n.
- **Badge mode player** di modal debugger: `WebRTC` bila `video.srcObject` terisi,
  `MSE` bila `video.src` berupa blob — tanpa mengubah `video-rtc.js` vendor.
- Semua string baru lewat `src/app/i18n.tsx`; mobile 390 px tanpa overflow horizontal.

## 8. Prasyarat di R5b: `ByteTracker.max_age` berbasis waktu

Temuan terbuka #2 (`docs/detection-behavior-inventory.md` §10): `max_age = 15` frame,
sementara gap motion gate = `force_interval_s × ai_fps`. Kamera attendance yang
dinaikkan ke 10 fps (untuk overlay lebih halus) akan memutus track wajah. `max_age`
diubah ke detik (`max_age_s = 3.0`, setara 15 frame @ 5 fps) dan dipakai kedua worker.
Tes `test_static_track_survives_the_gated_gap_at_deployed_settings` diperluas ke 10 fps.

## 9. Penanganan error

| Kondisi | Perilaku |
|---|---|
| Main stream putus | `FrameSource` reconnect backoff; worker tetap hidup |
| Model wajah gagal dimuat | worker jalan tanpa deteksi, log sekali, `face.loaded=false`; tidak ada event |
| SCRFD/ArcFace error di satu frame | frame dilewati, warning; worker tetap hidup |
| Upload crop/snapshot gagal | event tetap dengan embedding; backend mencocokkan tanpa crop |
| MQTT putus | event lewat antrean disk (sudah ada); overlay QoS0 dibuang |

## 10. Strategi tes

TDD; tanpa GPU kecuali bertanda `gpu`. Tiap tes harus gagal pada bug yang masuk akal.

- **Fungsi murni**: tiap gerbang §5.2 (termasuk yaw dari 5 landmark), titik tengah
  wajah di poligon, penggabungan (rata-rata berbobot, buang outlier, fallback).
- **`FaceGateWorker`** dengan mesin wajah palsu + `FrameSource.from_frames`: tepat 1
  event setelah K frame bagus; 0 event tanpa frame bagus; emit saat track kedaluwarsa
  dengan 1 frame bagus; overlay terkirim sebelum embedding; track tertukar → outlier
  dibuang; error mesin wajah tidak mematikan worker; payload memuat `face_stats`.
- **Node**: kamera hanya-attendance → hanya `FaceGateWorker` (detektor YOLO tidak
  dipanggil); kamera campuran → dua worker, satu `Recorder`; config pra-R5 `absensi`
  → `FaceGateWorker`.
- **ByteTracker**: track bertahan melewati gap gate pada 10 fps.
- **Backend**: cooldown (dalam/luar jendela, arah beda); embedding tidak tersisa di
  payload pada semua jalur; event embedding tanpa crop tetap cocok; migration 0016
  (kolom + pembersihan embedding lama); config push membawa setelan wajah; validasi
  API.
- **Frontend**: editor zona attendance tanpa trigger + petunjuk; grup Advanced; TTL dan
  label kode gerbang overlay; badge mode player.
- **`gpu` (server)**: SCRFD + ArcFace asli pada foto enrollment → embedding gabungan
  cocok dengan galeri di atas `FACE_MATCH_THRESHOLD`.

## 11. Verifikasi lapangan (syarat R5b selesai)

Bukti ke `docs/evidence/`, angka di CHANGELOG. Tidak ada klaim tanpa baris DB + file di
disk.

1. Zona 9 digambar ulang di area kepala (runbook).
2. Berjalan menuju cam 363 dengan kecepatan normal → event ≤ 2 s setelah wajah masuk
   zona (ts event vs ts kotak wajah pertama di zona), crop ≥ 80 px,
   `attendance_event` untuk karyawan ter-enroll, file crop + snapshot ada.
3. Membelakangi kamera → tidak ada event.
4. Orang belum ter-enroll → event tidak dikenal + crop.
5. Dua kali lewat dalam 5 menit → satu `attendance_event`, event kedua `cooldown`.
6. `nvidia-smi`: model wajah di GPU 2; `modules.face.loaded=true`; kotak wajah
   mengikuti wajah di debugger.
7. Kalibrasi: catat `face_stats` dari ≥ 10 lintasan; sesuaikan `face_blur_min` dan
   `face_min_width_px` bila perlu; catat nilai final di CHANGELOG.

## 12. Deploy dan rollback

- Deploy: migration 0016 → restart API → restart `vision-node` → **gambar ulang zona
  attendance** (7, 8, 9, 11 digambar untuk titik kaki; tidak bisa dimigrasi otomatis).
  Masuk runbook `docs/runbooks/`.
- Rollback: `git revert` rentang commit R5b, `alembic downgrade` ke 0015, restart API
  dan `vision-node`. Kolom baru hanya ditambah; pembersihan embedding lama tidak bisa
  dikembalikan (disengaja).

## 13. Di luar lingkup (dicatat)

- Liveness / anti-spoofing (insightface 2.0 punya addon liveness).
- Menambah galeri dari tangkapan CCTV (pola tab Train Frigate).
- Nama live di overlay (butuh galeri di node).
- Pin GPU model wajah backend (masih GPU 0, `ctx_id=0`).
- R5c klip segment cache.

## 14. Perbandingan dengan Frigate (rujukan desain)

| Aspek | Frigate | R5b |
|---|---|---|
| Urutan | person dulu, YuNet (CPU) di dalam kotak person | face-first tanpa YOLO |
| Stream | detect stream; resolusi harus cukup | main stream 1080p |
| Ambil frame | ffmpeg `fps=` + buang saat antrean penuh | reader thread frame-terbaru (`ddf8599`) |
| Keputusan | ≤ 12 percobaan/track, rata-rata berbobot luas × skor, `min_faces`, seri = tanpa label | K frame bagus, embedding rata-rata berbobot `q`, buang outlier, 1 event/track |
| Kualitas | `min_area` 750 px², skor ≥ 0,7, blur Laplacian, landmark fit | lebar ≥ 80 px, skor ≥ 0,6, yaw ≤ 0,35, blur ≥ 120 |
| Library | class mean + trim outlier; tab Train | galeri backend (3 foto enrollment) |

Sumber: [Axis — Identification and Recognition](https://www.axis.com/files/feature_articles/ar_id_and_recognition_53836_en_1309_lo.pdf),
[Incoresoft — Face Recognition Camera Installation](https://docs.incoresoft.com/ivig/latest/face-recognition-camera-installation-94609150.html),
[Human Recognition Accuracy on Low Resolution Faces](https://arxiv.org/pdf/2503.20108),
[SCRFD](https://arxiv.org/pdf/2105.04714),
[SER-FIQ](https://github.com/pterhoer/FaceImageQuality),
[OpenCV — delay karena buffer](https://forum.opencv.org/t/delay-in-videocapture-because-of-buffer/2755),
Frigate `docs/docs/configuration/face_recognition.md`,
`frigate/data_processing/real_time/face.py`, `frigate/data_processing/common/face/recognizer.py`.
