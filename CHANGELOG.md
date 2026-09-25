# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/) ringkas — satu baris per commit.
Skema versi: [SemVer](https://semver.org/). Status proyek: pra-rilis (`0.x`).

### Zona UX (2026-09-25 – …)

- **Vision: zona aktif = AI aktif**: mask `camera.analyzers` tidak dibaca lagi; kamera tanpa zona aktif tidak
  mendapat worker (stream tidak dibuka, tanpa YOLO → hemat GPU); flag Snapshot/Clip dibaca per behavior dengan
  fallback flag zona (zona lama berperilaku sama). Vision **203 passed**.
- **Backend**: item `behaviors` menerima `snapshot`/`clip` (bool, lainnya 422); zona absensi aktif dengan arah
  berbeda di kamera yang sama ditolak 422 saat create/patch (patch gagal tidak setengah tersimpan); config push
  tidak lagi mengirim `analyzers` (kolom dibiarkan, deprecated). Backend **367 passed**.
- **Zona Deteksi**: toggle Snapshot/Clip level zona dihapus; tiap behavior tercentang punya toggle Snapshot dan
  Clip (default mengikuti flag zona lama), dikirim sebagai key di item `behaviors`; zona absensi tanpa toggle
  media; konflik arah → "Kamera ini sudah punya zona absensi aktif dengan arah lain.". Frontend **132 passed**.
- **Halaman Gate Absensi dihapus**: zona absensi dibuat/diubah di Zona Deteksi (tipe Absensi, arah, aktif);
  kolom SNAPSHOT/CLIP Gates memang no-op (pipeline wajah selalu crop + snapshot, tanpa clip). `?tab=gates` lama
  jatuh ke tab Kamera. Frontend **126 passed**.
- **Deteksi & Model = parameter model**: chip analyzer dihapus; tabel memuat semua kamera dengan kolom
  **Status AI** ("Aktif · N zona" / "Tidak jalan (tanpa zona aktif)" / "Kamera nonaktif"); kartu model wajah
  (InsightFace buffalo_l); teks tracker diperbaiki ("lepas track setelah 3 s"); Reset tidak mengirim
  `analyzers`. Frontend **126 passed**, build 0, lint set sama.
- **Fix kontrak `behaviors`**: zona dengan `behaviors: []` (semua behavior di-uncheck) kini benar-benar zona visual
  saja — node tidak lagi membangkitkan analyzer dari kolom legacy; `behaviors` NULL tetap memakai fallback legacy
  (zona 15). Config push mengirim nilai `behaviors` apa adanya. Vision **204 passed**, backend **368 passed**.

### Pendaftaran kamera sederhana (2026-09-24 – 2026-09-25)

- **Halaman Kamera dirapikan**: panel "Sumber & kredensial" dihapus (`CameraSourcesPanel`); tombol
  **Lanjutan** berisi Import CCTV, Sync go2rtc, dan **Kelola kredensial** (ubah username/password — kosong =
  tidak diganti, nonaktifkan dengan pesan bila masih dipakai, tambah baru); kolom **Kredensial** di tabel
  (Default (NVR) / nama profil). Frontend **129 passed**, build 0, lint set sama.
- **Form kamera sederhana**: Nama, Lokasi (datalist), IP kamera (port opsional), Path mainstream, Path
  substream, Kredensial (Default (NVR) / profil / "+ Kredensial baru…") + Tes koneksi dengan thumbnail;
  peringatan sub = main; simpan tanpa tes = klik Simpan dua kali; Node (hanya bila > 1 node) + scan NVR di
  "Lanjutan". Frontend **127 passed**.
- **`secret_store`**: password kamera dari UI disimpan di file rahasia server (`CAMERA_SECRETS_FILE`,
  default `~/.isentinel/camera-secrets.json`, 0600, direktori 0700, tulis atomik, ditolak bila di dalam
  `STORAGE_ROOT`); DB hanya referensi `store:cred_<id>`, di-resolve oleh `stream_endpoint._secret`.
  Backend **348 passed**.
- **Profil kredensial menerima `password`** (write-only): disimpan ke `secret_store`, `secret_ref` =
  `store:cred_<id>`; tepat satu dari `password`/`secret_ref: env:` (422 bila tidak); PATCH `password`
  menimpa store (profil `env:` pindah ke `store:`) dan memicu sinkron go2rtc + config push; gagal tulis store
  → 500, profil tidak dibuat. Password tidak pernah muncul di response. Backend **353 passed**.
- **Form "Kredensial baru"** (`NewCredentialForm`, inline): Nama, Username, Password → `POST /credential-profiles`
  (password write-only); nama duplikat → pesan khusus. API client: `password` di payload profil, `snapshot`
  di probe. Frontend **123 passed**.
- **Kredensial per kamera direct-host**: `resolve_stream` memakai `credential_override` walau kamera tanpa
  stream source (13 kamera server semuanya direct-host); API kamera + probe tidak lagi menolak kombinasi itu.
  Password khusus ter-encode di URL RTSP; referensi `store:` yang hilang → probe 422. Backend **357 passed**.
- **Probe thumbnail**: `POST /cameras/probe` dengan `snapshot: true` mengembalikan `snapshot_jpeg_b64`
  (1 frame SUB, atau MAIN bila SUB kosong, lebar 480, ffmpeg timeout 6 s, tidak ditulis ke disk; gagal →
  `null`). Backend **361 passed**.
- **Fix review: 422 tidak menggemakan password**: handler `RequestValidationError` global membuang `input`/`ctx`
  dari error (bawaan FastAPI mengembalikan body klien mentah → password profil kamera dan password login ikut
  kembali di response 422). `msg`/`loc` tetap. Tes merah dulu (3 kasus profil + login). Backend **363 passed**.
- **Deploy + verifikasi (2026-09-25)**: branch `1924ef6` di gspe-ai3, restart `isentinel-api` (health ok, tanpa
  migrasi, `vision-node` tidak disentuh); `chmod 700 ~/.isentinel`. Smoke: `/cameras` 200, profil kredensial 0,
  422 login tanpa gema password. Kamera tanpa autentikasi (ZKteco `:8554/stream`) terbukti jalan dengan
  Default (NVR) — ffprobe tanpa/ dengan kredensial salah sama-sama 1920×1080, NVR tanpa kredensial 401.
  **E2E user OK** (review form, Tes koneksi, Lanjutan). Tanpa screenshot evidence (uji dilakukan user).

### Event clip pre-buffer (2026-09-24)

- **`ClipRing`** (`vision/vision/clipring.py`): ffmpeg `-c copy` per kamera menulis segmen MPEG-TS 2 s
  ke tmpfs; `cut` menggabung segmen yang menutupi jendela insiden (concat `-c copy`, `+faststart`);
  watchdog restart ffmpeg mati/stall dengan backoff ≤ 30 s; celah restart tidak dianggap tertutup.
  Watchdog tahan gagal start ffmpeg (`OSError` → ring nonaktif, bukan traceback).
  Belum dipakai recorder. Vision **190 passed**.
- **Recorder = insiden per kamera**: snapshot per event langsung diunggah + dipublikasi (dulu tertahan
  ~30 s oleh clip); event ber-clip membuka/bergabung ke satu insiden per kamera, ditutup 15 s setelah
  track insiden terakhir terlihat (cap 120 s), clip dipotong dari `ClipRing`, satu upload, media
  dipublikasi untuk setiap event. Ring tidak sehat → fallback live `cam_<id>_main` (perilaku lama).
  Config `record_clip_s` → `clip_pre_s/clip_post_s/clip_max_s/clip_ring_dir`. **Fix kebocoran
  outbox**: file lokal dihapus setelah upload (server: 582 MB / 2.464 file menumpuk).
  Vision **195 passed**.
- **Node memasang ring**: `ClipRing` dari `cam_<id>_main` hanya untuk `CameraWorker` yang punya
  analyzer `clip` aktif (atau `emit_person_detect`); kamera gate-only / tanpa zona clip tidak membuka
  koneksi mainstream. Worker memanggil `recorder.touch(track_ids)` tiap frame inferensi.
  Watchdog ring: ffmpeg yang tidak mati setelah kill tidak lagi melempar keluar `stop()` (config push tetap jalan).
  Vision **200 passed**.
- **Inbox**: tab Clip menampilkan "Clip sedang direkam…" untuk event keamanan < 3 menit tanpa
  `clip_path`, dan me-refresh daftar tiap 5 s sampai clip datang (poll live hanya menambah event baru,
  sehingga clip/snapshot yang datang belakangan dulu tak pernah tampil tanpa reload). Label zona
  "Rekam clip event" tanpa "(30 detik)". Frontend **120 passed**.
- **Docs**: ROADMAP tabel ringkasan diperbarui (Fase 5 DONE 2026-09-21, R5b deploy + lapangan
  2026-09-23, baris CP clip pre-buffer). Suite penuh: backend 339 passed, vision 200 passed
  (3 deselected), frontend 120 passed, build 0, lint 22 warning (set sama dengan sebelum perubahan).
- **Docs**: catatan deviasi implementasi (flag ffmpeg segmen, concat protocol, `covered_s` tidak dikembalikan,
  `SETTLE_S`/`prune`) + ekspektasi verifikasi lapangan di plan Task 6; sinkron status R5b di ROADMAP.

- **Deploy + pengukuran ring (2026-09-24)**: branch `feat/event-clip-prebuffer` (`8853bca`) di gspe-ai3,
  `pip install -e vision` di `vision-venv`, restart `vision-node`; chip analyzer intrusion cam 357
  diaktifkan (zona 6 tadinya di-skip oleh mask `analyzers=['attendance']`). Terukur: ffmpeg ring cam357
  **0,9 % CPU / 51 MB RSS**, segmen 2 s bergulir (`/dev/shm/isentinel/cam357`, total **484 KB**),
  `cam_357_main` **1 konsumen**, 0 warning `clip ring`; outbox lama dibersihkan (582 MB / 2.464 file → 0).
  **Uji lapangan (klip 1080p dari orang nyata) belum dijalankan** — bukti:
  `docs/evidence/clip-prebuffer-ring.txt`.
- **Fix retensi klip bersama**: lapis 1 tidak lagi menghapus file yang masih dirujuk event belum
  kedaluwarsa (klip insiden dipakai beberapa event; cutoff bisa jatuh di tengah insiden). Path event lama
  tetap di-null-kan; file dihapus saat event terakhir yang merujuknya kedaluwarsa. Backend **340 passed**.
- **Uji lapangan (2026-09-24)**: cam 357 intrusion 15:12 → klip **1920×1080, 48,0 s**, orang terlihat sejak
  sebelum masuk zona sampai keluar; snapshot tersimpan **0,5 s** setelah event (dulu ~30 s), klip 38 s. Cam 363:
  dua orang berbeda berjarak 12 s (15:19:26 / 15:19:38) → **satu file klip** bersama (68,2 s), snapshot per
  event berbeda — sesuai desain insiden per kamera. Temuan: ekor klip ~22 s lorong kosong.
- **Post-buffer default 15 → 8 s** (`VISION_CLIP_POST_S`, permintaan user setelah uji lapangan): ekor kosong
  ≈ post + 3 s tracker + 2–4 s segmen. Tes jendela insiden mem-pin post 15 s secara eksplisit.
  Vision **200 passed**.
- **Seek per event di klip bersama**: recorder mengirim `clip_offset_s` per event (= waktu event − pre − awal
  klip, ≥ 0; event pertama 0) di payload media; backend menyimpannya ke `event.payload.clip_offset_s`
  (angka ≥ 0 saja, tanpa migrasi); Inbox memutar `…mp4#t=<offset>` (media fragment), tautan unduh tetap
  tanpa offset. Backend **342**, vision **200**, frontend **121** passed, build 0, lint set rule+file sama.
- **Uji lapangan ulang (post 8 s + seek, 15:48–15:51)**: klip 1 orang 32–40 s (dulu 48 s); dua orang cam 363
  berjarak 21 s → 1 file 56,2 s, event kedua `clip_offset_s` 21.2 → Inbox mulai di detik orang kedua; 0 error
  `vision-node`. **E2E user OK.** Bukti `docs/evidence/clip-prebuffer-field.txt`.

### Enrollment & Shift refining (2026-09-23 – 2026-09-24)

- **Validasi backend**: nama/NIK/nama shift di-trim dan wajib isi (422); shift wajib `end_time >
  start_time` di POST dan PATCH gabungan; PATCH null eksplisit diabaikan (dulu 500), `shift_id: null`
  tetap melepas shift. Backend **336 passed**.
- **`EmployeeOut` memuat `photo_count` + `face_ready`** (≥ `MIN_PHOTOS` = 3, kini satu sumber di
  `models/employee.py`) → daftar Enrollment tak perlu lagi `enrollment-status` per karyawan (N+1).
- **Karyawan nonaktif tidak dikenali di gate**: `FaceGallery.load` hanya memuat embedding karyawan
  aktif; PATCH `active` me-refresh gallery. Aktif kembali → dikenali lagi tanpa enroll ulang.
  Konsekuensi: wajah karyawan nonaktif tidak memicu peringatan duplikat saat enroll.
- **Tab Shift** di Enrollment (`?tab=shifts`): tabel + modal tambah/edit (nama, jam `type=time`,
  toleransi, hari kerja) + hapus dengan konfirmasi; error duplikat / selesai ≤ mulai / "masih dipakai"
  tampil spesifik. Kartu shift dikeluarkan dari panel karyawan. Frontend **109 passed**.
- **Tab Karyawan dirapikan**: filter status (default Aktif) + tag Nonaktif; kartu Identitas dengan
  **NIK bisa diedit** (409 → "NIK sudah dipakai" inline); kartu Wajah memuat tombol **"Hapus semua
  foto wajah {nama}"** (nonaktif bila 0 foto, konfirmasi menyebut nama + jumlah foto); kartu Status:
  Nonaktifkan dengan konfirmasi, Hapus karyawan (riwayat absensi → tawaran Nonaktifkan). Badge wajah
  dari `photo_count` (tanpa N+1). Grid satu kolom di ≤ 671 px. Frontend **117 passed**.
- **Cleanup sisa refining**: hapus 3 API client mati (`EnrollmentStatus`, `uploadPhoto`,
  `enrollmentStatus` — endpoint backend tetap ada) + 8 baris key i18n `en.col.*` yatim.
  Frontend **117 passed** (tanpa perubahan hasil).
- **Fix review: suntingan identitas tidak hilang saat refresh**. Effect pengisi form bergantung pada
  objek `selected`, yang baru setiap `refresh()`; upload/hapus foto sebelum Simpan menimpa nama/NIK
  yang sedang diedit. Kini dependency primitif (nama, NIK, shift tersimpan). Tes baru merah dulu
  (`Budi Santoso` ≠ `Budi Baru`). Frontend **118 passed**, lint 22 set tetap.

- **Deploy branch + verifikasi UI** (2026-09-24): `feat/enrollment-refining` @ `f8028ed` di-push dan
  di-checkout di gspe-ai3, restart `isentinel-api` (tanpa migrasi), health `{"status":"ok"}`. API
  menampilkan `photo_count` Angly 5 / Ikhsal 5. Tidak ada shift lama dengan selesai ≤ mulai (3 shift:
  Shift 1, Sore, Tekno). CRUD shift uji `UJI` lewat UI: POST 200, PATCH 200 (tambah Sab), rename ke
  `Tekno` → 409 "Nama shift sudah dipakai", DELETE 200. 390 px: `scrollWidth = 390` di kedua tab.
  Temuan data: NIK Ikhsal kosong (`""`, data lama) → form menandai "Wajib diisi"; tidak diubah.
  Bukti `docs/evidence/enrollment-*.png`. Follow-up: shift malam; hitung ulang `attendance_day` setelah
  shift diedit; tabel shift di 390 px sempit (kolom hari terbungkus per kata, scroll di dalam tabel).

- **E2E user OK** (2026-09-24): user menguji UI secara menyeluruh; merge `--no-ff` ke `main`,
  server gspe-ai3 kembali ke `main`.

### R5b deploy + tes lapangan pertama + permintaan user (2026-09-23)

- **Deploy** `f22f2d6` ke gspe-ai3: backup `~/backup-pra-0016-20260923-1533.sql` (73 event, cocok
  dengan DB), alembic `0015 → 0016`, restart API + vision; event ber-embedding di DB = 0; config push
  membawa 6 kunci `face`; heartbeat `modules.face.device = cuda:2`.
- **Tes lapangan user (Angly)**: entry cam 364 zona 12 `matched` skor 0,714 (wajah 217 px, 3 frame),
  exit cam 365 zona 14 `matched` skor 0,65; `attendance_day` satu baris (masuk 15:45, pulang 15:59);
  crop + snapshot ada di disk; model wajah di GPU 2 (1054 MiB). Dua event `no_match` 15:45:07 = orang
  lain bermasker (benar tidak dikenal). User: flow dan overlay sudah halus.
- **Entry sekali per hari** (`9723a54`, permintaan user): entry kedua di hari yang sama →
  `match_reason: already_in` tanpa baris baru; entry lebih awal yang tiba belakangan tetap dicatat;
  exit boleh berulang. Backend **328 passed**.
- **Nama di overlay** (`89612ab`, permintaan user): label kotak wajah diganti nama / Tidak dikenal
  dari event attendance yang dibroadcast backend (event < 30 s, nama disimpan 30 s). Frontend **103 passed**.
- Klip attendance tidak ada: disengaja (spec §4 no.5, spec R5b §5.5).
- Temuan (belum dikerjakan): proses vision juga memakai 386 MiB di GPU 0 setelah model wajah dimuat
  (kemungkinan konteks CUDA default onnxruntime); model wajah sendiri di GPU 2.

### R5b review pra-deploy — celah privasi embedding + runbook (lokal, 2026-09-23)

- **Embedding tidak pernah tersimpan atau ter-broadcast** (`fa5d959`). Dulu `ingest_event`
  commit payload ber-embedding lalu `handle_face_event` membuangnya; bila pencocokan melempar
  error, rollback menyisakan embedding permanen di tabel `event` dan broadcast WS mengirimnya
  ke browser. Consumer kini memisahkan embedding sebelum ingest dan meneruskannya ke matcher.
  Test `test_attendance_embedding_never_persisted_or_broadcast_when_matching_fails` merah
  sebelum perbaikan. Backend **325 passed**.
- **Runbook deploy diperbaiki** (`docs/runbooks/attendance-face-first.md`): `git pull` saja tidak
  membawa R5b (server di `feat/detection-model`) → `git checkout feat/attendance-face-first`;
  `pg_dump "$DATABASE_URL"` gagal (skema `postgresql+psycopg`, variabel belum di-load, `~` di
  dalam kutip) sehingga migrasi purge bisa jalan tanpa backup → backup dengan cek `BACKUP OK`;
  `alembic` harus dari `backend/`. Perintah backup + `alembic current` diverifikasi baca-saja di
  server. Rollback memakai `git checkout feat/detection-model` setelah `downgrade 0015`.
- Review mandiri: vision 177/3 deselected, backend 324→325, frontend 99, build+lint (22 warning
  lama) hijau; mutasi cooldown satu-arah membuat `test_out_of_order_...` merah.

### R5b Task 11 — tes GPU, runbook, docs (PENDING verifikasi lapangan, lokal 2026-09-23)

- Konteks/path: `vision/tests/test_face_worker_gpu.py` baru bertanda `gpu`
  (SCRFD + ArcFace asli pada foto enrollment, konsistensi vektor >0,9 — hanya
  dijalankan di server, belum dieksekusi). `docs/runbooks/attendance-face-first.md`
  baru: urutan deploy (pull → **backup DB** → `alembic upgrade head` → restart
  API+vision), gambar ulang zona attendance 7/8/9/11 di area kepala, cara baca
  label gerbang debugger (kunci `face_min_det_score`), kalibrasi `face_stats`,
  rollback dengan urutan `alembic downgrade 0015` sebelum revert. `README.md` peta repo:
  `face_gate.py` dihapus, wajah kini `face_worker.py` di `vision/vision/`.
  `ROADMAP.md`: bagian R5b status lokal/PENDING lapangan; temuan terbuka R5a #2
  (max_age per frame) ditandai selesai oleh R5b Task 1. `docs/detection-
  behavior-inventory.md` §6 + §10 diberi catatan status R5b.
- Bukti: suite lengkap lokal (angka persis di bawah). **Tidak ada klaim GPU,
  deploy, server, atau field** — semua PENDING sampai deploy diizinkan user.
- Dampak: siap deploy; runbook menegaskan rollback perlu downgrade 0015 dulu.
  Rollback Task 11: `git revert` commit docs.

### R5b Task 10 — overlay halus + TTL, label gerbang, mode player, hasil wajah di Events (lokal, 2026-09-23)

- Konteks/path: `frontend/src/features/live/playerMode.ts` baru (WebRTC via `srcObject`,
  MSE via `blob:` URL). `LiveViewPage.tsx`: `DetBox.at` + `BOX_TTL_MS = 1000` dan sweep
  interval 250 ms menghapus kotak basi tanpa update WS; transisi `x/y/width/height`
  150 ms linear pada `<rect>` overlay; label kode gerbang wajah (`zone`, `small`,
  `score`, `yaw`, `blur`) diterjemahkan via `live.faceGate.*`; tile besar menampilkan
  badge transport `player-mode`. `EventsPage.tsx`: baris meta "Wajah" pada detail
  event attendance menampilkan nama karyawan + keterangan cooldown atau
  "Tidak dikenal" (payload `employee_name`/`match_reason` dari Task 8). `i18n.tsx`
  menambah kunci `live.faceGate.*`, `events.col.face`, `events.face.*` (id+en).
- Bukti TDD: RED terarah **liveview** import error modul `playerMode`, **events**
  2 failed / 15 passed (testid `event-face-match` tidak ada); GREEN terarah
  **26 passed / 2 files**; full frontend **99 passed / 14 files**, build hijau
  (chunk warning lama), lint exit 0 (22 warning lama, baseline sama).
- Dampak: overlay debugger tidak lagi menampilkan wajah/orang yang sudah keluar
  frame, keterangan gerbang wajah terbaca admin, transport player terlihat,
  hasil absensi terbaca di Events. Rollback: `git revert` commit Task 10. Belum
  deploy/GPU/field verification; tidak ada operasi server.

### R5b Task 9 — editor UI setelan wajah, zona attendance tanpa trigger (lokal, 2026-09-23)

- Konteks/path: `frontend/src/api/detection.ts` type `DetectorSettings` sudah memuat
  lima field wajah (Task 7); `DetectionPage.tsx` kini menampilkan grup Advanced
  "Wajah attendance" (lebar min px, skor deteksi, yaw, blur, jumlah frame K)
  dan mengirim kelima field saat simpan global. `ZonesPage.tsx` mengganti input
  trigger zone attendance dengan petunjuk area wajah (`zone-attendance-hint`);
  `setAttendanceTrigger` dihapus. `GatesPage.tsx` menghapus kolom trigger tabel
  gate dan menambah petunjuk `gates-face-hint`. `i18n.tsx` menambah kunci
  `detection.face*`, `zones.attendanceHint`, `gates.faceHint` (id+en) dan
  menghapus `gates.col.trigger` dari kedua kamus.
- Bukti TDD: RED terarah frontend **3 failed, 20 passed**; setelah implementasi
  GREEN **94 passed / 14 files**, build hijau (chunk warning lama), lint exit 0
  (22 warning lama, baseline sama sebelum/sesudah). Perintah Step 2/4 plan Task 9.
- Dampak: admin mengatur kualitas wajah dari UI tanpa edit env; UI attendance
  tidak lagi menjanjikan trigger detik yang tidak dipakai node wajah. Rollback:
  `git revert` commit Task 9. Deploy frontend harus sinkron dengan backend
  Task 7/8 (PUT wajib lima field). Belum deploy/GPU/field verification; tidak
  ada operasi server.

### R5b Task 8 — cooldown simetris dan sanitasi embedding (lokal, 2026-09-23)

- Konteks/path: `backend/app/services/attendance.py` mencocokkan embedding meski crop
  absen, membuang embedding dari `event.payload` pada semua jalur attendance normal,
  dan menolak baris attendance duplikat bagi karyawan+arah dalam ±5 menit waktu
  event (konfigurabel lewat `ATTENDANCE_COOLDOWN_MIN`). Payload cocok/cooldown
  mencatat identitas dan skor. `backend/tests/test_attendance_logic.py` mencakup
  jalur match, no-match, skip, lintas kamera/arah, batas, dan urutan kirim terbalik.
- Bukti TDD: RED terarah **7 failed, 20 passed**; GREEN **27 passed**; suite
  backend non-GPU **324 passed, 299 warnings** (warning JWT test-key lama).
- Dampak: event tanpa media tetap menghasilkan absensi bila embedding cocok;
  pengiriman event tidak urut tidak membuat absensi duplikat; embedding event baru
  tidak tersimpan setelah handler sukses. Rollback: `git revert` commit Task 8;
  jika rollback seluruh R5b, ikuti urutan migration 0016 pada entri Task 7.
  Belum deploy/GPU/field verification; tidak ada operasi server.

### R5b Task 7 review — urutan rollback migration 0016 (lokal, 2026-09-23)

- Konteks/path: `CHANGELOG.md`, spec R5b §12, dan plan R5b Task 11 Step 2
  sebelumnya menyuruh revert kode sebelum downgrade; Alembic tidak dapat
  menelusuri revision 0016 bila berkas migrasinya sudah hilang. Instruksi kini
  menghentikan layanan, backup DB, downgrade ke 0015 saat migration 0016 masih
  ada, lalu revert/deploy kode lama dan restart. Runbook Task 11 belum dibuat.
- Bukti: pemeriksaan urutan tiga dokumen RED (assertion CHANGELOG), GREEN
  **3 bagian sesuai**; backend non-GPU **315 passed, 299 warnings**, vision
  non-GPU **177 passed, 2 deselected, 2 warnings**, frontend **94 passed / 14 files**.
- Dampak: rollback mendahulukan operasi Alembic selagi revision tersedia;
  pembersihan embedding historis tetap irreversible. Rollback perubahan
  dokumen ini: `git revert` commit review ini saja (tidak dianjurkan bila
  rollback R5b masih dibutuhkan). Tidak ada migrasi/deploy/server/GPU lapangan.

### R5b Task 7 review — simpan setelan deteksi tidak kehilangan field wajah (lokal, 2026-09-23)

- Konteks/path: setelah API PUT mewajibkan lima setelan wajah baru, save lama di
  `frontend/src/features/config/DetectionPage.tsx` mengirim enam field saja dan
  selalu mendapat 422. `frontend/src/api/detection.ts` mengetik kontrak GET/PUT,
  save mengirim kelima nilai wajah yang diterima lewat GET tanpa UI editor baru;
  `frontend/src/__tests__/detection.test.tsx` memeriksa payload sebenarnya.
- Bukti TDD: RED frontend terarah **1 failed, 3 passed** (lima field tidak dikirim),
  GREEN **4 passed**; suite frontend **94 passed / 14 files**; build hijau
  (951 modul, warning chunk besar), lint exit 0 (22 warning lama), backend
  non-GPU **315 passed, 299 warnings**. Diff committed base Task 7 mencakup
  seluruh patch implementasi dan review.
- Dampak: tombol Simpan setelan global tetap bekerja sebelum editor wajah Task 9;
  nilai wajah tidak berubah diam-diam. Rollback: `git revert` commit review ini
  bersama Task 7, jangan rollback review saja selama schema PUT wajib masih aktif.
  Tidak ada deploy/GPU/field verification.

### R5b Task 7 — setelan wajah global + migration 0016 (lokal, 2026-09-23)

- Konteks/path: `backend/app/core/config.py`, `models/detector_setting.py`,
  `schemas/detector_setting.py`, `api/detector_settings.py`, dan
  `services/config_push.py` menambah lima setelan kualitas wajah global pada
  GET/PUT dan config push tanpa mengubah pin device. `.env.example` menambah
  `ATTENDANCE_COOLDOWN_MIN=5` untuk Task 8. Migration
  `backend/alembic/versions/0016_face_gate_settings.py` mengisi default kolom
  dan membuang embedding payload event attendance lama; tes di
  `backend/tests/test_migration_0016.py`, `test_detector_settings_api.py`,
  `test_config_push.py` (fallback dan pin device).
- Bukti TDD: RED migration **1 collection error** (file belum ada), RED API
  **4 failed, 1 passed**; GREEN targeted migration/API/config push **23 passed**;
  suite backend non-GPU **315 passed, 299 warnings**. Tes migrasi berjalan lokal
  dengan SQLite; Postgres/server belum dijalankan.
- Dampak: config gate wajah kini dapat disetel global; PUT butuh lima field baru,
  UI pengaturannya masih Task 9. Pembersihan embedding historis tidak dapat
  dipulihkan. Rollback jika sudah dimigrasi: hentikan API dan vision-node,
  backup DB, jalankan `alembic downgrade 0015` saat berkas migrasi 0016 masih
  tersedia, baru `git revert` rentang commit R5b/deploy kode lama dan restart
  layanan. Payload embedding yang dibuang tidak dapat dikembalikan. Tidak ada
  deploy/GPU/field verification.

### R5b Task 6 review — node idle tetap hidup, arah attendance divalidasi (lokal, 2026-09-23)

- Konteks/path: `vision/vision/node.py` mempertahankan config/heartbeat loop saat
  konfigurasi berisi kamera tetapi tidak ada worker (mis. `VISION_FACE_EMBED=false`
  pada kamera hanya-attendance), termasuk konfigurasi hot-reload; tanpa kamera
  dan tanpa config push tetap boleh berhenti seperti test mode sebelumnya.
  Zona attendance tanpa arah `entry`/`exit` tidak diberikan ke `FaceGateWorker`.
  `vision/tests/test_node.py` menguji startup maupun config push tanpa worker,
  hot-reload setelah idle, dan zona behavior attendance tanpa arah valid.
- Bukti TDD: RED arah invalid **2 failed, 1 passed, 18 deselected**; RED
  node idle **1 failed, 20 deselected** setelah melewati polling 0,2 s;
  GREEN tes terarah **3 passed, 18 deselected**, regresi node/config/worker/pin
  **57 passed**. Suite vision non-GPU **177 passed, 2 deselected, 2 warnings**
  lama (pynvml deprecated dan mock heartbeat tanpa `publish_heartbeat`).
- Dampak: node tidak terputus saat gate tidak dapat dijalankan; event invalid
  tidak memuat embedding yang akan dibuang backend. Rollback: `git revert`
  commit review ini. Pin `cuda:1`/`cuda:2` tetap, GPU/field belum diuji.

### R5b Task 6 — FaceGateWorker terpasang pada VisionNode (lokal, 2026-09-23)

- Konteks/path: `vision/vision/node.py` memisah zona attendance (termasuk legacy
  `absensi`) dari analyzer person, membuka main stream untuk `FaceGateWorker`,
  menghindari YOLO pada kamera hanya-attendance, berbagi satu recorder per kamera,
  dan menambah heartbeat face. Jalur lama dihapus dari `vision/vision/face.py`,
  `vision/vision/recorder.py`, dan `vision/vision/analyzers/face_gate.py`;
  tes lama diganti di `vision/tests/test_node.py`, `test_config_apply.py`,
  `test_node_face_embed.py`, `test_face_embed.py`, `test_recorder.py`,
  `test_intrusion.py`; `vision/tests/test_face_gate.py` dihapus.
- Bukti TDD: RED node 1 error collection (import `attendance_zones`), GREEN node
  16 passed; RED orphan recorder 1 failed/16 deselected, GREEN 1 passed/16
  deselected. Suite vision non-GPU **173 passed, 2 deselected, 2 warnings**
  (pynvml deprecation dan mock heartbeat tanpa method lama); `git diff --check`
  bersih. Pin detector `cuda:1` / face `cuda:2` tidak diubah.
- Dampak: pipeline attendance memakai wajah main stream secara independen;
  kamera campuran tetap menjalankan behavior di YOLO substream, attendance tidak
  lagi memakai clip/crop person. GPU/server/field belum diuji. Rollback:
  `git revert` commit Task 6; tanpa migrasi.

### R5b Task 5 review — burst event tidak menunggu antrean media (lokal, 2026-09-23)

- Konteks/path: `vision/vision/face_worker.py` mengirim event wajah berikut segera
  tanpa media saat satu upload antre/berjalan, bukan mengantre 1,1 s per orang;
  hanya satu finalisasi media per kamera dan riwayat `events` dibatasi 32 payload
  biometrik (transport tetap menerima semua). `vision/tests/test_face_worker.py`
  menguji tiga wajah dengan upload sukses 0,8 s per event dan 34 event untuk
  batas memori. Ruling urutan terima bisa berbeda `ts_event` dicatat di spec §5.5/§6
  dan plan Task 5; Task 8 harus uji cooldown simetris, belum diimplementasi.
- Bukti TDD: RED `2 failed, 20 deselected` (event ketiga ~2,54 s; riwayat 34
  tetap 34); GREEN worker `22 passed`; worker/source/recorder `42 passed`;
  suite vision non-GPU `198 passed, 2 deselected, 2 warnings` (pynvml + mock
  heartbeat lama). Pin detector `cuda:1` / face `cuda:2` tidak diubah.
- Dampak: metadata burst cepat namun media wajah berikut sengaja hilang selama
  kamera sibuk; event pertama masih dapat menyertakan crop/snapshot bila selesai
  dalam 1,1 s. Rollback: `git revert` commit review ini; tidak ada migrasi/tes GPU.

### R5b Task 5 review — overlay tetap lancar saat upload media macet (lokal, 2026-09-23)

- Konteks/path: `vision/vision/face_worker.py` memindahkan finalisasi event dan
  tunggu media 1,1 s ke satu thread per kamera; loop frame/overlay tidak menunggu.
  Saat motion gate melewati frame yang menghapus track terakhir, overlay kosong
  diterbitkan sekali. `vision/tests/test_face_worker.py` menguji cadence overlay
  dengan uploader macet dan force interval > usia track. Spec §5.5 dan plan Task 5
  diselaraskan; kontrak timeout media/backend tidak berubah.
- Bukti TDD: RED `2 failed, 18 deselected` (overlay berikut tertunda saat upload,
  gate skip tidak menghapus kotak). GREEN tes worker `20 passed`; suite relevan
  worker/source/recorder `40 passed`; full vision non-GPU
  `196 passed, 2 deselected, 2 warnings` (pynvml + mock heartbeat lama).
- Dampak: event/media tetap terikat saat upload selesai dalam batas; overlay
  lanjut tanpa menunggu API. Satu finalizer event dan maksimum satu upload tertahan
  per kamera. Rollback: `git revert` commit review ini; pin GPU tidak berubah,
  tanpa migrasi atau verifikasi lapangan.

### R5b Task 5 review — deadline media absolut saat uploader macet (lokal, 2026-09-23)

- Konteks/path: `vision/vision/face_worker.py` menunggu upload media paling lama
  1,1 s walau uploader mengabaikan timeout socket; hanya satu thread daemon upload
  per worker dan event lain tetap terkirim tanpa media selama upload pertama
  macet. `vision/tests/test_face_worker.py` menguji uploader macet 2 s, overlay
  lanjut, dua wajah tetap punya dua event tanpa thread upload tak terbatas.
  Ruling pilihan user dicatat di spec §2/§5.5, plan Task 5, ledger/checkpoint.
- Bukti TDD: RED uploader macet `1 failed, 16 deselected` (event tertahan ~4 s);
  GREEN regresi timeout `5 passed, 13 deselected`; full suite vision non-GPU
  `194 passed, 2 deselected, 2 warnings` (pynvml dan mock heartbeat lama).
- Dampak: batas tunggu pekerja nyata, tetapi short-pass saat API lambat dapat
  terbit ~1,1 s (+ polling ≤0,1 s) setelah `max_age_s`; media yang selesai setelah
  deadline tidak diasosiasikan, blob telat bisa orphan sampai retention.
  Rollback: `git revert` commit review ini; pin GPU tidak berubah, tanpa migrasi.

### R5b Task 5 review — expiry saat stream idle dan upload wajah berbatas (lokal, 2026-09-23)

- Konteks/path: `vision/vision/pipeline/source.py` memberi `next_frame(timeout)` tanpa
  menutup sumber saat idle; `vision/vision/face_worker.py` mengecek expiry walau
  RTSP belum mengirim frame baru. Upload crop/snapshot independen, tiap gambar
  satu percobaan socket 0,5 s agar event dan overlay tidak tertahan retry 60 s.
  `vision/vision/recorder.py` menerima override timeout/retries hanya untuk
  upload blob worker wajah; default recorder lain tetap. Tes di
  `vision/tests/test_face_worker.py` dan `vision/tests/test_source.py`.
- Bukti TDD: RED 3 failed, 13 deselected (idle stream, exception crop,
  enam percobaan upload lambat); GREEN tes terarah worker/source/recorder
  `36 passed`; suite vision non-GPU `192 passed, 2 deselected, 2 warnings`
  (pynvml dan mock heartbeat lama). Tidak ada GPU/server/field verification.
- Dampak: event short-pass bisa terbit setelah sumber diam; keterlambatan upload
  normal dibatasi dua socket timeout 0,5 s. Media mungkin hilang bila API lebih
  lambat; event embedding tetap terbit. Rollback: `git revert` commit review
  Task 5; tidak ada migrasi DB. Pin GPU tidak berubah.

### R5b Task 5 — FaceGateWorker (lokal, 2026-09-23)

- Konteks/path: `vision/vision/face_worker.py` menambah worker wajah di frame main
  stream (source disambung Task 6), motion gate, track per wajah, overlay sebelum
  embedding, satu event attendance per track, crop/snapshot frame terbaik tanpa clip.
  `vision/tests/test_face_worker.py` menguji gate, overlay, expiry, dua wajah,
  outlier, galat mesin/upload, dan media. Pin detector `cuda:1`/face `cuda:2`
  tidak berubah.
- Bukti TDD: RED awal `1 error` (modul worker belum ada); GREEN awal `11 passed`;
  tes tambahan ambang deteksi RED `1 failed, 12 passed`, kemudian GREEN `13 passed`.
  Suite vision non-GPU `188 passed, 2 deselected, 2 warnings` (pynvml dan
  mock heartbeat lama). Tidak ada tes GPU atau verifikasi lapangan.
- Dampak: kontrak worker siap untuk integrasi node Task 6; belum dipakai produksi.
  Rollback: `git revert` commit Task 5; tidak ada migrasi DB.

### R5b Task 4 — gerbang kualitas dan agregasi embedding (lokal, 2026-09-23)

- Konteks/path: `vision/vision/face_quality.py` menambah setelan default wajah,
  pemeriksaan zona/lebar/skor/yaw, skor blur/quality, crop box, dan agregasi berbobot
  dengan filter outlier; `vision/tests/test_face_quality.py` menguji setiap gerbang,
  fallback dan batas frame. Tidak ada perubahan pin detector `cuda:1` / face `cuda:2`.
- Bukti TDD: RED `1 error` (`ModuleNotFoundError: vision.face_quality`); tes
  rencana awal GREEN parsial `1 failed, 11 passed` karena pasangan vektor ortogonal
  semestinya terbuang oleh filter cosine < 0,5. Setelah tes memakai vektor berdekatan:
  `12 passed`; suite vision non-GPU `175 passed, 2 deselected, 2 warnings`
  (pynvml dan mock heartbeat lama).
- Dampak: fungsi murni siap dipakai FaceGateWorker di Task 5; belum ada pipeline
  baru, tes GPU, atau verifikasi lapangan. Rollback: `git revert` commit Task 4;
  tidak ada migrasi DB.

### R5b Task 3 — FaceEmbedder deteksi/align/embed terpisah (lokal, 2026-09-23)

- Konteks/path: `vision/vision/face.py` menambah `FaceDet`, SCRFD + landmark,
  alignment ArcFace 112×112 dan embedding L2; model hanya memuat modul detection
  dan recognition. `vision/tests/test_face_embed.py` menguji kontrak, pin GPU,
  fallback tanpa insightface, dan lazy loading. API `detect`/`embed_jpeg` lama tetap.
- Bukti TDD: RED `5 failed, 7 passed` (method baru belum ada); GREEN
  `12 passed`; suite vision non-GPU `163 passed, 2 deselected, 2 warnings`
  (pynvml dan mock heartbeat lama).
- Dampak: kontrak wajah untuk worker face-first siap secara lokal; provider face
  `cuda:2` tetap, detector `cuda:1` tidak diubah. Belum ada uji GPU/lapangan.
  Rollback: `git revert` commit Task 3; tidak ada migrasi DB.

### R5b Task 2 — FrameSource retry saat stream belum tersedia (lokal, 2026-09-23)

- Konteks: `FrameSource.start()` sebelumnya melempar `RuntimeError` jika go2rtc belum
  menyediakan stream saat worker mulai. `vision/vision/pipeline/source.py` kini
  membiarkan reader mencoba ulang dengan backoff yang sudah ada (1, 2, 4 … 30 s);
  `vision/tests/test_source.py` menguji stream muncul pada upaya kedua.
- Bukti TDD: RED `1 failed, 5 deselected` (`RuntimeError: cannot open video source`);
  GREEN `1 passed, 5 deselected`; suite vision non-GPU
  `158 passed, 2 deselected, 2 warnings` (pynvml dan mock heartbeat lama).
- Dampak: worker tetap hidup ketika stream belum siap saat startup; pin GPU detector
  `cuda:1` dan face `cuda:2` tidak diubah. Belum diuji pada server/GPU.
  Rollback: `git revert` commit Task 2; tidak ada migrasi DB.

### R5b Task 1 review evidence — commit patches (lokal, 2026-09-23)

- Konteks: reviewer hanya menerima diff working tree bersih, bukan dua patch commit
  Task 1; tidak ada cacat kode baru. Path yang diperiksa: `vision/vision/pipeline/tracker.py`,
  `vision/vision/node.py`, `vision/vision/motion.py`, `vision/tests/test_tracker.py`,
  `vision/tests/test_motion_gate.py`, `CHANGELOG.md`. Patch lengkap tersedia lewat
  `git show --format=fuller 0b5fcfa` dan `git show --format=fuller f9ee6be`.
- Bukti: kedua patch terbaca lokal; `git diff 0b5fcfa^ 0b5fcfa --check` dan
  `git diff f9ee6be^ f9ee6be --check` bersih; suite non-GPU diulang lokal:
  `157 passed, 2 deselected, 2 warnings` (`backend/.venv/bin/python -m pytest
  vision/tests -q -m 'not gpu'`). RED/GREEN historis tetap tercatat di bawah.
- Dampak: hanya keterlacakan review, tidak ada perubahan runtime/test baru,
  pin GPU tidak berubah. Rollback: `git revert` commit dokumentasi evidence.

### R5b Task 1 review — expiry sebelum matching (lokal, 2026-09-23)

- Konteks: `vision/vision/pipeline/tracker.py` masih mencocokkan deteksi sebelum
  menghapus track kedaluwarsa. Reconnect tanpa frame >3 s bisa menghidupkan ID lama
  dengan `last_seen` baru; kini track expired dibuang sebelum matching, `lost_ids`
  tetap berisi ID lama. `vision/tests/test_tracker.py` menguji gap tepat 3 s dan 4 s.
- Bukti TDD: RED `1 failed, 1 passed` (gap 4 s mewarisi ID 1); GREEN `2 passed`;
  tes terarah tracker+motion `22 passed`, suite vision non-GPU
  `157 passed, 2 deselected, 2 warnings`. Tidak ada akses GPU/server.
- Dampak: ID tidak bertahan melampaui `max_age_s` saat FrameSource reconnect;
  behavior lain dan pin GPU tidak berubah. Rollback: `git revert` commit review Task 1.

### R5b Task 1 — ByteTracker expiration berbasis detik (lokal, 2026-09-23)

- Konteks: `max_age=15` frame memutus track diam saat motion gate 2 s dan AI FPS ≥ 8.
  `vision/vision/pipeline/tracker.py` kini memakai `max_age_s=3.0` sejak `last_seen`
  untuk expiry; `misses`, `lost_ids`, dan matching tetap. Komentar lama di
  `vision/vision/node.py` dan docstring `vision/vision/motion.py` diselaraskan.
  Tes: `vision/tests/test_tracker.py`, `vision/tests/test_motion_gate.py`.
- Bukti TDD: tes terarah RED 5 failed, 14 passed; tes tambahan reset jam RED 1 failed;
  GREEN 20 passed; suite vision lokal `155 passed, 2 deselected, 2 warnings`
  (`backend/.venv/bin/python -m pytest vision/tests -q -m "not gpu"`).
- Dampak: track bertahan saat gap gate 2 s di 5/10/15 fps; kedaluwarsa setelah
  >3 s tanpa match, sehingga timer behavior tidak reset akibat FPS tinggi.
  Pin detector `cuda:1` / face `cuda:2` tidak diubah. Belum dideploy/diverifikasi GPU.
- Rollback: `git revert` commit Task 1; tidak ada migrasi DB.

## [0.7.0] — 2026-09-21 · Fase 5: GPU hardware probe + device delegation + soak

### GPU hardware probe per node + detector device pin (Task 9)

- Vision node kini melaporkan hardware GPU lewat heartbeat MQTT: kolom `hw`
  (daftar GPU: nama, VRAM used/total, util %, **proses pemakai lintas user** via
  NVML, `python_vram_mb`) dan `modules.detector` (device pin, model,
  ms/frame). File baru `vision/vision/hardware.py` (pynvml, graceful fallback
  `{}` tanpa NVIDIA — heartbeat tetap jalan). Dep baru: `pynvml`.
- Task 9: `VISION_DETECTOR_DEVICE` (mis. `cuda:1`) — pin device detektor,
  diteruskan ke `YOLO.predict`; **fail-fast** saat pin tidak valid (node exit
  dengan log ERROR, bukan fallback senyap ke GPU lain).
- Backend: migration `0009` (`node.hw`, `node.modules` JSON nullable,
  expand-only), heartbeat consumer menyimpan keduanya, `GET /api/v1/nodes`
  mengembalikan. Heartbeat lama tanpa `hw` tetap kompatibel.
- Frontend: kartu **Perangkat node** di Dashboard — GPU chips + proses pemakai
  + badge `Detektor: PIN cuda:N` / `AUTO`. i18n id+en.

### Detector device delegation via UI (Nodes tab) + hot-reload (Task 9 lanjutan)

- Tab **Node** di Konfigurasi: dropdown device per node — sumber dari heartbeat
  `hw`; simpan → config push MQTT → node **hot-reload tanpa restart**.
- Backend: migration `0010` (`node.detector_device`), API
  `PUT /api/v1/nodes/{id}/detector-device` (admin, validasi `cuda:N` + cek hw).
- Prioritas: **DB (config push) > env > auto**; key `device` selalu ada —
  `""` = auto eksplisit. Pin invalid via config push → **reject config, node
  tetap hidup** (beda dari fail-fast start).

### Soak harness + laporan (Task 10–11)

- `deploy/loadtest/`: `make-streams.sh` (32 stream via go2rtc API `ffmpeg:`
  file source), `register-cams.py` (kamera SYNTH-01..N), `soak.sh` (sampler
  30 s per-GPU + RSS), `soak-churn.sh` (remove+add 32).
- Soak 2 jam + churn: **RSS delta 2.2% < 10% = tanpa leak**; GPU1 pinned
  bersih; 0 detector error selama soak. Laporan:
  `docs/evidence/fase-5/soak.md` (termasuk catatan jujur: p95 latensi event
  tak terukur — 0 person di video sintetis).

### RUNBOOK + rekonsiliasi unit (Task 12)

- `docs/RUNBOOK.md` baru: restart/backup/kamera/pin GPU/troubleshooting/
  alert/JWT/retensi/load test.
- `deploy/systemd/` direkonsiliasi ke aktual (`User=gspe-ai3`, path
  `project_cv`, `isentinel-vision`, + `isentinel-web.service`) — P5 tuntas.
- Diagram arsitektur ASCII di README.

### Perbaikan

- Engine TensorRT tidak lintas-device: rebuild `yolo26s.engine` di device pin
  (`CUDA_VISIBLE_DEVICES=1`, smoke 9.9 ms/frame) setelah runtime gagal memuat
  engine lama (dibangun untuk compute 12.0).

Rollback semua: `git revert` + `alembic downgrade` per-migration (expand-only).

## [Unreleased] — R4 Dwell trigger + WS cookie auth + events tabstrip

### WS events auth fallback cookie (Task 1)

- `backend/app/api/events.py`: `ws_events` menerima JWT dari query `?token=`
  **atau** cookie `isentinel_token` (`app.api.deps.COOKIE`). Sebelum ini UI selalu
  ditolak 1008 (JWT httpOnly tak bisa ditaruh di query) sehingga bbox person
  realtime tak pernah sampai Live View debugger.
- Test baru `backend/tests/test_events_ws.py`: cookie valid → konek + terima
  broadcast; tanpa cookie/token dan cookie rusak → 1008; query token lama tetap.
- Bukti: backend `pytest -m "not gpu"` 279 passed. Klien (`frontend/src/api/useWs.ts`)
  menghubung tanpa `?token` (cookie httpOnly saja) — komentar basi di file itu
  ikut dikoreksi agar kontraknya jelas.

### zone.dwell_seconds — trigger setelah N detik di zona (Task 2)

- Migration `0013_zone_dwell_seconds` (expand-only, `Integer NULL=false
  server_default '0'`), kolom model `backend/app/models/zone.py`, dan 3 kelas
  schema (`ZoneIn`/`ZonePatch`/`ZoneOut`, `ge=0`) di `backend/app/schemas/zone.py`.
- `config_push.build_node_config` mengirim `dwell_seconds` di payload zona —
  node memakainya untuk menahan emit event (Task 3). `0` = perilaku lama.
- Bukti: backend `pytest -m "not gpu"` 284 passed; migration round-trip
  `upgrade 0013 → downgrade 0012 → upgrade 0013` pd DB scratch ok, kolom
  `dwell_seconds INTEGER NOT NULL DEFAULT '0'`.

### Vision face_gate hormati dwell zona (Task 3)

- `vision/vision/analyzers/face_gate.py`: `dwell_seconds` > 0 menahan emit
  sampai track sudah di dalam polygon selama itu (jam mulai saat masuk zona,
  reset saat keluar). Cooldown 10s tetap; kunjungan yang tersedot cooldown tetap
  tidak emit. `0` = perilaku lama (emit saat masuk).
- Alasan: crop attendance sering berisi lantai/dinding (orang sudah lewat saat
  frame diambil) — dwell menahan orang di frame hingga crop+snapshot diambil.
- Bukti: `pytest vision/tests -m "not gpu"` 118 passed.

### Events detail tabstrip — revisi: Snapshot | Clip | Face crop (Task 4 review)

- Review user: tab **Detail dihapus** dari tabstrip. Sekarang 3 tab media —
  **Snapshot | Clip | Face crop** (crop hanya untuk event `attendance`, disabled
  bila `payload.crop_path` kosong), default **Snapshot**. Metadata grid
  (**Details**) dikembalikan tampil **di bawah media** untuk semua tab, seperti
  layout awal — bukan lagi tab terpisah.
- `frontend/src/features/events/EventsPage.tsx`, `frontend/src/app/theme.scss`
  (CSS tabstrip tetap), `frontend/src/app/i18n.tsx` (kunci `events.tab.detail`
  dihapus, jadi 2 bahasa). Bukti: `npx vitest run` 81 passed (15 di
  events.test.tsx), `npm run build` ok.

### Events detail tabstrip per mockup 03 (Task 4)

- `frontend/src/features/events/EventsPage.tsx`: panel detail kini tabstrip
  **Detail | Clip | Snapshot | Face crop** (mockup `mockup-ui/03-events.html`).
  Media tidak lagi ditumpuk: Clip = player + unduh, Snapshot = img beranotasi
  bbox/ID, Face crop = crop wajah beranotasi. Metadata grid tetap di Detail.
  Tab Face crop hanya muncul untuk event `attendance` dan **disabled** bila
  `payload.crop_path` kosong; ganti event → tab kembali ke Detail (derived state,
  tanpa effect).
- `frontend/src/app/theme.scss`: `.ev-tabstrip` / `.ev-tab` (+`.on` biru
  `#4589ff`, `:disabled` abu) persis nilai mockup. `frontend/src/app/i18n.tsx`:
  kunci `events.tab.*` + placeholder snapshot/crop, EN+ID.
- Bukti: `npx vitest run` 77 passed (14 di events.test.tsx), `npm run build` ok,
  `npm run lint` tanpa warning baru.

### Setting dwell di UI zona + gate (Task 5)

- `frontend/src/features/config/ZonesPage.tsx`: NumberInput **Dwell (detik)** di
  panel properti zona (semua tipe), helper "0 = langsung";
  `GatesPage.tsx`: kolom **DWELL (S)** per gate (PATCH langsung, disabled untuk
  non-admin). `frontend/src/api/zones.ts`: `dwell_seconds` di `Zone`/`ZonePayload`;
  `ZoneEditor.tsx` ikut menulis `dwell_seconds: 0` untuk zona baru.
- i18n EN+ID: `zones.dwell`, `zones.dwellHint`, `gates.col.dwell`.
- Bukti: `npx vitest run` 80 passed (3× berturut stabil), `npm run build` ok,
  `npm run lint` tanpa warning baru.

### Deploy Task 6 + inventaris behavior deteksi

- Deploy `gspe-ai3`: branch `feat/events-dwell-crop` (1c4d9dc → 541cca3),
  **alembic 0013** (0012 → 0013 head, dari `backend/` dgn `.env` root), event
  debug **#4625 dihapus** (`person_detect` tersisa 0), API restart (health ok),
  vision restart (`kill -9`; SIGTERM hang, 4 camera worker naik).
- Config push diverifikasi di retained MQTT `isentinel/config/server`:
  `cam 363 zones=[(9,'entry',3)]`, `detector cuda:1`, `face cuda:2` — **pin device
  tidak diubah** sesuai keputusan user (zona dwell 3 hanya zona 9 `Absence Server`).
- Bukti lapangan: 6 event attendance pasca-deploy dgn `crop_path`; snapshot
  berisi orang + bbox `ID n` terbakar (diunduh & diperiksa). **Temuan: crop wajah
  masih bisa berisi lantai** — bbox dari frame substream (waktu deteksi) dipetakan
  ke snapshot main stream yang *live* (keyframe bisa 2–4 s basi); crop `#4647`
  benar (face_quality 0.78), `#4650` salah. `attendance_event=0` karena belum ada
  wajah yang match ke karyawan ter-enroll (1 employee, 5 embedding).
- Dokumen baru `docs/detection-behavior-inventory.md`: peta alur, daftar analyzer
  + kondisi trigger persis (intrusion/loitering/running/face_gate/person_detect),
  media per event, dedup + rate limit + alerting, rantai attendance, plus 10
  temuan inkonsistensi untuk pembahasan penataan arsitektur.

### fix(dev): proxy Vite teruskan WebSocket — overlay deteksi akhirnya sampai

- `frontend/vite.config.ts`: proxy `/api` diubah dari string ke objek dengan
  **`ws: true`**. Tanpa ini browser (UI di port 5173) tidak pernah berhasil
  handshake `ws://<host>:5173/api/v1/ws/events` — terbukti: `ws://localhost:5173/...`
  timeout, `ws://localhost:8000/...` connect OK. Akibatnya overlay bbox detection
  di modal debugger Live View tak pernah terisi (zona tetap tampil karena dari REST).
- Jalur backend sudah benar dan diverifikasi: pesan disuntik ke MQTT
  `isentinel/detections/server` → diterima klien WS (cookie auth) sebagai
  `{"type":"detections",...}`.

### Perencanaan R5 + temuan sync go2rtc (Task 0 disetujui)

- Spec keputusan: `docs/superpowers/specs/2026-09-22-detection-model-redesign.md`
  (8 keputusan user: behaviors per zona + master per kamera, `trigger_seconds`
  per behavior, Advanced global, klip segment cache substream, attendance
  face-first substream, motion gate on+override, alias kamera single-stream,
  endpoint+tombol Sync go2rtc).
- Plan eksekusi: `docs/superpowers/plans/2026-09-22-detection-model-r5a.md`
  (Task 0–10; Task 0 = perbaikan sync go2rtc, R5b attendance & R5c klip menyusul).
- Temuan: kamera tanpa substream (ZKteco cam 364) hanya terdaftar sebagai
  `cam_364_main` di go2rtc → worker vision mati (`cannot open video source:
  rtsp://localhost:8554/cam_364`) dan `_save_clip` (yang memakai `cam_<id>`)
  akan gagal; sumber kameranya sendiri sehat (`h264 1920x1080 25fps`). Sync ke
  go2rtc hanya dipicu mutasi lewat API — tidak ada rekonsiliasi saat drift.

### R5 Task 0 — sync go2rtc: alias kamera single-stream + endpoint/tombol

- `backend/app/services/go2rtc.py`: `sync_camera` kini membangun `cam_<id>` dari
  `sub_src or main_src` dan `cam_<id>_main` dari `main_src or sub_src` — kamera
  yang hanya punya satu stream (mis. ZKteco `cam 364`, `rtsp_sub` kosong) tetap
  punya kedua nama, sehingga konsumen (`config_push` node server, `recorder`
  klip, snapshot) tidak lagi menunjuk stream yang tidak ada. Fungsi baru
  `sync_all(db)`: rekonsiliasi `cam_*` go2rtc vs kamera enabled (PUT yang hilang /
  sudah ada, DELETE yang tidak dimiliki, stream non-`cam_*` tidak disentuh).
- `backend/app/api/cameras.py`: `POST /api/v1/cameras/sync-go2rtc` (admin) →
  `{added, removed, kept}`. `backend/app/main.py`: sync best-effort saat startup
  (go2rtc belum tentu siap; gagal = warning, bukan crash).
- Frontend: tombol **Sync go2rtc** di tab Kamera (`data-testid="go2rtc-sync"`) +
  notification hasil `+n / −n stream`; `frontend/src/api/cameras.ts:syncGo2rtc()`;
  i18n EN/ID (`cameras.sync.*`).
- Bukti: backend `pytest -m "not gpu"` **289 passed** (5 test baru: alias sub→main,
  alias main→sub, skip tanpa path, `sync_all` idempotent + stream asing aman,
  endpoint admin-only); frontend `npx vitest run` **82 passed**; `npm run build` ok;
  `npm run lint` 22 warning (tidak bertambah).

### R5 Task 1 — migration 0014: zone.behaviors + setelan deteksi per kamera

- `backend/alembic/versions/0014_zone_behaviors.py`: tambah `zone.behaviors` (JSON),
  `zone.trigger_seconds`, `camera.ai_fps/confidence/analyzers/motion_enabled`
  (expand-only; kolom lama tetap ada). Backfill memetakan data lama → behaviors:
  `absensi`→`attendance` `[{kind:attendance,trigger:dwell}]`;
  `restricted`→`behavior` `[intrusion(trigger=dwell)]` + `loitering(trigger=loiter_seconds)`
  + `running(trigger=dwell,speed_limit_mps)`; `free`→`behavior` `[]`. `downgrade`
  mengembalikan `type` ke kosakata lama (`absensi`/`restricted`) supaya kode pra-R5
  tetap jalan.
- Model + schema: `backend/app/models/{zone,camera}.py`,
  `backend/app/schemas/zone.py` (validator `behaviors`: kind ∈
  intrusion|loitering|running|attendance, `trigger_seconds` int ≥ 0,
  `speed_limit_mps` opsional ≥ 0), `ZoneOut` membawa `behaviors`/`trigger_seconds`.
  `backend/app/api/zones.py`: PATCH type `attendance` wajib `direction`.
- Bukti: backend `pytest -m "not gpu"` **301 passed**; migration round-trip di
  scratch DB: backfill benar (`attendance [{'kind':'attendance','trigger_seconds':3}]`,
  `behavior [intrusion 2, loitering 30, running 2/1.5]`, `free []`), downgrade
  mengembalikan type + drop kolom, upgrade ulang jalan lagi.

### R5 Task 2 — config push: behaviors zona + setelan deteksi kamera

- `backend/app/services/config_push.py`: payload kamera kini membawa `ai_fps`
  (override kamera atau `settings.default_ai_fps`), `confidence` (override atau
  `detector_conf`), `analyzers` (`None` = semua, `[]` = tanpa analitik),
  `motion{enabled,threshold,min_area,force_interval_s}` dan tetap
  `meters_per_pixel` (dipakai analyzer running). Payload zona membawa `behaviors`
  + `trigger_seconds`; kolom lama (`dwell_seconds`,`loiter_seconds`,
  `speed_limit_mps`) tetap dikirim sebagai deprecated sampai node R5 terpasang.
- `backend/app/core/config.py`: setelan baru `default_ai_fps`, `motion_enabled`,
  `motion_threshold`, `motion_min_area`, `motion_force_interval_s` (nilai awal;
  nanti bisa dioverride dari DB di Task 6).
- Bukti: backend `pytest -m "not gpu"` **305 passed** (4 test baru: behaviors zona,
  override kamera, default global, `meters_per_pixel` tetap ada).

### R5 Task 3 — analyzer dibangun dari `behaviors` + master per kamera

- `vision/vision/node.py`: `behaviors_of(z)` (fallback kolom lama bila config
  pra-R5) + `_make_analyzers` membuat analyzer per entry behavior
  (`intrusion`/`attendance`/`loitering`/`running`), dengan `trigger_seconds` dan
  `speed_limit_mps` dari entry. Master `cam.analyzers` menyaring: `None` = semua,
  `[]` = tanpa analitik (hanya live view). `CameraCfg` menerima
  `analyzers`/`confidence`/`motion`.
- `vision/vision/analyzers/intrusion.py`: **trigger threshold** — zona dengan
  `trigger_seconds > 0` menahan emit sampai track bertahan selama itu di polygon
  (jam mulai saat masuk, reset saat keluar); `0` = perilaku lama.
- `confidence` per kamera kini benar-benar dipakai `PersonDetector` (sebelumnya
  field mati): `VisionNode._camera_conf` diisi saat config apply, factory detektor
  memakai `_camera_conf.get(cam_id) or detector_conf`.
- Bukti: `pytest vision/tests -m "not gpu"` **133 passed**.

### R5 Task 4 — motion gate (inferensi hanya saat ada gerakan)

- `vision/vision/motion.py` (baru): `FrameMotionGate` — frame di-downscale 64×36
  grayscale, `absdiff` + threshold piksel (default 25) + blob terbesar via
  `connectedComponentsWithStats`; gerak ≥ `min_area` (default 1%) → inferensi.
  `force_interval_s` (default 2 s) memaksa inferensi berkala agar objek diam tetap
  terdeteksi dan id ByteTrack tidak hilang (jarak frame < `max_age`).
- `CameraWorker` (node.py): gate dipasang dari config kamera; saat tertahan,
  inferensi dilewati dan `tracker.update([], ts)` dipanggil supaya track lama
  expire alami. **Config tanpa `motion` (pra-R5) → gate OFF** (perilaku lama).
- `backend/app/core/config.py`: `motion_threshold` = selisih intensitas piksel
  (0–255, default 25), `motion_min_area` = rasio blob minimum (default 0.01).
- Bukti: `pytest vision/tests -m "not gpu"` **133 passed** (8 test motion baru:
  frame statis tertahan, blok bergerak lolos, interval paksa, noise kecil ditolak,
  worker: 10 frame statis → 1 inferensi vs 10 tanpa gate vs 3 pra-R5).

### Perbaikan tes (flake) — isolasi fake MQTT

- `backend/tests/test_config_push.py`: patch `paho.mqtt.Client` bersifat global
  (modul paho dipakai bersama `events_consumer`), sehingga klien latar ikut
  tercatat di `FakeClient.calls` → `ValueError: too many values to unpack`. Kini
  assertion hanya menghitung klien yang benar-benar `publish`, plus stub
  `reconnect_delay_set`. Bukti: backend `pytest -m "not gpu"` **305 passed** 3×
  berturut (sebelumnya flaky 1 gagal per run).

## [Unreleased] — R3 Live View debugger

### Modal debugger kamera — overlay zona & bbox person realtime

- Vision node publish deteksi per frame ke MQTT `isentinel/detections/{node}`
  (QoS 0 fire-and-forget, drop saat broker putus — data deteksi lama tak berguna).
- Backend `events_consumer` subscribe topic itu → broadcast WS
  `{type: "detections", camera_id, boxes}` melalui hub yang sudah ada.
- Live View: klik tile → **modal debugger** (menggantikan big-on-top lama):
  stream kamera + overlay SVG — toggle **Tampilkan zona** (semua zona kamera,
  label nama+type: absensi hijau, restricted merah) dan **Tampilkan bbox person**
  (kotak + `ID n` oranye, realtime ~0.2s). Tile grid tetap hidup saat modal terbuka.
- person_detect = flag debug (`VISION_EMIT_PERSON_DETECT`, default false) —
  tidak pernah masuk produksi; 88 event debug terhapus dari DB + blob.
- Bukti: vision 113, backend 275, frontend 72, build ok.

## [Unreleased] — R2 Media capture toggles

### Snapshot bawa identitas track + toggle snapshot/clip per zona

- Vision: snapshot event kini **dibakar bbox track + label `ID n`** (warna per
  severity: critical merah, warning oranye, info hijau) — mengikat visual
  orang-pemicu ke snapshot; menjawab laporan "miss" (snapshot vs clip beda orang).
- Zona kini punya **toggle clip** (migration `0012` `zone.clip`, default true)
  di samping toggle snapshot yang sudah ada; recorder akhirnya **menghormati
  keduanya** (sebelumnya toggle snapshot diabaikan — selalu capture dua-duanya).
  Flag zona dibawa ke event envelope oleh worker (`ev.snapshot`/`ev.clip`);
  event tanpa flag (legacy) default capture. Clip tetap 30s post-event —
  go2rtc 1.9.9 tidak mendukung pre-roll (`back` param → 404, terverifikasi).
- UI: tab Zones/Attendance Gates — toggle "Rekam clip event (30 detik)";
  detail Events menampilkan **crop wajah beranotasi** (payload `crop_path`)
  untuk event attendance.
- Bukti: vision 112 test (recorder flags + draw, config apply media), backend
  273 (config push zone clip), frontend 71 + build.

## [Unreleased] — R1 Testing & Refining (anotasi wajah, device split, enrollment)

### Delegasi device per-analyzer (tab Node) + rebuild embedder

- Delegasi GPU kini per-analyzer: **detector YOLO** dan **face recognition**
  masing-masing punya pin sendiri. Backend: migration `0011` (`node.face_device`),
  API `PUT /api/v1/nodes/{id}/face-device` (pola + validasi sama dengan
  detector-device), config push kirim `face: {device}` berdampingan
  `detector: {device}` — struktur map per-analyzer siap diperluas untuk
  analyzer baru. Vision: device face dari config push menang atas env;
  perubahan device → **FaceEmbedder di-rebuild** (provider onnxruntime ikut),
  pin invalid → config ditolak, node tetap hidup.
- UI tab Node: dua dropdown per node (Device detektor / Device face
  recognition), i18n EN/ID; simpan hanya mengirim PUT untuk field yang berubah.

### Anotasi wajah + identitas pada crop attendance

- Vision node: bbox wajah (SCRFD) + label `face <det_score>` digambar pada
  crop attendance **sebelum upload**; `payload.face_bbox` ikut di event.
- Backend: setelah match sukses, crop di-overwrite dengan nama employee +
  match_score (`app/services/annotate.py`, Pillow best-effort — gagal tidak
  memblok attendance). Dep baru backend: `pillow`.

### Enrollment multi-upload + auto-crop + gate

- API baru `POST /employees/{id}/photos/batch` (≤5 foto): per-file hasil
  `{ok, quality, reason, duplicate_of?}` — foto mentah tidak disimpan,
  hanya hasil crop wajah (SCRFD bbox + margin 30%). Dup wajah employee lain
  → warning cosine ≥ `FACE_DUP_WARN` (default 0.6, non-blocking).
- UI Enrollment: input `multiple`, hasil per foto (ok/skor/duplikat/alasan
  gagal), i18n EN/ID.

### Operasional

- Runbook baru `docs/runbooks/events-cleanup.md`; eksekusi 2026-09-21:
  events 4491 → 5 (1 contoh per type dengan 2 media), blob disk terbersihkan.
- Bukti: vision 108 test, backend 272, frontend 70, `npm run build` ok.

## [Unreleased] — Face embed at node (Opsi B)

### Face embedding pindah ke vision node — server hanya match gallery

- **Delegasi wajah per-node**: vision node kini embed wajah sendiri (InsightFace
  SCRFD + ArcFace `buffalo_l`) dari crop yang sudah di-produksi face gate, lalu
  event MQTT attendance membawa `embedding` (512-d L2-normed) + `face_quality`
  (det_score). Backend tidak lagi menjalankan inferensi wajah untuk match —
  cukup cosine vs gallery terpusat (`match_vector`). Gallery tetap di server:
  enroll baru langsung efektif tanpa sentuh edge (kriteria Fase E tetap terpenuhi).
- Kompatibel mundur dua arah: payload tanpa `embedding` → backend embed crop
  seperti sebelumnya (`match_crop`); node tanpa insightface → kirim crop saja.
- File: `vision/vision/face.py` (FaceEmbedder, lazy import + cache gagal),
  wiring `vision/vision/node.py` (`_attach_crop` menempel embedding, embedder
  dibuat sekali per node dan dibagikan ke worker), config node
  `VISION_FACE_EMBED` (default true), `VISION_FACE_DEVICE` (""/cpu/cuda:N),
  `VISION_FACE_MODEL_DIR` (default `<data_dir>/faces_models`). Backend:
  `match_vector()` di `app/services/face.py`, cabang embedding di
  `handle_face_event` (`app/services/attendance.py`). Extra paket vision:
  `face = [insightface>=0.7, onnxruntime-gpu>=1.19]`.
- Bukti: vision 98→104 test (`tests/test_face_embed.py` 5, `tests/test_node_face_embed.py` 6), backend 16 test attendance logic baru (embedding match,
  low_quality reject, fallback crop), full suite backend 265 passed.
- Deploy server: `pip install -e "./vision[face]"` di venv, `VISION_FACE_MODEL_DIR`
  mengarah ke `faces_models` di STORAGE_ROOT, restart `isentinel-vision`.
  Catatan: dep insightface menarik `onnxruntime` (CPU) yang menutupi
  `onnxruntime-gpu` → setelah install, uninstall `onnxruntime` polos atau
  `pip install --force-reinstall --no-deps onnxruntime-gpu` supaya CUDA EP aktif.
- Rollback: `VISION_FACE_EMBED=false` + restart node (kembali kirim crop saja);
  backend menerima kedua bentuk payload tanpa perubahan.

## [Unreleased] — Fase E: Edge Jetson

### Detector device delegation via UI (Nodes tab) + hot-reload

- Admin kini pin GPU detektor **per node via UI**: tab **Node** di
  Konfigurasi — dropdown diisi dari heartbeat `hw` per node (Auto +
  `cuda:N — <nama GPU>`), simpan → config push MQTT → node **hot-reload
  tanpa restart**, badge Dashboard ikut berubah.
- Backend: migration `0010` (`node.detector_device` string nullable),
  `build_node_config()` kirim `detector.device`, API
  `PUT /api/v1/nodes/{id}/detector-device` (admin; validasi format
  `cuda:N` + cek jumlah GPU dari hw heartbeat; 422 bila invalid).
- Prioritas device: **DB (config push) > env `VISION_DETECTOR_DEVICE` >
  auto**; key `device` selalu ada di payload sehingga "" = auto eksplisit.
- Vision `apply_config()`: pin invalid dari config push → **reject config +
  log ERROR, node tetap hidup dengan device lama** (fail-fast exit tetap
  hanya di start).
- Keterbatasan hot-reload: inferensia pindah device seketika, tapi CUDA
  context lama di GPU sebelumnya baru lepas saat proses node direstart.
- Evidence: backend **262 passed**, vision **93 passed**, vitest **68**,
  build OK; live: pin cuda:1 via API & UI → heartbeat `device: cuda:1`
  tanpa restart vision; unpin → `auto`; invalid ditolak 422.
  Screenshots: `docs/evidence/2026-09-18-nodes-tab-pin-cuda1.png`,
  `nodes-tab-en.png`. Rollback: `git revert` + `alembic downgrade 0009`.

### GPU hardware probe per node + detector device pin (Task 9)

- Vision node kini melaporkan hardware GPU lewat heartbeat MQTT: kolom `hw`
  (daftar GPU: nama, VRAM used/total, util %, **proses pemakai lintas user** via
  NVML, `python_vram_mb`) dan `modules.detector` (device pin, model,
  ms/frame). File baru `vision/vision/hardware.py` (pynvml, graceful fallback
  `{}` tanpa NVIDIA — heartbeat tetap jalan). Dep baru: `pynvml`.
- Task 9: `VISION_DETECTOR_DEVICE` (mis. `cuda:1`) — pin device detektor,
  diteruskan ke `YOLO.predict`; **fail-fast** saat pin tidak valid (node exit
  dengan log ERROR, bukan fallback senyap ke GPU lain).
- Backend: migration `0009` (`node.hw`, `node.modules` JSON nullable,
  expand-only), heartbeat consumer menyimpan keduanya, `GET /api/v1/nodes`
  mengembalikan. Heartbeat lama tanpa `hw` tetap kompatibel.
- Frontend: kartu **Perangkat node** di Dashboard — GPU chips + proses pemakai
  + badge `Detektor: PIN cuda:N` / `AUTO` (kuning bila auto). i18n id+en.
- Evidence: vision **89 passed**, backend **256 passed** (`-m "not gpu"`),
  frontend **66 tests**, build OK; live di server: 3 GPU (4090 + 2×5080) +
  proses vLLM/isaacsim/vision tampil. Screenshots:
  `docs/evidence/2026-09-18-dashboard-node-hw-{en,id}.png`.
  Rollback: `git revert` + `alembic downgrade 0008`.

### Camera flow polish: self-contained wizard, compact panel, columns

- Wizard self-contained: field **Port** (default 554) di samping IP/Host;
  endpoint host = `ip` atau `ip:port`. Panel **Sumber & kredensial** collapsed
  jadi satu baris ringkasan (khusus import CCTV / perubahan NVR); section Grup
  dihapus dari UI (grup auto dari Lokasi); CamerasPage berhenti fetch
  `/location-groups`. List kamera: **kolom Lokasi terpisah** dari Nama.
  Live View: filter lokasi bisa direset ke **All locations** (item `__all__`).
- Evidence: frontend **13 files / 65 tests passed**, build **949 modules**;
  verifikasi browser di server (port default 554, form grup hilang, reset
  filter terbukti). Screenshots: `docs/evidence/camera-page-compact-final.png`,
  `camera-wizard-v3-port.png`, `camera-list-location-column.png`,
  `live-view-filter-all.png`. Rollback: `git revert`.

### Camera management: wizard sederhana + scan channel + FK SET NULL

- Wizard "Tambah kamera" disederhanakan sesuai keputusan desain: field Nama, Lokasi,
  IP/Host, Node, lalu "Deteksi otomatis" (POST `/api/v1/cameras/scan` memindai channel
  NVR 1-32 paralel wave, berhenti 2 wave kosong; dropdown stream terdeteksi dengan
  label `ch N — MAIN res·codec / SUB res·codec`, pilihan pertama otomatis terpilih),
  fallback "Isi path manual" (MAIN/SUB + probe exact). Combobox Sumber stream/Grup
  lokasi/Override kredensial dihapus dari wizard; grouping kini otomatis dari teks
  Lokasi (get-or-create grup sama nama, backend `_prepare_camera_data`), masih bisa
  eksplisit lewat import. Error simpan kini InlineNotification (409 duplicate jelas
  terlihat), bukan teks kecil. `LocationGroupSelect.tsx` dihapus (tak terpakai).
- `POST /api/v1/cameras/scan` (admin) + `scan_camera_channels()` di services/probe.py.
- Migration `0008`: `alert.camera_id` nullable + FK `event/alert.camera_id` →
  `ON DELETE SET NULL` (hapus kamera tidak lagi 500 oleh event/alert lama).
- Evidence: backend **252 passed**, frontend **13 files / 64 tests passed**,
  `npm run build` 949 modules. Rollback: `git revert` + alembic downgrade 0007.

### Agent contributor guide

- `AGENTS.md` (new) documents project overview, tech stack, key features, structure,
  commands, coding conventions, workflow, current-state pointers, and the repo rules
  (incl. the no-AI-attribution rule). Derived from the actual tree: `backend/app/*`,
  `vision/vision/*`, `frontend/src/*`, `deploy/*`, `docs/*`, `pyproject.toml`s,
  `package.json`, `.env.example`. Server credentials are deliberately NOT recorded —
  only host/IP/paths plus a pointer to the gitignored note and server `.env`.
  Alongside: `README.md` server path corrected `/opt/isentinel` →
  `/home/gspe-ai3/project_cv/I-Sentinel`, stale "frontend placeholder" line replaced,
  and the repo-vs-running systemd unit mismatch (Fase 5 Task 12) plus the
  no-passwordless-sudo restart procedure noted; `frontend/package.json` gained
  `"test": "vitest run"`; `.gitignore` now excludes `.commandcode/`,
  `.cooperstructure/`, `.impeccable/`. Evidence: `npm test` → **13 files / 64 tests
  passed** in 32.26s. Impact: agents and new contributors get one accurate entry
  point; no runtime code touched. Rollback: `git revert` the two commits.

### Runtime data layout

- Runtime data on `gspe-ai3` now lives under the sibling
  `/home/gspe-ai3/project_cv/I-Sentinel-data/{api,vision}` instead of the Git
  worktree/default home paths. `.env` carries `STORAGE_ROOT`, `FACE_MODEL_DIR`,
  and `VISION_DATA_DIR`; old roots were copied, not deleted. Evidence: API health
  returned `{"status":"ok"}`, both systemd services are active, live process
  environments report the target paths, and target contents include
  `clips/crops/faces/faces_models/models/snapshots` plus `outbox/queue`. Impact:
  deployments no longer mix runtime growth with source checkout. Rollback:
  restore `.env.before-runtime-migration-20260916-160718` and restart API/vision;
  delete neither old root until separately approved.

### Camera management B′

- `feat/camera-management-b-prime`: adds source-aware camera management in
  `backend/app/models/camera.py`, `backend/app/models/credential_profile.py`,
  `backend/app/models/location_group.py`, `backend/app/models/stream_source.py`,
  `backend/app/api/cameras.py`, `backend/app/api/probe.py`,
  `backend/app/api/credential_profiles.py`, `backend/app/api/location_groups.py`,
  `backend/app/api/stream_sources.py`, `backend/app/schemas/camera.py`,
  `backend/app/schemas/credential_profile.py`, `backend/app/schemas/location_group.py`,
  `backend/app/schemas/stream_source.py`, `backend/app/services/stream_endpoint.py`,
  `backend/app/services/probe.py`, `backend/app/services/go2rtc.py`,
  `backend/app/services/config_push.py`, `backend/scripts/camera_management_migrate.py`,
  `backend/alembic/versions/0007_camera_management_expand.py`,
  `frontend/src/api/cameras.ts`, `frontend/src/api/credentialProfiles.ts`,
  `frontend/src/api/locationGroups.ts`, `frontend/src/api/streamSources.ts`,
  `frontend/src/features/config/CamerasPage.tsx`,
  `frontend/src/features/config/CameraWizard.tsx`,
  `frontend/src/features/config/CameraSourcesPanel.tsx`,
  `frontend/src/features/config/LocationGroupSelect.tsx`,
  `frontend/src/app/i18n.tsx`, `.env.example`, and
  `docs/runbooks/camera-management-migration.md`. Evidence: offline PostgreSQL
  Alembic SQL contains all five required `0007` statements; backend **249/249**
  collected tests passed in isolated batches; focused frontend **3 files / 19 tests**
  passed; `npm run build` transformed **950 modules** in **5.94s**. Impact: admins
  manage sources, locations, and environment-referenced credentials without API
  secret leakage while legacy camera fields remain compatible. Rollback: follow
  `docs/runbooks/camera-management-migration.md`; no server migration was run.

### CCTV inventory import

- `0f2a4b3`: safe admin-only import parses `temp/data/cctv-list.txt` in
  `frontend/src/features/config/CamerasPage.tsx`, then previews/applies normalized
  `(host, rtsp_main)` matches in `backend/app/api/cameras.py` and
  `backend/app/schemas/camera.py`; `frontend/src/api/cameras.ts` and
  `frontend/src/app/i18n.tsx` carry the contract. Existing camera IDs and probe metadata stay
  intact; apply refuses unmatched or invalid input and never deletes cameras. Coverage:
  `backend/tests/test_cameras_api.py` and `frontend/src/__tests__/cameras.test.tsx`.
  Evidence: backend camera API **14 passed**, frontend cameras/events/alerts **23 passed**,
  `npm run build` (**945 modules transformed**), server preview at `192.168.2.133:5173`
  returned **24/24 matched, 24 changed**, then explicit approval produced
  `POST /api/v1/cameras/import?apply=true` **200**, `applied=true`, **24 updated**, **0 errors**,
  **0 unmatched**. GET verification returned **25 total**: imported IDs **4–27** match every
  file name/location/path; legacy ID 3 (`Cam 1`, `192.168.0.64`) stayed untouched by the
  no-delete contract. Screenshots: `docs/evidence/camera-import-preview-desktop.png` and
  `docs/evidence/camera-import-applied-desktop.png`. Rollback: revert `0f2a4b3` for code;
  restore pre-import values from the preview `before` payload for data.

### Camera Edit & Events triage

- `feat/camera-edit-events` (`35bd458`, `6b48bd9`, `29301bc`, `a3753f7`): Camera admin kini
  punya tombol **Ubah** dengan wizard terisi; perubahan metadata tersimpan langsung, sedangkan
  perubahan host/node wajib probe baru. Probe edit tidak menulis state sebelum **Simpan** dan
  respons probe lama diabaikan. Perubahan source: `frontend/src/features/config/CamerasPage.tsx`,
  `frontend/src/features/config/CameraWizard.tsx`, `frontend/src/app/i18n.tsx`,
  `backend/app/schemas/camera.py`; coverage: `frontend/src/__tests__/cameras.test.tsx` dan
  `backend/tests/test_cameras_api.py`.
- Events diubah menjadi master-detail triage mengikuti `mockup-ui/03-events.html`: filter tipe/
  kamera/severity, rentang 24 jam/7 hari/30 hari/semua, pencarian, jumlah hasil, tombol baris
  yang keyboard-accessible, metadata/media nyata, dan status alert/Telegram tetap memakai API
  yang ada. Tidak ada fake zone history/tracking/false-positive dan tidak ada penghapusan riwayat.
  Perubahan source: `frontend/src/features/events/EventsPage.tsx`, `frontend/src/app/theme.scss`,
  `frontend/src/app/i18n.tsx`; coverage: `frontend/src/__tests__/events.test.tsx`.
  Bukti: focused frontend **3 files / 22 tests PASS**, camera API **11 passed**, `npm run build`
  (**945 modules transformed**, **8.21s**), dan Playwright langsung ke `192.168.2.133:5173`
  membuktikan modal Camera Edit prefilled + gate probe, Events search/range/detail, serta mobile
  tanpa horizontal overflow (`documentScrollWidth=375`, viewport `390`). Screenshot:
  `docs/evidence/camera-edit-desktop.png`, `docs/evidence/events-redesign-desktop.png`, dan
  `docs/evidence/events-redesign-mobile.png`. Dampak: admin dapat mengubah kamera tanpa
  mengandalkan User Management; operator mendapat triage event ringkas tanpa mengubah data
  historis. Rollback: revert `29301bc`, `6b48bd9`, `a3753f7`, `35bd458` (kembali ke `f3d960f`).

### UI shell & Configuration workbench

- `feat/ui-shell-configuration` (`79fe25a`, `e6b12c5`, `8b29e8a`, `918d526`, `dbb093d`,
  `eacc1dc`, `1404c57`): konsolidasi empat halaman admin menjadi satu workbench
  `/configuration?tab=cameras|zones|gates|storage`; sidebar kini punya satu entry
  Configuration di System, logout berada di kartu akun, rail Carbon tidak melebar saat
  link menerima pointer/fokus keyboard, label toggle mengikuti state desktop/mobile,
  dan editor Zones menumpuk pada viewport sempit. Perubahan source: `frontend/src/app/AppShell.tsx`,
  `frontend/src/app/theme.scss`, `frontend/src/app/i18n.tsx`, `frontend/src/main.tsx`,
  `frontend/src/features/config/ConfigurationPage.tsx`,
  `frontend/src/features/config/CamerasPage.tsx`,
  `frontend/src/features/config/ZonesPage.tsx`,
  `frontend/src/features/config/GatesPage.tsx`,
  `frontend/src/features/config/StoragePage.tsx`. Regression coverage diperbarui di
  `frontend/src/__tests__/shell.test.tsx`, `frontend/src/__tests__/configuration.test.tsx`,
  `frontend/src/__tests__/cameras.test.tsx`, `frontend/src/__tests__/zones.test.tsx`,
  `frontend/src/__tests__/gates.test.tsx`, dan `frontend/src/__tests__/storage.test.tsx`.
  Bukti: focused Vitest **6 files / 26 tests PASS**, `npm run build` (**945 modules transformed,
  built in 6.59s**), Playwright langsung ke `192.168.2.133:5173` membuktikan empat tab,
  fallback query invalid/missing, back/forward, Gate → Zones, rail pointer/keyboard,
  logout expanded/rail, mobile query-close, dan Zones tanpa horizontal overflow.
  Screenshot: `docs/evidence/ui-shell-configuration-desktop.png` dan
  `docs/evidence/ui-shell-configuration-mobile-zones.png`. Dampak: admin mendapat satu
  konteks konfigurasi tanpa kehilangan operasi panel yang ada; rollback: revert commit
  `1404c57`, `eacc1dc`, `dbb093d`, `918d526`, `8b29e8a`, `e6b12c5`, lalu `79fe25a`.

- `0b0e3ca` feat: playback live view memakai **mainstream** (`cam_N_main`) — WebRTC/MSE/HLS
  URL `/live` beralih dari sub ke main; substream tetap milik AI (vision pull RTSP lokal) +
  snapshot fallback. Terbukti di browser LAN: 24/24 tile playing, 23 tile ≥1920 lebar
  (`docs/evidence/fase-5/live-mainstream.png`). Catatan: backend URL berubah → API harus
  restart setelah pull.

- `6de1c50`/`06e7869` feat: live view streaming go2rtc — `<video-stream>` (vendor player
  resmi go2rtc video-rtc.js v1.6.0) mode `webrtc,mse` per tile; fallback snapshot proxy
  2 detik kalau transport gagal 10 s; backend tidak berubah (URL `/live` yang sudah ada).
  Syarat infra: firewall ufw LAN membuka 1984/tcp + 8555/udp, dan `api.origin` go2rtc
  diperluas (go2rtc menolak WS handshake 403 dengan Origin web). Bukti: Playwright di
  `docs/evidence/fase-5/live-streaming.png` — **24/24 tile playing** (readyState 4),
  fokus tile playing, go2rtc RSS 160 MB / CPU ~10%.

## [0.6.0] — 2026-09-16 · Fase 5: Hardening (Task 1-8)

Hardening retensi, keamanan, dan resiliensi. Sistem live di server terverifikasi:
migration 0006 diterapkan, API restart + route baru aktif, halaman Retensi & Storage
berjalan dengan data nyata, harness resiliensi **5 PASS / 0 FAIL**.

### Perubahan

- **Retensi dua-lapis** (`82538f7`, `21d4931`): `Event.media_expired` + migrasi 0006;
  sweeper `app/services/retention.py` — lapis DB (event > `RETENTION_DAYS` → file dihapus,
  event ditandai, path di-null-kan) + sapuan orphan (file tanpa baris event, berbasis mtime),
  dengan guard path-escape (`_safe_join` — path DB tak bisa menghapus di luar `storage_root`)
  dan dry-run yang tidak menyentuh apa pun.
- **API storage** (`1962cad`): `GET /api/v1/storage/stats` (disk, per-jenis, sweep terakhir
  dari `Setting.retention_last_sweep`) + `POST /api/v1/storage/sweep?dry_run=` (admin-gated);
  helper test `admin_headers`/`viewer_headers` di conftest.
- **Entrypoint + timer systemd** (`5618396`): `backend/scripts/retention_sweep.py`
  (bootstrap sys.path supaya `python scripts/…` jalan tanpa install paket) + unit
  `deploy/systemd/isentinel-retention.{service,timer}` (03:00 harian, `Persistent=true`).
  **Pemasangan di server menunggu user (sudo).**
- **Halaman Retensi & Storage** (`9e485e7`): route `/config/storage`, nav admin-only,
  kartu disk/retensi/path, tabel per jenis, kartu sweep terakhir, tombol Dry run +
  Jalankan sekarang; i18n ID/EN. Bukti: `docs/evidence/fase-5/storage-page.png`,
  `storage-dryrun.png` — data cocok `df -h` (915G, sisa 132G); dry run UI terbukti
  `2117 → 2117` file.
- **Rate-limit login** (`6da6af3`): 429 + `Retry-After` setelah `login_max_attempts`
  gagal per (username, ip); reset saat login sukses; state per-proses (uvicorn satu
  worker); fixture autouse reset `_FAILURES` mencegah kebocoran antar-test —
  full suite **215 passed** saat itu.
- **Sisa keamanan pass** (`1171d5e`): PATCH attendance ternyata sudah admin-gated
  (2 test penegasan); keputusan CORS (sengaja tak ada, same-origin) + rotasi JWT
  (prosedur operasional) tercatat di `docs/plans/00-master.md`.
- **Harness resiliensi** (`cf09af8`, `df2e3b0`, `85b14b1`): `deploy/loadtest/resilience.sh`
  — polling status node dengan deadline, bukan sleep tetap (LWT retained datang
  segera setelah kill -9; sleep tetap 20/30 s sempat menghasilkan FAIL palsu).
  Bukti: `docs/evidence/fase-5/resilience.txt` — 5 PASS / 0 FAIL di gspe-ai3.

### Verifikasi

- Backend: **217 passed** (204 sebelum Fase 5 + 6 retensi + 3 storage + 2 ratelimit + 2 security)
- Frontend: **39 passed** + `npm run build` sukses
- Alembic: 0005 → 0006 diterapkan di server (PostgreSQL) sebelum restart API
- Server `gspe-ai3`: main @ `85b14b1`, API + web aktif, node vision online

### Ditunda (keputusan user)

- Task 9-12 (pin GPU, generator stream sintetis, soak, dokumentasi operasional).
  D1 (GPU mana + durasi) dan D2 (izin `sudo apt install ffmpeg`) belum diambil.
- Pemasangan unit `isentinel-retention.{service,timer}` ke `/etc/systemd/system/`
  butuh `sudo` — perintah siap, menunggu user.

## [0.2.0] — 2026-09-15 · Fase 1: Vision Inti

Pipeline vision end-to-end: YOLO26s TensorRT (nms=False) + ByteTrack → MQTT → DB → dashboard/live/events. Terverifikasi 4 kamera NVR via go2rtc di server GPU.

### Commits (ringkas)

- `728de79`/`0449061` feat: event model, ingest idempotent, events API + ws hub
- `3454791` feat: mqtt events consumer (events + node lwt)
- `1098d86` feat: go2rtc stream sync + live url endpoint
- `9d5746e` feat: vision pipeline stages (source, detector iface, byte tracker)
- `b09c6cc`/`d3c5e7d` feat: vision node runner (mqtt transport, disk queue, graceful)
- `0d60702` feat: yolo26s tensorrt export script + gpu smoke test
- `cef8afa` feat: internal heartbeat ingest + node staleness + vision deploy files
- `3dced18` feat: dashboard tiles, live view (snapshot), events live list
- `f25c664` fix: g100 dark theme via css custom properties
- `ea892ee`/`e5a8302` fix: ts_event wall-clock (monotonic offset)
- `1bdb19b`/`9c25396`/`17f3d10` fix: ingest node-by-name + iso parsing + relationship
- `2a65d4c` feat: consumer marks node online from heartbeat topic

### Highlights

- **vision/** paket terpisah (tanpa FastAPI): pipeline source→detector→tracker→emit, DiskQueue store-and-forward, LWT+heartbeat MQTT
- **YOLO26s TRT FP16 nms=False**: 1.7 ms/frame di 4090, 762 MB GPU
- **Backend**: consumer MQTT (events/heartbeat/LWT), idempotent ingest, WS broadcast, go2rtc sync
- **Frontend**: dashboard tile hidup, live view snapshot grid (fokus+fullscreen), events list realtime

## [0.5.5] — 2026-09-15 · Zero-secret: dua file config ter-track

Ditemukan saat menjawab pertanyaan "apakah semua fitur berjalan?". Keduanya kelas yang sama
dengan temuan `.git/config` sebelumnya: **file template dan file runtime memakai nama yang sama**.

### Perbaikan

- `c391359` fix(security): `deploy/go2rtc/go2rtc.yaml` ter-track padahal dipakai go2rtc
  sebagai config runtime dan stream di dalamnya memuat kredensial RTSP kamera. Di server
  file itu 51 URL `rtsp://` (25 kamera × main+sub) dengan mode **664 (world-readable)**,
  dan karena ter-track, `git add -A` di server akan meng-commit semuanya.
  → `go2rtc.yaml` jadi `go2rtc.example.yaml` (template, tetap tracked) + `.gitignore`
  menambah `deploy/go2rtc/go2rtc.yaml`. Path runtime tidak berubah, unit systemd tidak disentuh.
- `e9a764b` fix(security): `vision.env` tidak ter-ignore — pola `.env` (nama persis) dan
  `.env.*` tidak menangkapnya. Tambah `*.env` + negasi `!*.env.example`.
- `c4bd09d` fix(ui): kamera `enabled=false` tidak lagi tampil di Live View

### Diverifikasi tidak bocor

- `git log -S gspe123456` / `-S gspe-intercon` / `-S 'admin:gspe'` → **0 commit**
- `git grep` kredensial di file ter-track → kosong
- Yang berisi kredensial hanya working copy server, tidak pernah ter-commit
- Setelah perbaikan: `git status` di server bersih, `git ls-files deploy/go2rtc/` hanya
  menyisakan `go2rtc.example.yaml`, config runtime mode **640**

### Catatan

Kredensial kamera ikut tercecer ke transcript sesi ini saat diagnosis (isi `go2rtc.yaml`
server ikut ter-dump oleh batch command). Kalau transcript ini tersimpan di tempat bersama,
kredensial kamera di jaringan CCTV perlu dianggap perlu dirotasi.

## [0.5.4] — 2026-09-15 · Live view benar-benar jalan dari klien LAN

`7c89eb1` fix(backend): `GET /api/v1/cameras/{id}/snapshot` mem-proxy frame go2rtc lewat API.

Urutan kejadiannya penting untuk dicatat:

1. Sebelum sesi ini: `snapshot` = `http://localhost:1984/...` (host dari header `Host`
   yang dihancurkan proxy Vite) → tiap tile gagal cepat, live view mati.
2. `fd42e31` memperbaiki host ke `GO2RTC_PUBLIC_HOST` → malah LEBIH BURUK: tiap tile
   menggantung 5 detik, karena port 1984 diblokir firewall server.
3. Diukur dari klien: `5173`/`8000`/`1883` TERBUKA, `1984`/`8554` TIMEOUT (connect DROP).
   `ss -lntp` menunjukkan go2rtc bind `*:1984` — jadi murni firewall.
4. Diperbaiki dengan proxy, bukan dengan membuka port.

Alasan memilih proxy: API go2rtc **tidak punya autentikasi**. Membuka 1984 ke LAN berarti
siapa pun di jaringan bisa membaca semua stream kamera. Proxy memakai port 8000 yang sudah
terbuka dan sudah di belakang `get_current_user`, jadi permukaan serangan tidak bertambah.

- `snapshot` kini path same-origin `/api/v1/cameras/{id}/snapshot` (butuh login, 401 tanpa sesi,
  502 bila go2rtc tak terjangkau — bukan 500)
- `webrtc`/`mse`/`hls` tetap URL go2rtc langsung; WebRTC nanti butuh 1984 dibuka atau
  di-proxy juga. `GO2RTC_PUBLIC_HOST` tetap dipakai untuk ketiga field itu.

### Bukti

- Di klien: 25 tile, gambar pertama `640x360 host=192.168.2.133:5173`, rata-rata kecerahan 106
  (bukan frame hitam). Satu kamera go2rtc 502 → tile-nya otomatis jadi OFFLINE
  (`tileOffline=1`), 24 lainnya render — degradasi rapi, bukan gagal total
- `curl` di server: `/snapshot` tanpa login → **401**, dengan login → **200 image/jpeg 44623 bytes**
- `pytest backend/tests` **203 passed** (+2) · `pytest vision/tests` **79 passed, 2 skipped** ·
  `npx vitest run` **37 passed** · `npm run build` sukses

## [0.5.3] — 2026-09-15 · Responsif: nol overflow horizontal di 390px

Audit 9 halaman di viewport 390px menemukan 4 halaman bisa di-scroll ke samping.
Semua diperbaiki; sekarang 9/9 `docOverflow=0`, termasuk `window.scrollX` setelah
`scrollTo(500,0)` — bukan cuma angka `scrollWidth`.

| Halaman | Sebelum | Sesudah | Penyebab |
|---|---|---|---|
| /events | 132px | **0** | 3 dropdown filter tidak wrap; `<dl>` detail memakai grid `auto 1fr` dengan UUID tanpa titik putus; grid master-detail menyusutkan panel detail ke ~30px tapi isinya (thumbnail 72px, `<video>`) punya `min-width:auto` |
| /attendance | 115px | **0** | baris tab + tombol Import/Export tidak wrap |
| /config/gates | 23px | **0** | overflow tabel tembus ke halaman walau `.cds--data-table-content` sudah `overflow-x:auto` |
| /live | 0 (tapi chip menimpa judul) | **0** | `.app-page__head` flex tanpa wrap, anak pertama `flex:1` boleh menyusut sampai 0 |
| 4 lainnya | 0 | 0 | — |

### Perbaikan

- `a0ab278` fix(ui): `.app-page__head` `flex-wrap` + basis 280px — aksi turun ke baris
  sendiri di layar sempit, tidak menimpa judul. Kena /live, /events, /enrollment, /config/cameras
- `f30dfa9` fix(ui): filter /events wrap (basis 200px / maks 240px) + baris tab /attendance wrap
- `ce081ee` fix(ui): `overflow-wrap:anywhere` pada `<dl>` detail event — min-content kolom
  `1fr` jadi satu karakter, tidak lagi selebar UUID
- `15505a4` fix(ui): scroller di `.cds--data-table-container` — diverifikasi dengan uji
  sembunyikan-elemen di browser (menyembunyikan container → overflow 0; menambah
  `overflow:hidden` di wrapper dalam tetap 23)
- `2e5abf4` fix(ui): `/events` ditumpuk satu kolom di bawah 900px; desktop tetap master-detail

### Bukti

- Pengukuran per halaman di 390px: `/dashboard /live /events /attendance /enrollment
  /config/cameras /config/zones /config/gates` → semua `overflow=0 scrollX=0`
- Screenshot mobile + desktop: `docs/evidence/ui-polish/after/`
- `pytest backend/tests` **201 passed** · `pytest vision/tests` **79 passed, 2 skipped**
- `npx vitest run` **37 passed** · `npm run build` sukses · `npx oxlint` 0 error

## [0.5.2] — 2026-09-15 · Penutup polish + bug live view LAN

Menutup dua elemen mockup yang belum dikerjakan, plus satu bug nyata yang
membuat Live View mati untuk semua klien LAN.

### Perbaikan

- `fd42e31` fix(backend): host go2rtc untuk browser tidak lagi diturunkan dari header
  `Host`. Proxy Vite dev mengirim `Host: localhost:8000` ke API → klien menerima
  `http://localhost:1984/api/frame.jpeg`, yaitu mesin klien sendiri. Live View mati
  total di luar server. Setting baru `GO2RTC_PUBLIC_HOST` (kosong = perilaku lama).
  Fix `9fcfbee` sebelumnya mengganti host ke host request, tapi sumbernya sudah rusak.
- `4413a7e` chore(.gitignore): `.env` tidak mengabaikan `.env.bak.*` / `.env.local`

### Fitur (elemen mockup yang tersisa)

- `9ca496c` feat(ui): Live View — chip "3/2/4 kolom" + filter "Semua lokasi" (mockup 02),
  pilihan kolom persist; dipaksa turun di layar sempit (≤1055px → 2, ≤671px → 1).
  Grid disamakan mockup: gap 1px di atas `#393939` + border luar.
- `9ca496c` feat(ui): /config/zones — daftar zona di bawah editor dengan swatch tipe,
  badge tipe + AKTIF/NONAKTIF, klik baris = pilih zona (mockup 06).

### Bukti

- `curl` lewat proxy Vite (jalur browser) sebelum/sesudah:
  `"snapshot":"http://localhost:1984/..."` → `"snapshot":"http://192.168.2.133:1984/..."`
- `pytest backend/tests` **201 passed** · `pytest vision/tests` **79 passed, 2 skipped**
- `npx vitest run` **37 passed** · `npm run build` sukses · `npx oxlint` 0 error
- Screenshot Live View (toolbar kolom + grid 3 kolom): `docs/evidence/ui-polish/after/`

### Keamanan (temuan sesi ini, sudah ditindak)

- PAT GitHub tersimpan plaintext di `.git/config` (remote URL) → sudah dicabut dari URL;
  autentikasi lewat Git Credential Manager. **Token-nya sendiri masih perlu di-revoke user.**
- `temp/data/` (gitignored, tidak pernah masuk history) berisi PAT, kredensial kamera uji,
  dan catatan login SSH plaintext → dipindahkan ke `~/.isentinel/secrets/` di luar pohon proyek.
- Tidak ada rahasia di file ter-track maupun di git history (diverifikasi `git grep` +
  `git log -S`). `.env` server mode 600.

## [0.5.1] — 2026-09-15 · UI/UX Polish

Semua 9 halaman dibuat proper terhadap mockup 01–06. Murni frontend — tidak ada perubahan
perilaku backend. Tiga bug fondasi yang sejak Fase 0 membuat tiap halaman salah tampil
diperbaiki di akarnya (offset konten, token tema, pemuatan font).

### Perbaikan

- `6c6545f` fix(ui): konten tertimpa sidebar fixed di semua halaman; sidebar rail collapse 48px
  (ikon saja, tanpa hover-expand, persist localStorage); markup `<ul>` valid; IBM Plex Sans akhirnya
  termuat; layout halaman diseragamkan (`.app-page`)
- `f9b4f9e` fix(ui): token g100 di-emit Carbon, bukan 31 token tulis-tangan — select "Arah" di
  /config/gates tidak lagi berlatar putih dengan teks putih
- `e2fe1d2` fix(ui): state no-signal untuk tile live view (ikon + OFFLINE + timestamp + badge
  LIVE/OFFLINE) dan fallback snapshot editor zona (tidak ada lagi ikon gambar rusak)
- `40b9548` fix(ui): brand header tidak lagi pecah dua baris di viewport < 480px
- `b5df1c9` fix(ui): /events, /live, /dashboard menampilkan error saat request gagal, bukan empty
  state yang menyesatkan; CamerasPage disamakan memakai `lowContrast`

### Bukti

- Screenshot sebelum/sesudah 9 halaman + rail/mobile/EN: `docs/evidence/ui-polish/`
- `npx vitest run` 36 passed · `npm run build` sukses · `pytest backend/tests` 199 passed ·
  `pytest vision/tests` 79 passed, 2 skipped · `npx oxlint` 0 error

## [Unreleased]

### R5a — Detection & Model

- Task 5: Live View debugger menerima payload deteksi `kind` (`person`/`face`) dan `label`; toggle menjadi **Tampilkan deteksi**, dengan bbox person oranye dan wajah biru.
- Task 6: `detector_setting` singleton dan API admin menyimpan override global FPS/confidence/motion; `config_push` mendahulukan DB daripada `.env` dan menerbitkan ulang konfigurasi node.
- Task 7: PATCH kamera menerima override AI FPS, confidence, analyzer, dan motion; perubahan memicu config push node terkait.
- Task 8: tab **Deteksi & Model** menampilkan nilai global efektif, override per kamera, chip analyzer, dan Advanced untuk motion gate.
- Task 9: editor zona memakai kosakata baru — tipe **Attendance | Behavior**, multi-select behavior
  (`intrusion`/`loitering`/`running`) dengan **Trigger threshold (detik)** per behavior dan
  `speed_limit_mps` khusus `running`; zona Attendance punya arah + satu trigger; `behaviors=[]`
  tetap valid sebagai zona visual. Field lama level-zona (`dwell_seconds`) hilang dari UI dan
  dari `frontend/src/api/zones.ts`; GatesPage menyaring `type='attendance'` dan menulis
  `{trigger_seconds, behaviors:[{kind:'attendance',trigger_seconds}]}`; `LiveViewPage` memakai
  warna zona `attendance`/`behavior`; i18n EN/ID diganti (`zones.trigger`, `zones.behaviors`,
  `zones.behavior.*`, `zones.speedLimit`, `zones.type.attendance|behavior`, `gates.col.trigger`;
  kunci `zones.dwell*`, `zones.type.{restricted,absensi,free}`, `gates.col.dwell` dihapus).
  Bukti: vitest zona+gate **RED 10 failed | 4 passed → GREEN 14 passed**, full `npx vitest run`
  **86 passed**, `npm run build` exit 0, `npm run lint` tanpa warning baru, backend
  `pytest -m "not gpu"` **308 passed**, vision **134 passed, 2 deselected**.
  Rollback: `git revert` commit `feat(zones-ui): ...` (perubahan murni frontend; skema DB tetap).

- `9fcfbee` fix: live endpoint rewrites go2rtc host to request host
- `3ec0d3a` feat: zone editor (click-to-draw polygon) + events master-detail inbox
- feat: loitering analyzer (dwell per zone)
- feat: running analyzer (calibrated m/s)
- feat: alert model + zone analyzer params + camera calibration
- feat: alerting service (rate-limit, telegram foundation)
- feat: alerts api + inbox badge + telegram status chip
- fix: ws guard drops alert frames by kind
- feat: attendance + enrollment + gates UI (AttendancePage tabs/summary/override, EnrollmentPage face gallery+shifts, GatesPage absensi zones + conflict; api/attendance.ts + api/employees.ts)
- fix: api client keeps FormData content-type (multipart CSV import + face upload)
- feat: gate crop from mainstream frame (face resolution) — `Recorder.fetch_frame` fetches `/api/frame.jpeg?src=cam_N_main`, `CameraWorker._attach_crop` crops attendance face from the full-res main stream with substream fallback

## [0.1.0] — 2026-09-10 · Fase 0: Skeleton

Backend, frontend, dan infrastruktur dasar I-Sentinel: auth, kamera + probe RTSP, UI shell Carbon dark, deploy configs. Terverifikasi end-to-end di server dev (login → wizard probe kamera nyata → kamera online).

### Commits

- `14e1294` chore: gitignore tensorrt engine artifacts
- `6e7a885` docs: sinkronkan checklist fase 0 + revisi kriteria fase 1
- `b72b592` docs: fase 1 detail plan (9 task)
- `12c8eca` docs: detektor dipilih YOLO26s nms=False (benchmark task tetap di fase 1)
- `d315f4e` docs: fase 0 selesai - bukti bring-up server
- `cbcec9b` fix: probe returns path without credentials (zero-secret)
- `94b95c9` fix: explicit setuptools packages (flat-layout ambiguity app+alembic)
- `1bd50bb` docs: fase 0 progress checkpoint di roadmap
- `8b7ebf4` fix: final review wave (logout endpoint, probe persistence, nav route, cookie_secure, jwt guard)
- `7af1f41` fix: alembic run path in bootstrap + soft env file in unit
- `c4a2e95` chore: deploy configs (go2rtc, mosquitto, systemd) + bootstrap script
- `05d3750` feat: cameras page with probe wizard
- `3699c88` fix: logout redirect, route-aware placeholder, api client opt merge
- `6a97216` feat: frontend scaffold (carbon g100, i18n id/en, app shell, login)
- `53e10e9` feat: rtsp probe service (ffprobe + vendor path candidates)
- `866bc87` feat: nodes + cameras CRUD API
- `35fb4e9` fix: user API validation (password length, role enum) + bootstrap cleanup
- `d7157a0` feat: auth API + user management + first-run admin bootstrap
- `27602c0` feat: password hashing + JWT auth helpers
- `51bf9f5` feat: fase0 models (user, node, camera, setting) + initial migration
- `8d87aa6` feat: backend core (settings, db, alembic, health endpoint)
- `f39cddb` chore: monorepo scaffolding (backend, vision stub, frontend placeholder)
- `4d7bd05` docs: roadmap dengan checkpoint per fase
- `1540e91` docs: master plan + fase 0 detail plan + milestone briefs (fase 1-5, edge)
- `6e4e363` docs: specify face match threshold default
- `f493b95` docs: I-Sentinel design spec + approved UI mockups

### Highlights

- **Backend**: FastAPI + SQLAlchemy 2 + Alembic; JWT httpOnly cookie auth, role admin/viewer; CRUD kamera/nodes; probe RTSP (ffprobe, path vendor Hikvision/Dahua/generic) dengan hasil persist; ingest event internal idempotent-ready.
- **Frontend**: React + TS + @carbon/react theme g100 dark, bilingual ID/EN, sidebar collapsible; login; halaman kamera + wizard probe; tanpa emoji (Carbon icons).
- **Deploy**: systemd units (api/web), go2rtc + mosquitto configs, bootstrap script; zero-secret (kredensial kamera via env, path RTSP saja di DB).
- **Keputusan model AI**: detektor YOLO26s TensorRT FP16 `nms=False` (spec §2.7); benchmark validasi di Fase 1.

## [0.3.0] — 2026-09-15 · Fase 2: Zona, Events, Clips, Web Inbox

Zona digambar di UI → vision-node eksekusi intrusion → event dengan clip mainstream + snapshot diputar di web inbox. 24 kamera NVR terdaftar.

### Commits (ringkas)

- `2bdaf71` feat: zone model + api (polygon validation, schedule)
- `88947ef` feat: mqtt config push (retained per node)
- `e41b8d5`/`c3bda0d` feat: intrusion analyzer + config apply (hot reload)
- `1fc3ed5`/`b20d138` feat: event recorder (clip via go2rtc mp4 + snapshot, blob upload)
- `d4b50c1` feat: blob storage + media streaming api + media topic consumer
- `9fcfbee` fix: live endpoint rewrites go2rtc host to request host
- `3ec0d3a`/`604afa8` feat: zone editor (click-to-draw polygon) + events master-detail inbox
- `0f979a0`/`75b75aa`/`3973e00` fix: config push zone key id, _config_q order, detector model path resolution
- `0a31dd8` fix: blob endpoint accepts node name (vision contract)
- `e03acfa` feat: person_detect events opt-in (debug), zones are the real signal

### Highlights

- **Zona**: model + editor polygon (klik-titik min 3, tutup start-point, drag handle, koordinat norm 0–1) + validasi absensi/direction
- **Config push MQTT retained** per node — hot-reload worker di vision tanpa restart
- **Intrusion analyzer** (ray-casting, jadwal, re-entry) + registry analyzer untuk fitur berikutnya
- **Recorder**: snapshot dari ring JPEG, clip mp4 via go2rtc, upload blob background + retry
- **Media API** auth + traversal guard + range request (video seek)
- **Web inbox** master-detail dengan player clip + snapshot + unduh

## [0.4.0] — 2026-09-15 · Fase 3: Loitering, Running, Alerting Foundation

Analyzer loitering + running (kalibrasi per kamera), alerting foundation: alert model, rate-limit, Telegram graceful-fail. Integrasi chatID menyusul (low priority).

### Commits (ringkas)

- `d0b6f16`/`18fae0f` feat: loitering analyzer (dwell per zone) + zone filter fix
- `9918933`/`8c6b163` feat: running analyzer (calibrated m/s) + anisotropic fix
- `dd9a72b` feat: alert model + zone analyzer params + camera calibration
- `cd353c9` feat: alerting service (rate-limit, telegram foundation)
- `2e05633`/`a69ad96` feat: alerts api + inbox badge + telegram status chip

### Highlights

- **LoiteringAnalyzer**: dwell akumulatif per track di polygon, reset saat keluar/hilang, gap >10s reset
- **RunningAnalyzer**: m/s via meters_per_pixel per kamera (xy anisotropik benar), EMA, cooldown 5s, skip tanpa kalibrasi
- **Alerting**: severity gate, toggle per zona, rate-limit window (camera:zone:type), retry 3×, status sent|failed|rate_limited|not_configured
- **Telegram**: sendMessage foundation, token env-only, tanpa token/chat → not_configured tanpa network call
- **UI**: badge status alert di event detail, chip status Telegram di inbox header

## [0.5.0] — 2026-09-15 · Fase 4: Absensi Wajah

Siklus absensi penuh: enrollment wajah → gate attendance → rekap dengan shift & status → export/import CSV. InsightFace buffalo_l di server, vision hanya crop.

### Commits (ringkas)

- `8acd420`/`c2aa341` feat+fix: attendance domain models (employee, shift, embedding, attendance) + FK guards + index parity
- `acd68e3` feat: face service (insightface wrapper, gallery, cosine match)
- `8892af4`/`092a6fb` feat+fix: face enrollment api (min 3 pose, pdp purge, gallery wiring) + upload cap
- `f3dc67a`/`1f4b1ec` feat+fix: face gate analyzer (crop + upload) + visit semantics
- `e2ef747`/`fe9dc99` feat+fix: attendance logic (match, aggregate, override, csv, close-days)
- `79532e2`/`ded189e` feat+fix: attendance + enrollment + gates UI + admin gating
- `41695a1` feat: gate crop from mainstream frame (face resolution)

### Highlights

- **Face pipeline server-side**: SCRFD+ArcFace, gallery <100 in-memory cosine, threshold knob; tanpa model → `not_configured` graceful
- **Enrollment**: upload image min 3 pose, quality gate, max 5; hapus biometrik per karyawan (PDP)
- **Attendance**: zona absensi + arah; agregasi harian ontime/late/waiting/no_exit/absent; close-days; override admin dengan catatan audit
- **CSV**: export (tanpa biometrik, anti-injection) + import upsert idempotent
- **Vision**: face_gate crop dari MAINSTREAM (resolusi wajah) + upload blob; error isolation

[Unreleased]: https://github.com/LyKhan77/I-Sentinel/compare/v0.7.0...HEAD
[0.5.5]: https://github.com/LyKhan77/I-Sentinel/compare/v0.5.4...v0.5.5
[0.5.4]: https://github.com/LyKhan77/I-Sentinel/compare/v0.5.3...v0.5.4
[0.5.3]: https://github.com/LyKhan77/I-Sentinel/compare/v0.5.2...v0.5.3
[0.5.2]: https://github.com/LyKhan77/I-Sentinel/compare/v0.5.1...v0.5.2
[0.5.1]: https://github.com/LyKhan77/I-Sentinel/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/LyKhan77/I-Sentinel/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/LyKhan77/I-Sentinel/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/LyKhan77/I-Sentinel/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/LyKhan77/I-Sentinel/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/LyKhan77/I-Sentinel/commits/v0.1.0
- Task 10 (fix): `GET /api/v1/detector-settings` 500 di server (`ResponseValidationError:
  updated_at input None`). Akar masalah **bukan** baris DB NULL (kolom `nullable=False`)
  melainkan objek fallback di `_effective()` yang tidak pernah di-flush — `default=` SQLAlchemy
  hanya jalan saat INSERT, jadi `updated_at` tetap `None` saat tabel masih kosong. Fallback kini
  mengisi `updated_at` sendiri; tanpa migration baru. Bukti: test baru
  `test_get_without_row_returns_env_defaults` RED (`datetime_type ... input None`) → GREEN;
  backend `pytest -m "not gpu"` **309 passed**, vision **134 passed, 2 deselected**,
  `npx vitest run` **86 passed**, `npm run build` exit 0, lint tanpa warning baru.
- Task 10 (deploy + lapangan): motion gate dinyalakan lewat tab **Deteksi & Model →
  Advanced** (bukan `.env`; `.env` server tetap `MOTION_ENABLED=false` → membuktikan
  precedence **DB > env**). Retained `isentinel/config/server` berubah ke
  `motion.enabled=true` untuk 5 kamera. Heartbeat node kini melaporkan `detect_n`
  (jumlah pemanggilan detektor) — util GPU tidak bisa dipakai sebagai bukti karena
  kartu jenuh ~90% di kedua keadaan. Hasil A/B di `gspe-ai3`: gate ON **2,41** dan
  **4,13** panggilan/detik vs gate OFF **25,00**/detik (plafon teoretis 5 kamera ×
  5 fps) → hemat ≈84–90% inferensi; `ms_per_frame` tetap dilaporkan (24,8 ms) dan
  detektor tetap pin `cuda:1`.
- Task 10 (perbaikan UI): kolom override AI FPS/confidence di tab Deteksi & Model
  tampil merah "invalid" saat kosong, padahal kosong berarti "pakai nilai global" —
  `allowEmpty` pada Carbon NumberInput.
- Task 10 (temuan, BELUM diperbaiki): `ByteTracker.max_age` dihitung per frame (15),
  sedangkan gap motion gate = `force_interval_s × ai_fps`. Aman pada setelan
  terpasang (10 ≤ 15), tetapi `ai_fps ≥ 8` — nilai yang diizinkan schema (s/d 25)
  dan bisa diisi admin dari tab yang sama — membuat track objek diam mati tiap gap,
  sehingga `trigger_seconds` loitering/intrusion tidak pernah terpicu. Didokumentasi
  di `docs/detection-behavior-inventory.md` §10 dan dijaga test invarian.
- Task 10 (perbaikan inti): keanggotaan zona diukur dari **titik pijak** (bottom-center
  bbox) lewat helper baru `ground_point()`, bukan centroid badan. Zona digambar di
  lantai sementara centroid melayang setengah tinggi badan di atasnya — makin jauh
  subjek dari kamera makin besar selisihnya, sehingga orang yang jelas berdiri di dalam
  zona terbaca di luar. Dipakai seragam oleh `intrusion`, `loitering`, `running`, dan
  `face_gate` (kecepatan `running` tetap dari centroid). Bukti lapangan cam 357: satu
  lintasan memberi centroid di dalam polygon hanya ~3 detik (17:16:11→13) sementara
  `trigger_seconds=5`, jadi analyzer benar tidak emit — kaki masih di dalam zona jauh
  lebih lama. Test: `pytest vision/tests -m "not gpu"` **140 passed** (dari 136),
  backend **309 passed**, frontend **88 passed**, build exit 0.
- Task 10 (verifikasi lapangan, TUNTAS): trigger behavior terbukti di cam 357 —
  titik pijak masuk zona 17:32:00, bertahan 5 detik, event `intrusion` id=4664
  zona 6 terbit 17:32:05 dengan `clip_path` (221 KB) + `snapshot_path` (72 KB)
  keduanya ada di disk dan tampil di UI Events. Pembuktian bahwa perbaikan titik
  pijak yang menentukan: `bbox_norm` event itu `[0.402, 0.335, 0.532, 0.992]` →
  centroid y=0,663 **di luar** polygon (0,718–0,998), jadi logika centroid lama tidak
  akan pernah menerbitkannya. Bukti: `docs/evidence/r5a-task10-intrusion-event.png`.

### R5a lanjutan — refining UI konfigurasi (2026-09-23)

- **Chip `attendance` dihapus dari tab Deteksi & Model** (kini 3 chip, sesuai mockup 06).
  Absensi diatur dari tab Gate Absensi saja. Chip itu sebelumnya saklar ketiga yang
  nyata: `_make_analyzers` melewati behavior yang tidak ada di `camera.analyzers`,
  jadi mematikannya membunuh seluruh gate kamera itu diam-diam dari tab lain.
  Nilai `attendance` tetap dipertahankan saat chip lain di-toggle — dijaga test
  `chip attendance tidak ditampilkan tapi tetap tersimpan saat chip lain di-toggle`,
  tanpa itu regresi "mematikan intrusion ikut mematikan absensi" akan lolos.
- **Rail kamera di tab Zona Deteksi** menggantikan dropdown: tiap kamera menampilkan
  jumlah zona + badge tipe, kamera tanpa zona tampil redup — mana yang sudah
  dikonfigurasi terlihat tanpa membuka satu per satu. **Menyimpang dari mockup 06**
  (`<select id="zoneCam">`) atas permintaan user; berkas mockup sengaja tidak diubah.
  Grid jadi `200px | editor | detail`, runtuh ke satu kolom + strip horizontal di ≤671px.
- **Feedback Save/Delete**: `ToastNotification` sukses (auto-dismiss 4 s), `Modal`
  konfirmasi sebelum hapus zona, dan tombol disabled + label "Menyimpan…"/"Menghapus…"
  selama request. Diterapkan di ZonesPage dan GatesPage supaya perilakunya sama.
- Bukti: frontend **93 passed** (dari 88), `npm run build` exit 0, lint tanpa warning
  baru (1 warning `set-state-in-effect` yang sudah ada sebelumnya, diverifikasi dengan
  membandingkan lint sebelum/sesudah). Backend **309 passed**, vision **140 passed**.

### R5a lanjutan — bloker attendance + overlay wajah debugger (2026-09-23)

- **Gate absensi tidak lagi disaring master `camera.analyzers`** (`5711160`).
  Kasus nyata: kelima kamera kini `analyzers=['intrusion','loitering','running']`
  (tertulis dari klik chip), sehingga zona 9 cam 363 yang sudah aktif tidak pernah
  membuat analyzer `face_gate`. `_make_analyzers` kini mengecualikan `attendance`
  dari filter — absensi diatur dari tab Gate Absensi (zona `active`). Juga berlaku
  untuk `analyzers: []`. Test: `test_attendance_gate_ignores_camera_analyzers_master`
  (`['intrusion']` dan `[]`), merah sebelum perbaikan.
- **`face_gate` memakai `trigger_seconds`** (`b60c602`). UI hanya menulis
  `trigger_seconds`, analyzer membaca `dwell_seconds` → trigger yang diubah dari UI
  atau zona attendance baru (dwell 0) tidak sampai ke gate. Zona 9 kebetulan aman
  (keduanya 3). `dwell_seconds` tetap fallback config pra-R5.
  Test: `test_trigger_seconds_wins_over_stale_legacy_dwell`.
- **Produsen overlay wajah `kind="face"`** (`e508a97`). Kamera yang punya
  `FaceGateAnalyzer` menjalankan `FaceEmbedder.detect()` (SCRFD saja, tanpa embedding,
  `cuda:2`) pada frame substream yang lolos motion gate dan hanya saat ada track;
  kotak dinormalisasi, label = `det_score`. Satu publish kosong saat wajah hilang.
  Error deteksi tidak mematikan worker (test mutasi: tanpa `try` test merah).
  Lazy-load `FaceEmbedder` dikunci supaya beberapa worker tidak memuat model dua kali.
- **Overlay Live View**: pesan person dan face tidak lagi saling menimpa — hanya
  kotak dengan `kind` sama yang diganti; key/testid memuat kind (`51ba870`).
- Bukti lokal: vision **147 passed, 2 deselected** (dari 140), frontend **94 passed**,
  build exit 0, lint: set warning identik sebelum/sesudah (dibandingkan via stash),
  backend **309 passed**.
- Dampak: kamera attendance kini memakai GPU face per frame saat ada orang.
- Rollback: `git revert 51ba870 e508a97 b60c602 5711160` lalu restart `vision-node`.
- Deploy 2026-09-23: server `9d459fb`, `vision-node` di-restart (5 worker, heartbeat
  `detect_n` 100→148 dalam 10 s). `analyzers` kamera 357/358/362/363/364 dikembalikan
  ke `null` lewat `PATCH /api/v1/cameras/{id}` (retained config terverifikasi).
  `FaceEmbedder.detect()` diuji di insightface 2.0 server pada foto enrollment → 1 wajah,
  skor 0,69. **Tes lapangan attendance cam 363 belum dilakukan.**

### R5a lanjutan — frame basi + pin GPU model wajah (2026-09-23)

Konteks: tes attendance user di cam 363 menghasilkan overlay yang sangat lambat dan
seluruh event `match_reason: no_face` (2 di cam 363, 6 di cam 364). Diukur dulu sebelum
diperbaiki.

- **`FrameSource` memberi frame terbaru, bukan antrean basi** (`ddf8599`). Lag terukur
  +19,8 s setelah 30 s (cam 363, 15 fps dibaca 5 fps) dan terus naik. Reader thread
  menguras stream pada fps asli. Test `test_live_source_returns_latest_frame_not_stale_buffer`
  mereproduksi pola produksi (lag 8→35 frame, lalu ≤10 setelah perbaikan). Bukti di
  stream nyata: selisih konstan −0,85 s selama 30 s. Error decode h264 36 → ≤8 per 5 menit.
  Biaya: CPU vision-node ~23% → ~64% dari satu core.
- **Pin `cuda:2` model wajah benar-benar berlaku** (`7127f94`). insightface mengabaikan
  `ctx_id >= 0`, sehingga sesi CUDA tanpa `device_id` jatuh ke GPU 0 (RTX 4090 bersama
  vLLM). Provider kini `("CUDAExecutionProvider", {"device_id": N})`. Bukti di server:
  sesi dengan `device_id=2` → GPU index 2 (902 MiB). Setelah deploy, proses vision tidak
  lagi memakai GPU 0.
- Bukti: vision **151 passed, 2 deselected**. Deploy `ddf8599` pukul 10:13, 5 worker jalan.
- Temuan (tidak dikerjakan): model wajah **backend** (enrollment/match_crop) memakai GPU 0
  tanpa pin device, sengaja `ctx_id=0`.
- Rollback: `git revert ddf8599 7127f94` lalu restart `vision-node`.
