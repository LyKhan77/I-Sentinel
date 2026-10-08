# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/) ringkas — satu baris per commit.
Skema versi: [SemVer](https://semver.org/). Status proyek: pra-rilis (`0.x`).

### Face ID pada intrusion critical — uji kamera 357 setelah 2K dan gerbang relatif (2026-10-08)

- **Konteks:** user mengubah kamera 357 "Lorong Manager" menjadi 2K 15 fps, Max. bitrate 8192 kbps (terverifikasi `ffprobe` pada `cam_357_main`: H.264 Main, **2560×1440, 15 fps**), dengan server di branch `feat/intrusion-face-progressive` @ `2cedca8` (gerbang identitas relatif, lebar ≥ 60 px, pembaruan progresif, ambang uji 0,35 / margin 0,15, `ai_fps` 15).
- **Hasil (DB, kamera 357):**

  | Event | Jam WIB | Orang | `payload.face` | Crop |
  |---|---|---|---|---|
  | 4899 | 16:36:27 | karyawan | `recognized`, skor 0,444, margin 0,267 | 118×142 |
  | 4900 | 16:37:01 | karyawan | `recognized`, skor 0,586, margin 0,339 | 135×153 |
  | 4901 | 16:37:50 | karyawan | `recognized` (karyawan #5), skor 0,639, margin 0,444 | 140×179 |
  | 4902 | 16:39:12 | non-karyawan | `unknown`, `no_match`, skor 0,222 | 117×156 |
  | 4903 | 16:42:03 | karyawan, jarak 2 m+ | `recognized`, skor 0,452, margin 0,252 | 100×123 |

- **Terbukti:** semua karyawan dikenali (skor 0,444–0,639; margin ≥ 0,25), non-karyawan tidak (skor 0,222; sebelumnya 0,243 agregat dan 0,298 frame tunggal maks); alert dan caption tersinkron (`face_synced` true di semua). Crop 100–140 px lebar berarti wajah ±62–88 px (padding 30%), sehingga uji 2 m+ dikenali pada wajah ±62 px, di dekat batas 60 px.
- **Belum terbukti:** tingkat salah-orang (baru 2 non-karyawan di dua sesi), jarak 3 m, dan pengaruh resolusi 2K secara terpisah dari jarak/pose (jarak uji tidak seragam). Ambang 0,35 / 0,15 tetap nilai uji; ROADMAP `IFI` tetap `[~]`.
- **Rollback:** tidak ada perubahan kode pada entri ini (hanya konfigurasi kamera dan catatan).

### Face ID pada intrusion critical — gerbang identitas relatif untuk jarak sampai ±3 m (2026-10-08)

- **Konteks:** uji kamera 357 (fps 15) memberi 4 event dari 4 percobaan, tetapi hanya uji pertama dikenali; uji mundur/maju `not_visible/small` dan uji non-karyawan `not_visible/blur` sehingga tidak ada skor impostor. Analisis klip (dibatasi CPU): pada keempat klip tidak ada frame yang lolos gerbang lama (lebar ≥ 80 px, blur ≥ 120); tanpa gerbang blur dengan peringkat `det × blur` dan lebar ≥ 60 px, karyawan 0,427–0,483 (margin 0,26–0,29) dan non-karyawan 0,243 (margin 0,01). Variansi Laplacian pada crop 112×112 bergantung pada ukuran wajah asli (median 28–73 untuk wajah 76–88 px di kamera 357 lawan 150–230 untuk 100–120 px di kamera 363), padahal skor per frame di 357 justru lebih tinggi (median 0,42 lawan 0,36): label "buram" menyesatkan. Kebutuhan user: akurasi tinggi sampai ±3 m dan frame terbaik saat orang berjalan.
- **Perubahan (khusus identitas intrusion, absensi tidak berubah):** `IdentCollector` tidak lagi memakai gerbang blur absolut maupun gerbang `quality` berbasis lebar; gerbang geometri = lebar ≥ `IDENT_MIN_WIDTH_PX` (60), skor deteksi, yaw, pitch. K=5 frame terbaik dipilih relatif per orang dengan peringkat `skor deteksi × ketajaman` (agregasi tetap berbobot kualitas). Label overlay frame yang lolos berupa lebar piksel (`86px`), penolakan hanya `small`/`score`/`yaw`/`pitch`. API: `_identify_with_name` tidak lagi menolak `low_quality` (ambang 0,35/margin 0,15 dan margin top-1/top-2 yang memutuskan). Konstanta `IDENT_MIN_QUALITY` dihapus.
- **Bukti:** RED vision `7 failed` (`assert 0 == 1` untuk wajah 60 px, `1 == 0` untuk wajah halus, `1 == 5 + 1` untuk peringkat ketajaman, label `0.90` lawan `120px`) dan RED backend `not_visible == recognized` untuk `quality=0.2`; GREEN setelah implementasi. Suite berurutan: backend `954 passed, 1 deselected`, vision `331 passed, 3 deselected` (328 + 3), docker `77 passed`, vitest `38 files / 497 passed`, build exit 0, lint 24 warning. Log `temp/logs/intrusion-face-id/gate-*.txt`, `clip-width-sweep.txt`, `clip-stats-4895-4898.txt`.
- **Belum terbukti:** akurasi pada ±3 m (belum ada uji 3 m), tingkat salah-orang (baru satu non-karyawan dengan 14 frame), perilaku saat berjalan. Kamera 357 main-stream 1920×1080 H.264 25 fps; sub-stream 640×480 10 fps (detektor efektif ≤ 10 fps walau `ai_fps` 15).
- **Rollback:** revert commit ini dan rebuild `vision` + `api`.

### Face ID pada intrusion critical — pembaruan identitas progresif (2026-10-08)

- **Konteks:** analisis klip (entri berikutnya) menunjukkan frame terbaik sering datang setelah jendela 8 dtk karena orang bergerak mencari titik terbaik: agregasi seluruh klip memberi 0,446–0,564, sedangkan skor node 0,350–0,576 (4885 jatuh 0,0002 di bawah ambang). Keputusan user: pembaruan progresif.
- **Perubahan (node):** `IdentCollector` tidak lagi selesai setelah hasil pertama. Selama orang masih di zona (maks `MAX_TRACK_S` = 90 dtk setelah event) pengumpulan berlanjut dan pembaruan (`seq` > 0) dikirim bila K terbaik berubah, dengan jeda minimum `UPDATE_EVERY_S` = 10 dtk dan maks `MAX_UPDATES` = 6; pembaruan akhir dikirim saat orang pergi atau worker berhenti (`flush`). Pekerjaan dan memori tetap terbatas: embed hanya bila frame mengalahkan K terbaik. Crop diunggah ulang hanya bila kandidat membaik. **(API):** `handle_face_result` menerima hanya hasil yang lebih baik (`recognized` > `unknown` > `not_visible` > `unverified`; status sama dengan skor lebih tinggi), memperbarui `payload.face` dan `crop_path`, dan mengedit caption lagi hanya bila status atau karyawan berubah; hasil yang lebih rendah tidak pernah menimpa. `FaceResultIn.seq` ditambah.
- **Bukti:** RED vision `7 failed` (`KeyError: 'seq'`, fitur belum ada) lalu `30 passed` pada berkas kolektor; RED backend `3 failed` (`crops/.../a.jpg == b.jpg`, hasil `not_visible` menimpa `recognized`, skor tidak diperbarui). Dua tes lama diubah karena siklus hidup berubah: entri tetap dipantau setelah hasil pertama (`registry.entries()`), dan tes "abaikan orang setelah terkirim" diganti dengan tes pekerjaan terbatas. GREEN suite berurutan: backend `954 passed, 1 deselected` (950 + 4), vision `328 passed, 3 deselected` (323 + 5), docker `77 passed`, vitest `38 files / 497 passed`, build exit 0, lint 24 warning. Log di `temp/logs/intrusion-face-id/prog-*.txt`.
- **Dampak:** caption bisa naik setelah alert (mis. `tidak dikenali` → `Dikenali: <nama>`) selama orang di zona; entri registry bertahan sampai 90 dtk sehingga motion gate dilewati selama itu (SCRFD jalan saat orang berada di zona). BELUM diuji di lapangan.
- **Rollback:** revert commit ini dan rebuild `vision` + `api`.

### Face ID pada intrusion critical — uji ambang 0,35/0,15 dan analisis klip (2026-10-08)

- **Konteks:** dua uji karyawan terdaftar pada jarak 1–2 m dengan ambang uji server 0,35 / margin 0,15: event 4885 (14:57:21) `unknown`, skor **0,3498** (kurang 0,0002 dari ambang) dan event 4886 (14:58:18) `recognized`, skor 0,410, margin 0,220. Pada 4885 user berjalan mencari titik terbaik. Klip keempat event jarak dekat (4883–4886, 1080p) dianalisis frame demi frame di container `api` (read-only; SCRFD + ArcFace seperti jalur node; hanya angka).
- **Temuan 1, jendela waktu:** agregasi K=5 terbaik atas **seluruh klip** (gerbang node) memberi 4883 `0,564` (aktual node 0,370), 4884 `0,529` (0,576), 4885 `0,446` (0,350), 4886 `0,444` (0,410), margin ke kandidat kedua selalu ≥ 0,25. Selisih terbesar muncul saat user bergerak mencari titik terbaik: frame terbaik datang **setelah** jendela node (dwell sebelum event + 8 dtk sesudahnya) berakhir. K=3…12 hampir sama (K=all sedikit lebih rendah pada klip berderau); K bukan tuas utama.
- **Temuan 2, proksi kualitas lemah:** korelasi skor per frame ke karyawan #1 (n = 126): lebar −0,28, `det` +0,45, pitch −0,40, yaw −0,02, blur +0,07, `quality` −0,06. Top-5 menurut `quality` rata-rata hanya +0,03–0,04 di atas rata-rata semua frame (oracle +0,12–0,15). Frame sempit tetapi frontal dan tajam (55–61 px, gerbang `small`) kadang memberi skor tertinggi (0,50–0,56); pose (pitch) lebih berpengaruh daripada ukuran. Dua klip saja: tidak cukup untuk mengganti proksi.
- **Implikasi:** pada ambang 0,50 bahkan agregasi seluruh klip hanya mengenali 4883 dan 4884; pada 0,35–0,40 keempatnya dikenali. Genuine 0,44–0,56 lawan kandidat kedua 0,10–0,25. Belum ada uji non-karyawan, jadi ambang tetap nilai uji.
- **Belum dikerjakan:** pembaruan identitas progresif (terus mengumpulkan selagi orang berada di zona dan mengirim pembaruan bila membaik), uji non-karyawan.

### Face ID pada intrusion critical — kalibrasi awal dan ambang uji 0,35 / 0,15 di server (2026-10-08)

- **Konteks:** user meminta tuning agar wajah pada jarak 1–2 m dikenali. Diagnostik read-only di container `api` (CPU, galeri 7 karyawan × 5 foto pendaftaran; skrip sekali pakai, hanya angka) memakai crop event 4881, 4883, 4884.
- **Data:** impostor (skor terbaik terhadap non-pemilik, n = 35) median 0,225, p95 0,277, maksimum 0,280; genuine antar foto pendaftaran (n = 70) minimum 0,582, median 0,727. Crop jarak dekat, skor ke karyawan #1 (kandidat kedua): 4884 `0,534` (0,232), 4883 `0,387` (0,172), 4881 `0,272` (0,103); skor tersimpan node: 0,576 / 0,370 / 0,327. Pose (frontal) berpengaruh lebih besar daripada ukuran (4881: 111 px menunduk lebih rendah dari 4883: 96 px frontal). Upscaling ×2 tidak membantu; flip-averaging +0,01–0,02 (4881 −0,006) sehingga tidak dipasang. Asumsi: ketiga crop adalah orang yang sama (karyawan #1); belum ada uji non-karyawan.
- **Perubahan di server (atas persetujuan user, bukan di repo):** `docker/.env` gspe-ai3 ditambah `FACE_ID_THRESHOLD=0.35` dan `FACE_ID_MARGIN=0.15` (default compose 0,50 / 0,10), lalu `api` dibuat ulang (`up -d --force-recreate api`); terverifikasi di container: `settings.face_id_threshold = 0.35`, `face_id_margin = 0.15`, `face_min_quality = 0.5`, `/api/v1/health` ok, alembic `0023`. Pada sampel di atas, ambang 0,35 mengenali 4883 dan 4884 (margin 0,215 dan 0,30) dan tidak 4881; jarak ke impostor maksimum pasangan pendaftaran hanya 0,07.
- **Belum terbukti:** tingkat salah-orang pada orang asing di depan kamera (dasar impostor hanya pasangan pendaftaran; N kecil). Nilai ini adalah nilai uji, bukan hasil kalibrasi akhir; ROADMAP `IFI` tetap `[~]` sampai uji non-karyawan dan beberapa karyawan terdaftar selesai.
- **Rollback:** hapus dua baris itu dari `docker/.env` server (atau set 0.50 / 0.10) lalu `docker compose -f docker/compose.yml up -d --force-recreate api`.

### EEA ditutup — konfirmasi user atas chip Exit awal dan layar 390 px (2026-10-08)

- **Konteks:** setelah catatan UI sebagian (`23bba64`), user mengonfirmasi lisan bahwa chip Exit awal tampil di sel exit dan tampilan 390 px tanpa overflow horizontal. ROADMAP `EEA` menjadi `[x]`.
- **Bukti:** pernyataan user hari ini; tidak ada screenshot tambahan (screenshot 11:26 hanya memuat tombol Correct dan modal). Bukti lain tidak berubah: CSV dengan kolom `exit_early_min`, suite backend/frontend lulus.
- **Rollback:** kembalikan baris ROADMAP `EEA` ke `[~]`.

### Face ID pada intrusion critical — hasil uji lapangan di zona 15 (2026-10-08)

- **Konteks:** deploy branch `feat/intrusion-face-id` ke `gspe-ai3` (tanpa merge ke `main`), user menguji lima event intrusion di zona 15 "Server" (kamera 363, critical, trigger 10 dtk, `face_id: true`). Data dari DB (`payload.face`, `payload.crop_path`, `alert`) dan crop yang dilihat langsung (kualitas/ukuran saja; tidak ada identifikasi dari wajah).
- **Hasil:**

  | Event | Jam WIB | Deploy | `payload.face` | Crop | Catatan |
  |---|---|---|---|---|---|
  | 4876 | 13:35:53 | `49b75b2` | `unverified` | tidak ada | kamera tanpa zona attendance aktif: tidak ada worker wajah (batasan v1, dihapus di `2b65346`) |
  | 4878 | 13:49:31 | `2b65346` | `not_visible`, `small` | 86×96 | wajah ±54 px |
  | 4880 | 13:54:57 | `2b65346` | `not_visible`, `small` | ada | jarak jauh |
  | 4881 | 13:59:23 | `2b65346` | `unknown`, `no_match`, skor 0,327 | 166×218 | jarak dekat, wajah ±111 px, kepala menunduk; embedding hanya dari 3 frame pertama (diperbaiki di `fc99372`) |
  | 4883 | 14:25:02 | `fc99372` | `unknown`, `no_match`, skor 0,370 | 158×197 | wajah ±99 px, hampir frontal |
  | 4884 | 14:26:18 | `fc99372` | **`recognized`**, skor 0,576, margin 0,332 | 202×254 | wajah ±126 px, lebih dekat dan frontal |

- **Terbukti:** jalur lengkap bekerja (pesan susulan node, pencocokan ketat, `payload.face`, `payload.crop_path`, tab Crop di Inbox, caption Telegram diedit; `face_synced` true di semua alert) dan `recognized` pertama berhasil dengan margin besar terhadap kandidat kedua. Keberhasilan bergantung pada ukuran dan frontalitas wajah: ±99 px frontal masih di bawah ambang 0,50, ±126 px frontal lolos.
- **Belum terbukti:** tingkat false accept (belum ada uji impostor/non-karyawan), tingkat true accept (hanya 1 dari 3 uji jarak dekat), latensi caption identitas di Telegram (hanya flag DB), perilaku pada zona critical di ruang sebenarnya. Ambang `FACE_ID_THRESHOLD = 0,50` dan `FACE_ID_MARGIN = 0,10` tetap nilai awal; tidak diubah berdasar uji ini. ROADMAP `IFI` tetap `[~]`.
- **Catatan terpisah:** AI caption event 4883 dan 4884 gagal `LLM timeout` (4878–4881 berhasil): endpoint LLM yang putus-putus, tidak terkait fitur ini.
- **Rollback:** `ssh gspe-ai3`, `cd /home/gspe-ai3/project_cv/I-Sentinel-docker && git checkout main && ./docker/setup.sh` (kolom 0023 aditif, tanpa downgrade).

### Face ID pada intrusion critical — kandidat terbaik, flush saat berhenti, overlay mengikuti kepala orang (2026-10-08)

- **Konteks:** uji lapangan kedua dan ketiga (deploy `2b65346`): event 4878 `not_visible/small` (crop 86×96 px, wajah ±54 px) dan uji jarak dekat event 4881 (13:59:23) `unknown/no_match`, skor 0,327 terhadap galeri 7 karyawan (crop 166×218, wajah ±111 px, kepala menunduk; mesin API sendiri memberi skor 0,27). Masukan user: pengenalan terlalu cepat sehingga kandidat terbaik belum ditemukan, dan overlay debugger tidak boleh mengikuti status zona. Penyebab pertama adalah perbaikan review sebelumnya (H2) yang membatasi embedding ke `min_frames` (3) **pertama**, yaitu frame paling awal dan paling buruk, serta pengiriman segera setelah 3 frame. Penyebab kedua: label kotak wajah memakai gerbang attendance, jadi pada worker identitas-saja (zona kosong) semua wajah berlabel `zone`.
- **Perubahan:** `IdentCollector` menyimpan **BEST_K = 5 embedding terbaik berdasar kualitas** (embed hanya bila mengalahkan K terbaik), mengirim hasil di akhir jendela 8 dtk setelah event atau saat person pergi (tidak lagi setelah 3 frame), dan memilih crop berdasar lebar × skor × (1 − yaw) × (1 − pitch) sehingga yang dipilih wajah paling frontal. `flush()` mengirim hasil sebagian saat worker berhenti (config berubah/shutdown). `observe` mengembalikan label overlay per wajah; `FaceGateWorker` memakainya: wajah di kepala orang berlabel hasil gerbang identitas (kualitas atau `small`/`score`/`yaw`/`pitch`/`blur`/`quality`); worker tanpa zona attendance tidak menggambar wajah lain; kamera ber-zona attendance tetap berlabel zone untuk wajah yang bukan kandidat identitas. Frontend: kode `pitch` dan `quality` diterjemahkan di overlay. `UNVERIFIED_AFTER_S` 15 → 20 dtk (jendela 8 dtk + unggah crop ≤ ±6 dtk + antrean MQTT).
- **Bukti:** RED (vision) `7 failed, 35 passed` (`assert 3 == 5`, pengiriman dini, crop terlebar bukan terfrontal, `observe` mengembalikan `None`, `flush` belum ada, overlay `6 == 3`) lalu `6 failed` di tes worker saat jendela diterapkan tanpa flush; RED vitest `2 failed` (kode `pitch`/`quality` belum diterjemahkan). Satu asersi lama tentang keadaan internal registry setelah worker selesai (`reg.active(11.0)`) dihapus karena flush kini melepas entri. GREEN suite berurutan: backend `950 passed, 1 deselected`, vision `323 passed, 3 deselected` (317 + 6), docker `77 passed`, vitest `38 files / 496 passed` (494 + 2), build exit 0, lint 24 warning. Log di `temp/logs/intrusion-face-id/review4-*.txt`.
- **Dampak:** hasil identitas tiba ±8 dtk setelah event (lebih lambat dari sebelumnya, lebih banyak kesempatan menemukan wajah frontal). Memori kolektor tetap terbatas (K vektor per orang). Tanpa perubahan kontrak, migrasi, atau backend selain konstanta timer. BELUM diuji ulang di lapangan.
- **Rollback:** revert commit ini dan rebuild `vision`, `api`, `web`.

### Face ID pada intrusion critical — uji lapangan pertama: batasan zona attendance dihapus (2026-10-08)

- **Konteks:** uji user di zona 15 "Server" (kamera 363, critical, `face_id: true`, trigger 10 dtk; deploy branch `49b75b2`) menghasilkan satu event (4876, 13:35:53): alert terkirim berfoto, caption diedit `Identitas tidak terverifikasi`, `payload.face = {"status": "unverified"}`, tanpa `crop_path`. Penyebab (DB + log `vision`): zona attendance satu-satunya di kamera 363 (zona 19) kini `active = false`, sehingga node tidak membuat `FaceGateWorker` dan mencatat `face_id zone tanpa worker wajah (zona attendance); identitas tidak aktif`; API menandai `unverified` setelah 15 dtk (sesuai desain v1). Pipeline identitas sendiri belum teruji di lapangan.
- **Perubahan:** `VisionNode._start_camera` kini membuat `IntrusionRegistry` dan `FaceGateWorker` untuk kamera dengan zona critical ber-`face_id` **tanpa syarat zona attendance** (worker berzona kosong: tanpa event absensi, hanya identitas dan crop). Bila model wajah tidak tersedia, dicatat peringatan `zona face_id tetapi model wajah tidak tersedia` (sebelumnya diam). Teks bantuan toggle UI, README, ARCHITECTURE, dan runbook menyesuaikan. Spec §2 (batas "kamera critical tanpa zona attendance") tidak diubah karena spec/plan adalah catatan; keputusan ini tercatat di sini.
- **Bukti:** RED `test_start_camera_face_id_without_attendance_zone_still_gets_a_face_worker` (`assert ['CameraWorker'] == ['CameraWorker', 'FaceGateWorker']`; menggantikan tes lama yang mengunci batasan) dan `test_start_camera_warns_when_face_id_zone_but_face_model_unavailable` (`assert False`); `test_face_worker_without_attendance_zones_sends_identity_but_no_attendance_event` lulus sejak awal (worker sudah mendukung zona kosong; jaga regresi). GREEN suite vision `317 passed, 3 deselected`; vitest `38 files / 494 passed`, build exit 0, lint 24 warning (teks i18n saja). Log di `temp/logs/intrusion-face-id/review3-*.txt`.
- **Dampak:** kamera critical ber-`face_id` membaca stream utama sendiri (dekode 1080p tetap berjalan; SCRFD hanya saat ada gerakan atau orang di zona). Tanpa perubahan backend, migrasi, atau kontrak.
- **Catatan terpisah:** AI caption event 4876 dan "Tanya AI" gagal `LLM timeout` (tabel `event_ai`; keberhasilan terakhir 2026-10-07): masalah endpoint LLM, bukan fitur ini. Belum ada retry otomatis.
- **Rollback:** revert commit ini dan rebuild `vision` + `web`.

### Face ID pada intrusion critical — perbaikan review sesi perencanaan (2026-10-08)

- **Konteks:** review `560b590` oleh sesi perencanaan (suite diulang berurutan: backend `947`, vision `307`, docker `77`, vitest `494`, build exit 0, lint 24 warning, sama dengan laporan executor). Empat temuan diperbaiki lewat TDD atas persetujuan user; M3 (`with_for_update` pada event) dan temuan Low dicatat sebagai follow-up.
- **H1 isolasi:** kegagalan di jalur identitas (`IdentCollector.observe/drain`, `_ident_step`, `CameraWorker._touch_ident`, `registry.bind`) mematikan `FaceGateWorker` (absensi) atau `CameraWorker` (event intrusion itu sendiri hilang bila `bind` melempar). Kini tiap panggilan dibungkus `try/except` dengan log terbatas (`ErrorThrottle`, sekali per 60 dtk). `st.rejects[code]` tidak lagi `KeyError` untuk kode tak terduga (`"zone"`).
- **H2 kolektor:** setelah pesan terkirim, track yang masih berdiam di zona terus dikumpulkan (reproduksi: 100 frame berarti 100 panggilan embed dan 100 vektor tertahan) dan state orang yang pergi tidak dibuang. Kini `IntrusionRegistry` mengingat kunci yang sudah selesai (touch/bind diabaikan), pengumpulan embedding dibatasi `min_frames`, dan `drain` membuang state tanpa entri registry.
- **M1 caption:** caption dirender di luar `_edit_lock`, sehingga caption basi yang menunggu lock bisa menimpa yang lengkap. Kini klaim dulu, lalu render dari keadaan DB terbaru di dalam lock (`_render_fresh`: `expire_all` + `build_caption` + `commit` sebelum I/O). Tes `test_concurrent_edits_are_serialised` sebelumnya tetap lulus tanpa lock (mutasi membuktikannya); ditulis ulang dengan penghitung konkurensi.
- **M2:** `identify()` yang tidak dipakai di `services/intrusion_face.py` dihapus.
- **Bukti:** RED vision `8 failed, 27 passed` (`assert 23 == 3`, `assert 30 == 3`, state tertinggal, `KeyError: 'zone'`, absensi dan event intrusion hilang saat identitas melempar); GREEN `35 passed`, suite vision `315 passed, 3 deselected`. RED backend `3 failed, 7 passed` (`assert ([False] and False)`, caption tanpa baris Identitas); GREEN `65 passed` pada berkas terkait, suite backend `950 passed, 1 deselected` (947 + 3 tes), docker `77 passed`. Mutasi: hapus lock membuat 4 tes merah (termasuk tes serialisasi yang baru), render di luar lock membuat 3 merah; keduanya dikembalikan. Log mentah di `temp/logs/intrusion-face-id/review-*.txt` dan `review2-*.txt`.
- **Dampak:** tanpa perubahan kontrak, migrasi, atau UI. Frontend tidak disentuh (vitest `494`, build, lint tidak diulang). BELUM diuji di server nyata.
- **Rollback:** revert dua commit perbaikan ini (`a7dca26` dan commit backend sesudahnya).

### Face ID pada intrusion critical — T9 dokumen + verifikasi akhir (2026-10-08)

- **Konteks:** menutup siklus T1–T8 (`5b49fc5`…`ef43997`) fitur identitas wajah pada alert intrusion
  `critical` (spec `c6733af` + plan `5d5cf8f` + revisi `1181229`). ROADMAP sengaja `[~]`: kode
  selesai, **BELUM diuji di server nyata** — menunggu review, deploy, uji lapangan, dan kalibrasi
  ambang.
- **Perubahan:** `ARCHITECTURE.md` — baris topik `isentinel/events/face` + alur face ID pada bagian
  vision dan Alur utama. `WORKFLOW.md` — langkah 6 alur Event behavior (empat hasil identitas) dan
  butir §10 Alert Telegram (edit `sync_face_caption` dengan klaim `face_synced`).
  `docs/runbooks/intrusion-face-id.md` (baru) — cara menyalakan, membaca hasil, kalibrasi, retensi
  crop, rollback, prasyarat GPU container `vision`. `README.md` — bagian fitur singkat.
  `ROADMAP.md` — baris `IFI` `[~]`. `CHANGELOG.md` — entri ini.
- **Bukti:** suite berurutan pada HEAD executor (log mentah `temp/logs/intrusion-face-id/final-*.txt`):
  ```text
  backend: 947 passed, 1 deselected, 561 warnings in 173.80s (0:02:53)   (baseline 904)
  vision:  307 passed, 3 deselected, 2 warnings in 13.76s                (baseline 273)
  docker:  77 passed in 9.05s                                            (baseline 76 + tes guard)
  vitest:  Test Files 38 passed (38) · Tests 494 passed (494)            (baseline 36/487)
  build:   ✓ built in 3.15s                                              exit 0
  lint:    24 warnings / 16 pasangan file-rule identik baseline
  ```
  Naik hanya karena tes baru; tes lama tidak diubah (guard statis: 0 baris `-` pada
  `test_face_worker.py`, `test_node.py`, `test_alert_ai.py`, `test_telegram.py`).
- **Dampak:** dokumentasi dan lulusan verifikasi akhir; tidak ada perubahan kode.
- **Rollback:** revert commit ini.

### Face ID pada intrusion critical — T8 frontend (2026-10-08)

- **Konteks:** backend T1–T7 sudah mengirim `payload.face` dan `payload.crop_path`; UI perlu saklar,
  tampilan hasil, dan refresh realtime.
- **Perubahan:** `api/zones.ts` — `Behavior.face_id?: boolean`. `ZonesPage.tsx` — `Toggle`
  `zone-face-id-intrusion` (hanya behavior `intrusion`, default mati) + paragraf bantuan
  `zones.faceIdHint`. `EventsPage.tsx` — baris `event-identity` untuk `payload.face` (empat status,
  skor tampil untuk semua peran), tab Crop tampil untuk event apa pun ber-`crop_path` (perilaku
  attendance tidak berubah), cabang WS `kind: "face"` → `refresh('merge')`. `i18n.tsx` — kunci
  `zones.faceId(Hint)` dan `events.identity.*` di kedua kamus; `t()` menerima parameter `{name}`.
- **Bukti:** vitest `38 files / 494 passed` (tes baru: toggle default-off dan simpan `face_id: true`,
  toggle tidak tampil untuk loitering, baris identitas empat status + tanpa `payload.face`, WS face
  memicu refresh, tab Crop intrusion tampil/tidak tampil); build exit 0; lint 24 warning, pasangan
  identik. RED benar (toggle/baris/tab tidak ditemukan) sebelum implementasi.
- **Dampak:** operator menyalakan fitur per zona dan membaca hasilnya di Telegram/Inbox.
- **Rollback:** revert commit ini.

### Face ID pada intrusion critical — T7 retensi crop (2026-10-08)

- **Konteks:** crop wajah intrusion (`payload.crop_path`, T2/T6) berisiko dihapus sapuan retensi
  sebagai "orphan" mengikuti `attendance_days` sementara path tertinggal di DB.
- **Perubahan:** `services/retention.py` — `_expire_crops` menerima `event_type` (default
  `attendance`, perilaku lama utuh); `sweep` menjalankannya juga untuk `intrusion` dengan cutoff
  `snapshot_days`; `parts` dan nama jenis `_media_free_after` bertambah satu elemen; himpunan
  `referenced` sapuan orphan menyertakan `payload.crop_path` event `attendance` dan `intrusion`.
- **Bukti:** RED `test_sweep_does_not_treat_referenced_intrusion_crop_as_orphan`: file crop intrusion
  (mtime 60 hari, event 2 hari) TERHAPUS sebagai orphan sebelum fix. GREEN: `test_retention.py` 25
  passed termasuk tiga tes baru (kedaluwarsa `snapshot_days` + null path + `media_expired`, bukan
  orphan, dry-run tak menyentuh); suite backend penuh hijau.
- **Dampak:** bukti manual intrusion bertahan sesuai retensi snapshot, tidak mengubah retensi absensi.
- **Rollback:** revert commit ini.

### Face ID pada intrusion critical — T6 consumer pesan susulan (2026-10-08)

- **Konteks:** node mengirim hasil wajah ke `isentinel/events/face`; API perlu mencocokkan ketat,
  menyimpan `payload.face`/`crop_path`, memetakan `unverified`, dan menolak flag zona non-bool.
- **Perubahan:** `services/intrusion_face.py` (baru) — `wants_identity`, `handle_face_result`
  (embedding di-pop sebelum validasi/penyimpanan; tidak pernah melempar; duplikat diabaikan; hasil
  nyata menimpa `unverified` + reset `face_synced`; `crop_path` hanya `crops/...` tanpa `..`),
  `finalize_unverified` + `schedule_unverified` (Timer daemon 15 dtk, sesi DB sendiri).
  `schemas/intrusion_face.py` (baru) — `FaceResultIn`. `events_consumer.py` — `FACE_TOPIC`,
  langganan `(FACE_TOPIC, 1)`, cabang handler, jadwal fallback di cabang EVENTS
  (`wants_identity` → `schedule_unverified`). `schemas/zone.py` — `face_id` masuk tuple flag bool.
- **Bukti:** RED ImportError; GREEN `test_intrusion_face_api.py` 12 tes (pemetaan status dan `reason`
  dominan, embedding tak pernah ada di payload/WS, duplikat, penimpaan `unverified`, path tidak aman
  diabaikan, broadcast `kind:"face"`, langganan topik, guard `wants_identity` per severity/saklar),
  plus 422 flag non-bool di `test_zones_api.py` dan `face_id` raw di `test_config_push.py`;
  suite backend `944 passed`.
- **Dampak:** alert critical yang fiturnya aktif selalu berakhir salah satu dari empat hasil.
- **Rollback:** revert commit ini.

### Face ID pada intrusion critical — T5 caption identitas + migrasi 0023 (2026-10-08)

- **Konteks:** hasil identitas harus sampai ke Telegram: baris `Identitas` pada caption alert foto,
  sekali, aman terhadap edit bersamaan dari worker AI.
- **Perubahan:** `alembic/versions/0023_alert_face_synced.py` (baru; `alert.face_synced` Boolean
  NOT NULL default false) + `models/alert.py`. `services/telegram.py` — `format_caption` menambah
  baris `("Identitas", …)` setelah Level untuk event `intrusion` ber-`payload.face` (empat teks,
  status asing diabaikan, nama ter-escape, tetap dalam batas 1024 UTF-16).
  `services/alert_ai.py` — `_edit_lock` modul; `sync_ai_caption` membungkus I/O Telegram dengan
  lock; `sync_face_caption` (guard tanpa syarat teks AI, skip `identity_skipped_text_only` untuk
  alert teks, skip bila identitas belum ada — consumer yang memanggil ulang; klaim atomik
  `face_synced` + commit sebelum I/O; `_release` kolom face saat gagal).
  `services/alert_dispatcher.py` — `has_face` dihitung sebelum snapshot; `face_synced = has_face and
  sent`; pasca-kirim `db.refresh(event)` lalu `sync_ai_caption` dan `sync_face_caption`.
- **Bukti:** RED (kolom/fitur belum ada); GREEN `test_migration_0023.py` dua siklus + uji bertumpuk
  di atas 0022; `test_telegram.py` +10 tes caption; `test_face_alert_sync.py` 7 tes (edit dengan AI
  + identitas, tanpa AI, klaim sekali + rilis saat gagal, noop kedua kali, skip teks, kedua urutan,
  dua thread serial oleh lock dan `not db.in_transaction()` selama I/O); dispatcher dua tes
  (identitas awal tanpa edit kedua; face tertulis setelah caption dirender → edit pasca-kirim).
- **Dampak:** dua sumber edit (AI, identitas) bekerja pada urutan apa pun tanpa saling menimpa.
- **Rollback:** revert commit ini; kolom 0023 aditif aman dibiarkan.

### Face ID pada intrusion critical — T4 pencocokan ketat (2026-10-08)

- **Konteks:** salah-cocok lebih berbahaya daripada tidak dikenal: butuh ambang ketat + margin
  top-1/top-2 di API.
- **Perubahan:** `services/face.py` — `MatchResult.margin` (default `None`, terakhir agar pemanggil
  posisional lama tetap cocok), `FaceGallery.top2` (satu pass, terbaik per karyawan, maks dua
  karyawan), `match_strict` (`low_quality|no_match|ambiguous|matched`; tanpa runner-up
  `top2 = 0.0`). `core/config.py` — `face_id_threshold = 0.50`, `face_id_margin = 0.10` (nilai awal,
  dikalibrasi lapangan). `docker/compose.yml` — dua env itu di anchor `x-api-environment`.
- **Bukti:** RED ImportError + compose guard merah; GREEN `test_face_strict.py` 8 tes + guard compose
  (`api` dan `retention` menerima default resolve, `vision` tidak); suite backend `912 passed`.
- **Dampak:** identitas hanya `recognized` bila top1 ≥ ambang dan menang margin — ragu = tidak dikenal.
- **Rollback:** revert commit ini.

### Face ID pada intrusion critical — T3 identity_zones (2026-10-08)

- **Konteks:** fitur hanya boleh aktif pada kamera yang memenuhi syarat; sisanya persis perilaku lama.
- **Perubahan:** `node.py` — `identity_zones(cam)` (zona `critical` dengan behavior `intrusion`
  ber-`face_id is True`; string `"true"` ditolak); `_start_camera` membuat `IntrusionRegistry` bersama
  hanya bila ada ident zone **dan** worker wajah; ident tanpa worker wajah → peringatan sekali dan
  fitur tidak aktif; registry/ident diteruskan sebagai keyword opsional ke kedua worker.
- **Bukti:** RED ImportError; GREEN `test_node_intrusion_face.py` 6 tes (parametrize severity/saklar,
  registry dibagi dua worker, tanpa face_id → tanpa registry, warning tanpa attendance, toggle
  face_id hanya merestart kamera itu); suite vision `307 passed`.
- **Dampak:** saklar per zona aman; kamera lain tidak tersentuh (dibuktikan tes restart per kamera).
- **Rollback:** revert commit ini.

### Face ID pada intrusion critical — T2 kabel worker + transport (2026-10-08)

- **Konteks:** registry harus diisi CameraWorker dan dikosongkan jadi pesan oleh FaceGateWorker;
  loop frame tidak boleh menunggu unggahan crop.
- **Perubahan:** `transport/mqtt.py` — `FACE_TOPIC` + `publish_face` (QoS1, antrean disk).
  `face_worker.py` — keyword `registry`; bypass motion gate selama `registry.active`; `observe` di
  `_process` memakai deteksi SCRFD yang sama; `_ident_step` pada jalur proses/idle/motion-skip;
  pengiriman per pesan di thread daemon `ident-ship-<camera>` (pop `_crop`, unggah
  `upload_bytes(crop, "crop", timeout=3.0, retries=1)`, publish; gagal unggah tetap kirim), join
  maks 5 dtk di `finally`. `node.py` — `registry` + `ident_zones`; `touch` untuk track `misses == 0`
  yang titik kakinya di polygon; `bind` saat event intrusion zona ident terbit.
- **Bukti:** RED (keyword `registry` dan `publish_face` tidak ada); GREEN
  `test_intrusion_face_workers.py` 13 tes + tes transport QoS1/antrean; tanpa registry jalur lama
  persis (`FakeTransport` tanpa `publish_face` tidak error); suite vision `301 passed`.
- **Dampak:** inti integrasi berjalan tanpa mengubah gerbang attendance yang ada.
- **Rollback:** revert commit ini.

### Face ID pada intrusion critical — T1 modul intrusion_face (2026-10-08)

- **Konteks:** fondasi murni tanpa CUDA: registry person TTL 3 dtk, asosiasi kepala 40%, pitch,
  crop JPEG, kolektor embedding per event.
- **Perubahan:** `vision/vision/intrusion_face.py` (baru) + `tests/test_intrusion_face.py` (17 tes).
  Kolektor memisahkan hitungan penolakan dari `_funnel` attendance; kandidat crop diranking
  `lebar_px × skor` tanpa melihat hasil gerbang; pesan `drain` siap setelah `min_frames`, jendela
  8 dtk, atau person hilang; `_crop` di-pop pemanggil.
- **Bukti:** RED `ModuleNotFoundError: vision.intrusion_face`; GREEN 17/17; dua mutasi terbukti
  merah dan dikembalikan (`HEAD_FRAC 0.40→1.0` merah tes torso; jendela `>=`→`>` merah setelah tes
  jaga entri segar); suite vision `290 passed` (273 + 17).
- **Dampak:** logika identitas dapat diuji tanpa GPU sebelum dikabel ke worker.
- **Rollback:** revert commit ini.

### Deploy `web` modal Koreksi ke `gspe-ai3` dan cek UI Exit awal sebagian (2026-10-08)

- **Konteks:** `f8d370a` (merge `fix/attendance-late-label`, `c9a52aa`) di-deploy atas persetujuan user: `git pull --ff-only` lalu `./docker/setup.sh` di clone Docker; hanya container `web` dibuat ulang (`api`, `retention`, `vision`, `go2rtc`, `mosquitto`, `postgres` tidak berubah). Tanpa migrasi.
- **Terverifikasi di server:** clone di `f8d370a`; `/api/v1/health` ok; `web` `Up (healthy)`, `/` mengembalikan 200; `index.html` `Cache-Control: no-cache`; bundle yang disajikan memuat kunci `at.status.lateOption`.
- **Cek UI Exit awal oleh user (sebagian):** (1) CSV ekspor `rekap_absensi_2026-10-05_2026-10-08.csv` punya kolom terakhir `exit_early_min` dengan 12 baris, 2 berperingatan (EMP-001 = 115 menit, EMP-002 = 169 menit, keduanya 2026-10-07 `late`; sesuai perhitungan server sebelumnya). (2) Screenshot 11:26 (UI bahasa Inggris, tab Daily 2026-10-07): tombol **Correct** tampil pada dua baris `LATE 338 MIN` dan `LATE 355 MIN` yang berperingatan (dan pada baris `NO EXIT`), modal "Attendance correction" terbuka dengan jam masuk 14:23 dan jam keluar 15:35 yang cocok dengan CSV, dan dropdown Status menampilkan `LATE` tanpa `{n}` (perbaikan di atas sudah aktif).
- **BELUM dikonfirmasi:** chip Exit awal di sel exit (tertutup overlay modal pada screenshot, jadi tidak terlihat) dan tampilan layar 390 px tanpa overflow horizontal. ROADMAP EEA tetap `[~]`.
- **Dampak:** hanya UI web; tidak ada perubahan API, data, atau node.
- **Rollback:** `ssh gspe-ai3`, `cd /home/gspe-ai3/project_cv/I-Sentinel-docker && git checkout 7e5d39c && ./docker/setup.sh` (tanpa migrasi).

### Modal Koreksi — opsi Status "Telat" tanpa placeholder `{n}` (2026-10-08)

- **Konteks:** dari cek UI Exit awal, dropdown Status di modal "Koreksi absensi" menampilkan opsi `LATE {n} MIN` (EN) / `TELAT {n} MNT` (ID) dengan `{n}` mentah. `AttendancePage.tsx` memakai `t('at.status.late')` apa adanya untuk opsi, sedangkan badge di tabel (`statusLabel`) sudah mengganti `{n}` dengan `late_minutes` baris. Menit tidak bermakna pada opsi pilihan (menit dihitung server dari jam masuk dan shift), jadi opsi dibuat tanpa menit.
- **Perubahan:** kunci i18n baru `at.status.lateOption` (`TELAT` / `LATE`) di kedua kamus; opsi `late` pada `Select` `ov-status` memakainya. Label badge di tabel tidak berubah.
- **Bukti:** RED `dropdown Status di modal Koreksi tidak menampilkan placeholder {n}`: `AssertionError: expected true to be false` (ada opsi bermuatan `{n}`); GREEN `attendance.test.tsx` `20 passed`; suite berurutan: vitest `36 files / 488 passed` (487 + 1 tes baru), build exit 0 (`✓ built in 2.85s`), lint 24 warning (sama dengan baseline). Log mentah di `temp/logs/late-label/`.
- **Dampak:** hanya teks opsi dropdown; tidak ada perubahan perilaku, API, atau data. BELUM dilihat di browser.
- **Rollback:** revert commit ini.

### Exit awal — deploy `gspe-ai3` (2026-10-08)

- **Konteks:** `5c2c21b` (merge `feat/exit-early-warning`, termasuk perbaikan review `d2ec2cb`) di-deploy atas persetujuan user: pull `main` lalu `./docker/setup.sh`; container `api`, `web`, dan `retention` (berbagi image `api`) dibuat ulang, `vision`, `go2rtc`, `mosquitto`, `postgres` tidak berubah. Tanpa migrasi.
- **Terverifikasi di server:** `/api/v1/health` ok; `EXIT_EARLY_MIN = 60` dan `exit_early_min` ada di container `api`; `index.html` dikirim dengan `Cache-Control: no-cache` (tidak perlu hard refresh); fungsi dijalankan pada data nyata: 28 baris rekap, 2 berperingatan (dua baris `late` dengan exit terakhir lebih dari 60 menit sebelum shift selesai, sama dengan temuan sebelum fitur ini).
- **BELUM diuji:** tampilan chip dan tombol Koreksi di browser (termasuk layar 390 px, nol overflow horizontal), unduhan CSV dengan kolom `exit_early_min` di server, dan perilaku zona waktu pada Postgres untuk jam shift nyata di luar dua baris di atas. Status ROADMAP tetap `[~]` sampai user memeriksa UI.
- **Rollback:** `ssh gspe-ai3`, `cd /home/gspe-ai3/project_cv/I-Sentinel-docker && git checkout 67cd400 && ./docker/setup.sh` (tanpa migrasi).

### Exit awal — perbaikan review: tombol Koreksi untuk baris berperingatan (2026-10-08)

- **Konteks:** review sesi perencanaan atas `c2e91bd`. Spec, WORKFLOW, dan runbook menyuruh admin "membuka Koreksi" untuk menindaklanjuti chip Exit awal, tetapi tombol Koreksi hanya dirender untuk `no_exit`/`no_entry`. Baris `ontime`/`late` berperingatan hanya bisa dikoreksi dengan mengklik barisnya, tanpa petunjuk visual.
- **Perubahan:** `AttendancePage.tsx`: tombol Koreksi (admin) juga tampil bila `exit_early_min != null`. Dua tes baru di `attendance.test.tsx`; `WORKFLOW.md`, runbook, dan baris ROADMAP EEA disesuaikan.
- **Bukti:** RED `admin: baris ber-peringatan Exit awal punya tombol Koreksi yang membuka modal`: `Unable to find an element by: [data-testid="fix-12"]`; tes viewer dibuktikan lewat mutasi (hapus `isAdmin &&` membuat tes viewer lama dan baru merah, dikembalikan). GREEN terarah `19 passed`; suite: frontend `36 files / 487 passed`, build exit 0, lint 24 warning dengan pasangan identik baseline.
- **Dampak:** admin melihat jalan tindak lanjut yang jelas di baris berperingatan; viewer tetap tanpa tombol. BELUM diuji di server nyata.
- **Rollback:** revert commit ini.

### Peringatan exit awal pada rekap attendance — T3 dokumen + verifikasi akhir (2026-10-08)

- **Konteks:** menutup siklus T1–T2 (`b51bbb5` backend, `c916cb6` frontend) dengan alur pemakaian dan prosedur operasional. ROADMAP sengaja tetap `[~]`: belum di-push, belum di-deploy, belum dilihat user di browser.
- **Perubahan:** `WORKFLOW.md` §12 butir 3 — chip **Exit awal** pada rekap dan kolom CSV-nya, status tidak berubah, keputusan akhir lewat **Koreksi**. `ARCHITECTURE.md` baris domain Absensi — semantik `exit_early_min`, kelima syarat, ambang 60 menit, dan catatan tanpa kolom DB baru/migrasi. `docs/runbooks/attendance.md` — subbagian **Peringatan "Exit awal"** (peringatan bisa berarti pulang awal *atau* exit sore tidak terdeteksi dan sistem tidak bisa membedakan; `last_exit` tetap exit terakhir walau exit berulang; langkah cek event `exit` di Inbox lalu Koreksi; kapan peringatan tidak muncul), butir 5 di *Koreksi manual*, dan kolom `exit_early_min` di *Import/export CSV*. `ROADMAP.md` — baris `EEA` `[~]` dengan angka tes.
- **Bukti:** suite berurutan pada tree ini (log mentah `temp/logs/exit-early-warning/t5-*.txt`):
  ```text
  backend: 904 passed, 1 deselected, 559 warnings in 170.64s (0:02:50)   exit 0
  vitest:  Test Files 36 passed (36) · Tests 485 passed (485)            exit 0
  build:   ✓ built in 3.04s                                              exit 0
  lint:    Found 24 warnings and 0 errors (16 pasangan file-rule identik baseline)
  docker:  76 passed in 9.29s                                            exit 0  (tidak disentuh)
  ```
  Sesuai target handoff §3: backend 896 → 904 dan frontend 483 → 485 hanya karena tes baru, docker sama persis, build exit 0, tanpa warning lint baru.
- **Dampak:** tidak ada perubahan kode atau kontrak; dokumen mengikuti perilaku yang sudah diimplementasikan di T1–T2.
- **Rollback:** revert commit ini.

### Peringatan exit awal pada rekap attendance — T2 frontend: chip "Exit awal" (2026-10-08)

- **Konteks:** lanjutan Task 1 — peringatan API `exit_early_min` harus terlihat di halaman rekap supaya admin bisa memutuskan lewat **Koreksi**. Spec/plan: `docs/superpowers/specs/2026-10-08-exit-early-warning-design.md` + `docs/superpowers/plans/2026-10-08-exit-early-warning.md`.
- **Perubahan:** `src/api/attendance.ts` — `AttendanceRow.exit_early_min?: number | null` (opsional agar fixture tes lama dan respons tanpa field tetap lolos `tsc -b`). `src/features/attendance/AttendancePage.tsx` — chip di sel exit di bawah jam (`data-testid={exit-early-<id>}`, amber `#f1c21b`, font 11 seperti `StatusBadge`), hanya dirender bila field terisi. `src/app/i18n.tsx` — satu kunci baru `at.exitEarly` (`id` + `en`), durasi memakai ulang `at.duration.hm`. Tidak ada CSS baru.
- **Tes:** 2 tes baru di `src/__tests__/attendance.test.tsx` — teks persis `Exit 3j 57m sebelum shift selesai` untuk `{ ...ROWS[1], exit_early_min: 237 }`, dan tidak ada chip untuk `null` maupun baris fixture lama tanpa field (Review Focus 5).
- **Bukti:** RED `1 failed | 16 passed` — `Unable to find [testId] exit-early-12` (chip belum ada). Tes penjaga kedua lulus sejak awal karena menguji perilaku yang memang sudah benar; dibuktikan bisa gagal lewat mutasi sementara `!= null` → `!== undefined` (tes "tidak tampil bila null" merah, tes tampilan tetap hijau) lalu dikembalikan — `temp/logs/exit-early-warning/mutation-t2.txt`. Suite berurutan pada kode final: vitest `Test Files 36 passed (36)`, `Tests 485 passed (485)`, exit 0 (4× berturut-turut); build exit 0 (`✓ built in 2.96s`); lint `24 warnings and 0 errors` dengan 16 pasangan file-rule identik baseline. Catatan: run pertama setelah implementasi menunjukkan **1 kegagalan intermiten** (nama tes tidak tercatat karena keluaran dipotong `tail -8`); empat run berikutnya hijau semua dan tidak ada tes yang diubah.
- **Dampak:** Hanya sel exit yang berubah tampil (satu baris tambahan di bawah jam); status, tile ringkasan, filter, dan modal koreksi tidak berubah. Chip sengaja tidak diberi `whiteSpace: nowrap` agar bisa berganti baris dan tidak memaksa kolom melebar di 390 px — nol overflow horizontal masih perlu diverifikasi user di browser.
- **Rollback:** revert commit ini; tanpa migrasi.

### Peringatan exit awal pada rekap attendance — T1 backend (2026-10-08)

- **Konteks:** `recompute_day` menyimpan `last_exit = max(semua exit)`, sehingga exit makan siang yang tidak diikuti exit sore tetap membuat baris tampak lengkap. Sistem tidak bisa membedakan "pulang awal" dari "exit sore tidak terlintas kamera" — hanya admin yang bisa memutuskan. Keputusan user: **peringatan tanpa mengubah status** (opsi B, `docs/superpowers/specs/2026-10-08-exit-early-warning-design.md` + plan `2026-10-08-exit-early-warning.md`).
- **Baseline ulang sebelum Task 1** (`d40d0f1`, suite berurutan; keluaran mentah `temp/logs/exit-early-warning/preflight*.txt`): backend `896 passed, 1 deselected, 551 warnings in 161.62s`; vitest `36 berkas / 483 passed`, exit 0; build exit 0; lint `24 warnings and 0 errors` dengan 16 pasangan file-rule identik dengan `baseline-lint.txt`; docker `76 passed` (keluaran perencana, tidak disentuh). Sama persis dengan acuan §3 handoff.
- **Perubahan:** `services/attendance.py` — konstanta `EXIT_EARLY_MIN = 60` dan fungsi murni `exit_early_min(row, shift, now=None)` mengikuti pola `effective_status` (dihitung saat baca, tanpa migrasi, tanpa setelan): hanya untuk status tersimpan `ontime`/`late`, `override_note` kosong, shift dan `last_exit` ada, waktu baca sudah lewat `shift.end_time` pada `row.date`, dan selisih **lebih dari** 60 menit. `api/attendance.py` — field `exit_early_min` di `_row_dict` (satu tempat untuk daftar harian/rentang/per karyawan dan respons `PATCH`) serta kolom terakhir `CSV_COLUMNS` + selnya di `export_csv` (kosong bila `None`). Impor tidak diubah.
- **Tes:** 4 unit di `test_attendance_logic.py` (237 menit; batas 60 → None dan 61 → 61; tunggu jam shift selesai; tujuh keadaan None termasuk `override_note="import"` dan exit sesudah shift) dan 4 API di `test_attendance_api.py` (field daftar, kolom CSV terakhir, impor mengabaikan kolom, `PATCH` catatan → None). Satu-satunya perubahan tes lama: dict persis di `test_csv_export_rows` menambah `"exit_early_min": ""` (kolom baru memang bagian kontrak ekspor).
- **Bukti:** RED `9 failed, 67 passed` — 4 `AttributeError: module 'app.services.attendance' has no attribute 'exit_early_min'`, 3 `KeyError: 'exit_early_min'`, 2 `AssertionError` (dict ekspor dan header CSV); seluruhnya karena fitur belum ada, bukan galat impor. Mutasi sementara `>` → `>=` membuat tes batas merah dan `< end` → `<= end` membuat tes "tunggu shift selesai" merah, keduanya lalu dikembalikan. GREEN terarah `76 passed`. Suite backend penuh: `904 passed, 1 deselected, 559 warnings in 164.73s` (896 + 8 tes baru).
- **Dampak:** Status, `compute_status`, `recompute_day`, `AttendanceCloser`, tile ringkasan, filter, dan Telegram tidak berubah. Pembaca CSV pihak ketiga yang menghitung jumlah kolom perlu penyesuaian (kolom baru hanya di akhir); impor internal membaca per nama kolom sehingga CSV lama dan CSV hasil ekspor baru sama-sama lolos, dan baris hasil impor (`override_note='import'`) tidak diberi peringatan.
- **Rollback:** revert commit ini; tanpa migrasi dan tanpa setelan baru. BELUM diuji di server nyata.

### Node apply per kamera — deploy dan verifikasi server `gspe-ai3` (2026-10-07)

- **Konteks:** `ad93bf0` (merge `feat/node-apply-per-camera`, termasuk perbaikan review `27cecf8`) di-deploy atas persetujuan user: pull `main` di clone Docker lalu `./docker/setup.sh`; hanya container `vision` dibuat ulang (`api`, `web`, `go2rtc`, `mosquitto`, `postgres` tidak berubah). Pasca-deploy: `/api/v1/health` ok, kode baru ada di container.
- **Uji (user mengedit AI FPS kamera 358 "Lorong 1" di UI, satu kali):**
  - Log `vision`: `config applied: restarted [358], added [], removed [], unchanged 8`; satu `started 6 worker(s) for 9 camera(s)` sebelumnya = restart penuh setelah container dibuat ulang (config pertama). Tanpa `config diff failed`, `failed to start`, atau `worker died`.
  - Log `api`: tepat satu `PATCH /api/v1/cameras/358` (debounce kolom AI FPS bekerja).
  - Pemantau 8 menit (49 heartbeat): worker 362, 363, 364, 365 (face) dan 367 (detect) tetap `streaming`, fps tidak jatuh ke 0 atau `None`, `reconnects_1h` tetap 0 sepanjang edit. Kamera 358: fps `None` pada satu jendela (worker baru) lalu 8.0, state `streaming` sejak heartbeat berikutnya (<10 dtk).
- **Catatan:** fps semua kamera turun ±10% serentak tiap ±2–3 menit (17:33:41, 17:35:11, 17:36:41, 17:38:21) tanpa config apply; pola ini tidak terkait perubahan ini dan belum diselidiki.
- **Belum terverifikasi:** waktu restart kamera dengan worker detect (muat engine TensorRT); edit zona; perubahan setelan global (restart penuh); jalur kegagalan dan pemulihan worker mati di server. Perkiraan "20–30 detik" di dokumen diganti dengan angka terukur untuk kamera worker face saja.
- **State kamera 358:** `ai_fps` sekarang 8.0 (sebelumnya kosong = default 5) — perubahan uji user.
- **Rollback:** `ssh gspe-ai3`, `cd /home/gspe-ai3/project_cv/I-Sentinel-docker && git checkout a6b549e && ./docker/setup.sh` (tanpa migrasi).

### Node apply per kamera — perbaikan review: worker mati dihidupkan lagi dan start gagal dibersihkan (2026-10-07)

- **Konteks:** review sesi perencanaan atas `c3c2426`. (1) Rekonsiliasi hanya membandingkan config. Sebelumnya setiap push ulang (termasuk pengiriman ulang retained saat MQTT tersambung kembali dan `republish_all` saat API start) merestart semua worker sehingga worker yang mati ikut pulih; kini config identik tidak menyentuh apa pun, jadi worker yang mati (mis. `detector_factory` gagal memuat engine) tetap mati sampai kamera itu berubah, dan `run()` hanya keluar bila **semua** worker mati. (2) Bila `_start_camera` melempar setelah worker detect berjalan, kamera itu tidak dicatat di `_applied` tetapi worker detect dan recorder/ClipRing-nya tetap berjalan sampai push berikutnya.
- **Perubahan:** `vision/vision/node.py`: kamera yang punya worker tidak `is_alive()` masuk `changed` walau config sama; saat `_start_camera` gagal, `_stop_workers({i})` membuang worker dan menutup recorder yang sempat dibuat. Dua tes baru di `test_config_apply_per_camera.py`. Dokumen: `ARCHITECTURE.md` §3 dan baris ROADMAP NAC.
- **Bukti:** RED `test_camera_with_a_dead_worker_is_restarted_even_when_config_is_unchanged`: worker mati tetap ada di `_workers`; RED `test_failed_start_leaves_no_half_started_camera_or_open_recorder`: dua worker setengah jalan tertinggal. Mutasi sementara (hapus tiap perbaikan) membuat tiap tes merah, lalu dikembalikan. GREEN terarah `26 passed`; suite berurutan: vision `273 passed, 3 deselected, 2 warnings`, backend `896 passed, 1 deselected, 551 warnings`, docker `76 passed`.
- **Dampak:** perilaku pemulihan setara dengan sebelumnya untuk worker mati, tetapi hanya untuk kamera yang bermasalah. Hasil sampingan positif: pesan retained yang dikirim ulang saat MQTT tersambung kembali tidak lagi merestart kamera yang sehat. BELUM diuji di server nyata.
- **Rollback:** revert commit ini.

### Node apply per kamera T4 — docs: alur config apply dan runbook (2026-10-07)

- **Konteks:** dokumentasi kebijakan apply per kamera dan verifikasi lokal; BELUM diuji di server nyata.
- **Perubahan:** `ARCHITECTURE.md` §3 menjelaskan diff CameraCfg, lifecycle bersama, restart penuh pertama/global/fallback, FaceSettings, retry push dan log; `WORKFLOW.md` dan `docs/RUNBOOK.md` membedakan restart worker dari restart service manual. `ROADMAP.md` tetap `[~]`, kode selesai tetapi belum di-deploy/diuji server.
- **Bukti:** suite berurutan sebelum commit dokumen:
  ```text
  vision: 271 passed, 3 deselected, 2 warnings in 14.19s
  backend: 896 passed, 1 deselected, 551 warnings in 164.50s (0:02:44)
  docker: 76 passed in 9.01s
  ```
  Vision naik tepat 24 tes baru; backend dan Docker sama dengan baseline. Diff backend/frontend/docker, face_worker/recorder/config dan tiga berkas tes lama kosong; `git diff --check` exit 0. Scope diff hanya kode node, tes baru, dokumen task dan dua catatan spec/plan yang sudah ada.
- **Dampak:** perkiraan reconnect 20–30 detik berasal dari plan, bukan pengukuran sesi ini; durasi dan isolasi kamera tetap perlu diuji di server. Smoke test di commit terakhir dilakukan setelah commit ini dan dilaporkan terpisah.
- **Rollback:** revert commit perubahan node dan dokumen terkait, lalu rebuild `vision`; tanpa migrasi atau perubahan backend.

### Node apply per kamera T3 — feat(vision): gabungkan antrean config (2026-10-07)

- **Konteks:** snapshot config penuh yang menumpuk tidak perlu diterapkan satu per satu; BELUM diuji di server nyata.
- **Perubahan:** `run()` menguras antrean dengan `get_nowait()` sesudah `get(timeout=0.2)`, lalu menerapkan hanya snapshot terakhir. Tes memakai thread dengan Event untuk menunggu snapshot terakhir tanpa jeda arbitrer.
- **Bukti:** RED `1 failed, 1 warning in 0.39s`: spy menerima tiga config (FPS 5, 10, 15), bukan hanya FPS 15. GREEN terarah dan penjaga pesan tunggal lama `25 passed, 1 warning in 1.62s`; suite vision `271 passed, 3 deselected, 2 warnings in 14.18s`.
- **Dampak:** satu apply per kumpulan snapshot yang sudah tersedia; kontrak MQTT dan pesan tunggal tidak berubah. Worker thread tes di-join dalam finally.
- **Rollback:** revert commit ini dan rebuild `vision`; tanpa migrasi.

### Node apply per kamera T2 — feat(vision): diff config per kamera (2026-10-07)

- **Konteks:** satu perubahan kamera tidak boleh menghentikan kamera lain; BELUM diuji di server nyata.
- **Perubahan:** `apply_config` membandingkan `CameraCfg`, menyimpan tanda tangan global, memulai ulang hanya kamera berubah/ditambah, menghentikan kamera dihapus, merestart kamera ber-worker face saat `FaceSettings` berubah, menghapus kamera gagal dari `_applied`, dan fallback penuh pada galat diff. Log diff berisi daftar ID terurut.
- **Bukti:** RED `14 failed, 9 passed in 0.28s`: worker kamera lain ikut diganti, recorder lain ditutup, start failure lolos keluar, confidence kamera dihapus tertinggal, log diff belum ada. GREEN terarah `23 passed in 0.18s`; suite vision `270 passed, 3 deselected, 2 warnings in 13.95s`. Tes config pertama dan empat variasi global detector sudah hijau sebelum implementasi karena restart penuh merupakan perilaku lama; belum dimutasi, dicatat eksplisit.
- **Dampak:** worker dan recorder kamera tidak berubah tetap identik dan hidup. Enam perubahan kamera, add/remove, FaceSettings, gagal lalu config kembali, fallback, kamera tanpa zona dan confidence diuji dengan fake. Blok detector/face-device lama tidak diubah; tes GPU baru tidak ditambahkan.
- **Rollback:** revert commit ini dan rebuild `vision`; tanpa migrasi atau perubahan backend.

### Node apply per kamera T1 — refactor(vision): lifecycle worker per kamera (2026-10-07)

- **Konteks:** pemisahan lifecycle sebelum diff config; BELUM diuji di server nyata.
- **Perubahan:** `vision/vision/node.py`: `_start_camera`, `_stop_workers(camera_ids)` berfilter, daftar worker ditukar sebelum join, recorder bersama ditutup sekali, `_applied` mencatat kamera tanpa zona. Tes baru memakai sumber idle dan recorder palsu.
- **Bukti:** baseline ulang `247 passed, 3 deselected, 2 warnings in 13.98s`; RED `3 failed, 1 passed in 0.32s` karena filter belum diterima dan `_applied` belum ada; GREEN terarah `4 passed in 0.20s`; suite vision `251 passed, 3 deselected, 2 warnings in 13.96s`. Tes tanpa filter sudah lulus sebelum implementasi karena menjaga perilaku lama.
- **Dampak:** belum mengubah kebijakan restart config. Inisialisasi `_detector_settings = None` membutuhkan pembaca info detector memakai `or {}`; algoritma heartbeat dan `_camera_stats` tidak berubah. Dua warning identik baseline.
- **Rollback:** revert commit ini dan rebuild `vision`; tanpa migrasi.

### Ops kecil C — docs: profil parameter wajah untuk Kantor dan Industri (2026-10-07)

- **Konteks:** uji lapangan face gate refine menunjukkan gerbang node (lebar 80 px, skor 0,6) meloloskan frame yang pasti ditolak API karena kualitas gabungan `det_score × min(1, lebar/112) × (1 − yaw)` < `face_min_quality` (0,5): event `low_quality` pada wajah 82–85 px. Keputusan user: gerbang tidak diubah di kode (event `low_quality` tetap terlihat di Inbox); yang diubah dokumennya, dengan parameter praktik terbaik hanya untuk lingkungan Kantor dan Industri.
- **Perubahan:** `docs/runbooks/attendance.md`: bagian "Profil parameter: Kantor dan Industri" (rumus lebar minimum `≈ 56 / (det_score × (1 − yaw))` dan tabel, parameter UI per profil, kamera/cahaya/APD/enrollment) dan catatan kalibrasi (ubah lebar dan skor bersamaan). **Koreksi:** `face_match_threshold`, `face_min_quality`, dan `attendance_cooldown_min` hanya env (`Settings`) dan **tidak diteruskan** `docker/compose.yml`, jadi di Docker tetap default (0,40 / 0,5 / 5 menit) dan bukan setelan UI; saran lisan sebelumnya untuk menurunkan `face_min_quality` lewat UI keliru. Tidak ada perubahan kode, default, atau setelan server.
- **Bukti:** dokumen saja; angka tabel rumus dihitung ulang (`56/(0,6×0,95)=98`, `56/(0,7×0,8)=100`, `56/(0,65×0,8)=108`); contoh lapangan lebar 82 px, skor 0,64, yaw 0,03 → kualitas 0,45.
- **Dampak:** panduan setel awal per lingkungan; tetap wajib protokol uji penerimaan 10×5 per lokasi. Mengubah `FACE_MIN_QUALITY`/`FACE_MATCH_THRESHOLD` di Docker membutuhkan perubahan `docker/compose.yml` (di luar siklus ini).
- **Rollback:** revert commit ini.

### Ops kecil B — fix(web): index.html selalu divalidasi ulang oleh browser (2026-10-07)

- **Konteks:** setelah deploy face gate refine, toggle baru tidak tampil di browser user sampai hard refresh. `curl -sI localhost:7700/` hanya menampilkan `Last-Modified` dan `ETag`, tanpa `Cache-Control`, sehingga browser boleh memakai `index.html` lama yang menunjuk bundle lama (`assets/index-<hash>.js`); bundle baru sudah ada di image `web`.
- **Perubahan:** `docker/web/nginx.conf`: `location = /index.html { add_header Cache-Control "no-cache"; }` (juga berlaku untuk `/` dan route SPA lewat `index`/`try_files`). Bundle ber-hash tidak diubah. Guard statis baru `test_index_html_is_revalidated_so_deploys_reach_browsers`.
- **Bukti:** RED `assert (None)` (blok tidak ada); GREEN `pytest docker/tests` semua lulus. Verifikasi header di server dicatat setelah deploy.
- **Dampak:** deploy berikutnya langsung terlihat tanpa hard refresh; browser tetap mengirim request ringan (304 via ETag).
- **Rollback:** revert commit ini dan rebuild image `web`.

### Ops kecil A — fix(config): simpan AI FPS dan confidence setelah jeda ketik (2026-10-07)

- **Konteks:** pada uji lapangan face gate refine, tiap ketikan atau klik spinner kolom AI FPS (Deteksi & Model) langsung mengirim `PATCH /cameras/{id}`. Tiap PATCH mendorong config ke node dan node memulai ulang **semua** worker: log `gspe-ai3` mencatat 9 kali "started 5 worker(s)" dalam 20 menit, dan node sempat melaporkan `target_fps` 9.5 dan 1.0 (nilai antara).
- **Perubahan:** `DetectionPage.tsx`: tampilan tetap berubah seketika, tetapi PATCH dikirim 600 ms setelah perubahan terakhir per (kamera, kolom); perubahan yang masih menunggu dikirim saat halaman ditinggalkan. Berlaku untuk AI FPS dan confidence. Tes lama `detection tab saves per-camera fps…` hanya diubah waktu tunggunya (`timeout: 3000`).
- **Bukti:** RED `ketikan beruntun…`: PATCH `[{ai_fps: 1}, {ai_fps: 10}]` terkirim langsung, `perubahan yang masih tertunda…`: PATCH terkirim sebelum unmount; GREEN `detection.test.tsx` 7 passed; frontend `36 files / 483 passed`; build exit 0; lint 24 warning, pasangan identik baseline.
- **Dampak:** satu PATCH (dan satu restart worker) per perubahan, bukan satu per ketikan. Restart semua worker pada tiap config push tetap ada; itu topik terpisah (node menerapkan config per kamera yang berubah).
- **Rollback:** revert commit ini.

### Face gate refine — deploy dan uji lapangan `gspe-ai3` (2026-10-07)

- **Konteks:** deploy `45f7e5e` (branch fitur) ke `gspe-ai3` atas persetujuan user: `git checkout feat/face-gate-refine && ./docker/setup.sh`; `api`, `vision`, `web`, `retention` dibuat ulang. Server **masih di branch fitur** sampai merge. Verifikasi pasca-deploy: `/api/v1/health` ok, `alembic` `0022 (head)`, kode baru ada di container, 3 GPU terlihat di `vision`, log `api` tanpa error, `app_url` = `http://192.168.2.133:7700`.
- **Hasil uji user:** toggle "Catat absensi" dan "Kirim wajah tidak dikenal" tampil setelah hard refresh (browser menyimpan `index.html` lama: nginx hanya mengirim `Last-Modified`/`ETag`); skenario Telegram (CHECK IN, SUDAH CHECK IN, TERDETEKSI, Unknown OFF) dinyatakan sesuai. Lintasan cepat tanpa berhenti sebagian besar **tidak tercatat**.
- **Data pemantau live** (heartbeat ±10 dtk, `cameras[].ai.funnel`, dua jendela: 7 dan 10 menit; semua orang yang lewat ikut terhitung, jadi angka kasar):
  - 10 menit (15:31–15:41, 362/363 pada 10 fps): 7 track emit vs 36 silent. Frame lolos: 362 `9/472` (`blur` 237, `small` 153), 363 `4/523` (`small` 309, `zone` 87), 365 `39/523` (`zone` 129, `small` 75, `blur` 43), 364 `30/119`. Waktu ke frame lolos pertama 2,6–3,8 dtk di 365/363 (outlier 17,5 dtk).
  - Stream main 362/363/365: H.264 1920×1080 25 fps (`ffprobe` via go2rtc `:7705`), jadi resolusi bukan batasnya; wajah di zona terlalu sedikit piksel (event sukses lebar 111–199 px; kamera 364 `blur` 1251–2733, ttfg 0,0 dtk sebagai acuan ideal).
  - Menaikkan `ai_fps` 5→10 (362 Tangga 2, 363 Lorong Server) menggandakan frame tetapi tidak menaikkan frame lolos.
- **Keputusan user:** zona diperluas; SOP menatap kamera sebentar diterima; **protokol penerimaan 10×5 lintasan tidak dijalankan**; tidak ada perubahan ambang (`face_min_width_px`, `face_min_quality`, `blur_min`).
- **Belum dikerjakan:** geometri kamera 362/363/365 (dekatkan atau lensa lebih sempit; target lebar wajah ≥110 px); debounce kolom `ai_fps` (tiap ketikan memicu PATCH dan restart semua worker, ±9 kali dalam 20 menit); `Cache-Control: no-cache` untuk `index.html`; selaraskan gerbang node (lebar 80 px, skor 0,6) dengan kualitas minimum API 0,5 (muncul event `low_quality` pada wajah 82–85 px); uji `_seen_recently`/`_detected_recently` di Postgres (hanya SQLite); semantik rekap exit berulang (exit tengah hari menutupi `no_exit`).
- **Rollback:** `ssh gspe-ai3`, `cd /home/gspe-ai3/project_cv/I-Sentinel-docker && git checkout main && ./docker/setup.sh` (tanpa migrasi).

### Face gate refine — perbaikan review: throttle evidence "SUDAH CHECK IN" (2026-10-07)

- **Konteks:** review sesi perencanaan atas `8487b29`. Cooldown absensi hanya menghitung baris `AttendanceEvent`, sedangkan `already_in` tidak pernah membuatnya; setelah 5 menit pertama dari check in, **setiap** deteksi karyawan yang menetap di area kamera entry (resepsionis, satpam) akan mengirim satu pesan "SUDAH CHECK IN". Asumsi spec §8 ("cooldown yang ada sudah menyaring") keliru; spec/plan tidak diubah (catatan lama). Keputusan user: jendela 5 menit memakai `attendance_cooldown_min`, tanpa setting baru.
- **Perubahan:**
  - `attendance.py`: `_detected_recently` menjadi `_seen_recently(db, event, employee_id, *, same_zone, reason=None)`; cabang `already_in` kini memberi `match_reason="cooldown"` (tanpa alert) bila karyawan itu terlihat (event attendance mana pun, zona mana pun, ± cooldown). Evidence hanya terbit setelah karyawan tidak terlihat ≥ cooldown lalu muncul lagi. Jalur `detected` (zona OFF) tidak berubah perilaku.
  - `ZonesPage.tsx`: paragraf `zone-record-off-hint` memakai gaya yang sama dengan `zone-attendance-hint`.
  - Dokumen: WORKFLOW §12, ARCHITECTURE (kontrak `already_in`), runbook attendance, baris ROADMAP FGR.
- **Bukti:** RED `test_already_in_evidence_only_after_employee_was_unseen_for_the_window`: `assert 'already_in' == 'cooldown'` pada event 07:19 (jalur spam terbukti); tes penjaga `test_already_in_not_suppressed_by_another_employee_being_seen` lulus sejak awal dan menjadi merah (`'cooldown' == 'already_in'`) saat filter `employee_id` dihapus sementara (dikembalikan). GREEN terarah `130 passed`; suite berurutan: backend `896 passed, 1 deselected, 551 warnings in 157.24s`; frontend `36 files / 481 passed`; build exit 0; lint 24 warning, pasangan identik baseline.
- **Dampak:** pesan "SUDAH CHECK IN" tidak lagi berulang untuk orang yang terus terlihat; masih terbit saat masuk ulang setelah hilang ≥5 menit. Event tetap tercatat di Inbox (`cooldown`). BELUM diuji di server nyata; Postgres untuk `_seen_recently` belum diuji (SQLite saja).
- **Rollback:** revert commit ini; tanpa migrasi.

### Face gate refine T9 — docs: face gate refine (alur Telegram, zona deteksi-saja, runbook, corong) (2026-10-07)

- **Konteks:** eksekusi plan face gate refine. BELUM diuji di server nyata.
- **Perubahan:** Alur tiga pesan, flag JSON, kontrak payload/heartbeat, runbook kamera dan corong, protokol penerimaan 10×5; ROADMAP tetap [~].
- **Bukti:** Suite berurutan: backend `894 passed, 1 deselected, 551 warnings in 164.75s`; Docker `75 passed in 9.36s`; vision `247 passed, 3 deselected, 2 warnings in 13.67s`; frontend `36 files / 481 passed`; build exit 0; lint `24 warnings and 0 errors`, 16 pasangan rule-file identik baseline.
- **Dampak:** Panduan lokal lengkap; BELUM diuji di server nyata. Review, deploy, tuning dan penerimaan server tetap di luar sesi.
- **Rollback:** Revert commit task ini; tanpa migrasi.
- **Catatan:** Runbook lama memiliki kalimat kalibrasi terputus; diganti panduan berbasis face_stats dan corong pada bagian yang memang ditargetkan plan.


### Face gate refine T8 — feat(vision): corong face worker di heartbeat dan monitoring (2026-10-07)

- **Konteks:** eksekusi plan face gate refine. BELUM diuji di server nyata.
- **Perubahan:** Counter wajah per track/frame, rejects lima kode, emitted/silent, median ttfg; reset dict tanpa lock; in_zone dibersihkan; heartbeat face funnel/skip; schema monitoring kompatibel node lama.
- **Bukti:** RED vision `9 failed, 56 passed, 1 warning in 9.06s`; RED backend `4 failed, 31 passed`; GREEN vision `247 passed, 3 deselected, 2 warnings in 13.36s`; GREEN backend `894 passed, 1 deselected, 551 warnings in 168.27s`.
- **Dampak:** Corong per jendela heartbeat, tanpa UI atau biometrik tambahan; node lama funnel None.
- **Rollback:** Revert commit task ini; tanpa migrasi.
- **Catatan:** Tambahan tes rejects zone/score/yaw/blur dan boundary API. Run backend pertama 1 failed/893 passed karena fixture API baru node.modules=None; diperbaiki tanpa menyentuh tes lama. Mutasi sementara field skema membuktikan RED KeyError funnel setelah fixture benar, lalu field dipulihkan sebelum GREEN penuh.


### Face gate refine T7 — fix(vision): motion gate tidak memutus bukti wajah yang masih terlihat (2026-10-07)

- **Konteks:** eksekusi plan face gate refine. BELUM diuji di server nyata.
- **Perubahan:** Motion gate tetap update setiap frame; wajah yang terlihat mempertahankan pemrosesan; counter motion_skipped; tes gate kembali skip setelah wajah hilang.
- **Bukti:** RED `3 failed, 22 passed in 5.22s`; GREEN `67 passed, 1 warning in 8.63s` (face_worker, motion_gate, node).
- **Dampak:** Wajah diam mencapai tiga embedding tanpa menunggu force interval; overlay expiry lama tetap hijau.
- **Rollback:** Revert commit task ini; tanpa migrasi.
- **Catatan:** Ditambah satu tes eksplisit gate kembali skip setelah wajah hilang, sesuai kriteria smoke S3(g).


### Face gate refine T6 — feat(zones): toggle Catat absensi pada zona attendance (2026-10-07)

- **Konteks:** eksekusi plan face gate refine. BELUM diuji di server nyata.
- **Perubahan:** Toggle Catat absensi default ON; hint OFF lokal id/en; tes Inbox detected, tanpa mengubah EventsPage.
- **Bukti:** RED `1 failed | 104 passed (105)`; GREEN ulang `36 files / 481 passed`; build exit 0; lint `24 warnings and 0 errors`, pasangan identik baseline.
- **Dampak:** OFF menulis record:false hanya ketika toggle disentuh; nama detected tetap tampil tanpa label absensi.
- **Rollback:** Revert commit task ini; tanpa migrasi.
- **Catatan:** Run suite pertama: 1 failed/480 passed pada tes lama save calls createZone with normalized polygon (zone-start-ring hilang). Ulang tanpa beban lulus, tes lama tidak diubah. Tes detected lulus sejak awal; dicatat sebagai characterization, bukan klaim RED; tidak memutasi EventsPage yang di luar scope.


### Face gate refine T5 — feat(attendance): opsi zona catat absensi (OFF = deteksi saja) (2026-10-07)

- **Konteks:** eksekusi plan face gate refine. BELUM diuji di server nyata.
- **Perubahan:** Flag record boolean; cabang OFF setelah anotasi sebelum cooldown absensi; dedup Event ±1 hari prafilter dan jendela lokal tepat; detected alert dan caption MASUK/KELUAR.
- **Bukti:** RED `7 failed, 141 passed, 78 warnings in 19.59s`; GREEN suite backend `890 passed, 1 deselected, 549 warnings in 166.63s`.
- **Dampak:** Zona OFF tidak menulis AttendanceEvent/AttendanceDay; default zona tetap mencatat.
- **Rollback:** Revert commit task ini; tanpa migrasi.
- **Catatan:** Tambahan tes dedup untuk event terlambat, batas tepat 5 menit, dan pengabaian alasan cooldown. Tes Unknown/default true lulus sejak awal sebagai kompatibilitas, dicatat sesuai handoff.


### Face gate refine T4 — feat(zones): toggle kirim wajah tidak dikenal ke Telegram (2026-10-07)

- **Konteks:** eksekusi plan face gate refine. BELUM diuji di server nyata.
- **Perubahan:** Toggle Carbon Unknown hanya saat Telegram efektif aktif; default true, PATCH hanya ketika disentuh; label id/en.
- **Bukti:** RED `1 failed | 29 passed (30)` karena toggle belum ada; GREEN `30 passed (30)`; lint `24 warnings and 0 errors`, pasangan identik baseline.
- **Dampak:** Zona lama tidak mendapat key baru saat toggle tidak disentuh.
- **Rollback:** Revert commit task ini; tanpa migrasi.
- **Catatan:** Tes toggle tidak tampil lulus sejak awal: penjaga perilaku negatif yang sudah ada, dicatat sesuai handoff.


### Face gate refine T3 — feat(alerting): opsi zona kirim wajah tidak dikenal ke Telegram (2026-10-07)

- **Konteks:** eksekusi plan face gate refine. BELUM diuji di server nyata.
- **Perubahan:** Zone.behavior_flag aman untuk data lama/non-dict; validasi boolean telegram_unknown; suppress no_match setelah saklar induk.
- **Bukti:** RED `7 failed, 57 passed in 17.71s`; GREEN `82 passed, 76 warnings in 18.73s`.
- **Dampak:** Unknown tetap Inbox; matched tidak terpengaruh; key hilang default true.
- **Rollback:** Revert commit task ini; tanpa migrasi.
- **Catatan:** Tes flag hilang/true lulus sejak awal sebagai penjaga kompatibilitas; tujuh RED fitur baru disaksikan. Fixture memblokir TCP eksternal.


### Face gate refine T2 — feat(telegram): entry berulang dikirim sebagai evidence "sudah check in" (2026-10-07)

- **Konteks:** eksekusi plan face gate refine. BELUM diuji di server nyata.
- **Perubahan:** Helper entry pertama dan exit sejak entry; payload evidence; already_in melewati rate-limit; caption SUDAH CHECK IN dengan fallback waktu tidak valid.
- **Bukti:** RED `8 failed, 85 passed in 1.42s`; GREEN `112 passed, 33 warnings in 9.15s` (attendance_logic, alerting, telegram, attendance_api).
- **Dampak:** Cooldown tetap diam; evidence tidak membuat attendance_event atau mengubah rekap.
- **Rollback:** Revert commit task ini; tanpa migrasi.
- **Catatan:** Run GREEN pertama gagal pada empat tes caption karena impor datetime belum ada; diperbaiki setelah membaca traceback. Tes baru mencakup waktu hilang, rusak, dan non-string.


### Face gate refine T1 — label tautan Telegram (2026-10-07)

- **Konteks:** tautan membuka detail event, bukan hanya klip. BELUM diuji di server nyata.
- **Perubahan:** `backend/app/services/telegram.py` dan tiga assertion `test_telegram.py`: label menjadi `Lihat event`.
- **Bukti:** baseline ulang: backend `864 passed, 1 deselected, 545 warnings in 163.11s`; Docker `75 passed in 8.92s`; vision `235 passed, 3 deselected, 2 warnings in 13.49s`; frontend `36 files / 477 passed`; build exit 0; lint `24 warnings and 0 errors`, exit 0. T1 RED `2 failed, 27 passed`; GREEN `70 passed in 1.05s`.
- **Penyimpangan:** plan mengharapkan tiga kegagalan; assertion tanpa URL tetap lulus karena tidak ada tautan, sehingga hanya dua tes merah. Assertion tersebut mengunci perilaku lama tanpa URL.
- **Dampak:** semua tipe alert memakai label baru; format lain tidak berubah.
- **Rollback:** revert commit T1; tanpa migrasi.


### Caption AI di alert Telegram (edit pesan, sekali per alert) — deploy + uji nyata `gspe-ai3` (2026-10-06)

- **Konteks:** lanjutan fitur AI (opsi A dari spec
  `docs/superpowers/specs/2026-10-06-telegram-ai-caption-design.md`): caption `🤖 AI:`
  terlihat langsung di grup Telegram. Eksekusi TDD native pada
  `feat/telegram-ai-caption` (T1 `4be2fed`, T2 `55c51ec`, T3 kode+dokumen).
  Sudah di-deploy dan diuji pada alert nyata (lihat **Uji nyata** di bawah).
- **Perubahan:**
  - `telegram.py`: `Delivery` (tuple kompatibel + `message_id`/`photo`),
    `edit_caption` (retry, "message is not modified" = sukses, galat bebas token),
    `format_caption(ai_text=...)` (baris AI di-escape, dilipat, anggaran ≤ 1024
    dengan margin 8 untuk emoji UTF-16, sisa < 40 → tanpa baris AI).
  - Migrasi `0022_alert_telegram_message`: `alert.message_id`, `alert.message_photo`,
    `alert.ai_synced` (default false, aditif).
  - `alert_ai.py` baru: `ai_text`, `build_caption` (dipindah dari dispatcher),
    `sync_ai_caption` idempoten (guard: `sent`, `message_id`, foto, chat aktif,
    token, caption `ok`; klaim atomik `UPDATE … WHERE ai_synced = false` (lihat perbaikan review); commit
    sebelum jaringan; tidak pernah raise, log tanpa nilai rahasia).
  - `alert_dispatcher.process`: pakai `build_caption`, simpan `message_id`/
    `message_photo`, `ai_synced=True` bila AI sudah di pesan awal, panggil
    `sync_ai_caption` setelah commit status.
  - `ai_worker.process`: caption `ok` memicu `sync_ai_caption` setelah commit dan
    broadcast, dibungkus try/except (kegagalan Telegram tidak mengubah baris caption).
- **Bukti (lokal):** RED benar per task; T2 GREEN 38 passed (test_alert_ai +
  test_alert_dispatcher); T3 test_ai_worker 19 passed; suite final S1 pada HEAD:
  backend `860 passed, 1 skipped, 545 warnings` (baseline `818 passed, 1 skipped` —
  naik hanya karena tes baru); Docker `75 passed`; vision `235 passed, 3 deselected`
  (tidak disentuh); frontend `36 files / 477 passed` (tidak disentuh); build exit 0;
  lint exit 0, `24 warning / 16 pasangan` identik baseline.
- **Perbaikan review (sesi perencanaan, code-review high; tiap temuan diverifikasi ke kode):**
  - `aeecc54` lock proses diganti klaim atomik: lock dipegang selama I/O Telegram (hingga ~48 dtk) dan juga dipakai
    thread dispatcher; objek `alert` di sesi bisa basi (`SessionLocal` memakai `expire_on_commit=False`) sehingga
    guard `ai_synced` meloloskan edit kedua. Kini `UPDATE … WHERE ai_synced = false` mengklaim edit, edit tanpa
    lock, klaim dilepas bila gagal.
  - `b2595d2` anggaran caption dihitung dalam unit UTF-16 untuk seluruh isi caption (nama kamera/zona berisi
    emoji astral sebelumnya bisa melewati 1024 dan ditolak 400).
  - `cdd0514` `build_caption` menolak event kosong secara eksplisit; dua lookup dan dua impor tak terpakai di
    dispatcher dibuang.
  - **Sengaja tidak diubah:** retry pada galat permanen dan `retry_after` (dampak kecil setelah lock dihapus);
    `ai_synced=True` walau baris AI terbuang karena anggaran (edit lanjutan akan membuangnya lagi); sinkron inline
    di thread `AiWorker` (keputusan spec, `ponytail:`); fallback `getattr` untuk tuple polos dari tes lama.
  - Bukti setelah perbaikan (berurutan, HEAD `cdd0514`): backend `864 passed, 1 skipped, 545 warnings in 154.79s`
    (860 → 864); Docker `75 passed`; vision `235 passed, 3 deselected`; frontend `36 files / 477 passed`; lint
    `24 warning / 16 pasangan` identik; build exit 0.
- **Uji nyata (`gspe-ai3`, 2026-10-06 17:15–17:21 WIB):** push `feat/telegram-ai-caption` @ `ea6afeb`, backup DB
  `isentinel-pre-telegram-ai-20261006-171509.sql`, `./docker/setup.sh`, migrasi `0022` jalan di Postgres; Telegram
  `app_url` dikoreksi ke `http://192.168.2.133:7700`. Zona 18 (kamera 362) diaktifkan user, dua event loitering:
  - event 4782 → alert 1312 `sent`, `message_id=34`, `message_photo=true`, `ai_synced=true`; caption AI `ok` 4089 ms
    (alert dibuat 17:19:00.860, caption selesai 17:19:04.974).
  - event 4783 (73 dtk kemudian) → alert 1313 `sent`, `message_id=35`, `ai_synced=true`; caption AI `ok` 3859 ms.
  - Satu alert per event, tanpa warning/galat Telegram di log api; user mengonfirmasi baris `🤖 AI:` muncul di
    grup Telegram. Zona 18 lalu dinonaktifkan kembali oleh user.
  - **Belum teruji nyata:** jalur AI siap sebelum alert terkirim (baris AI langsung di pesan awal), throttle 60 dtk
    per zona, dan galat Telegram saat edit (hanya tes otomatis). Waktu kirim alert tidak dicatat di DB, jadi urutan
    edit-setelah-kirim disimpulkan dari selisih ±4 dtk.
- **Dokumentasi:** `docs/RUNBOOK.md` — migrasi `0022` pada langkah deploy, verifikasi pesan Telegram + `app_url`,
  rollback caption Telegram (`git revert -m 1` merge / `alembic downgrade 0021`), dan gejala "baris AI tidak muncul".
- **Dampak:** alert tetap terkirim ±1 dtk tanpa menunggu LLM; tepat satu edit per
  alert apa pun urutan caption/pengiriman (dijamin klaim atomik + tes otomatis).
- **Rollback:** `git revert` (kolom aditif aman) atau `alembic downgrade 0021`.

### Deploy dan uji lapangan Caption AI, Tanya AI, dan AI Integration — gspe-ai3 (2026-10-06)

- **Konteks:** deploy cabang `feat/ai-event-caption` lalu `feat/ai-integration-settings` ke `gspe-ai3`
  (Docker; image `api` mendapat `ffmpeg`; migrasi `0021` di Postgres, idempoten; backup
  `isentinel-pre-ai-20261005-161652.sql`). Server pindah jaringan selama pengujian (IP sempat berubah,
  kembali `192.168.2.133`); LLM `intercon-agent` di LAN.
- **Hasil uji:**
  - **AI Integration (user, UI):** URL/model/kunci tersimpan; Tes koneksi `Teks OK · Vision OK · 1347 ms`; toggle
    aktif tersimpan. Server: `setting.llm` hanya field yang diubah, kunci di secret_store 0600, 0 kemunculan di log `api`.
  - **Tanya AI (server, service yang sama dengan UI, LLM nyata):** 7 event nyata + preset + teks bebas multi-turn:
    semua jawaban sesuai penilaian visual (laptop kini terbaca benar pada 4742); preset kedua dari cache (1 ms);
    7–16 dtk per pertanyaan; 10 baris audit `actor=user:1`, `channel=web`.
  - **Caption otomatis live (user memicu):** event 4770 loitering zona 18 "Pantry 2" → caption `ok`, 3,2 dtk, ±3,3 dtk
    dari event; user menilai caption akurat dan tampilan UI OK. Telegram tidak terpengaruh (belum dikonfigurasi).
  - Kontrak endpoint: `pytest -m llm` lulus 0,74 dtk (sebelum endpoint macet).
- **Temuan lapangan dan tindakan:**
  - Container `vision` kehilangan akses GPU setelah berhari-hari (`nvidia-smi` di dalam: `Failed to initialize NVML: Unknown Error`;
    ribuan `detector error`): **restart `vision`** memulihkannya (disetujui user). Hardening (device cgroup/CDI di compose)
    belum dikerjakan.
  - Jawaban kronologi klip 70 dtk berisi 12 baris (tiga identik), label "Satu kalimat ringkasan:" ikut tertulis, 30 dtk:
    diperbaiki (`ea6938c` prompt maks 8 baris + gabungkan + tanpa label; `f78d53c` parser membuang label). **Belum diverifikasi
    ke LLM nyata** karena inferensi endpoint sedang macet.
  - Inferensi endpoint LLM macet (`/models` 0,1 dtk, tetapi chat 8 token timeout): satu pertanyaan viewer (`user:5`, event
    4748) gagal `LLM timeout` 120 dtk dan tercatat `failed` (alur galat berfungsi). Perlu diperiksa di mesin LLM.
  - Kamera 367 dan 357 tanpa stream go2rtc; `camera_no_frames` untuk 367 menghasilkan event `system` (tidak di-caption).
- **Belum diuji live:** throttle zona 60 dtk, prompt Kustom, kuota 6/menit lewat UI, tab AI Integration tersembunyi untuk viewer di
  browser, reset ke env, hapus kunci. Telegram Tanya AI: fase 2, belum dibuat.
- **Rollback:** `LLM_ENABLED=false` (UI: matikan toggle) atau `git revert`; skema aditif.

### Blok AI ringkas di bawah meta grid dan kronologi rapi — lokal, belum di-deploy (2026-10-06)

- **Konteks:** permintaan user setelah mencoba UI: bagian Ask AI jarang dipakai, jadi harus ringkas dan hanya
  caption yang disorot; meta grid tetap utama; kronologi ditampilkan rapi. Rancangan disetujui di chat.
  Tahap deploy dan uji lapangan menunggu OK. ROADMAP tetap `[~]`.
- **Perubahan:**
  - `601e67a` blok AI dipindah ke bawah meta grid; caption disorot (latar aksen + garis kiri + lencana Dibuat AI);
    caption belum ada/menunggu/gagal satu baris redup; bagian **Tanya AI** tertutup secara default (tombol
    `aria-expanded`), tertutup lagi saat event berganti.
  - `936c725` `AiAnswer`: parser per baris menjadi elemen React tanpa HTML mentah: `m:dd — teks` / `detik N — teks`
    menjadi linimasa, butir menjadi daftar, `**tebal**`, ringkasan, `Kesimpulan:`; markdown lama (termasuk cache)
    ikut rapi; markup apa pun tetap teks.
  - `f6e9031` pesan sistem: teks biasa tanpa markdown; urutan kejadian `m:dd — kejadian` + `Kesimpulan:`.
  - `02d17b5` preset `what_happened` dan `report` meminta kronologi; preset lain 1-3 kalimat. Diverifikasi ke
    LLM nyata dengan bingkai event 4738 (kronologi `00:00 — …` + Kesimpulan; preset singkat 2 kalimat).
- **Bukti:** tes baru backend (preset/prompt) dan frontend (`ai-answer.test.tsx` 5 tes; `ask-ai-panel.test.tsx`
  tertutup default, caption disorot, kronologi, urutan di bawah meta grid). Browser 390×844 dengan API stub:
  `scrollWidth` 375 (< 390), blok AI di bawah meta grid, 3 baris linimasa; screenshot lokal
  `docs/evidence/ai-panel-{collapsed,open}-390.png` (gitignored). **BELUM diuji di server/UI nyata.**
- **Suite berurutan (HEAD `211066c`):** backend `817 passed, 1 skipped, 545 warnings in 153.54s` (807 → 817);
  Docker `75 passed`; vision `235 passed, 3 deselected`; frontend `Test Files 36 passed (36)` /
  `Tests 474 passed (474)` (464 → 474); lint exit 0, 24 warning, 16 pasangan identik baseline; build exit 0.
- **Dampak:** hanya tampilan dan teks prompt; tanpa migrasi, tanpa perubahan API. Jawaban cache lama tetap
  ber-markdown tetapi dirender rapi. **Rollback:** `git revert` commit di atas.

### Perbaikan review cabang AI Integration — lokal, tanpa deploy (2026-10-06)

- **Konteks:** review independen cabang `feat/ai-integration-settings` (skill code-review, level high;
  tiap temuan diverifikasi ke kode). Sembilan temuan diperbaiki dengan TDD (RED dilihat dulu, alasan
  merah benar), satu commit per perbaikan. **BELUM diuji di server/UI/LLM nyata.** ROADMAP tetap `[~]`.
- **Perbaikan:**
  - `85e17f2` kunci LLM di-strip dan divalidasi (spasi/newline hasil tempel membuat header Bearer
    ilegal; kunci spasi-saja dianggap tersimpan; kontrol/spasi di tengah atau >512 ditolak).
  - `8476ad6` `api_url` menolak kredensial tertanam (`user:pass@host`; sebelumnya tersimpan plaintext di
    `setting` dan dikembalikan oleh GET).
  - `3fc0995` `SecretStoreError` dari `secret_store.get` tidak lagi menghentikan `apply()` (override DB
    terbuang) atau membuat `GET /ai/settings` 500; diperlakukan seperti kunci kosong dengan peringatan log.
  - `bc018b6` + `1bd836d` `key_source` (`db|env|none`): UI tidak lagi menampilkan kunci env sebagai
    "tersimpan" dengan tombol hapus yang tidak berefek.
  - `8e3deb8` `llm_client.config_lock`: `apply()` dan `current_connection()` memakai lock yang sama
    sehingga satu `Connection` tidak memadukan nilai lama dan baru.
  - `00677b3` + `c55d008` tes koneksi menerima `clear_api_key` dan memakai kunci env (hasil setelah
    simpan), bukan kunci tersimpan.
  - `64b010a` kunci yang diketik dipertahankan saat Test atau simpan gagal; dikosongkan hanya setelah
    simpan berhasil (tes executor yang mengunci perilaku lama diperbarui).
  - `5d84b33` detail validasi 422 (nama field dan batas, tak pernah nilai) tampil di halaman.
  - `5d486cb` label latensi tes koneksi lewat i18n (id dan en).
- **Sengaja tidak diubah:** urutan `secret_store` sebelum commit dan lost update PUT bersamaan (admin-only,
  frekuensi rendah); kunci tersimpan dikirim ke URL form saat tes (keputusan spec §9, admin sudah bisa
  mengarahkan URL lewat simpan; memaksa mengetik ulang kunci menghambat pemakaian utama saat endpoint pindah);
  `style={{}}` inline (pola yang sama di halaman lain).
- **Bukti (berurutan, HEAD `1bd836d`):** backend `807 passed, 1 skipped, 545 warnings in 153.28s`
  (793 → 807: +14 tes); Docker `75 passed`; vision `235 passed, 3 deselected`; frontend
  `Test Files 35 passed (35)` / `Tests 464 passed (464)` (458 → 464: +6 tes); `tsc -b --noEmit` exit 0;
  lint exit 0, 24 warning, 16 pasangan identik baseline; build exit 0. Satu run vitest penuh (tepat
  setelah suite backend) mencatat 1 tes gagal yang tidak reproduksi: 4 run penuh berikutnya dan 6 run
  `zones.test.tsx` terpisah hijau; pola sama dengan flake `zones.test.tsx` yang dicatat executor pada baseline.
  Hasil run independen pada `7d53451` (sebelum perbaikan) cocok dengan laporan executor.
- **Dampak:** tanpa migrasi; kontrak API bertambah `key_source` (GET) dan `clear_api_key` (POST test).
  Perilaku default tanpa override tidak berubah.
- **Rollback:** `git revert` commit perbaikan terkait; `llm.env` tetap berlaku sebagai nilai awal.

### Pengaturan LLM di UI — AI Integration, lokal tanpa deploy (2026-10-05)

- **Konteks:** Task 1–4 plan `2026-10-05-ai-integration-settings` dijalankan native dengan
  RED → GREEN dan commit lokal. Admin kini dapat mengatur koneksi LLM tanpa SSH/restart,
  memakai prioritas DB > env > default. **BELUM diuji di server/UI/LLM nyata**; ROADMAP `[~]`.
- **Commit:** `f59fee1` layanan `llm_config` dan `Connection`; `a4fda8b` API admin/startup;
  `ff6c4ca` tab AI Integration. Commit keempat memperbarui dokumentasi dan bukti verifikasi.
- **Berkas:** `llm_client.py`, layanan/tes `llm_config`, router/skema/tes `ai_settings`, lifespan;
  frontend `api/aiSettings.ts`, `AiIntegrationPage.tsx`, `ConfigurationPage.tsx`, i18n dua bahasa,
  tes `ai-integration.test.tsx`; README, ARCHITECTURE, WORKFLOW, DESIGN, ROADMAP, RUNBOOK,
  CHANGELOG, dan daftar struktur AGENTS. Tidak ada migrasi/dependensi baru; konsumen LLM tidak diubah.
- **RED → GREEN:** T1 `2 failed, 9 passed, 41 errors` (fitur/modul belum ada) → `52 passed`;
  T2 `11 failed` (404 dan startup belum apply) → `11 passed`;
  T3 `14 failed` (tab/form belum ada) → `14 passed`.
  Fixture Storage pada percobaan RED pertama T3 diperbaiki lalu RED diulang.
  TypeScript sempat TS2322 pada tipe fixture hasil; anotasi kontrak diperbaiki lalu noEmit/build lulus.
- **Baseline diukur ulang:** backend `739 passed, 1 skipped, 521 warnings in 146.50s`;
  Docker `75 passed in 9.00s`; vision `235 passed, 3 deselected, 2 warnings in 13.58s`;
  frontend `34 files / 444 passed` setelah ulang flake lama `zone-start-ring`
  (run pertama `1 failed / 443 passed`). Build exit 0; lint exit 0, 24 warning / 16 pasangan.
- **Verifikasi penuh berurutan sebelum commit dokumen (perintah S1):**
  ```text
  backend: 793 passed, 1 skipped, 539 warnings in 154.27s (0:02:34)
  docker: 75 passed in 8.92s
  vision: 235 passed, 3 deselected, 2 warnings in 13.73s
  frontend: Test Files 35 passed (35); Tests 458 passed (458)
  build: exit 0; built in 2.89s
  lint: exit 0; 24 warning / 16 pasangan; baseline identical: True
  ```
  Backend naik 54 tes (43 T1 + 11 T2), frontend naik 14 tes. Tes lama tidak dihapus/diubah,
  kecuali dua penegasan jumlah tab `7→8` di `configuration.test.tsx` (judul tes tetap).
  Vision memiliki warning lama pynvml dan thread fixture `publish_heartbeat`; build tetap warning
  ukuran chunk. Suite S1 diulang pada commit terakhir untuk laporan handoff.
- **Bukti perilaku:** viewer 403 pada ketiga endpoint; key tidak di respons/DB;
  PUT invalid bersama key tidak menulis secret_store; null kembali ke env/default;
  form/stored key terredaksi pada error; apply DB kosong tidak merusak monkeypatch;
  tab viewer tidak fetch; simpan model saja tidak mengirim api_key.
  Browser stub API 390×844: document/body scrollWidth 390, koneksi, Lanjutan terbuka, dan Inggris.
  Browser dan Vite verifikasi telah dihentikan. Ini bukan penerimaan UI/endpoint nyata.
- **Dampak/keputusan:** `apply` hanya menyentuh override aktif/lama dan mengembalikan `_BASE`
  bila override dihapus. Kunci di `secret_store`, form tulis-saja dan dibersihkan saat dikirim.
  Validasi lengkap sebelum efek samping; clear key mengembalikan env, clear bersama key nonkosong
  ditolak. Input API strict, field tak dikenal ditolak; token/rate integer, timeout/interval boleh
  pecahan. Tes form tidak menyimpan/tidak mengambil slot worker, timeout 30 detik per panggilan,
  teks sukses dengan vision ditolak → `ok=true`, `vision_ok=false`.
  Konkurensi/antrean tetap env dan memerlukan recreate; pengaturan DB berlaku tanpa restart.
- **Rollback:** matikan AI dari UI lalu Simpan (override DB mengalahkan env), atau reset enabled
  lalu gunakan env false + recreate. Reset per field menghapus override, clear key tidak menghapus
  env. Rollback kode tahap ini: revert commit task urut terbalik lalu rebuild api/web; tanpa
  downgrade skema. Bila key hanya di secret_store, siapkan fallback env secara privat sebelum
  rollback karena kode lama hanya membaca env. Push, review, deploy, dan merge belum dilakukan.

### Perbaikan review cabang Caption AI dan Tanya AI — lokal, tanpa deploy (2026-10-05)

- **Konteks:** review independen cabang `feat/ai-event-caption` (skill code-review, level high;
  tiap temuan diverifikasi ke kode, temuan header juga dengan percobaan nyata `httpx` ke server
  lokal). Delapan temuan diperbaiki dengan TDD (RED dilihat dulu, alasan merah benar), satu commit
  per perbaikan. **BELUM diuji di server/UI/LLM nyata**; jaringan server dev sedang mati,
  deploy menunggu user. ROADMAP tetap `[~]`.
- **Perbaikan:**
  - `3b753c7` header `Authorization: Bearer ` (kunci kosong) ditolak h11 → tidak dikirim bila kunci kosong.
  - `689515e` caption otomatis menunggu slot LLM selama Tanya AI boleh memegangnya
    (`llm_timeout_ask_s`), bukan 5 detik yang membuat caption `failed` permanen; snapshot
    didekode sebelum mengambil slot.
  - `c5afcad` `recover()` menandai baris `pending` yang tak muat antrean sebagai `failed`
    ("antrean penuh"), tidak lagi menggantung.
  - `7eda054` cache preset tidak menyajikan jawaban `frames_used=0` bila event punya klip.
  - `a88e801` `PATCH /zones` `ai_caption: null` → 422 (sebelumnya IntegrityError 500);
    validator panjang prompt dicabut dari `ZoneOut` (nilai >600 di DB membuat daftar zona 500).
  - `898f098` panel Tanya AI: event hanya-klip (snapshot=false, clip=true) dinonaktifkan dengan
    pesan snapshot (`ai.err.snapshot`, id dan en), bukan "media kedaluwarsa"; 409
    `snapshot_unavailable` memakai pesan yang sama.
  - `5e4cc4c` panel memantau caption `pending` lewat polling 5 detik (maks 60 kali) bila WS
    tidak mengirim `kind:'ai'`.
- **Sengaja tidak diubah:** kuota rate limit dihitung sebelum `ffmpeg` (urutan spec, melindungi CPU)
  sehingga permintaan yang gagal sebelum LLM tetap menghabiskan kuota; dict `_limits` tumbuh per
  user (dibatasi jumlah user).
- **Bukti (berurutan, HEAD `5e4cc4c`):** backend `739 passed, 1 skipped, 521 warnings in 147.28s`
  (733 → 739: +6 tes); Docker `75 passed in 8.62s`; vision `235 passed, 3 deselected, 2 warnings`;
  frontend `Test Files 34 passed (34)` / `Tests 444 passed (444)` (441 → 444: +3 tes);
  `tsc -b --noEmit` exit 0; lint exit 0, 24 warning, 16 pasangan identik baseline; build exit 0.
  Hasil run pertama pada `f9fa24d` (sebelum perbaikan) dari sesi ini cocok dengan laporan executor.
- **Dampak:** perilaku default tidak berubah (`LLM_ENABLED=false`). Tanpa migrasi baru.
- **Rollback:** `git revert` commit perbaikan terkait; atau seluruh fitur via `LLM_ENABLED=false`
  + recreate `api` (lihat RUNBOOK).

### Caption AI per zona dan Tanya AI — MVP lokal (2026-10-02)

- **Konteks:** spec/plan `2026-10-02-ai-event-caption-ask`; Task 1–12 native dengan TDD
  dan commit lokal per task. **BELUM diuji di server/UI/LLM nyata**. ROADMAP tetap `[~]`;
  review, push, deploy, tes kontrak endpoint, penerimaan user, dan merge dikerjakan sesi berikutnya.
- **Berkas:** backend Settings, model `event_ai`/Zone, migrasi `0021_ai_caption`, retensi,
  skema zona, `llm_client`, `ai_prompts`, `ai_media`, `ai_worker`, `ask_ai`, router/skema `ai`,
  lifespan, dua hook tambahan pada `events_consumer`, marker dan tes baru. Docker runtime API
  mendapat ffmpeg, compose env_file API-only, setup template komentar llm.env (0600);
  `.env.example` root hanya komentar. Frontend klien AI, editor zona, AskAiPanel, EventsPage,
  id/en, theme, tes. Dokumen inti/RUNBOOK/AGENTS dan dua klausul lokasi env spec diperbarui.
  Vision, alerting, dispatcher, telegram, deploy, lock, dan `docker/.env.example` tidak diubah.
- **Commit implementasi:** `8fc67eb` data/migrasi; `2dbf332` API zona; `a8dfce2` klien LLM;
  `3bca991` prompt; `be4eb07` media; `199ab86` worker/hook; `32de5d9` Tanya AI;
  `70a56c9` API AI; `e661687` Docker/env; `aea8dbb` editor; `0bb7b8a` panel.
  Commit kedua belas mencatat dokumen dan bukti ini.
- **RED → GREEN:** T1 4 failed; T2 2 failed; T3 8 errors; T4 10 failed; T5 4 failed;
  T6 2 failed/14 errors; T7 18 errors; T8 13 failed; T9 4 failed; T10 3 failed;
  T11 15 failed, ditambah mutation RED event key sebelum restore GREEN.
  Tes existing tidak diubah/dihapus. Tes viewer/config push T2 serta attendance/status failure
  T10 langsung lulus karena perilaku lama, dicatat tanpa klaim RED.
- **Baseline ulang lokal, berurutan:** backend `656 passed, 491 warnings in 129.76s`;
  Docker `71 passed in 7.58s`; vision `235 passed, 3 deselected, 2 warnings in 13.47s`;
  frontend `Test Files 33 passed (33)` / `Tests 420 passed (420)`; build/lint exit 0,
  lint 24 warning / 16 pasangan (rule,file).
- **Keluaran nyata verifikasi T12 sebelum commit (urutan S1, kontrak nyata dikecualikan):**

  ```text
  backend: 733 passed, 1 deselected, 517 warnings in 147.96s (0:02:27)
  docker: 75 passed in 8.54s
  frontend: Test Files 34 passed (34)
            Tests 441 passed (441)
            Duration 21.76s
  lint: exit 0; 24 warnings; 16 pairs; new pairs 0; count changes 0
  build: 998 modules transformed.
         built in 2.82s
         exit 0
  tests/test_migration_0021.py::test_upgrade_downgrade PASSED
  1 passed in 0.31s
  ```

  Backend memakai `-m "not gpu and not llm"`, Docker dan frontend berjalan berurutan.
  S1 lengkap termasuk backend `not gpu`/vision diulang pada commit terakhir; hasil final
  diserahkan dalam `temp/prompt/ai-event-caption-report.md` (lokal, gitignored).
  Peringatan JWT test key, Starlette, Pillow, HTMLMediaElement load(), dan chunk >500 kB
  berasal dari pola baseline. Lint dibanding per pasangan, bukan jumlah saja.
- **Migrasi:** percobaan rantai SQLite sementara berhenti pada migrasi lama 0007:
  `NotImplementedError: No support for ALTER of constraints in SQLite dialect.`
  Karena itu upgrade head ×2/downgrade -1/upgrade head tidak dapat dibuktikan lewat rantai penuh.
  Tes mandiri 0021 membuktikan default false/NULL, index, upgrade/downgrade dua siklus;
  SQLite sementara dibersihkan. Rantai PostgreSQL/idempotensi head tetap tugas deploy.
- **Smoke UI sintetis:** browser dengan API stub 390×844; Events dan editor kustom memiliki
  page scrollWidth 390, panel 292/292 setelah jawaban panjang tanpa spasi, input prompt maxLength 600.
  Bukti lokal `docs/evidence/ai-event-caption-390.png` dan `ai-event-zone-390.png`.
  Dev server dan Chromium yang dibuat untuk smoke sudah dihentikan; layanan user tidak disentuh.
- **Dampak/keputusan:** default off, tanpa panggilan LLM, panel tersembunyi, ask 503.
  Caption per zona tanpa severity gate; manual ask tidak mengisi caption. Semua `LLM_*`
  dan `AI_QUEUE_MAX` di `secrets/llm.env`, API-only; audit mengikuti retensi event.
  JPEG sintetis menggantikan PNG contoh tes; scale ffmpeg 960×960 menjaga batas sisi portrait;
  field Zone frontend opsional untuk zona draft/fixture lama, payload menormalisasi false/null.
  Satu proses API; kuota/cache/admission lokal proses.
- **Rollout/rollback:** rebuild API (ffmpeg) dan web, migrasi 0021, isi llm.env,
  **recreate API** agar env_file terbaca (restart pada plan/spec saja tidak cukup), kemudian
  aktifkan satu zona uji. Konfirmasikan privasi pemilik endpoint sebelum mengirim gambar.
  Rollback aman: `LLM_ENABLED=false` + recreate. Downgrade 0020 bersifat destruktif terhadap
  seluruh audit/prompt AI: backup, hentikan writer, downgrade dengan image migrasi 0021,
  baru jalankan kode lama. Tanpa deploy pada sesi ini, rollback lokal cukup revert task urut terbalik.

### README siap produksi: alur instalasi sampai penyiapan pertama (2026-10-02)

- **Konteks:** README lama memuat ±150 baris sebelum cara pakai, diagram dan peta folder usang ("referensi systemd", `deploy/sql`, "9 halaman"), tautan rusak ke `docs/RUNBOOK.md#docker--prosedur-pending-cutover` (judul sudah diganti), dan instruksi umum bercampur path khusus `gspe-ai3`.
- **Diubah:** `README.md` — bagian depan ditulis ulang menjadi Arsitektur (diagram Docker + tabel layanan/port/akses), Instalasi (persyaratan, 3 langkah, apa yang dilakukan `setup.sh`, asal model YOLO/`buffalo_l`, opsi, lokasi data), **Penyiapan pertama** (8 langkah dari login sampai deteksi aktif, dengan nama menu UI yang sebenarnya), Operasi harian (perintah dari `docker/`, update, backup, tabel masalah umum), Panduan fitur (isi lama dipertahankan, dikoreksi untuk Docker: kredensial di `secrets/camera.env`, retensi oleh container `retention`, token Telegram lewat UI), Pengembangan (peta folder baru) dan Peta dokumen. `docs/RUNBOOK.md` §3 (tab Gate Absensi sudah tidak ada); `.gitignore` +`*.pt` `*.onnx` (tidak ada model ter-track).
- **Verifikasi:** semua tautan berkas dan anchor README valid (skrip), variabel/flag yang disebut ada di `docker/.env.example` dan `docker/setup.sh`, `cd docker && docker compose config` memakai `docker/.env` otomatis, alur sinkron kamera→go2rtc dibaca dari kode (`create_camera` → `sync_camera` + `_config_push`). Tanpa perubahan kode, tanpa dampak ke server.
- **Rollback:** `git revert` commit ini.

### Docker — kode, rehearsal, dan cutover di gspe-ai3 (2026-10-02)

- **Konteks:** tahap 2 setelah port non-default, spec/plan `2026-10-01-docker-deploy`;
  implementasi native Task 1–7, TDD dan commit lokal per task (sesi executor tanpa SSH/deploy/push). Rehearsal dan cutover dikerjakan
  sesi perencanaan; **aktif di `gspe-ai3` sejak 2026-10-02 13:36 WIB**.
- **File:** `docker/backend` (image editable CPU + entrypoint migrasi), `docker/web`
  (Vite build devDependencies + nginx resolver/proxy variabel tanpa URI),
  `docker/vision` (CUDA 13 + lock existing tidak diubah), `docker/compose.yml`,
  `.env.example`, template go2rtc/mosquitto, `setup.sh`, export/migrasi/retention
  scripts, tujuh berkas tes; backend/pyproject.toml hanya extra
  `face = ["insightface>=0.7", "onnxruntime>=1.19"]`; `.gitignore`; README,
  ARCHITECTURE, RUNBOOK, DEVELOPMENT, ROADMAP, CHANGELOG. `backend/app`, `vision/`,
  `frontend/`, dan `deploy/` tidak diubah.
- **Komit implementasi:** `75e0cdf` backend; `c725b50` web; `bb7096b` vision/export;
  `48ea9e5` compose/retention; `3b3ef75` setup; `c7e6df2` migrasi. Commit ketujuh
  mencatat dokumen ini. Tidak ada atribusi tambahan pada commit.
- **Tes merah→hijau:** T1 4 gagal karena entrypoint/extra belum ada; T2 5 gagal
  karena nginx.conf belum ada; T3 export 2 gagal dan pin lock dibuktikan merah
  dengan `foo>=1` sementara lalu dikembalikan identik; T4 loop/env belum ada
  (5 gagal + 9 fixture errors); T5 9 gagal karena setup belum ada, ditambah
  guard env literal; T6 9 tes dry-run/guard, ditambah guard env target/secrets.
  Fixture yang semula lulus karena exit nonzero generik diperketat dan diuji
  merah sebelum implementasi guard.
- **Baseline ulang sebelum T1 (Mac lokal, berurutan):** backend
  `656 passed, 491 warnings in 131.17s`; frontend `Test Files 33 passed (33)` /
  `Tests 420 passed (420)`; build exit 0; lint exit 0, 24 warning / 16 pasangan
  rule-file. Peringatan backend, HTMLMediaElement load(), serta chunk >500 kB
  sudah ada pada baseline.
- **Verifikasi sebelum commit dokumen (berurutan):** docker `48 passed in 3.89s`
  (0 skipped); backend `656 passed, 491 warnings in 130.53s`; frontend
  `Test Files 33 passed (33)` / `Tests 420 passed (420)`; build exit 0
  (`996 modules transformed`, `built in 2.93s`); lint
  `Found 24 warnings and 0 errors.`, 16 pasangan rule-file, sama dengan baseline.
  Compose config dengan/tanpa flag `--profile vision` exit 0 tanpa daemon.
  Skrip setup/migrasi `bash -n` exit 0. Build API/web, import, nginx -t,
  rehearsal container, login/proxy/health nyata, dan shellcheck container:
  **tidak dijalankan: daemon mati** (`Cannot connect to the Docker daemon ...`).
  Image vision tidak dibangun di Mac arm64. Smoke akhir di commit ketujuh
  dicatat terpisah dalam `temp/prompt/docker-deploy-report.md` (lokal, gitignored).
- **Keputusan/ketidakcocokan:** contoh plan 23:30→03:00 dikoreksi 43200→12600
  detik sesuai jadwal spec; default shm `2gb` sementara sampai pengukuran Part B;
  Python stdlib untuk dotenv/rendering (bukan sed); env tidak dieksekusi sebagai
  shell; rehearsal/no-NVIDIA membatasi profile proses tanpa menimpa env existing.
  Task 6 hanya rsync API saat rehearsal, berbeda dari ringkasan spec yang
  menyebut API+vision; vision disinkron saat cutover. Node id diperbarui lagi
  setelah restore. Password DB host dipisah ke PGPASSWORD dan tidak masuk
  command/dry-run. Guard tambahan menolak overlap data, env tidak lengkap,
  systemctl tak dapat diverifikasi, secrets existing saat rehearsal, dan
  overwrite setelah marker tanpa force.
- **Review sesi perencanaan (2026-10-02) dan perbaikan:** suite diulang berurutan di `a66945e`
  (docker 48 passed; backend 656; frontend 33 file / 420; build 0; lint 24/16) — sama dengan laporan eksekutor.
  Temuan dan perbaikan (TDD, merah dulu): **I1** kredensial kamera (`CAM_USERNAME`/`CAM_PASSWORD` di `.env` server dev,
  dibaca kode dari environment) tidak diteruskan ke container API → `api` memuat `${DATA_DIR}/secrets/camera.env` lewat
  `env_file` opsional, `setup.sh` membuatnya kosong 0600, `migrate-from-host.sh` mengisinya lewat
  `scripts/extract_camera_env.py` (nilai dikutip tunggal agar `$` dan `#` tetap literal, tidak dicetak, tidak menyentuh
  token Telegram); **I2** `compose run` tanpa `-T` di `setup.sh` dan `export-engine.sh`; **I3** unduh model wajah yang
  gagal membatalkan setup (kini peringatan, dan `api/faces_models` dibuat lebih dulu agar bind mount `/faces` tidak
  dimiliki root); **m1** peringatan bila IP LAN tak terdeteksi; **m3** catatan sweep retensi terlewat di RUNBOOK.
  Tes baru: alur `setup.sh` penuh dengan docker palsu (urutan panggilan, node id, idempotensi), kontrak compose untuk
  `camera.env`, ekstraktor kredensial, langkah kredensial di rencana migrasi. Belum terbukti: build image, healthcheck
  nyata, TZ di image slim, resolusi lock vision — tetap Part B.
- **Rehearsal di `gspe-ai3` (2026-10-02, clone `I-Sentinel-docker`, DATA_DIR terpisah):** build `api` (1,04 GB), `web` (50,4 MB),
  `vision` (13 GB, pin `requirements.lock` ter-resolve) exit 0; `setup.sh --rehearse --no-engine` semua `healthy`, run kedua idempoten
  (hash `.env`/`go2rtc.yaml`/`camera.env`/`passwd` dan umur container identik); LAN: `7700–7704` terbuka, `7705` dan `5432` tertutup;
  login lewat proxy 200 dan proxy tetap 200 setelah `api` dibuat ulang; `migrate-from-host.sh --rehearse`: alembic `0020`, tabel statis
  cocok persis, checksum klip dan jumlah file cocok, 14 stream go2rtc terdaftar dan satu frame kamera nyata (JPEG 640x360) lewat go2rtc
  Docker; log API tanpa error; TZ container `WIB`. **Temuan dari uji vision:** container `vision` restart-loop (`started 0 worker(s) for
  0 camera(s)`, exit 0): `VisionNode.run()` keluar bila tanpa worker dan `_await_config` False, sedangkan systemd selalu memberi
  `VISION_CAMERAS_JSON` statis. Perbaikan: setting `VISION_AWAIT_CONFIG` (`NodeSettings.await_config`, default False, tidak mengubah
  systemd/mode uji) dan compose mengaktifkannya; tes vision +2 (233 -> 235 passed, 3 deselected) dan tes compose +1.
  **Temuan kedua dari uji vision:** container hidup tapi idle, log API `heartbeat for unknown node '1'`. Node dikenali lewat
  **nama** di bidang MQTT (`isentinel/nodes/<name>/heartbeat`, `isentinel/config/<name>`), bukan id numerik; `vision.env` host
  memang `VISION_NODE_ID=server`. `setup.sh`, `migrate-from-host.sh`, `.env.example` (dan komentar menyesatkan di
  `deploy/vision.env.example`) mengasumsikan id numerik, dan fixture tes (docker palsu mengembalikan `7`) ikut mengunci asumsi
  itu. Kini `select name from node`, divalidasi `^[A-Za-z0-9._-]+$`; tes setup membedakan query nama dari id; docker tests 65 -> 68.
  **Temuan ketiga (vision dengan zona aktif di salinan):** engine TensorRT dimuat di container dan proses container tampil di
  `nvidia-smi`, tetapi log memuat `CUDAExecutionProvider is not in available provider names` dan CPU container melonjak ke 977%
  (load server 9,6): `onnxruntime-gpu 1.24.4` adalah build CUDA 12 yang di server dev memakai `/usr/local/cuda-12.8`, sedangkan image
  berbasis CUDA 13 sehingga face embedder jatuh ke CPU. Perbaikan: lapisan apt `cuda-cudart-12-8 libcublas-12-8 libcufft-12-8
  libcurand-12-8 libcudnn9-cuda-12` setelah instal pip (cache pip tetap). Catatan: semua 6 zona di DB host live memang `active=false`
  (event deteksi terakhir 1 Okt 10:02), jadi tanpa mengaktifkan zona di salinan tidak ada pekerja yang berjalan.
  **Temuan keempat:** setelah library CUDA 12 ditambahkan, `get_available_providers()` di image tetap hanya `Azure`/`CPU`: image berisi
  `onnxruntime 1.30.0` (CPU, ditarik `insightface` yang `Requires: onnxruntime`) di samping `onnxruntime-gpu 1.24.4`, keduanya berbagi
  `site-packages/onnxruntime` sehingga modul CPU menimpa modul GPU (venv server hanya punya `onnxruntime-gpu`). Perbaikan: lock dipasang
  `pip install --no-deps -r` (freeze lengkap) dan build gagal bila `CUDAExecutionProvider` tidak tersedia.
  **Hasil akhir uji vision di rehearsal (image `isentinel-vision:local` 15,4 GB):** paket ORT hanya `onnxruntime-gpu 1.24.4`;
  providers `Tensorrt`/`CUDA`/`CPU`; sesi ORT di GPU 2 memakai `CUDAExecutionProvider`; `started 2 worker(s) for 7 camera(s)`, restart 0;
  engine TensorRT hasil salinan host dimuat (21 MiB, detektor `cuda:1`, rata-rata 4,4 ms); container memakai 412 MiB (GPU 1) dan
  1014 MiB (GPU 2, face), pola yang sama dengan node systemd; CPU container sekitar 35% (sebelum perbaikan 977%), load server 1,4-2,1;
  ring klip `/dev/shm/isentinel/cam363` sekitar 1 MB per kamera (default `VISION_SHM_SIZE=2gb` memadai); 1 embedding wajah. Zona diaktifkan
  hanya di salinan lalu dikembalikan `false`. **Belum teruji:** event nyata sampai klip terunggah (tidak ada orang di zona saat uji) dan
  **Uji lanjutan di rehearsal (2026-10-02):** (a) pindah pin detektor `cuda:1` -> `cuda:2` -> `cuda:1` lewat DB salinan + config push, tanpa
  restart vision (restarts 0): heartbeat mengikuti pin, VRAM berpindah, pekerja dan engine dimuat ulang; efek samping: konteks CUDA ~386 MiB
  muncul di GPU 0 (4090 bersama vLLM) dan menetap — perilaku muat-ulang engine di GPU non-0, bukan khas Docker. (b) event nyata: orang berdiri
  di zona 15 (kamera Lorong Server, loitering 15 dtk) -> event 4777, snapshot JPEG 70 KB, klip MP4 2,6 MB (h264 1920x1080, 29,996 dtk,
  `ffprobe`), `POST /internal/nodes/server/blobs` kind=snapshot dan kind=clip keduanya 200, alert `not_configured` (tanpa token), antrean
  vision kosong. (c) `export-engine.sh 2`: unduh `yolo26s.pt`, ONNX FP16, engine TensorRT 21,3 MB dalam 18 dtk, smoke 5,1 ms/frame; engine
  baru dimuat vision di `cuda:1` (4,7 ms rata-rata). Semua zona live memang `active=false`; di salinan hanya diaktifkan sementara lalu
  dikembalikan. Tes: `docker/tests` 71 passed, vision 235 passed.
- **Cutover produksi dev (2026-10-02):** pra-cek bersih; user menjalankan `sudo systemctl disable --now isentinel-api isentinel-web
  vision-node go2rtc isentinel-retention.timer`; kelima unit `inactive` diverifikasi; cadangan final `pg_dump` host
  (`.../I-Sentinel-data/backups/isentinel-pre-docker-20261002-133603.sql`, 1,8 MB, mode 600); `migrate-from-host.sh --cutover` selesai 19 dtk
  (exit 0, marker `.cutover-done`). Verifikasi: 7 container healthy (vision restart 0), health `ok` langsung dan lewat proxy web, node
  `server` online (detektor `cuda:1`, face `cuda:2`), alembic `0020`, **25 tabel dibandingkan dengan DB host yang dibekukan, 0 selisih**,
  14 stream go2rtc + frame kamera nyata HTTP 200, clips 76 / snapshots 81 / crops 345 / faces 10 identik, `camera-secrets.json` dan
  `camera.env` mode 600, port lama (`5173/8000/1984/8554`) tertutup, `7700–7704` terbuka dari LAN dan `7705` tertutup, retensi terjadwal 03:00
  WIB. Gap deteksi: heartbeat lama terakhir 13:35:25, baru 13:36:42 (±77 dtk). User memeriksa UI (login, Live View, dashboard) dan
  mengubah `app_url` Telegram: OK. Catatan: semua 6 zona live `active=false` sejak 1 Okt (sebelum dan sesudah migrasi).
- **Dampak:** server dev kini di Docker (blok port `7700–7705`, bind mount `I-Sentinel-docker-data`, Postgres named volume `pgdata`); unit
  systemd lama dinonaktifkan (bukan dihapus); Postgres host, `I-Sentinel-data`, dan pohon `I-Sentinel` menjadi cadangan beku.
  Rahasia/YAML runtime di luar repo, Postgres named volume, API face CPU,
  vision profile/GPU all, log dibatasi. Belum ada bukti build image, live LAN,
  engine 4090/5080, shm, metrik/enrollment CPU, atau reboot di server.
- **Rollback:** (kini berlaku) tanpa data baru yang perlu dipertahankan: `docker compose down` (tanpa `-v`) lalu `sudo systemctl enable --now
  isentinel-api isentinel-web vision-node go2rtc isentinel-retention.timer`. Bila sudah ada data baru di Docker: dump balik `pg_dump` dari
  container dan sinkron data sesuai RUNBOOK Docker sebelum menyalakan unit lama. Kode: `git revert` commit Task 1–7 dan perbaikannya.

### Port non-default blok 7700–7705 — repo saja, tanpa deploy (2026-10-01)

- **Konteks:** semua port masih default (`5173/8000/1984/8554/1883`) dan rawan bentrok di server dev
  bersama; port berpindah **sekali** lewat cutover Docker (tahap 2, spec `2026-10-01-docker-deploy-design.md`).
  Tahap 1 ini perubahan repo: peta `7700` web · `7701` API · `7702` go2rtc API · `7703` WebRTC · `7704` MQTT ·
  `7705` RTSP (hanya `127.0.0.1`) ditulis di template/unit/dokumen, dan dua nilai yang tertanam di kode menjadi
  bisa dikonfigurasi. Default kode tetap port lama — dev lokal tidak berubah; tanpa variabel `PORT_*`.
  Spec + plan 2026-10-01; eksekusi native TDD Task 1–4, commit lokal per task (belum push/deploy).
- **Diubah:** backend `config.py` (setting baru `go2rtc_rtsp_url`, default `rtsp://localhost:8554`),
  `config_push.py` (`source_url` node server dari setting + `rstrip('/')`), `live.py` (docstring saja);
  frontend `vite.config.ts` (target proxy `/api` dari env `API_URL` dengan `||` agar nilai kosong jatuh ke
  default), `i18n.tsx` (hint `notifications.appUrlHint` id/en 5173→7700); template `isentinel-api.service`
  (`--port 7701`), `isentinel-web.service` (`--port 7700 --strictPort` + `Environment=API_URL=http://localhost:7701`),
  `go2rtc.example.yaml` (api 7702, webrtc 7703, rtsp 127.0.0.1:7705), `mosquitto.conf` (`listener 7704 0.0.0.0`),
  `bootstrap.sh` (health 7701), `.env.example` (`MQTT_URL=localhost:7704`, `GO2RTC_URL=http://localhost:7702`,
  baris baru `GO2RTC_RTSP_URL=rtsp://127.0.0.1:7705`, komentar di baris sendiri), `vision.env.example`
  (7704/7701, `VISION_GO2RTC_URL=http://localhost:7702`, contoh `source_url` `rtsp://127.0.0.1:7705/cam_2`); dokumen README, ARCHITECTURE, RUNBOOK
  (tabel peta port + status server dev), DEVELOPMENT (catatan port); koreksi satu baris spec 3.2
  (nilai `127.0.0.1` + alasan `localhost` bisa me-resolve ke `::1`). Perintah operasional `gspe-ai3`
  di RUNBOOK/DEVELOPMENT tidak diubah. Tanpa migrasi.
- **Uji (ditulis gagal dulu):** backend +3 — `test_build_node_config_server_source_url_uses_go2rtc_rtsp_url`
  dan `test_build_node_config_server_source_url_ignores_trailing_slash` (merah terverifikasi: `AttributeError`
  field `go2rtc_rtsp_url` belum ada), `test_live_endpoint_urls_follow_go2rtc_url_port` (pin regresi fakta 4;
  langsung lulus, dan terbukti bisa merah lewat mutasi sementara `_rewrite_host` lalu dikembalikan).
  Uji default `rtsp://localhost:8554/cam_{id}` tidak diubah.
- **Evidence (Mac lokal, berurutan):** backend `656 passed, 491 warnings in 127.26s` (653+3); frontend
  `Test Files 33 passed (33)` / `Tests 420 passed (420)` (tetap); `npm run build` exit 0; `npm run lint`
  24 warning / 0 error, 16 pasangan (rule, file) — set identik baseline. Verifikasi proxy 3 kasus
  (http.server tiruan di 7701, vite `--port 5199`): `API_URL=http://localhost:7701` → `404` (dijawab server
  tiruan); tanpa `API_URL` → `502`; `API_URL=` kosong → `502` (Vite 8 membalas 502 untuk upstream
  ECONNREFUSED, bukan 500 seperti perkiraan plan; dua kasus terakhir identik = fallback `||` bekerja).
  S2: diff `backend/app/core/config.py` hanya menambah field; grep `5173|8000|1984|8554|1883` di
  `deploy/systemd`, `deploy/go2rtc`, `deploy/mosquitto`, `deploy/bootstrap.sh`, `deploy/vision.env.example`,
  `.env.example` kosong; baris `GO2RTC_RTSP_URL/MQTT_URL/GO2RTC_URL=` bebas komentar inline; tanpa atribusi AI.
- **Review (sesi perencanaan, 2026-10-02):** suite diulang berurutan di `2a2ed8e` dengan `env -u NODE_ENV`: backend 656 passed,
  frontend 33 file / 420 passed, build 0, lint 24 baris / 16 pasangan — sama dengan laporan eksekutor. Satu temuan Important
  diperbaiki: `VISION_GO2RTC_URL` (setting vision sendiri, default port lama, dipakai `recorder._save_clip`) terlewat di spec/plan
  → ditambahkan ke `vision.env.example` dan spec 3.2; tiga temuan Minor/Nit (docstring uji snapshot basi, redaksi firewall
  `7703/udp`, komentar `vite.config.ts`). Deviasi `rtsp://127.0.0.1:7705` disetujui user.
- **Dampak:** tidak ada perubahan di server `gspe-ai3` (unit repo diperbarui, tidak di-deploy); dev lokal
  (`uvicorn --port 8000`, `npm run dev`) tetap jalan tanpa env tambahan. Instalasi baru yang memakai template
  butuh pembukaan firewall `7700:7704/tcp` + `7703/udp`; `7705` tidak dibuka.
- **Rollback:** `git revert` rentang commit `f287689..`; tanpa migrasi, tanpa perubahan server/DB.

### Bukti event system permanen — deploy dan merge (2026-10-01)

- **Konteks:** setelah review dan perbaikan (`0514fcd`), user mengizinkan push, deploy, lalu merge.
- **Deploy `gspe-ai3`:** `git checkout feat/events-permanent-evidence` (dari `main` @ `cf6f07e`, tree bersih) → `0514fcd`; tanpa migrasi; hanya API yang di-restart (cgroup kill, backend berubah);
  frontend lewat Vite dev server (`isentinel-web`).
- **Smoke server:** `/api/v1/health` → `{"status":"ok"}` (±10 dtk setelah restart); `openapi.json` terbaca; `GET /events` tanpa auth → 401; web `:5173` → 200; journal API 2 menit pertama 0 error/traceback.
- **Uji UI user: BELUM dilakukan dengan event berbukti.** Event lama tidak memiliki `payload.evidence`, sehingga verifikasi hanya bisa dengan event **baru** (health alert menyala/pulih atau node offline sesudah deploy);
  user menilai uji itu memerlukan pemasukan event dan menyetujui merge tanpa uji tersebut (keputusan 2026-10-01). Bukti yang ada: 653 uji backend (termasuk pembangunan bukti firing/resolved/node offline, batas 360 titik,
  kegagalan bukti tidak menggagalkan event), 420 uji frontend, dan smoke render mock (event berbukti tersimpan bergrafik tanpa permintaan history, event 10 hari tetap bergrafik).
- **Cara memverifikasi nanti (tanpa mengganggu layanan):** Monitoring → aturan `infer_latency` ambang 5 ms, durasi 5 menit (Telegram default mati) → ±6 menit → event `firing` baru di Events harus bergrafik langsung tanpa jeda fetch,
  lalu kembalikan ke 50 ms → ±2 menit → event `resolved` berbukti. Atau tunggu health alert/node offline berikutnya. Jangan menghentikan vision node di produksi untuk uji ini.
- **Rollback:** `git revert` merge ini atau commit per task (tanpa migrasi); event yang sudah memuat `evidence` tetap valid (field tambahan diabaikan klien lama); server: `git checkout main && git pull` + restart API.

### Perbaikan review bukti event system permanen (2026-10-01)

- **Konteks:** review sesi perencanaan atas `feat/events-permanent-evidence` menemukan satu hal: `systemEvidence` masih mengosongkan `charts` bila `node_id` kosong
  (`nodeId == null || …`), padahal spec/plan menyatakan bukti tersimpan tidak membutuhkan `node_id`. Event yang justru berbukti permanen (mis. node sudah dihapus)
  kehilangan grafiknya dan menampilkan "Tidak ada rincian tambahan untuk event ini".
- **Diubah:** `features/events/systemEvidence.ts` — `charts` hanya dikosongkan untuk jalur fetch (`nodeId == null` atau kedaluwarsa); bukti tersimpan selalu menghasilkan grafik.
  Deviasi eksekutor `135118e` (jendela tersimpan `to = max(from + n·step, ts_event)` agar penanda waktu event tetap tampil) disetujui: waktu bukti dan `ts_event` sama-sama dari jam server.
- **Uji (ditulis gagal dulu):** `system-evidence.test.ts` (bukti valid + `node_id` kosong/null → satu grafik, `stored` terisi; tanpa bukti dan tanpa `node_id` → tanpa grafik),
  `system-evidence-panel.test.tsx` (event 10 hari, `node_id: null` → grafik tergambar, tanpa permintaan history).
- **Evidence (Mac lokal, berurutan):** backend `653 passed, 489 warnings in 132.17s` (tidak berubah); frontend `Test Files 33 passed (33)` / `Tests 420 passed (420)` (417 + 3);
  `npm run build` exit 0; `npm run lint` 24 baris, pasangan (file, rule) identik baseline; `git grep -nE "style=\{\{|#[0-9a-fA-F]{6}" -- frontend/src/features/events` kosong.
- **Dampak:** event system berbukti tersimpan tetap bergrafik walau `node_id` kosong; jalur lama tidak berubah.
- **Catatan:** `GET /events` kini membawa `payload.evidence` (±1–3 KB per event system) pada tiap baris dan frame WebSocket; event system jarang sehingga dapat diterima.
- **Rollback:** `git revert` commit perbaikan ini; tanpa migrasi.

### Bukti event system permanen (`payload.evidence`) (2026-10-01)

- **Konteks:** panel Bukti event system dulu hanya bergrafik dari `GET /monitoring/history` (retensi 7 hari), sehingga event sistem yang usianya melewati 7 hari kehilangan grafik.
  Kini seri menit disimpan di `payload.evidence` **saat event dibuat** (health firing/resolved, node offline; `closed` tanpa bukti); event lama tidak di-backfill dan tetap lewat jalur history.
  Spec + plan 2026-10-01; eksekusi native TDD Task 1–5, commit lokal per task (belum push/deploy).
- **Diubah:** backend `health_alerts.py` (bukti firing/resolved dibangun sebelum mutasi DB, batas 360 titik, gagal bukti tidak menggagalkan event), `monitoring_history.py` (`minute_samples`),
  `node_health.py` (`last_seen`, `down_s`, seri `cpu_pct`/`infer_fps` 30 menit); frontend `systemEvidence.ts` (`parseStored` ketat), `EvidencePanel.tsx` (cabang tersimpan: tanpa fetch, tanpa batas 7 hari), `i18n.tsx` (5 kunci id/en). Tanpa migrasi.
- **Perbaikan saat verifikasi:** `systemEvidence.ts` — jendela bukti tersimpan diperluas ke `ts_event` (`to = max(ujung seri, ts)`) agar penanda waktu event tetap tampil;
  tanpa itu uji `stored evidence draws charts without any history request` merah di tree bersih (LineChart menjatuhkan marker di luar `[from,to]`, sedangkan seri tersimpan berakhir di awal menit).
- **Uji (ditulis gagal dulu):** backend +12 (`test_health_alerts.py`, `test_monitoring_history.py`, `test_node_health.py`); frontend +13 (`system-evidence.test.ts`, `system-evidence-panel.test.tsx`).
- **Evidence (Mac lokal, berurutan):** backend `653 passed, 489 warnings in 133.61s` (641+12); frontend `Test Files 33 passed` / `Tests 417 passed` (404+13); `npm run build` exit 0 (996 modules, warning chunk lama);
  `npm run lint` 24 baris / 16 pasangan rule-file (set sama baseline); S2: `git diff --stat main...HEAD` 13 berkas = daftar task + spec/plan, `style={{`/hex di `features/events` 0 baris (= `main`), paritas i18n id = en (5 kunci), tanpa berkas Alembic;
  S3 (mock `/api/v1/**`, Playwright, 1440 px + 390 px): 0 error konsol, event berbukti tersimpan bergrafik tanpa panggilan `/monitoring/history`, event berbukti 10 hari tetap bergrafik, node offline 2 grafik + "Heartbeat terakhir",
  event tanpa bukti lewat fetch (usia 10 hari → catatan "Data tren hanya disimpan 7 hari"), `scrollWidth 375 ≤ 390`.
- **Dampak:** payload event system membesar ≈ 1–3 KB per event (≤ 360 titik, 1 desimal; frame WS ikut membesar); satu query sampel tambahan hanya saat transisi. Kegagalan membangun bukti tidak menahan event (dicatat di log).
- **Rollback:** `git revert` commit per task; tanpa migrasi; event ber-`evidence` tetap valid (field tambahan diabaikan klien lama). **Uji UI user menyusul setelah deploy.**

### Filter Events di URL, muat lebih banyak, tab Konfigurasi viewer — deploy dan uji UI user (2026-10-01)

- **Konteks:** setelah review dan perbaikan (`c6be585`), user mengizinkan push dan deploy; hasil uji UI dicatat di sini.
- **Deploy `gspe-ai3`:** `git checkout feat/events-list-url-paging` (dari `main` @ `afd95ff`, tree bersih) → `c6be585`; tanpa migrasi; hanya API yang di-restart
  (cgroup kill, backend berubah); frontend lewat Vite dev server (`isentinel-web`). Restart API butuh ±35–40 dtk karena proses lama menunggu shutdown graceful.
- **Smoke server:** `/api/v1/health` → `{"status":"ok"}`; `GET /events?offset=200` dan `GET /events?camera_id=<20 digit>` tanpa auth → 401 (rute hidup); `openapi.json`
  memuat `offset` (0–10000) dan `camera_id` `maximum: 2147483647`; web `:5173` → 200; proses baru 0 error/traceback.
- **Uji UI user:** "sudah sesuai" (konfirmasi di chat, 2026-10-01; tanpa screenshot) atas daftar cek: filter di URL (salin/buka di tab baru, Back, reload), daftar menyempit seketika,
  "Muat lebih banyak" tanpa duplikat dan batas 1000, tile Dashboard "Event hari ini" → `/events?type=security&range=today`, viewer hanya tab Storage tanpa kilatan, URL `?camera=` raksasa diabaikan, 390 px.
- **Catatan:** satu `QueuePool limit of size 5 overflow 10 reached` (1× dalam 24 jam) tercatat tepat saat proses API lama shutdown; proses baru bersih. Pola yang mungkin melatarbelakangi:
  `ws_events` memegang satu koneksi DB selama WebSocket hidup (tiap tab `/events` membuka dua WS). Belum diubah; kandidat perbaikan berikutnya.
- **Rollback:** `git revert` merge ini atau commit per task (tanpa migrasi); server: `git checkout main && git pull` + restart API.

### Perbaikan review filter di URL, muat lebih banyak, tab Konfigurasi viewer (2026-10-01)

- **Konteks:** review sesi perencanaan atas `feat/events-list-url-paging` menemukan lima hal: (R1) daftar tidak menyempit seketika saat filter diganti
  (menunggu respons server; bila gagal, dropdown menunjukkan filter baru tetapi isi daftar milik filter lama); (R2) refresh interval klip tertunda (mode `merge`)
  menaikkan token permintaan yang sama dengan "Muat lebih banyak" sehingga halaman yang sedang dimuat dibuang diam-diam; (R3) `?camera=<angka 20 digit>` lolos
  validasi frontend dan di Postgres (`camera_id` int4) membuat `GET /events` melempar → 500; (R4) `event-limit-hint` dan `event-cap-hint` tampil bersamaan di batas 1000;
  (R5) selama `me` belum termuat, `ConfigurationPage` memasang tujuh tab sehingga viewer sempat memanggil API admin (`/users`, `/cameras`).
- **Diubah:** `EventsPage.tsx` — `filtered` ikut `matchesFilters` (spec §3.2); hanya refresh mode `replace` yang menaikkan `reqRef`, mode `merge` dan `loadMore` hanya membandingkan;
  `event-limit-hint` hanya di bawah `MAX_EVENTS`. `eventFilters.ts` — `camera` dibatasi ≤ 2³¹−1. `backend/app/api/events.py` — `camera_id` `Query(None, le=2**31 − 1)` (422 bukan 500).
  `ConfigurationPage.tsx` — `me === null` (shell sedang memuat) tidak memasang tab/panel; `me` undefined tetap tujuh tab.
- **Uji (ditulis gagal dulu):** backend `test_list_events_camera_id_out_of_range_is_422` (gagal `OverflowError` SQLite); frontend `parseFilters` camera di luar int4, daftar menyempit seketika,
  daftar sesuai filter setelah refetch gagal, merge refresh tidak membuang halaman load-more, `event-limit-hint` hilang di batas, tab/panel tidak dipasang saat `me` null.
  Harness uji disesuaikan agar realistis: stub daftar menyaring tipe seperti server (tiga uji + stale test memakai baris cocok-filter), `renderConfiguration` serta uji `detection`/`notifications`
  dipasang di bawah `Outlet context` admin seperti di `AppShell` (tanpa Outlet `useOutletContext()` bernilai null = sesi belum termuat).
- **Evidence (Mac lokal, berurutan):** backend `641 passed, 489 warnings in 127.01s` (640 + 1); frontend `Test Files 33 passed (33)` / `Tests 404 passed (404)` (399 + 5);
  `events.test.tsx` + `configuration.test.tsx` 5/5 percobaan hijau; `npm run build` exit 0; `npm run lint` 24 baris, pasangan (file, rule) identik baseline;
  `git grep -nE "style=\{\{|#[0-9a-fA-F]{6}" -- frontend/src/features/events frontend/src/features/config` 102 baris (= `main`).
- **Dampak:** perubahan filter terasa seketika dan konsisten walau server lambat/gagal; "Muat lebih banyak" tidak lagi tertelan interval klip; URL hasil sunting tangan tidak bisa membuat 500;
  viewer tidak lagi memicu panggilan API admin saat sesi dimuat.
- **Rollback:** `git revert` commit perbaikan ini; tanpa migrasi.

### Filter Events di URL, "Muat lebih banyak", tab Konfigurasi viewer (2026-10-01)

- **Konteks:** backlog penutupan siklus deep link (bagian 1 dari 2; bagian 2 = bukti permanen event system). Filter Events
  hilang saat reload dan tak bisa dibagikan, daftar terkunci 200 baris tanpa jalan memuat lebih, tile "Event hari ini"
  menaut ke `/events` polos yang angkanya tak sepadanan, dan viewer melihat ketujuh tab Konfigurasi.
  Spec/plan `docs/superpowers/{specs,plans}/2026-10-01-events-list-url-paging*` (D1–D6).
- **Diubah:** `backend/app/api/events.py` — `GET /api/v1/events` menerima `offset` (`Query(0, ge=0, le=10_000)`, di luar
  rentang → 422) dan urutan `ts_event DESC, id DESC` (pemutus seri deterministik antar-halaman; tanpa `offset` identik).
  `frontend/src/features/events/eventFilters.ts` (baru) — fungsi murni `parseFilters`/`writeFilters` (URL = sumber
  kebenaran, nilai tak valid → default, default tidak ditulis, param lain termasuk `event` terjaga), `typesFor`
  (grup `security` = semua tipe kecuali `attendance`), `sinceFor` (`today` = 00:00 lokal), `matchesFilters`,
  `appendPage`, `mergeFirstPage`. `frontend/src/features/events/EventsPage.tsx` — filter diturunkan dari
  `useSearchParams` (state lokal filter dihapus, penulisan `replace`); opsi Tipe "Keamanan (tanpa absensi)" +
  rentang "Hari ini"; tombol **Muat lebih banyak** (`offset`, dedupe `id`, batas `MAX_EVENTS=1000` dengan
  `event-cap-hint`, `event-limit-hint` memuat `{n}`); `refresh` dua mode (ganti + reset `hasMore` saat filter berubah,
  `mergeFirstPage` saat interval klip tertunda); event live prepend dengan dedupe tanpa `slice(0, LIMIT)`;
  pencarian `q` dari URL tetap klien. `frontend/src/api/events.ts` — `EventListParams.offset`.
  `frontend/src/features/dashboard/KpiTiles.tsx` — tile Event hari ini → `/events?type=security&range=today`.
  `frontend/src/features/config/ConfigurationPage.tsx` — viewer hanya tab Storage (`?tab=` di luar daftar → tab
  terlihat pertama; panel dipetakan dari daftar terlihat). `frontend/src/app/i18n.tsx` — kunci baru
  `events.range.today`, `events.type.security`, `events.loadMore`, `events.capHint` (id + en); teks
  `events.limitHint` berubah di kedua bahasa. Dokumen: `WORKFLOW.md §8/§15`, `ARCHITECTURE.md`, `README.md`.
- **Uji (ditulis gagal dulu; tidak ada uji dihapus kecuali satu ekspektasi `href` tile Event):** backend
  `test_events_api.py` +3 (halaman tidak tumpang tindih, `ts_event` sama → id menurun, validasi `offset`);
  frontend `event-filters.test.ts` +14 (fungsi murni), `events.test.tsx` +15 (filter hidup dari URL awal, penulisan
  URL `replace`, reset menjaga `?event=`, Back memulihkan, `since` tengah malam lokal, `type=security` berisi 7 tipe
  tanpa `attendance`, nilai URL tak valid jatuh default, `q` klien tanpa request baru, muat lebih banyak
  `offset=200` + dedupe saat halaman bergeser, tombol hilang di halaman tak penuh, batas 1000 + `event-cap-hint`,
  interval klip tidak membuang halaman, respons muat-lebih-banyak dibuang saat filter berubah, reset daftar +
  `hasMore`), `dashboard-blocks.test.tsx` +1, `configuration.test.tsx` +4 (viewer 1 tab, `?tab=users` jatuh ke
  Storage tanpa `/users`, admin 7 tab, `me` kosong 7 tab). Uji yang lulus sebelum implementasi dibuktikan bisa
  gagal lewat mutasi sementara (validasi `parseFilters`, `setHasMore(true)`, `restricted=true`).
- **Evidence (Mac lokal, smoke S1–S3 berurutan; uji UI user menyusul setelah deploy):** S1: backend
  `640 passed, 487 warnings in 127.81s` (baseline 637 + 3); frontend `Test Files 33 passed (33)` /
  `Tests 399 passed (399)` (baseline 365 + 34); `npm run build` exit 0; `npm run lint` 24 baris warning,
  16 pasangan (rule, file) identik baseline. S2: grep `style=\{\{|#[0-9a-fA-F]{6}` di `features/events` +
  `features/config` identik `main` (102 baris, 0 baris baru); `git diff --stat main...HEAD` hanya berkas task +
  dokumen + spec/plan; paritas i18n id=en untuk kelima kunci. S3 (Playwright + mock `/api/v1/*`, sesi admin &
  viewer, dev server): 0 error konsol di 1440 px dan 390 px; `/events?type=system&severity=critical&range=today`
  → dropdown Sistem/critical + `range=today`, request `type=system&severity=critical&since=<00:00 lokal>&limit=200`;
  ganti rentang → URL `range=7d` (replace) dan Back memulihkan filter; "Atur ulang filter" menghapus param;
  "Muat lebih banyak" → request `offset=200`/`offset=400`, hitungan 200+ → 400+ → 455, tombol hilang di halaman
  tak penuh; tile "Event hari ini" → `/events?type=security&range=today`; admin 7 tab; viewer hanya
  "Retensi & Storage" dan `?tab=users` jatuh ke Storage (panel `storage-retention` tampil); 390 px
  `scrollWidth 375 ≤ 390`.
- **Dampak:** filter Events dapat dibagikan dan tahan reload/Back; riwayat di atas 200 baris terjangkau sampai
  1000; angka tile Dashboard sepadanan dengan daftar yang dituju; viewer hanya melihat Storage di Konfigurasi
  (backend tetap menegakkan role).
- **Catatan:** (1) `filtered` tidak memfilter ulang di klien lewat `matchesFilters` (dipakai untuk event live saja)
  karena uji lama `a stale response does not overwrite a newer one` mensyaratkan baris hasil stub tetap tampil;
  server tetap otoritas filter. (2) Saat `me` belum termuat (`null`), Konfigurasi masih menampilkan tujuh tab
  (perilaku yang dispesifikasikan untuk `me` null/undefined) sehingga viewer sempat memanggil `/users` sebelum
  `me` turun — endpoint menolak non-admin; dibiarkan sesuai D6/spec §3.4. (3) `event-limit-hint` tetap tampil
  pada batas 1000 bersama `event-cap-hint` (bacaan literal plan).
- **Rollback:** `git revert` commit per task (`ea863cd`, `a7be5f1`, `587852a`, `cee0558`, `f58f4b8`); tanpa migrasi.

### Tautan event by id — deploy dan uji UI user (2026-10-01)

- **Konteks:** setelah review dan perbaikan (`c776a0b`), user mengizinkan push dan deploy; hasil uji UI dicatat di sini.
- **Deploy `gspe-ai3`:** `git checkout fix/events-deeplink` (dari `main` @ `9c8b220`, tree bersih) → `c776a0b`; tanpa migrasi;
  hanya API yang di-restart (cgroup kill, backend berubah); frontend lewat Vite dev server (`isentinel-web`).
- **Smoke server:** `/api/v1/health` → `{"status":"ok"}`; `GET /events/<id>` dan `GET /events/99999999999999999999` tanpa auth → 401
  (rute hidup); `openapi.json` memuat `/api/v1/events/{event_id}`; web `:5173` → 200; journal API 20 baris terakhir 0 error/traceback.
- **Uji UI user:** "sudah sesuai" (konfirmasi di chat, 2026-10-01; tanpa screenshot) atas daftar cek: tautan event lama, klik lonceng/toast
  saat sudah di `/events`, id terhapus/raksasa → peringatan, klik baris memperbarui URL tanpa menumpuk riwayat, salin URL ke tab baru,
  tautan menang atas filter, 390 px.
- **Catatan:** L1 (sematan tetap saat filter mengecualikan event yang diklik), L2 (kolom kiri kosong tanpa pesan bila daftar kosong dan ada event
  tersemat), L3 (selisih deploy API lama → "tidak ditemukan") dinilai dapat diterima, tidak diubah.
- **Rollback:** `git revert` merge ini atau commit per task (tanpa migrasi); server: `git checkout main && git pull` + restart API.

### Perbaikan review tautan event by id (2026-10-01)

- **Konteks:** review sesi perencanaan atas `fix/events-deeplink` menemukan dua hal: (M1) saat membuka `/events?event=<id luar daftar>`,
  panel detail sempat menampilkan event pertama sebelum fetch by-id selesai (melanggar K4 "tidak pernah diam-diam menampilkan
  event lain") dan membuat uji `?event beyond the loaded list…` flaky (gagal 1 dari 3 percobaan); (M2) id sangat besar di URL
  (`/events?event=99999999999`) lolos validasi frontend dan di Postgres (`Event.id` INTEGER/int4) membuat `GET /events/{id}` melempar
  `integer out of range` → 500, sehingga pengguna melihat "Gagal memuat" alih-alih "tidak ditemukan".
- **Diubah:** `features/events/EventsPage.tsx` — `resolving` (event dituju belum di daftar dan fetch by-id belum selesai) → `selected`
  kosong dan panel menampilkan `InlineLoading` (`data-testid="event-detail-loading"`); fallback ke event pertama hanya bila hasil
  `missing`/`error`. `backend/app/api/events.py` — `get_event` menjawab 404 untuk id di luar `1…2³¹−1` (`MAX_EVENT_ID`).
- **Uji (ditulis gagal dulu):** `test_get_event_by_id_out_of_range_is_404` (gagal dengan `OverflowError` SQLite sebelum perbaikan);
  `while the by-id fetch is pending a loading placeholder is shown, not the first event` (gagal: detail event pertama tampil).
- **Evidence (Mac lokal, berurutan):** backend `637 passed, 481 warnings in 127.89s` (636 + 1); frontend `Test Files 32 passed (32)` /
  `Tests 365 passed (365)` (364 + 1); `events.test.tsx` 8/8 percobaan hijau (sebelumnya 1 dari 3 gagal); `npm run build` exit 0;
  `npm run lint` 24 baris, pasangan (file, rule) identik baseline; `git grep -nE "style=\{\{|#[0-9a-fA-F]{6}" -- frontend/src/features/events` kosong.
- **Dampak:** deep link ke event lama tidak lagi berkedip ke event yang salah; id ngawur → "tidak ditemukan", bukan error 500.
- **Rollback:** `git revert` commit perbaikan ini; tanpa migrasi.

### Tautan `/events?event=<id>` yang andal (2026-10-01)

- **Konteks:** tautan event (Telegram, lonceng/toast, Dashboard) punya tiga cacat: `?event=` hanya dibaca saat mount
  (klik lonceng saat sudah di `/events` terasa tak berbuat apa-apa), event di luar 200 terbaru ditampilkan diam-diam
  sebagai event pertama, dan klik baris tidak menulis URL. Spec/plan `docs/superpowers/{specs,plans}/2026-10-01-events-deeplink*`.
- **Diubah:** `backend/app/api/events.py` — `GET /api/v1/events/{event_id}` → `EventOut`, 404 `"event not found"`, wajib
  login (rute `stats/today` tidak berubah). `frontend/src/api/events.ts` — `getEvent(id)` (`null` pada 404, lempar
  `Error` pada status lain). `frontend/src/features/events/EventsPage.tsx` — `?event=` jadi sumber kebenaran pemilihan
  (state `selectedId` dihapus); event di luar daftar diambil sekali lewat id dan disematkan dengan catatan; klik baris
  menulis `?event=<id>` (`replace`); 404 → peringatan + jatuh ke event pertama; 500 → pesan gagal. `frontend/src/app/i18n.tsx`
  — kunci `events.pinnedNote`, `events.deeplinkMissing`, `events.deeplinkFailed` (id + en).
- **Uji (ditulis gagal dulu):** backend `test_events_api.py` +5 (200 isi, 404, 401, 422 non-int, regresi `stats/today` —
  3 fail dulu karena rute belum ada); frontend `events.test.tsx` +11 (sematan tepat 1 fetch, 0 fetch bila sudah di daftar,
  param tak valid tanpa fetch, 404/500 berbeda pesan, pindah saat terpasang, klik baris = REPLACE, tanpa param URL utuh,
  respons basi tidak menimpa, sematan bertahan saat refetch, daftar kosong + sematan tetap tampil); 3 guard perilaku lama
  dibuktikan bisa gagal lewat mutasi sementara (inList=false, cek integer dibuang, fallback pertama dibuang).
- **Evidence (Mac lokal):** backend `636 passed` (baseline 631); frontend `Test Files 32 passed (32)` / `Tests 364 passed
  (364)`; `npm run build` exit 0; `npm run lint` 24 baris warning, pasangan (rule, file) identik baseline; smoke S3
  (Playwright, mock `/api/v1/*`): sematan ev-777 + catatan, 404 #999 → peringatan + event pertama, pushState+popstate
  memindahkan pilihan, klik baris → `?event=3`, 390 px `scrollWidth 375 ≤ 390`; konsol 0 error (satu log resource 404
  yang diharapkan saat kasus 404). **Uji UI oleh user menyusul setelah deploy** (tautan Telegram lama, lonceng saat sudah
  di `/events`, id terhapus, tombol Back, buka URL di tab baru).
- **Dampak:** tautan lama Telegram tetap membuka event yang benar; klik lonceng/toast saat halaman terbuka langsung
  berpindah; URL bilah alamat selalu menunjuk event yang tampil.
- **Rollback:** `git revert` commit per task (`6e5edd6`, `518e2b0`); tanpa migrasi DB; frontend lama + backend baru aman
  (`getEvent` 404/405 → pesan, tidak crash).

### Filter Events + bukti event system — deploy dan uji UI user (2026-10-01)

- **Konteks:** setelah review dan perbaikan (`d81d1d1`), user mengizinkan push dan deploy; hasil uji UI dicatat di sini.
- **Deploy `gspe-ai3`:** `git checkout feat/system-event-evidence` (dari `main` @ `b8c54db`, tree bersih) → `d81d1d1`;
  tanpa migrasi; hanya API yang di-restart (cgroup kill, backend berubah); frontend lewat Vite dev server (`isentinel-web`).
- **Smoke server:** `/api/v1/health` → `{"status":"ok"}`; `GET /events?severity=critical` dan
  `GET /monitoring/history?from=…&to=…` tanpa auth → 401 (rute hidup); `openapi.json` memuat parameter `severity` dan
  `from`/`to`/`node_id`; web `:5173` → 200; journal API 20 baris terakhir 0 error/traceback.
- **Uji UI user:** "sudah sesuai hasilnya" (konfirmasi di chat, 2026-10-01; tanpa screenshot) atas daftar cek: "Semua" tiap
  dropdown, Atur ulang filter, penanda `N+`, panel Bukti per jenis event system, event kamera tak berubah, 390 px.
- **Catatan review:** satu uji flaky tak terkait (`zones.test.tsx > save calls createZone with normalized polygon`) gagal
  sekali saat pytest dan vitest berjalan bersamaan; lulus 3/3 sendiri dan 2/2 suite penuh tanpa beban — belum diselidiki.
- **Rollback:** `git revert` merge ini atau commit per task (tanpa migrasi); server: `git checkout main && git pull` + restart API.

### Perbaikan review filter Events + bukti event system (2026-10-01)

- **Konteks:** review sesi perencanaan atas `feat/system-event-evidence` menemukan tiga hal kecil: (M1) event system
  dengan `ts_event` jauh di masa depan (jam node salah) menghasilkan jendela `from >= to` → API 422 → panel menulis
  "Gagal memuat grafik", bukan "Tidak ada data tren"; (L1) efek `[refresh]` di `EventsPage` memanggil ulang
  `listCameras()`/`listZones()` pada tiap perubahan filter; (L2) rule health yang belum diterjemahkan tampil sebagai
  kunci i18n mentah (`health.rule.<rule>`).
- **Diubah:** `features/events/systemEvidence.ts` — `window` null bila `from >= to` (panel menampilkan catatan tanpa data
  dan tidak meminta history); fakta Aturan memakai nama rule bila terjemahan tidak ada. `features/events/EventsPage.tsx` —
  kamera dan zona di-fetch sekali saat mount (efek terpisah dari `refresh`).
- **Uji (ditulis gagal dulu):** `system-evidence.test.ts` (jendela masa depan, nama rule), `system-evidence-panel.test.tsx`
  (event masa depan: `evidence-empty` tanpa request), `events.test.tsx` (ganti filter tidak mengulang `/cameras`/`/zones`).
- **Evidence (Mac lokal):** frontend `Test Files 32 passed (32)` / `Tests 353 passed (353)` (349 + 4); `npm run build` exit 0;
  `npm run lint` 24 baris, pasangan (file, rule) identik sebelum dan sesudah perbaikan; `git grep -nE "style=\{\{|#[0-9a-fA-F]{6}"
  -- frontend/src/features/events` kosong; backend tidak diubah (631 passed pada review).
- **Dampak:** panel Bukti jujur untuk event berjam salah; tiap perubahan filter kini 1 request (bukan 3).
- **Rollback:** `git revert` commit perbaikan ini; tanpa migrasi.

### Filter Events konsisten + bukti event system (2026-10-01)

- **Konteks:** dua permintaan user atas `/events`: (1) event `system` (node offline/pulih, health alert) hanya
  menampilkan tab Snapshot/Clip yang selalu kosong dan teks mentah `system · cam null`; (2) filter belum konsisten —
  Tipe/Kamera/Severity difilter di klien atas 200 event terbaru (event `attendance` memenuhi kuota, event keamanan
  lama tak terjangkau), opsi Tipe mengikuti data yang termuat, dan Carbon `Dropdown` tak bisa membatalkan pilihan
  sehingga tidak ada jalan kembali ke “Semua” tanpa reload. Event system juga memicu polling klip 5 detik dan teks
  “Clip sedang direkam” yang tak pernah terpenuhi.
- **Diubah — backend:** `app/api/events.py` — `list_events` mendapat `severity` berulang (`Event.severity.in_(...)`),
  sama polanya dengan `type`. `app/services/monitoring_history.py` — badan `query` dipecah menjadi `_series(start, end,
  bucket_s, node_id)`; `query_window` baru memakai bucket tetap 60 dtk, `range: "custom"`, batas naive = UTC, dan
  `_offline(db, node, start, end)`. `app/api/monitoring.py` — `get_history` dua mode: `range` (default `6h`, perilaku
  lama) atau jendela `from`/`to` + `node_id` opsional; `range` bersama `from`/`to`, hanya salah satu, `to <= from`,
  atau rentang > 6 jam → 422.
- **Diubah — frontend:** `features/events/eventTypes.ts` baru (daftar tipe ingest statis + label lokal).
  `api/events.ts` (`severities`, `EventOut.node_id` opsional), `api/monitoring.ts` (`getMonitoringHistoryWindow`,
  `MonitoringHistory.range` → `string`). `EventsPage.tsx` — tiga dropdown berbentuk item yang sama (`{value, label}`,
  nilai primitif) dengan opsi **Semua** sebagai item pertama, tombol **Atur ulang filter**, `refresh` bergantung pada
  nilai filter dan membuang respons basi lewat penghitung permintaan, hitungan `N+` + petunjuk batas 200, event live
  yang tak cocok filter tidak ditambahkan, judul/lokasi event system terlokalisasi, sel ikon menggantikan thumbnail,
  `clipPending` selalu false untuk event system. `features/events/systemEvidence.ts` baru (fungsi murni: jendela,
  fakta, pemetaan grafik per rule termasuk `camera_low_fps` dalam persen target FPS; retensi 7 hari → `expired`).
  `features/events/EvidencePanel.tsx` baru (panel Bukti, satu fetch per event, dependensi primitif).
  `components/LineChart.tsx` — prop `markers` (penanda waktu event, di luar rentang tidak digambar) dan token SCSS
  `.lc__marker`/`.ev-evidence*`/`.ev-thumb--icon` di `app/theme.scss`. Kunci i18n baru 42 (`events.type.*`,
  `events.evidence.*`, `events.filterReset`, `events.limitHint`) — paritas id/en 86=86.
- **File:** `backend/app/api/{events,monitoring}.py`, `backend/app/services/monitoring_history.py`,
  `backend/tests/{test_events_api,test_monitoring_history}.py`,
  `frontend/src/{api/{events,monitoring}.ts,app/{i18n.tsx,theme.scss},components/LineChart.tsx,
  features/events/{EventsPage.tsx,eventTypes.ts,systemEvidence.ts,EvidencePanel.tsx},
  __tests__/{events,alerts,linechart,system-evidence,system-evidence-panel}}`, `WORKFLOW.md`, `ARCHITECTURE.md`,
  `README.md`, `ROADMAP.md`, `docs/runbooks/monitoring.md`, `CHANGELOG.md`.
- **Evidence (Mac lokal, commit terakhir branch):** backend `631 passed, 471 warnings in 126.55s` (622 → 631: +1 uji
  filter `severity`, +8 uji jendela history); frontend `Test Files 32 passed (32)` / `Tests 349 passed (349)`
  (296 → 349; tidak ada uji yang dihapus, 1 uji lama disesuaikan karena Carbon `Dropdown` kini butuh
  `Element.prototype.scrollIntoView` di jsdom dan stub fetch daftar event ikut memfilter seperti server nyata);
  `npm run build` exit 0; `npm run lint` **24 baris warning** (0 error) — set pasangan (rule, file) identik baseline
  (3× `react(set-state-in-effect)` di `EventsPage.tsx` sebelum dan sesudah). `git grep -nE "style=\{\{|#[0-9a-fA-F]{6}"
  -- frontend/src/features/events` kosong (sama dengan `main`). Uji mutasi dijalankan untuk penjaga respons basi,
  filter event live, batas 6 jam, `node_id`, `camera_low_fps` persen, garis ambang, dan `markers` — semuanya gagal
  saat penjaganya dilepas. **Smoke render mock** (Vite dev + Playwright, `/api/v1/**` di-mock, 1440 px dan 390 px):
  0 error konsol (WebSocket juga di-mock); filter Sistem → 2 baris, Severity critical → 0 baris + pesan kosong,
  “Semua” memulihkan masing-masing ke 3 baris, tombol reset muncul saat filter aktif dan hilang setelah ditekan
  (pencarian kosong, rentang `all`, Tipe `Semua`); event health terpilih → 1 grafik + 1 garis ambang + 1 marker,
  fakta `[CPU node tinggi, Server, 91.5%, 90%, 5 mnt, Menyala]`, 0 tab media; event node offline → 2 grafik
  (`node_cpu_offline`, `node_fps_offline`) dengan 2 arsir offline; 390 px `scrollWidth 375 ≤ innerWidth 390`.
  **Uji UI visual oleh user menyusul setelah deploy** — belum ada klaim visual di entri ini.
- **Dampak:** filter Inbox akhirnya menjangkau seluruh riwayat (bukan 200 teratas) dan selalu bisa dikembalikan ke
  “Semua”; event system menampilkan bukti yang relevan (fakta + tren per aturan) tanpa polling klip yang sia-sia.
  Dua parameter API baru bersifat opsional → kompatibel mundur, tanpa migrasi DB.
- **Rollback:** `git revert` per commit task (6 commit) di branch `feat/system-event-evidence`; tanpa migrasi.
  Server: `git checkout main && git pull` + restart API; frontend lewat Vite dev.

### Dashboard status-first — deploy dan uji UI user (2026-10-01)

- **Konteks:** setelah review dan perbaikan (`6e9f7f0`), user mengizinkan push dan deploy; hasil uji UI dicatat di sini.
- **Deploy `gspe-ai3`:** `git checkout feat/dashboard-revamp` (dari `main` @ `8e57d09`, tree bersih) → `6e9f7f0`;
  tanpa migrasi; hanya API yang di-restart (cgroup kill); frontend lewat Vite dev server (`isentinel-web`).
- **Smoke server:** `/api/v1/health` → `{"status":"ok"}`; `GET /events/stats/today` tanpa auth → 401 (rute hidup);
  `openapi.json` memuat `EventStatsOut`; web `:5173` → 200; journal API 15 baris terakhir tanpa error/traceback.
- **Uji UI user:** "sudah bagus dan sesuai" (konfirmasi di chat; tanpa screenshot). Angka "Event hari ini" yang turun
  (D1, `attendance` tidak dihitung) diterima bersama uji ini. Item viewer-klik-tile-Disk (L1) dan `?.` urutan deploy (L2)
  tidak dikerjakan.
- **Rollback:** `git revert` commit di `feat/dashboard-revamp` (tanpa migrasi); server: `git checkout main && git pull` + restart API.

### Perbaikan review Dashboard status-first (2026-10-01)

- **Konteks:** review sesi perencanaan atas `feat/dashboard-revamp` menemukan 4 hal sebelum deploy: (M1) panel
  "Masalah aktif" menulis "Tidak ada masalah aktif" saat strip/tile menunjukkan masalah (alert baru menyala setelah
  durasi rule); (M2) strip menulis "Semua sistem normal" saat sumber alert gagal/belum termuat dan catatan basi
  memakai jam refresh sumber lain; (M3) tiap event realtime memicu satu scan penuh `stats/today`; (M4) batas bawah
  filter hari (setelah normalisasi UTC) belum diuji. Sisanya: ROADMAP memakai `[x]` sebelum uji lapangan, komentar
  eslint-disable tak perlu, typo "parsitas".
- **Diubah:** `StatusStrip` — "normal" hanya bila monitoring **dan** alert termuat (loading → skeleton; alert gagal →
  "Status alert tidak tersedia"; health ≠ ok → "Status sistem: {state}"); catatan basi memakai sukses terakhir sumber
  yang gagal (`DashboardData.lastOk` per sumber). `useDashboardData` — refetch `statsKey` di-debounce 2 dtk
  (`STATS_DEBOUNCE_MS`), burst event → satu refetch. Teks kosong ActiveIssues: "Tidak ada alert kesehatan aktif"
  (id) / "No active health alerts" (en). Kunci baru `dash.status.health`, `dash.status.alertsUnavailable` (id+en,
  paritas `dash.*` 36=36). `RecentEvents` — komentar eslint-disable dibuang. ROADMAP: `[x]` → `[ ]`.
- **Uji:** backend `test_stats_today_excludes_yesterday` (diuji gagal bila filter batas bawah dibuang: `assert 2 == 1`);
  frontend: strip (konteks health, alert gagal, alert loading, catatan basi per sumber), hook (debounce burst, `lastOk`
  per sumber).
- **File:** `frontend/src/features/dashboard/{StatusStrip.tsx,useDashboardData.ts,RecentEvents.tsx}`,
  `frontend/src/app/i18n.tsx`, `frontend/src/__tests__/{dashboard-blocks,dashboard-data,dashboard,dashboardFixtures}`,
  `backend/tests/test_events_api.py`, `ROADMAP.md`, `CHANGELOG.md`.
- **Evidence (Mac lokal):** backend `622 passed, 463 warnings in 124.42s` (621 + 1); frontend `Test Files 30 passed (30)`
  / `Tests 296 passed (296)` (292 + 4); `npm run build` exit 0; `npm run lint` 24 baris warning (sama; 0 di
  `features/dashboard`); `git grep -nE "style=\{\{|#[0-9a-fA-F]{6}" -- frontend/src/features/dashboard` kosong.
- **Dampak:** tampilan status lebih jujur (tidak ada "normal" palsu); stats Dashboard tertunda ≤ 2 dtk setelah event
  (poll 15 dtk tetap berjalan). Belum diuji visual oleh user.
- **Rollback:** `git revert` commit perbaikan ini; tanpa migrasi DB.

### Revamp Dashboard status-first (2026-09-30)

- **Konteks:** Dashboard lama (3 tile, tanpa link, "kamera online" = status row, event terbaru 3 baris
  `cam {id}`, hex + inline style, polling terpisah) belum mengikuti fitur yang ada. Spec + plan:
  `docs/superpowers/{specs,plans}/2026-09-30-dashboard-revamp-*.md`. Keputusan D1: `stats/today`
  mengecualikan tipe `attendance` (menunggu konfirmasi eksplisit user).
- **Backend:** baru `services/event_stats.py` (`today(db)`); `GET /api/v1/events/stats/today` kini
  `EventStatsOut` (`total`, `by_type`, `by_severity` tiga kunci selalu ada, `by_hour`,
  `critical_by_hour` 24 angka jam lokal; filter `ts_event >= tengah malam lokal` + `type != attendance`);
  router tipis, kompatibel mundur untuk klien lama.
- **Frontend:** `useDashboardData` (5 sumber, polling 15 dtk, kegagalan terisolasi per sumber — nilai
  lama bertahan + strip menandai basi; refetch stats saat id event realtime terakhir berubah),
  `summary.ts`, blok `StatusStrip`/`KpiTiles` (4 tile `<Link>`) /`EventsPerHour` (+ prop `digits` di
  `LineChart`) /`RecentEvents` (thumbnail, Tag severity berteks, nama kamera via `useEventAlerts`,
  tanpa langganan realtime kedua) /`ActiveIssues` /`NodeCompact`; `DashboardPage` ditulis ulang —
  kartu GPU, badge detektor PIN/AUTO, `InlineNotification` bawah, dan semua `style={{}}`/hex hilang;
  kelas `.dash-*` di `theme.scss` (token `var(--cds-*, fallback)`); kunci i18n `dash.*` baru (id+en),
  kunci mati dihapus.
- **File:** `backend/app/{services/event_stats.py,schemas/event.py,api/events.py}`,
  `backend/tests/test_events_api.py`, `frontend/src/{api/events.ts,components/LineChart.tsx,
  features/dashboard/**,app/theme.scss,app/i18n.tsx,__tests__/**}`, `WORKFLOW.md §15`, `README.md`,
  `ARCHITECTURE.md`, `ROADMAP.md`. Commit per task `0f8b39a..ac83cc0` di `feat/dashboard-revamp`.
- **Evidence (smoke test executor, Mac lokal, commit terakhir):**
  - backend `pytest tests -q -m "not gpu"` → `621 passed, 461 warnings in 122.36s` (baseline 618 + 3 uji Task 1)
  - frontend `npx vitest run` → `Test Files 30 passed (30)` / `Tests 292 passed (292)` (baseline 248 − 4 uji lama + 48 uji baru)
  - `npm run build` → exit 0; `npm run lint` → `Found 24 warnings and 0 errors` (baseline 25 minus
    warning `DashboardPage.tsx:151`; tanpa pasangan rule/file baru)
  - S2 statis: `git grep -nE "style=\{\{|#[0-9a-fA-F]{6}" -- frontend/src/features/dashboard` → kosong;
    `git diff --stat main...HEAD` hanya berkas yang diizinkan; kunci `dash.*` id=en=34 (paritas penuh)
  - S3 render mock (`npm run dev` + Playwright, tanpa screenshot): 0 error konsol; strip
    "2 peringatan aktif" + "Diperbarui 17.37"; 4 tile `<a>` href benar (`/monitoring`, `/events`,
    `/attendance`, `/configuration?tab=storage`) dengan teks lengkap ("Kamera 5/7 · 2 bermasalah",
    "Event hari ini 47 · 3 critical", "Kehadiran 3 · 1 telat · 1 perlu koreksi", "Disk 62% ·
    353,9 GB kosong"); chart per jam ter-render; event terbaru "Intrusi Gate-A Critical" dengan
    thumbnail (fallback OK) + tautan `/events?event=11`; masalah aktif 2 baris (critical dulu);
    node ringkas 2 baris (GPU0 55% · VRAM 21%); warna titik dari token Carbon (bukan fallback, tidak
    kosong); 390 px: `scrollWidth 375 <= innerWidth 390` → true, keempat blok tetap ada.
  - Uji UI visual **menyusul oleh user setelah deploy** — belum ada klaim visual dari mata user.
- **Dampak:** angka "Event hari ini" turun di pabrik ramai (lintasan wajah tak dihitung lagi — D1);
  "kamera online" berganti makna jadi "sehat" (health rule); detektor/GPU detail hanya di Monitoring;
  dashboard tak lagi membuat langganan WS kedua.
- **Rollback:** `git revert` commit per task (`ac83cc0`, `a3d4c89`, `fe024e2`, `62d1f64`, `91aedd9`,
  `0f8b39a`); tanpa migrasi DB; `stats/today` kompatibel mundur (satu filter D1 untuk dibalik).

### WORKFLOW.md jadi alur per fitur (2026-09-30)

- **Konteks:** yang dimaksud WORKFLOW adalah alur kerja setiap fitur aplikasi, bukan siklus pengembangan.
- **Diubah:** isi lama (siklus fitur, branch/commit, verifikasi, deploy, rollback) dipindah ke
  `docs/DEVELOPMENT.md`; `WORKFLOW.md` baru berisi 15 alur fitur (login, user, kamera, Live View/TV,
  deteksi & node, zona, event behavior, Inbox, notifikasi web, Telegram, enrollment & shift, absensi,
  retensi & storage, monitoring, dashboard) — pengguna, langkah UI, alur sistem, rujukan runbook.
  `README.md`/`AGENTS.md` menautkan ketiganya.
- **Dampak:** dokumentasi saja. **Rollback:** `git revert` commit ini.

### Dokumen ARCHITECTURE.md & WORKFLOW.md (2026-09-30)

- **Konteks:** arsitektur dan cara kerja tim tersebar di README, AGENTS.md, dan riwayat chat.
- **Baru:** `ARCHITECTURE.md` (topologi, unit systemd, lapisan backend + thread latar, data utama,
  vision pipeline, kontrak MQTT/HTTP internal/WebSocket, alur utama, frontend, keamanan & storage);
  `WORKFLOW.md` (siklus brainstorm → spec → plan → eksekusi → review → deploy → uji user → merge,
  branch & commit, verifikasi, deploy `gspe-ai3`, rollback, dokumen yang ikut diperbarui, aturan keamanan).
- **Diubah:** `README.md` dan `AGENTS.md` menautkan kedua dokumen.
- **Dampak:** dokumentasi saja. **Rollback:** `git revert` commit ini.

### Evidence lokal & plan tersisa hanya Edge Jetson (2026-09-30)

- **Konteks:** `docs/evidence/` (22 MB screenshot) terus menumpuk di git; `docs/plans/` masih berisi plan
  Fase 0–5 yang sudah selesai sehingga terkesan masih terbuka (checkbox tidak pernah dicentang).
- **Diubah:** `docs/evidence/` di-untrack (`git rm --cached`) dan masuk `.gitignore` — berkas tetap di
  mesin lokal, bukti uji berikutnya disimpan lokal saja; `docs/plans/00`–`06` dihapus (tetap di riwayat
  git); `07-edge-jetson.md` ditandai satu-satunya milestone tersisa; spec desain awal diberi banner arsip.
- **Dokumentasi:** `AGENTS.md` (status Fase 0–5 selesai, migrasi terakhir 0020, branch dari `main`,
  unit systemd sudah direkonsiliasi, evidence lokal), `README.md` (peta docs), `ROADMAP.md` (header +
  rujukan plan fase jadi "arsip git").
- **Dampak:** tanpa perubahan kode. Path `docs/evidence/…` di CHANGELOG/ROADMAP lama merujuk riwayat git.
- **Rollback:** `git revert` commit ini (evidence kembali ter-track).

### Rapikan project & dokumentasi (2026-09-30)

- **Konteks:** artefak lama yang sudah tidak dipakai membingungkan peta repo.
- **Dihapus:** `mockup-ui/` (6 HTML mockup awal; semua halaman sudah dibangun, tampilan tetap
  terekam di `docs/evidence/ui-polish/mockup/`, sumber di commit `f493b95`);
  `docs/runbooks/events-cleanup.md` (digantikan mode cleanup `events` di UI Storage);
  `docs/runbooks/camera-management-migration.md` (migrasi 0007 sudah lama selesai);
  `docs/runbooks/attendance-face-first.md` (deploy R5b selesai — bagian zona, label gerbang, dan
  kalibrasi `face_stats` dipindah ke `docs/runbooks/attendance.md` §Gerbang wajah).
- **Diubah:** `docs/detection-behavior-inventory.md` diberi banner arsip (snapshot 2026-09-22);
  peta repo `AGENTS.md`/`README.md` tanpa `mockup-ui/`; komentar `theme.scss` tidak lagi menunjuk
  path yang dihapus; ROADMAP R5b menunjuk runbook gabungan.
- **Dampak:** tanpa perubahan kode/perilaku. `temp/` (gitignored) dibersihkan lokal, sisa `data/` + `log.txt`.
- **Rollback:** `git revert` commit ini.

### Refining halaman Attendance (2026-09-30)

- **Konteks:** tabel Attendance tidak punya kolom tanggal (tab Rentang/Per karyawan mencampur
  hari), dan pemeriksaan menemukan bug logika: status disimpan hanya saat ada event baru atau
  endpoint manual `close-days` yang **tidak pernah dijadwalkan** — akibatnya entry tanpa exit
  tetap "MENUNGGU" (durasi "berjalan…") berhari-hari, karyawan yang tidak datang tidak punya
  baris sehingga "Tidak hadir" selalu 0, dan exit tanpa entry dihitung `absent` (orangnya
  sebenarnya hadir). Desain: `docs/superpowers/specs/2026-09-30-attendance-refine-design.md`.
- **Perubahan backend** (`app/services/attendance.py`, `app/api/attendance.py`, `app/main.py`):
  status baru `no_entry` (hanya exit terdeteksi → perlu koreksi, `late_minutes`/`duration_min`
  null); `deadline()` (jam selesai shift + `NO_EXIT_GRACE_MIN`, tz lokal); `effective_status()`
  — `waiting` yang lewat batas tampil `no_exit` saat dibaca (list API + CSV) walau job belum
  jalan; list API urut `date DESC` lalu nama (CSV tetap kronologis menaik, status efektif);
  `PATCH`/`import` menerima `no_entry`. Job latar `AttendanceCloser` (`CLOSE_INTERVAL_S=900`,
  run pertama saat start, sesi DB sendiri, tahan error, stop rapi di lifespan): `close_due`
  tiap 15 menit + catch-up 7 hari membuat baris `absent` / menutup `waiting` → `no_exit`
  untuk karyawan aktif ber-shift di hari kerjanya yang sudah lewat batas. **`override_note`
  non-kosong tidak pernah diubah** oleh `effective_status`, `close_due`, maupun `close_days`.
  conftest menonaktifkan job di tes (autouse, pola `_quiet_node_monitor`).
- **Perubahan frontend** (`features/attendance/AttendancePage.tsx`, `api/attendance.ts`,
  `app/i18n.tsx`): kolom Tanggal (format lokal pendek, tahun bila bukan tahun berjalan) hanya
  tab Rentang/Per karyawan; Entry/Exit `HH:MM` dengan judul `ENTRY/EXIT (WIB)`; durasi
  `8j 12m` dan `3j 10m · berjalan` dihitung live tiap 60 s hanya untuk `waiting` hari ini —
  hari lampau / `no_exit` / `no_entry` / `absent` tampil `—`; label status "DI DALAM",
  "TANPA EXIT/TANPA ENTRY — PERLU KOREKSI" (oranye), "TIDAK HADIR"; tile Harian jadi filter
  klik (`aria-pressed`, grid `auto-fit minmax(160px,1fr)` — aman 390 px) termasuk tile baru
  **Perlu koreksi**; chip filter `lv-chip` di tab Rentang/Per karyawan (penghitungan tile dari
  semua baris, tabel tersaring; pesan khusus "Tidak ada baris yang cocok dengan filter" saat
  filter menyaring semua); tombol **Koreksi** hanya admin & baris `no_exit`/`no_entry`
  (stopPropagation, tanpa double-open); ikon pensil `corrected-<id>` (tooltip = catatan);
  modal override menawarkan `no_entry`. i18n id/en 720 kunci identik.
- **Bukti:** backend **617 passed** (baseline `c22eac5` 606; +11, durasi ~120 s tidak naik
  berarti), vision **233 passed, 3 deselected** (sama), frontend **248 passed** (baseline 237;
  +11), `npm run build` 0 error, lint 25 warning / 0 error dengan **pasangan rule+file identik
  baseline**. Cek visual Chromium (stub API berisi semua status): `/attendance` Harian &
  Rentang 1440 px & 390 px tanpa overflow halaman (`scrollWidth == viewport`), kolom Tanggal
  benar, chip/tile/tombol Koreksi/ikon koreksi tampil — `docs/evidence/2026-09-30-attendance-
  {daily,range}-{1440,390}.png` + `range-filter.png` (harness `temp/cdp-attendance.mjs`).
  Review independen (subagent, diff `e959ba0..0979469`): 8/8 fokus PASS, **0 Critical /
  0 Important / 2 Minor** — Minor 1 (pesan kosong menyesatkan saat filter menyaring semua)
  diperbaiki + tes regresi di `cdb7a40`; Minor 2 (`stop()` join 2 s vs catch-up panjang,
  pola sama `node_health`) dicatat sebagai risiko ~0.
- **Dampak deploy:** tanpa migrasi; deploy = restart `isentinel-api` (frontend HMR). **Saat
  pertama start, catch-up 7 hari membuat baris "Tidak hadir" untuk hari kerja tertinggal**
  (karyawan aktif ber-shift tanpa baris) dan menutup "MENUNGGU" lama → "Tanpa exit"; idempoten
  (restart ulang tidak menduplikasi).
- **Rollback:** `git revert` rentang commit + restart `isentinel-api` + build frontend. Baris
  `absent`/`no_exit` yang sudah dibuat job tetap ada (data turunan; bisa dibersihkan lewat
  Storage cleanup "Data absensi"); nilai `no_entry` tampil sebagai teks mentah di UI lama.
- **File:** `backend/app/services/attendance.py`, `backend/app/api/attendance.py`,
  `backend/app/main.py`, `backend/tests/conftest.py`, `backend/tests/test_attendance_logic.py`,
  `backend/tests/test_attendance_api.py`, `frontend/src/features/attendance/AttendancePage.tsx`,
  `frontend/src/api/attendance.ts`, `frontend/src/app/i18n.tsx`,
  `frontend/src/__tests__/attendance.test.tsx`, `README.md`, `ROADMAP.md` (baris AR),
  `docs/runbooks/attendance.md` (baru), `docs/evidence/2026-09-30-attendance-*.png`.
- **Review perencana:** catch-up 7 hari akan membuat "Tidak hadir" untuk hari **sebelum karyawan didaftarkan**
  (karyawan baru langsung punya beberapa hari absen palsu). `close_due` dan `close_days` kini melewati hari sebelum
  `employee.created_at` (tanggal lokal) untuk baris baru; tes regresi + fixture tes karyawan diberi `created_at` lama.
  Backend 618.
- **Deploy & verifikasi user (2026-09-30):** server `gspe-ai3` @ `a9630cc`, restart API (tanpa migrasi). Catch-up saat
  start: 2 baris `waiting` lama EMP-001 (25 & 29 Sep) → `no_exit`; `absent` dibuat untuk hari kerja tanpa deteksi
  23/24/28/29 Sep (EMP-002 mulai tanggal daftar 23 Sep), akhir pekan 26–27 Sep dilewati. Uji user tab Harian/Rentang,
  koreksi, filter, CSV: **sesuai**. Merge ke `main`.

### Cleanup data absensi (rekap & riwayat) (2026-09-30)

- **Konteks:** server berisi campuran karyawan uji dan karyawan nyata. Mode cleanup yang sudah ada
  (`events`, `attendance_media`) sengaja tidak pernah menyentuh riwayat/rekap absensi, jadi tidak ada
  cara membuang data uji tanpa memengaruhi karyawan nyata selain manipulasi DB manual — berisiko dan
  tidak ter-audit.
- **Perubahan:** mode ketiga `attendance_data` di `POST /storage/cleanup` (admin) yang menghapus
  PERMANEN `attendance_event`, `attendance_day` (**termasuk `override_note`** — koreksi manual admin
  ikut hilang, sesuai keputusan produk: hapus semuanya untuk seleksi, tanpa pengecualian), event Inbox
  tipe `attendance` terkait beserta alert-nya, dan semua medianya (foto, crop wajah, clip lama) untuk
  karyawan terpilih atau semua karyawan pada rentang tanggal. Validasi (422): `date_to` maksimum
  **kemarin** (bukan hari ini — shift mungkin masih berjalan), `camera_ids`/`types` tidak berlaku,
  wajib `employee_ids` **atau** `all_employees` (XOR — tidak boleh keduanya kosong atau keduanya
  terisi); mode lain menolak `employee_ids`/`all_employees` bila diisi. `all_employees=true` juga
  menghapus event wajah tak dikenal (attendance tanpa baris riwayat) di rentang itu; filter karyawan
  tidak. File yang masih dirujuk baris **di luar** seleksi (karyawan lain / rentang lain) dipertahankan
  — pola sama dengan `cleanup_attendance_media`. Baris dihapus dalam satu transaksi (alert → event →
  riwayat → rekap) sebelum file dihapus dari disk; dry run tidak mengubah apa pun dan menampilkan
  ringkasan + breakdown per karyawan (nama, jumlah riwayat, jumlah hari). Audit log
  (`attendance data cleanup by <admin>: <from>..<to> employees=<id...|all> → N attendance_events,
  M days, K events, F files`) **hanya mencatat ID karyawan, tidak pernah nama** (data pribadi).
  Frontend: radio ketiga "Data absensi (rekap & riwayat)" di kartu Bersihkan event — menyembunyikan
  kamera & jenis, MultiSelect karyawan + checkbox "Semua karyawan", tanggal maksimum kemarin, tabel
  pratinjau per karyawan, dan modal konfirmasi yang mengunci tombol Hapus sampai kata `HAPUS` diketik
  persis (lebih ketat dari dua mode lain — data ini tidak bisa dipulihkan dan memengaruhi ekspor CSV).
- **File:** `backend/app/schemas/storage.py`, `backend/app/services/retention.py`,
  `backend/app/api/storage.py`, `backend/tests/test_attendance_data_cleanup.py`,
  `frontend/src/api/storage.ts`, `frontend/src/features/config/EventCleanupCard.tsx`,
  `frontend/src/app/i18n.tsx`, `frontend/src/__tests__/storage.test.tsx`,
  `frontend/src/__tests__/storage-attendance.test.tsx`, `docs/runbooks/storage-retention.md`,
  `README.md`.
- **Bukti:** backend **606 passed** (baseline 597, +9), frontend **237 passed** (baseline 232, +5),
  build exit 0, lint 0 error (rule+file warning identik dengan baseline, tanpa warning baru),
  `git diff --stat main -- vision` kosong, tanpa dependensi baru, tanpa migrasi DB.
- **Dampak:** admin bisa membuang data absensi uji per karyawan/rentang dengan aman tanpa menyentuh
  karyawan lain; setiap penghapusan tercatat di audit log tanpa membocorkan nama karyawan; ekspor CSV
  untuk rentang yang dibersihkan akan kosong setelahnya (diperingatkan di modal konfirmasi).
- **Rollback:** `git revert` dua commit fitur ini; tanpa migrasi, aman di-revert kapan saja — tetapi
  baris `attendance_event`/`attendance_day` yang sudah dihapus lewat mode ini **tidak bisa
  dipulihkan** (itulah alasan pratinjau wajib + konfirmasi ketik `HAPUS`).
- **Deploy & verifikasi user (2026-09-30):** server `gspe-ai3` @ `cc8a058`, restart API (tanpa migrasi). Dry run di
  server (1 Sep–kemarin, semua karyawan): 5 riwayat, 6 hari, 2 entri Inbox, 4 file, 2 karyawan; hari ini & tanpa
  pilihan karyawan → 422. Uji user hapus data karyawan uji: **sesuai**. Merge ke `main`.

### Status alert Telegram realtime + rapikan tabel aturan (2026-09-30)

- **Konteks:** chip status alert Telegram di Events (Inbox) tertulis "queued" saat
  event masuk, lalu `alert_dispatcher` mengirim & menetapkan status akhir detik
  kemudian — browser tidak pernah diberi tahu, jadi chip tetap "Antre" sampai
  reload manual. Terpisah: tabel **Aturan & alert** Monitoring mengulang label
  kolom ("Aktif", "Ambang", "Durasi (menit)", "Severity", "Telegram") di tiap baris.
- **Perubahan:** `alert_dispatcher.process()`/`_reconcile()` broadcast
  `{kind:"alert", event_id, status}` lewat `hub` setelah status final di-commit
  (`sent`/`failed`/`not_configured`), dibungkus try/except (`logger.exception`) agar
  kegagalan WS tidak pernah mengubah baris alert atau menghentikan worker. Events
  page memakai frame ini (bukan membuangnya) untuk update chip + badge detail live;
  event/status tak dikenal diabaikan. Fallback saat WS mati: id yang masih `queued`
  di-cek ulang via `alertsByEvents` tiap 10 detik, berhenti begitu tak ada lagi yang
  queued. Kosmetik: `Toggle`/`NumberInput`/`Select` per baris tabel aturan pakai
  `hideLabel` (+ `aria-label` pada Toggle), nama aksesibel tetap `"<aturan> — <kolom>"`.
- **File:** `backend/app/services/alert_dispatcher.py`,
  `backend/tests/test_alert_dispatcher.py`, `frontend/src/features/events/EventsPage.tsx`,
  `frontend/src/__tests__/events.test.tsx`, `frontend/src/features/monitoring/AlertsTab.tsx`.
- **Bukti:** backend **597 passed** (baseline 592, +5), frontend **232 passed**
  (baseline 229, +3), build exit 0, lint 0 error (warning rule+file sama dengan
  baseline, tanpa warning baru), `git diff --stat main -- vision` kosong.
- **Dampak:** chip/badge Telegram di Inbox ikut status nyata tanpa reload; tabel
  aturan Monitoring lebih ringkas tanpa kehilangan nama aksesibel (screen reader
  & tes tetap bisa menargetkan kontrol per baris).
- **Rollback:** revert tiga commit item ini (`830aad2`, `343db8b`, `2e682d0`); tidak
  ada migrasi/skema yang berubah, aman di-revert kapan saja.
- **Commit:** `830aad2` broadcast status dispatcher; `343db8b` Events page pakai
  frame alert + fallback polling; `2e682d0` label tabel aturan.
- **Deploy & verifikasi user (2026-09-30):** ikut deploy `cc8a058` (restart API). Uji user chip status Inbox berubah
  tanpa reload + tabel aturan rapi: **sesuai**. Merge ke `main`.

### Monitoring Resource S3 (2026-09-30)

- **Konteks:** operator membutuhkan alert berkelanjutan untuk kamera/AI/hardware,
  bukan hanya status sesaat atau grafik. Delapan aturan global memakai sampel menit S2.
- **Perubahan:** katalog `health_rules` (default, batas, validasi atomik) dan ambang S1
  bersama; migrasi `0020_health_alert` (`down_revision="0019"`), model, evaluator
  stateless setelah sampler, retensi resolved 7 hari; API rules/alerts (PUT admin,
  GET semua user login); tab ketiga **Aturan & alert** (Carbon, id/en, PUT parsial,
  polling 30 detik); badge kamera Live View/TV dan label event kesehatan menyala/normal.
  Event kesehatan tidak membuat chip node offline, outline kamera, atau arsir offline.
- **Semantik:** setiap menit selesai dalam durasi harus punya sampel dan melanggar;
  pulih setelah 2 menit normal. Node offline/tanpa sampel menahan alert. Aturan nonaktif
  atau target hilang ditutup tanpa Telegram. Event web selalu, Telegram per aturan
  tanpa pengingat ulang. Default FPS rendah S1 sengaja **80 % → 50 % target**.
  Start menit UTC, unique fence + lock node Postgres, conditional resolve menjaga
  transisi tunggal saat evaluator diulang; daftar alert di service, bukan SQL router.
- **Verifikasi:** backend **592 passed** (baseline 549, +43; **119,78 s** vs 117,97 s),
  vision **233 passed / 3 deselected** (tanpa diff), frontend **229 passed** (223, +6),
  build 0, lint **25 warning / 0 error**, set **17 pasangan rule+file identik** baseline.
  Paritas id/en 726 kunci; tanpa dependensi baru. Seluruh tes memakai fake layanan.
- **Review independen:** satu reviewer baru pada `14edf59..3ca8cbc`, **0 Critical /
  2 Important / 0 Minor**. Bagian valid diperbaiki di `f9faba6`: transisi alert +
  event satu commit (gagal insert tidak meninggalkan firing/resolved/closed tanpa
  event), tiga regresi RED→GREEN; race barrier dua sesi/koneksi SQLite untuk ketiga
  transisi, satu event/broadcast/send. Target evaluator/history/migrasi 51 pass.
  Permintaan outbox/retry Telegram tidak diadopsi: spec menetapkan gagal kirim tetap
  menyimpan alert/event, bukan jaminan exactly-once transport. Telegram/WS tetap
  best-effort. PostgreSQL hanya review statis + kompilasi `FOR UPDATE`, tanpa server
  sesuai batasan sesi. Tidak ada re-review; tool tidak menyediakan pemilihan model.
- **File utama:** `services/{health_rules,health_alerts,monitoring,monitoring_history}.py`,
  model/migrasi `health_alert`, router/schema monitoring; frontend `AlertsTab.tsx`,
  `useCameraHealthAlerts.ts`, `CameraTile.tsx`, `LiveWall.tsx`, provider/label
  notifikasi, API monitoring, i18n, dan `theme.scss`; tes backend/frontend + evidence.
- **Cek visual:** Chromium stub API, admin/viewer `/monitoring?tab=alerts` pada 1440
  dan 390 px; viewer seluruh kontrol disabled/tanpa Save. Badge kamera bermasalah
  saja di Live View 1440/390 dan TV 1440. Lebar dokumen = viewport. Overflow Carbon
  Toggle (822 > 390) diperbaiki dengan containing block scroller (`2edb414`).
  Screenshot `docs/evidence/2026-09-30-monitoring-alerts-*.png`; server dev dimatikan.
- **Flake tercatat:** run frontend awal: kasus streaming Live View gagal (226 pass),
  rerun file 17 pass. Dua run lain: kasus hapus zona gagal (226 pass), rerun file
  23 pass. Harness zona kini menunggu snapshot selesai sebelum menggambar, tanpa
  melemahkan assertion; full suite berikutnya hijau. Kasus “tile di luar layar”
  tidak gagal. Warning vision lama: fake `T` tanpa `publish_heartbeat`; tidak diubah.
- **Operasi:** belum deploy/merge. Migrasi 0020 (env `.env`), restart `isentinel-api`
  + frontend HMR/build pada sesi terpisah; vision tidak perlu restart. Rollback:
  revert commit S3 + `alembic downgrade 0019` (menghapus riwayat alert permanen),
  restart API + frontend HMR/build. Rincian: `docs/runbooks/monitoring.md`.
- **Commit per task:** `f46d738` rules/ambang S1; `046704c` migrasi/model;
  `8140380` evaluator; `7af1487` API; `2a1749d` tab; `3ca8cbc` badge/event;
  `2edb414` fix visual + evidence; `f9faba6` fix review + tes konkuren.
  Dokumentasi ini menutup Task 7.
- **Deploy & verifikasi user (2026-09-30):** server `gspe-ai3` @ `1dd9fb3` — `alembic upgrade head` (0020) + restart
  API 13:25; log evaluator bersih, `/rules` & `/alerts` OK, `evaluate` + `history` dijalankan manual di Postgres (kunci
  baris node, `payload->>'reason'`) tanpa error. Uji user tab Aturan & alert: **sesuai**. Merge ke `main`.

### Monitoring Resource S2 (2026-09-30)

- **Konteks:** operator perlu melihat **pola**, bukan hanya kondisi saat ini — mis. GPU penuh tiap pagi atau
  fps kamera turun di jam tertentu. S2 menambah riwayat metrik per menit (disimpan 7 hari) dan tab **Tren**
  berisi grafik SVG di halaman Monitoring (tanpa dependensi grafik baru).
- **Perubahan:** (a) backend — migrasi `0019_monitoring_sample` (ts menit UTC, FK node CASCADE, unique
  `(node_id, ts)`), `services/monitoring_history.py` (agregasi heartbeat → bucket menit di memori: avg/max/min
  sesuai metrik, fps kamera digabung antar worker = terendah, state = terburuk; `HistorySampler` thread 60 s
  flush + prune > 7 hari tiap jam; `query()` downsample 1 jam/6 jam per menit, 24 jam per 5 menit, 7 hari per
  30 menit + periode offline dari event `system`), hook `record` di handler heartbeat MQTT, endpoint
  `GET /api/v1/monitoring/history?range=` (semua user, 422 bila rentang tidak valid); (b) frontend —
  `components/LineChart.tsx` (SVG: celah > 1,5 bucket, arsir offline, refLine putus-putus, tooltip hover,
  `role="img"` + aria-label, lebar ikut kontainer), halaman Monitoring jadi dua tab (`CurrentTab` = isi S1,
  `TrendTab` baru; hanya tab aktif yang di-mount → polling S1 berhenti di tab Tren; rentang di URL
  `?tab=trend&range=`; pemilih node bila > 1; kamera maks 4 via MultiSelect; refresh 60 s).
- **File:** `backend/alembic/versions/0019_monitoring_sample.py`, `backend/app/models/monitoring_sample.py`,
  `backend/app/services/monitoring_history.py`, `backend/app/{services/events_consumer,api/monitoring,
  schemas/monitoring,main,models/__init__}.py`, `backend/tests/{test_monitoring_history,test_migration_0019}.py`,
  `backend/tests/{conftest,test_events_consumer}.py`; `frontend/src/components/LineChart.tsx`,
  `frontend/src/features/monitoring/{MonitoringPage,CurrentTab,TrendTab}.tsx`,
  `frontend/src/{api/monitoring.ts,app/i18n.tsx,app/theme.scss}`,
  `frontend/src/__tests__/{linechart,monitoring-trend}.test.tsx`; runbook `docs/runbooks/monitoring.md`,
  README, ROADMAP (baris MO2).
- **Bukti:** backend **549 passed** (baseline 532, durasi suite ~121 s tidak naik berarti — sampler
  dinonaktifkan lewat fixture conftest), vision **233 passed / 3 deselected** (tidak tersentuh), frontend
  **222 passed** (baseline 211), build 0, lint 25 warning 0 error (set lama + 1 `react/only-export-components`
  di `LineChart.tsx` — pola yang sama dengan `EventAlertsProvider.tsx`/sesi notifikasi); `git diff --stat
  main -- vision` kosong. Bukti visual Chromium `docs/evidence/2026-09-30-monitoring-trend-{1440,390,cameras,
  tooltip}.png` (stub data rapat per menit; 1440 px `scrollWidth 1425 ≤ 1440`, 390 px `scrollWidth == 390`
  tanpa overflow; 6 grafik node + 4 kamera + arsir offline + tooltip nilai tiap seri).
- **Review independen (subagent reviewer, diff `e10505d..278fd6d`):** 8/8 fokus PASS, **0 Critical /
  0 Important / 3 Minor** — ketiganya diperbaiki di `278fd6d` + tes regresi merah-sebelum: (a) `_offline`
  kini whitelist `reason in {lwt, timeout}` (event `system` lain dengan `node_id` tidak lagi membuat arsir
  offline palsu); (b) `_minute` membaca datetime naive sebagai UTC (konsisten `_utc`, bukan zona lokal mesin);
  (c) `MultiSelect` kamera diberi `key={node.id}` — centakan remount saat ganti node (sebelumnya state
  Downshift basi menampilkan centakan node lama).
- **Dampak:** API menjalankan satu thread sampler tambahan (`monitoring-history`, 60 s); tumbuh ±1.440 baris
  `monitoring_sample` per node per hari (±10 rb baris per node per 7 hari), dipangkas otomatis. Heartbeat
  vision tidak berubah (handler backend saja). Bucket menit berjalan hilang saat API restart (≤ 1 menit data).
- **Deploy:** `alembic upgrade head` (0019, env dari `.env`) + restart `isentinel-api`; frontend build/HMR;
  **vision tidak perlu restart**. Uji lapangan: ±2–3 menit setelah deploy tab Tren (1 jam) menampilkan titik
  CPU/RAM/GPU/inferensi/kamera; cek 6 jam/24 jam setelah ±1 jam; bekukan vision 60 s (izin) → celah + arsir
  merah. Rollback: `git revert` rentang commit S2 + `alembic downgrade 0018` (drop tabel, riwayat hilang —
  data turunan) + restart API + build frontend.
- **Review perencana:** titik data tunggal di antara celah (mis. menit pertama setelah deploy / node pulih) tidak
  tergambar karena segmen hanya `M` → kini digambar sebagai dot (`LineChart`, tes regresi). Frontend 223.
- **Deploy & verifikasi user (2026-09-30):** hapus 3 event `system` palsu lama (4757/4760/4761, LWT saat restart API)
  agar arsir 7 hari tidak palsu; server `gspe-ai3` @ `f58046e` — `alembic upgrade head` (0019) + restart API 11:20,
  sampel pertama 11:21, `/history` OK. Uji user tab Tren (grafik node/GPU/inferensi/kamera, tooltip, ganti rentang,
  390 px): **sesuai**. Merge ke `main`.

### Monitoring Resource S1 (2026-09-29)

- **Konteks:** operator perlu satu halaman kondisi saat ini (kamera, inferensi AI, hardware, layanan) dan
  deteksi node offline/pulih yang andal. Ditemukan bug terverifikasi: LWT MQTT `retain=True` tidak pernah
  dibersihkan → setiap API restart membaca LWT `offline` lama dan mencatat event `system` "Node offline" palsu
  (bukti server: hanya 2 event `system` di DB, tepat waktu start `isentinel-api` 11:39:32 & 15:04:02).
- **Perubahan:** (a) vision — `FrameSource.stats()` (state, umur frame, reconnect 1 jam), fps/skip per worker
  kamera, jendela inferensi (`ms_avg/ms_max/infer_fps`), antrean face, backlog MQTT, host `/proc`
  (CPU/RAM/disk) + GPU `temp_c`/`power_w`, dan **LWT `{"status":"online"}` retained qos 1 saat connect**;
  (b) backend — `node_health` (satu-satunya jalur ubah `node.status`, event `system` + WS + Telegram sekali per
  transisi, `NodeHealthMonitor` tiap 15 s, timeout 35 s, `unknown → online` tanpa event; `mark_stale_nodes`
  dihapus, `GET /nodes` tidak lagi menyapu status), `telegram.send_text`, heartbeat menyimpan `cameras` +
  `mqtt_backlog` ke JSON `node.modules`, `GET /api/v1/monitoring` (semua user, agregasi DB + go2rtc + cek
  layanan cache 10 s, `NodeOut.last_seen`); (c) frontend — halaman `System › Monitoring` (polling 10 s, tabel
  kamera urut kritis→peringatan→sehat + filter "Hanya bermasalah", kartu node/server, layanan), banner node
  offline persisten (AppShell + mode TV), notifikasi "Node pulih" + chip offline hilang.
- **File:** `vision/vision/{pipeline/source,node,face_worker,hardware,pipeline/detector,transport/mqtt}.py`,
  `backend/app/services/{node_health,monitoring,host_stats,telegram,disk_alert,events_consumer,go2rtc}.py`,
  `backend/app/{api/events,api/nodes,api/monitoring,models/node,schemas/camera,schemas/monitoring,main}.py`,
  `frontend/src/{api/monitoring.ts,features/monitoring/*,components/NodeOfflineBanner.tsx,
  features/notifications/*,app/*,main.tsx}`; runbook `docs/runbooks/monitoring.md`.
- **Bukti:** backend **530 passed** (baseline 491), vision **233 passed / 3 deselected** (baseline 223),
  frontend **210 passed** (baseline 203), build 0, lint set pasangan rule+file identik dengan baseline (16/16);
  bukti visual Chromium `docs/evidence/2026-09-29-monitoring-{page-1440,page-390,banner-appshell,banner-tv}.png`
  (`/monitoring` 1440 & 390 px: `scrollWidth == viewport`, tabel kamera scroll di dalam kartunya; banner muncul
  saat node offline dan hilang dengan `?online=1`, termasuk mode TV).
- **Review independen (subagent reviewer, diff `d25d0ab..239ec71`):** fokus 1/2/6/7 PASS; 3 temuan valid
  diperbaiki di `c446e5e` + tes regresi: (a) `NodeHealthMonitor` mati bila pembuatan/penutupan sesi DB melempar
  (kini dicatat dan thread lanjut); (b) `ai.state` bertipe ngawur dari node membuat response validation → HTTP 500
  (kini dikoersi ke `null`) dan heartbeat tanpa key `cameras` dianggap kritis `not_running` padahal statistik
  belum ada → `no_data` warning; (c) DB benar-benar mati membuat `snapshot()` melempar (kini degradasi: layanan
  `database` critical, node/kamera kosong, endpoint tetap 200). Tidak diverifikasi (tanpa Postgres/uvicorn/broker
  nyata): perilaku timestamptz Postgres, pengiriman WS dari thread worker di uvicorn, dan uji lapangan LWT
  (butuh izin user — spec §6).
- **Dampak:** heartbeat vision sedikit lebih besar (statistik host/kamera) dan API menjalankan satu thread monitor
  (`node-health`, cek 15 s); cek layanan di halaman di-cache 10 s. Tanpa dependensi baru, **tanpa migrasi**
  (data baru di JSON `node.hw`/`node.modules`).
- **Rollback:** `git revert` rentang S1 + build frontend + restart vision & API; kode lama mengabaikan field JSON
  tambahan. Catatan: kode lama kembali membawa bug LWT retained kecuali retained `online` dari node baru masih
  tersimpan di broker.
- **Deploy:** restart `isentinel-vision` (fix LWT + heartbeat baru) dan `isentinel-api` (monitor + endpoint);
  frontend build/HMR. Tanpa migrasi.
- **Fix uji deploy (2026-09-30):** di data nyata 6 kamera aktif tampil kritis `not_running` padahal tidak punya
  zona aktif — vision memang tidak menjalankan worker untuk kamera tanpa zona aktif ber-behavior (live view saja).
  Kamera kini hanya diharapkan berjalan bila punya zona `active` dengan `behaviors` tidak kosong (sama dengan
  logika vision); selain itu `analyzed: false`, status sehat, kolom Sumber AI "Tanpa zona aktif", tidak terpengaruh
  node offline. File: `backend/app/services/monitoring.py`, `schemas/monitoring.py`, `tests/test_monitoring.py`,
  `frontend/src/features/monitoring/MonitoringPage.tsx`, `api/monitoring.ts`, `i18n.tsx`, runbook. Backend 532,
  frontend 210, build 0.
- **Fix notifikasi (uji user 2026-09-30):** refresh Live View menyalakan outline/toast/bunyi tanpa event baru.
  Akar masalah (terverifikasi data server): sejak lonceng hanya memuat riwayat 00:00 kemarin, poll pertama
  `useLiveEvents` (`limit=50`, semua waktu) membawa event lama (25–28 Sep) yang tidak ada di riwayat → dianggap
  baru. Event dengan `ts_event` sebelum awal jendela riwayat kini selalu diperlakukan sebagai riwayat (`2a20d21`,
  tes regresi di `event-alerts.test.tsx`).
- **Rapikan UI Monitoring (review user):** jarak antar blok/tile/kartu lebih lega, kartu node dikelompokkan
  (Hardware · GPU · Inferensi AI · Masalah), tabel & layanan ber-padding lebih besar, umur heartbeat "N dtk/mnt/jam",
  tag Peringatan kuning (`61a6b5f`). Frontend 211, build 0, lint tanpa error.
  Lanjutan: halaman memakai `.app-page` (padding 24/32 px, judul/sub sama dengan halaman lain), kartu & tile
  mengikuti ukuran `.st-card` (14/16 px), banner node offline sejajar konten (`0ab28ee`).
- **Deploy & verifikasi user (2026-09-29/30):** server `gspe-ai3` — restart vision lalu API (09:11/09:12), fix
  susulan via restart API + HMR. Uji user: halaman Monitoring (kamera dianalisis Streaming + fps, kamera tanpa zona
  "Tanpa zona aktif"), akses viewer, refresh Live View tanpa outline palsu, dan node offline/pulih (vision
  dibekukan 60 s: event `timeout` 27 s setelah beku + event `online` saat lanjut, satu per transisi, Telegram, banner
  AppShell/TV, chip, toast): **sesuai**. Merge ke `main`.

### Notifikasi event web UI + outline tile Live View (2026-09-29)

- **Konteks:** operator command center perlu tahu event baru tanpa membuka halaman Events; tile kamera yang kena
  event harus menonjol di Live View / mode TV.
- **Perubahan:** `EventAlertsProvider` (satu langganan WS/polling, riwayat vs event baru, anti duplikat),
  lonceng header + panel (20 event terakhir, badge `20+`), toast (maks 3, 8 detik), bunyi Web Audio (mute per
  browser, maks 1×/5 s), outline severity 30 s di tile, chip untuk tile tersembunyi dan node offline, toggle bunyi
  di toolbar TV. Backend tidak berubah.
- **File:** `frontend/src/features/notifications/*`, `features/live/{LiveWall,LiveTvPage,useInView}.tsx`,
  `app/{AppShell,i18n}.tsx`, `app/theme.scss`, `main.tsx`, `api/events.ts`, `__tests__/event-alerts.test.tsx`.
- **Bukti:** frontend **202 passed**, build 0, lint set pasangan rule+file lama (+3 warning
  `react/only-export-components` di file provider saja); bukti visual Chromium `docs/evidence/2026-09-29-notif-*.png`
  (`/dashboard` lonceng + panel 1440 & 390 px, `/live` outline + chip, `/live/tv` chip non-interaktif; `scrollWidth`
  = lebar viewport di semua kasus, chip/panel terverifikasi pada koordinat kanan bawah/atas).
- **Review independen:** `8f1d746..9dd8c7c` — 6/6 fokus PASS; temuan valid diperbaiki di `b83349b`
  (lonceng dibuka sebelum riwayat selesai menyimpan penanda dibaca `0` palsu → badge `20+`; riwayat gagal → event
  basi dihitung belum dibaca; `asNotifyEvent` menerima tipe warisan `Object.prototype`). Ditolak dengan bukti:
  kontrol keyboard di badan toast (Carbon `useNoInteractiveChildren` melempar error di dev) dan aturan basi
  diterapkan tanpa syarat (akan mematikan notifikasi klien yang jamnya beda > 60 s dari server).
- **Dampak:** polling `/events` bertambah satu per tab (5 s) + satu koneksi WS per tab; tanpa migrasi, tanpa
  dependensi baru.
- **Rollback:** `git revert` rentang `8385d61..b83349b` + build frontend; key localStorage
  `isentinel_notif_seen` / `isentinel_notif_mute` diabaikan kode lama.
- **Revisi uji user (tab Hari ini / Kemarin):** panel lonceng dibagi dua tab Carbon **Hari ini (N)** / **Kemarin (N)**,
  hanya event sejak 00:00 kemarin (waktu lokal; event lebih lama dibuang, juga saat hari berganti); badge sampai
  `99+`; riwayat dimuat `?since=<00:00 kemarin>&type=<6 jenis pemicu>&limit=200`. Backend: `GET /api/v1/events`
  menerima `type` berulang (filter `IN`, `?type=x` lama tetap sama). File: `backend/app/api/events.py`,
  `backend/tests/test_events_api.py`, `frontend/src/api/events.ts`, `features/notifications/{EventAlertsProvider,
  NotificationBell,labels}`, `app/{i18n.tsx,theme.scss}`, `__tests__/event-alerts.test.tsx`. Bukti: backend 491,
  frontend 203, build 0, lint set sama. Deploy: restart `isentinel-api` (filter multi-type) + HMR frontend.
- **Deploy & verifikasi user (2026-09-29):** server `gspe-ai3` @ `d5dcf66` (14:45, HMR frontend) lalu `981897e`
  (15:04, restart `isentinel-api`). User menguji lonceng, toast, bunyi/mute, outline tile + chip Live View/TV, dan tab
  Hari ini/Kemarin: **sesuai**. Merge ke `main`.

### Event wajib bermedia (2026-09-29)

- **Event tanpa media dihapus**: sweep retensi menghapus baris event + alert bila media terakhirnya (clip,
  snapshot, crop) habis oleh retensi — juga event lama ber-`media_expired` tanpa path (sisa retensi versi
  sebelumnya); `events_deleted` di hasil sweep/dry run & tab Storage. Mode cleanup "Media absensi saja" ikut
  menghapus entri Inbox absensi (rekap `attendance_day` & riwayat `attendance_event` tetap). Log `system`
  dikecualikan; event baru yang medianya belum datang tidak tersentuh (butuh `media_expired`).
- **Behavior wajib Snapshot/Clip**: backend 422 bila behavior `snapshot` & `clip` sama-sama `false` (attendance:
  `snapshot` `false` → 422); Zona Deteksi menampilkan peringatan merah per behavior dan menonaktifkan Simpan.
- Tes lama retensi/cleanup diperbarui ke semantik baru (event kedaluwarsa kini terhapus). Backend **488 passed**,
  frontend **182 passed**, build 0, lint set sama.
- **Fix uji user — clip absensi lama**: 35/36 event absensi (15–22 Sep, pipeline sebelum face worker) punya clip yang
  disembunyikan UI Events → cleanup "Media absensi saja" & retensi melewatkannya, card tetap muncul. Media absensi
  kini mencakup clip (cleanup media + retensi `attendance_days` untuk clip event absensi); event lama yang hanya
  tersisa clip ikut terhapus. Tes: clip lama + event yang sudah dikosongkan build lama. Backend **490 passed**,
  frontend **182 passed**, build 0.
- **Deploy + verifikasi user (2026-09-29)**: server di `16e8396`, restart isentinel-api (tanpa migrasi). Uji user OK:
  cleanup "Media absensi saja" 1–23 Sep menghapus clip lama + entri Inbox absensi, rekap/export utuh; peringatan
  behavior tanpa media + Simpan diblokir. Rollback: `git revert -m 1 <merge>` + restart API (event yang sudah
  terhapus tidak kembali).

### Cleanup media absensi per tanggal (2026-09-29)

- **Mode "Media absensi saja"** di Bersihkan event (`POST /storage/cleanup` `mode: "attendance_media"`): hapus foto +
  crop wajah event absensi di rentang tanggal lokal (filter kamera opsional; `types` → 422), null-kan
  `event.snapshot_path`, `payload.crop_path`, `attendance_event.snapshot_path`, `media_expired=True`; event,
  riwayat masuk/keluar, dan rekap `attendance_day` tetap; file yang juga dirujuk di luar rentang dipertahankan;
  path dulu lalu file (gagal hapus → orphan sweep). UI: pilihan "Yang dibersihkan", Jenis disembunyikan pada mode
  media, pratinjau basi saat mode berganti, teks konfirmasi "Rekap dan riwayat absensi tidak berubah".
- **Fix**: sweep retensi ikut null-kan `attendance_event.snapshot_path` (salinan path crop) saat crop dihapus.
- Backend **484 passed**, frontend **181 passed**, build 0, lint set sama. Log audit cleanup kini mencatat `mode=`.
- **Deploy + verifikasi user (2026-09-29)**: server di `1745f26`, restart isentinel-api; uji user OK (media absensi
  terhapus, event/rekap/export utuh, mode event behavior tetap). Rollback: `git revert -m 1 <merge>` + restart API.

### Retention & Storage UI (2026-09-29)

- **Pengaturan storage editable**: setting `storage` (`clip_days`, `snapshot_days`, `disk_alert_percent`; field yang
  belum disimpan ikut `RETENTION_DAYS`/85 %), `GET/PUT /storage/settings` (PUT admin, 1–3650 hari, 50–99 %),
  `/storage/stats` memuat `settings` + `disk_alert`. Backend **453 passed**.
- **Sweep retensi terpisah**: clip memakai `clip_days`, snapshot/crops memakai `snapshot_days` (juga orphan);
  event yang clip-nya sudah kedaluwarsa tetap diproses saat snapshot-nya kedaluwarsa; dry run menghitung clip
  bersama sekali; hasil sweep mencatat `clip_days`/`snapshot_days`. Backend **456 passed**.
- **Cleanup event per tanggal**: `POST /storage/cleanup` (admin, dry run default) menghapus event non-attendance +
  clip/snapshot + alert-nya pada rentang tanggal lokal (filter kamera/jenis opsional); attendance tidak pernah
  dihapus walau diminta; clip bersama dengan event di luar rentang dipertahankan; validasi tanggal/jenis 422;
  cleanup nyata dicatat di log dengan username admin. Backend **463 passed**.
- **Peringatan disk hampir penuh**: `disk_alert.check` (ambang dari pengaturan; Telegram sekali, ulang ≤ 1×/24 jam,
  "pulih" saat < ambang − 2 %; tanpa Telegram state tetap disimpan) + thread `DiskAlertMonitor` tiap 10 menit di
  lifespan API. Backend **467 passed**.
- **UI pengaturan retensi + banner disk**: kartu Pengaturan retensi (clip/snapshot/ambang, admin simpan, viewer
  hanya-baca, pesan 422), tile "Clip N hari · Snapshot M hari", banner "Disk hampir penuh" di Storage & Dashboard.
  Frontend **176 passed**, build 0, lint set sama. Bukti: `docs/evidence/2026-09-29-storage-settings-{1440,390}.png`,
  `2026-09-29-dashboard-disk-alert.png` (390 px tanpa overflow).
- **UI Bersihkan event**: rentang tanggal (maks hari ini), kamera & jenis opsional (tanpa attendance) → Pratinjau
  "N event · M file · X" → Hapus dengan konfirmasi merah; tombol Hapus nonaktif sampai pratinjau untuk filter yang
  sama. Frontend **179 passed**, build 0, lint set sama. Bukti:
  `docs/evidence/2026-09-29-storage-cleanup-{1440,390}.png`, `2026-09-29-storage-cleanup-confirm.png`.
- **Perbaikan review independen** (1 Important + 9 Minor): `cleanup` menghapus baris event/alert lebih dulu
  (satu transaksi) lalu file — kegagalan hapus file dicatat dan sisanya disapu orphan sweep; `IN (...)` dipecah
  per 5000 id; log audit juga ditulis saat gagal; `system` (node offline/LWT) ikut dilindungi dan `types` dibatasi
  ke jenis behavior (422 di luar itu); nilai retensi dari DB divalidasi ulang (rusak/0 → env/default + peringatan);
  `DiskAlertMonitor.start()` tidak bisa menggandakan loop; StoragePage tetap jalan dengan API lama (tanpa
  `settings`). Backend **475 passed**, frontend **179 passed**, build 0, lint set sama.
- **Dokumentasi**: README bagian Retensi & Storage (retensi editable clip/snapshot, cleanup per tanggal dengan
  `attendance` + `system` terlindungi, crop lewat orphan sweep, alert disk + Telegram), runbook
  `docs/runbooks/storage-retention.md` (ubah retensi, cleanup aman, tanggap alert disk, verifikasi, rollback),
  ROADMAP baris RS. Suite akhir: backend **475 passed**, vision **223 passed (3 deselected)**, frontend
  **179 passed**, build 0, lint set sama. Review independen: 4/4 fokus PASS, 1 Important + 9 Minor diperbaiki.
- **Feedback user — retensi media absensi sendiri**: `attendance_days` (default `RETENTION_DAYS`, 1–3650) untuk
  snapshot + crop wajah event absensi, terpisah dari snapshot behavior; crop (`payload.crop_path`) kini dirujuk
  resmi → dihapus lapis 1 dan path di-null-kan (Inbox tanpa gambar rusak), `crops/` orphan ikut `attendance_days`;
  baris absensi, rekap, dan `faces/` tetap tidak disentuh. UI: field "Retensi media absensi (hari)", tile
  "Clip · Snapshot · Absensi", hint cleanup diperjelas. Backend **479 passed**, frontend **179 passed**, build 0,
  lint set sama. Catatan: `liveview.test.tsx` "tile di luar layar…" sekali gagal di suite penuh lalu lulus 3×
  berturut (flaky, di luar perubahan ini).
- **Feedback user — log sistem bisa dibersihkan bila dipilih**: jenis `system` (event node offline/LWT, satu baris
  tiap vision-node restart) kini boleh di filter Jenis ("Log sistem (node offline)"); filter Jenis kosong tetap
  tidak menyentuhnya; `attendance` tetap tidak pernah. Backend **480 passed**, frontend **180 passed**,
  build 0, lint set sama. Penghapusan data uji absensi = siklus berikutnya (desain terpisah, menyentuh rekap).
- **Deploy + verifikasi user (2026-09-29)**: server `gspe-ai3` di `592691d`, restart isentinel-api (tanpa migrasi).
  Uji user OK: pengaturan retensi clip/snapshot/absensi, dry run & sweep, cleanup per tanggal (pratinjau →
  konfirmasi; absensi utuh), log sistem opsional, banner + Telegram disk. Rollback: `git revert -m 1 <merge>` +
  restart API (setting `storage`/`disk_alert_state` diabaikan kode lama; event yang sudah dibersihkan tidak kembali).

### User management (2026-09-28)

- **Migrasi `0018_user_status`**: `user.is_active` (default true), `user.token_version` (default 0),
  `user.last_login_at`; downgrade lewat batch. Backend **436 passed**. Rollback: `alembic downgrade 0017`.
- **Pencabutan sesi**: JWT membawa klaim `tv` (`token_version`); `get_current_user` menolak akun nonaktif dan versi
  token lama (termasuk sesi bergulir); token tanpa `tv` = versi 0 (tanpa logout massal saat deploy). Login akun
  nonaktif → 403 `account disabled` hanya bila password benar; `last_login_at` terisi. Backend **441 passed**.
- **API user ketat**: `UserPatch` (`extra="forbid"`, role `admin|viewer`), password ≥ 8 / ≤ 72 byte, username
  `[A-Za-z0-9._-]{3,64}`; reset password & nonaktif menaikkan `token_version`; admin tidak bisa mengubah role,
  menonaktifkan, atau menghapus akun sendiri; pengaman admin aktif terakhir. Backend **445 passed**.
- **Ganti password sendiri**: `POST /auth/change-password` (semua role); password lama salah → 400 dan dihitung ke
  batas percobaan login (429); sukses menaikkan `token_version` (perangkat lain keluar) dan menulis cookie baru
  (browser ini tetap login, menang atas cookie perpanjangan). Backend **448 passed**.
- **Tab User (Konfigurasi)**: tabel username/role/status/dibuat/login terakhir + aksi (jadikan admin/viewer, reset
  password, nonaktifkan dengan konfirmasi, aktifkan, hapus); akun sendiri ditandai "(Anda)" dan aksi berbahayanya
  nonaktif; modal tambah user dengan validasi klien = backend; pesan 409 server dipetakan ke teks. Frontend
  **165 passed**, build 0, lint set sama.
- **Ganti password sendiri (UI) + login nonaktif**: tombol "Ganti password" di kartu akun sidebar (semua role) →
  modal lama/baru/konfirmasi, pesan password lama salah/terkunci, notifikasi sukses; login akun nonaktif
  menampilkan "Akun dinonaktifkan — hubungi admin". Frontend **169 passed**, build 0, lint set sama.
- **Dokumentasi**: README bagian User management (role, nonaktif/aktif, reset, ganti sendiri, aturan
  password, pencabutan sesi); runbook TV: akun TV = viewer + perangkat hilang; ROADMAP baris UM.
  Suite akhir: backend **448 passed**, vision **223 passed (3 deselected)**, frontend **169 passed**,
  build 0, lint set sama.
- **Review perencana — WebSocket ikut pencabutan sesi**: `/api/v1/ws/events` dulu hanya memeriksa tanda tangan
  JWT, jadi token akun nonaktif / versi lama masih bisa berlangganan event realtime (nama karyawan, deteksi).
  Helper `session_user` (deps) kini dipakai REST dan WS; handshake ditolak 1008. Tes merah sebelum fix.
  Backend **449 passed**, vision **223**, frontend **169**, build 0.
- **Feedback uji user**: ganti password sendiri **khusus admin** (`POST /auth/change-password` →
  `require_admin`, viewer 403; tombol sidebar hanya untuk admin) — password viewer/akun TV diatur admin lewat
  reset; halaman login memakai `PasswordInput` (tampilkan/sembunyikan password, label i18n). Backend
  **450 passed**, frontend **171 passed**, build 0, lint set sama. Rollback: revert commit + restart API.
- **Deploy + verifikasi user (2026-09-28)**: server `gspe-ai3` di `64f68b4`, alembic `0017 → 0018`, restart
  isentinel-api (health ok). Uji user OK: tambah user, nonaktifkan → sesi viewer keluar + pesan login khusus,
  aktifkan, reset password → sesi lama keluar, ganti password admin tetap login, aksi akun sendiri nonaktif,
  viewer tanpa tombol Password, tampilkan/sembunyikan password di login. Rollback: `git revert -m 1 <merge>` +
  `alembic downgrade 0017` + restart API.

### Live View mode TV (2026-09-28)

- **Sesi bergulir 48 jam**: `get_current_user` menerbitkan cookie baru bila token cookie lewat separuh umur (Bearer
  tidak diubah); default `ACCESS_TOKEN_EXPIRE_MIN` 480 → 2880. Layar TV yang me-refresh Live View tidak logout.
  Backend **435 passed**. Rollback: revert commit + restart API.
- **Pengaturan Live View per layar**: `screenPrefs` (kolom, pilihan kamera `all`/`some`, auto-scroll) disimpan per
  `?screen=` di `localStorage` (`isentinel_live_screen:<nama>`), nilai rusak → default per field, kunci lama
  `isentinel_live_cols` jadi default layar `default`. Frontend **149 passed**.
- **Tile Live View hemat & pulih sendiri**: grid dipisah ke `LiveWall`/`useLiveCameras`; `<video-stream>` hanya
  di-mount untuk tile dekat layar (`IntersectionObserver`, pra-muat 50 % viewport), tile lain snapshot terakhir;
  snapshot tampil sampai video `playing`; tile gagal stream dicoba ulang tiap 60 s (dulu snapshot selamanya; efek
  stream kini `[streaming, ws]`). Frontend **151 passed**, build 0, lint set rule+file sama.
- **Pemilih kamera Live View**: dropdown lokasi diganti checkbox per kamera dikelompokkan per lokasi (grup
  indeterminate, Semua/Kosongkan, "Kamera (n/m)"); disimpan di layar `default`; pilihan kosong → pesan + tombol
  pemilih. Frontend **153 passed**, build 0, lint set rule+file sama.
- **Auto-scroll + idle**: `stepScroll` (turun px/s dengan posisi pecahan, jeda 5 s di dasar, kembali ke atas, jeda
  5 s; konten muat → diam; frame tertunda dibatasi 100 ms), `useAutoScroll` (rAF di dokumen, sinkron ulang setelah
  jeda), `useIdle`. Frontend **157 passed**, build 0, lint set rule+file sama.
- **Mode TV (kiosk)**: route `/live/tv?screen=<nama>` di luar AppShell; toolbar auto-hide 4 s (kursor ikut hilang):
  kolom, pemilih kamera, gulir otomatis + kecepatan, keluar; auto-scroll jeda saat operator aktif (lanjut 10 s),
  pemilih/debugger terbuka; teks tile membesar di 2K/4K; tombol **Mode TV** di Live View (fullscreen bila
  diizinkan). Frontend **161 passed**, build 0, lint set sama. Cek visual CDP Chrome headless (stub API):
  `/live/tv?screen=A` 1920×1080/2560×1440/3840×2160 = 3 kolom, 1080×1920 = 2 kolom, semua tanpa overflow
  horizontal; `/live` 390×844 `scrollWidth=390`.
- **Dokumen + suite penuh**: runbook `docs/runbooks/live-view-tv-pi.md` (Chromium kiosk 2 monitor, autostart,
  operasional, rollback), README §Live View & Mode TV, ROADMAP baris **TV** `[~]`. Suite akhir: backend
  **435 passed** (baseline 432), vision **223 passed, 3 deselected** (baseline 223), frontend **161 passed**
  (baseline 142), build 0, lint set rule+file lama (1 warning pindah file: `set-state-in-effect`
  `LiveViewPage.tsx` → `useLiveCameras.ts`, kode sama ikut refactor Task 3).
- **Review perencana — snapshot segar saat tile masuk layar lagi**: tile yang kembali terlihat (auto-scroll ke atas)
  dulu menampilkan snapshot dari cache browser sejak halaman dibuka (bisa berjam-jam) selama stream menyambung;
  kini `_t` dinaikkan saat masuk layar → snapshot baru. Tes IO diperluas (merah sebelum fix). Frontend
  **161 passed**, backend **435**, vision **223** (3 deselected), build 0, lint set sama.
- **Deploy + verifikasi user (2026-09-28)**: server `gspe-ai3` di `762bde7`, restart isentinel-api (health ok,
  `.env` tanpa `ACCESS_TOKEN_EXPIRE_MIN` → 2880 berlaku). Uji user di browser desktop OK: pemilih kamera, mode TV
  kiosk + toolbar auto-hide, auto-scroll, dua layar `?screen=A/B`, pulih setelah offline, stream hanya tile terlihat.
  Uji Raspberry Pi 2 monitor menunggu server production (runbook `docs/runbooks/live-view-tv-pi.md`). Rollback:
  `git revert -m 1 <merge>` + restart API.

### Behavior Idle Zone + Crowd (2026-09-28)

- **Fix jadwal zona**: frame live membawa ts monotonic, tetapi jadwal intrusion membacanya sebagai epoch (hari/jam
  dari 1970 + uptime) → jadwal intrusion salah di produksi (belum berdampak: 0 zona berjadwal). Helper bersama
  `analyzers/base.py`: `wall_time`, `schedule_active`, `persons_in_zone` (+ `point_in_polygon`/`ground_point` dipindah,
  tetap di-re-export dari `intrusion`). Vision **209 passed**.
- **Analyzer Idle Zone + Crowd**: idle = zona kosong ≥ `trigger_seconds` dalam jadwal → event + pengingat tiap
  `reminder_minutes` (0 = sekali), siaga lagi saat ada orang; crowd = ≥ `min_count` orang ≥ `trigger_seconds`,
  toleransi turun sesaat 2 s, pengingat sama. Event tanpa track didukung node (`bbox_norm` None, dedup key per
  pengingat `r<n>`). Vision **218 passed**.
- **Snapshot idle/crowd**: crowd menggambar semua kotak orang + label `CROWD (n)`; idle menggambar garis poligon zona
  + label `IDLE ZONE`. Vision **219 passed**.

- **Backend idle/crowd + jadwal ikut shift**: kind `idle_zone`/`crowd` (crowd wajib `min_count` ≥ 1,
  `reminder_minutes` ≥ 0); `schedule` boleh `{"shift_id": N}` (shift tak ada → 422), di-resolve ke
  `{days, start, end}` saat config push (shift hilang → `null` + warning); ubah shift → push ulang kamera terkait;
  hapus shift yang dipakai zona → 409 dengan nama zona. Backend **429 passed**.
- **Caption idle/crowd**: judul `IDLE ZONE` / `CROWD`, baris `Kosong: n menit` / `Jumlah: n orang (min m)`,
  pengingat ditandai `(pengingat ke-n)`. Backend **430 passed**.
- **Zona Deteksi**: baris **Zona kosong (Idle)** (kosong selama, pengingat; clip default off) dan **Kerumunan
  (Crowd)** (minimal orang, selama, pengingat); jadwal **Ikut shift** (`{shift_id}`) di samping 24/7 dan jam manual.
  Frontend **142 passed**, build 0, lint set rule+file sama.
- **Review regresi behavior**: dedup event tanpa track dibedakan per zona + pengingat; snapshot idle mengambil frame
  kosong terbaru; crowd me-reset bila jumlah pulih setelah jeda > 2 s; parameter yang absen memakai default
  idle/crowd; pengingat Telegram berkala tidak ditahan rate-limit 2 menit; ingest internal menerima kedua tipe.
  Backend **432 passed**, vision **223 passed** (3 deselected).
- **Dokumen + verifikasi akhir**: README menjelaskan parameter, pengingat, jadwal ikut shift dan batas shift malam;
  ROADMAP menandai lokal selesai, deploy serta uji lapangan tertunda. Suite akhir: backend **432 passed**
  (baseline 423), vision **223 passed, 3 deselected** (baseline 205), frontend **142 passed**
  (baseline 140), build 0, lint set rule+file lama; Zona Deteksi 390 px overflow 0 (lima behavior).
- **Review perencana — toleransi crowd 5 s**: kerumunan diam hanya diinferensi tiap ~2 s (frame paksa motion gate);
  satu deteksi meleset + jitter > 2 s dulu me-reset durasi dan menunda alert. `GRACE_S` 2 → 5 s (> 2× force
  interval); tes jitter (merah di 2 s) + tes reset disesuaikan. Vision **223 passed** (3 deselected).
  Rollback: `git revert` commit ini + restart vision-node.
- **Deploy + verifikasi lapangan (2026-09-28)**: server `gspe-ai3` di `127b779`, restart isentinel-api + vision-node
  (health ok, TZ server WIB, tanpa migrasi). Uji user OK: Idle (alert + pengingat, siaga saat orang masuk), Crowd
  (alert, snapshot semua kotak `CROWD (n)`), caption Telegram, jadwal ikut shift. Rollback: `git revert -m 1 <merge>`
  + restart kedua service; ubah/hapus behavior `idle_zone`/`crowd` dan `schedule.shift_id` sebelum kembali ke kode lama.

### Fix geometri zona (2026-09-28)

- **Koordinat zona = frame penuh**: editor Zona Deteksi dan tile/modal Live View memakai `object-fit: fill` (dulu
  `cover` di kotak 16:9). Substream NVR 640×480 adalah frame 16:9 anamorfik (dibuktikan: sub direntang 16:9 = main
  1920×1080, OSD sejajar); `cover` memotong 12,5 % atas-bawah sehingga titik zona tersimpan relatif ke tampilan
  terpotong sementara vision memakainya sebagai frame penuh → zona di deteksi bergeser dan overlay debugger tampak
  tidak sesuai. Migrasi data `0017_zone_full_frame` memetakan polygon lama ke frame penuh per rasio probe kamera
  (4:3 → `y' = 0,125 + 0,75·y`; 16:9 tetap; probe tak diketahui dilewati; downgrade = kebalikan), dites di tabel
  nyata lewat konteks Alembic. Backend **423**, vision 205, frontend **140** passed, build 0, lint set sama.
- **Deploy + verifikasi (2026-09-28 09:27)**: `alembic 0016→0017` di gspe-ai3 (zona 15/14/6 dikonversi, zona 12
  16:9 tetap; cadangan poligon lama di `temp/zones-before-0017.json`), restart API, vision menerima config baru.
  **Cek visual user OK**: editor tidak lagi melar, overlay debugger Live View sama persis dengan editor.

### Integrasi bot Telegram (2026-09-25)

- **`services/telegram.py`**: klien stdlib (getMe, getUpdates → daftar grup unik, sendPhoto multipart,
  sendMessage, retry 3× backoff), token di `secret_store` (fallback env), grup = satu baris aktif
  `telegram_chat`, URL aplikasi di `setting`; caption (behavior, absensi tercatat, wajah tidak dikenal, fallback
  tipe baru, ≤ 1024); token tidak pernah masuk pesan error. Tes memakai file rahasia terisolasi. Backend **381 passed**.
- **Gerbang alert baru**: toggle `telegram` per behavior (fallback `zone.telegram`, default off; berlaku untuk tipe
  apa pun), `ALERT_MIN_SEVERITY` bukan gerbang lagi; attendance hanya `matched` (tanpa rate-limit) dan wajah tidak
  dikenal (`alert.type = attendance_unknown`, rate-limit sendiri); `handle` tanpa I/O jaringan → status `queued` +
  antrean dispatcher. Consumer memproses attendance sebelum alert. Fix `GET /alerts` 500 (`camera_id` null).
  Backend **388 passed**.
- **Dispatcher alert**: thread di proses API (start/stop di `lifespan`) mengambil antrean, menunggu snapshot ±5 s
  (10 × 0,5 s), kirim `sendPhoto` dari `storage_root` atau teks bila snapshot tidak datang / file hilang; hasil
  `sent` / `failed` (+ pesan Telegram) / `not_configured` di baris alert. Backend **395 passed**.
- **API Telegram**: `GET/PUT /telegram/settings` (token write-only, validasi format + `getMe`, 422 tanpa gema token;
  grup; URL aplikasi; alert terakhir), `POST /telegram/discover` (grup dari `getUpdates`, 409/502),
  `POST /telegram/test` (1 percobaan). Admin saja; `/status` tetap. Backend **404 passed**.
- **Tab Notifikasi**: token bot (write-only, "Token tersimpan ✓" + Ganti), Deteksi grup → pilih → simpan, URL
  aplikasi (default alamat browser), Kirim pesan uji, status alert terakhir. Frontend **129 passed**.
- **Zona Deteksi + Inbox**: toggle **Telegram** per behavior (default off, di samping Snapshot/Clip) dan satu toggle
  pada zona absensi; toggle level zona "tersedia di Fase 3" dihapus. Inbox mendukung `?event=<id>` (tautan caption)
  dan status alert `queued` ("MENGIRIM…"). Frontend **132 passed**.
- **Dokumen**: README §Alert Telegram (sambungkan bot @BotFather → grup → tab Notifikasi →
  toggle per behavior; snapshot keluar LAN, tautan klip LAN-saja, token di `CAMERA_SECRETS_FILE`),
  ROADMAP baris **TG** `[~] lokal selesai, PENDING deploy + verifikasi`, `.env.example`
  (`TELEGRAM_BOT_TOKEN` = fallback, `ALERT_MIN_SEVERITY` deprecated) — tanpa perubahan kode.
- **Fix review: dispatcher stop instan + pemulihan saat restart**: `stop()` membangunkan worker lewat sinyal di
  antrean (dulu menunggu `get(timeout=0.5)` → setiap shutdown API dan setiap teardown TestClient tertahan; suite
  backend 164 s → 90 s); startup API mengantre ulang alert `queued` ≤ 10 menit dan menandai yang lebih tua `failed`
  "interrupted by restart" (dulu chip "MENGIRIM…" menggantung selamanya). Backend **406 passed**.
- **Fix review: tautan Telegram selamat melewati login**: 401 mengarahkan ke `/login?next=<path asal>` dan login
  kembali ke `next` (hanya path internal; `//host`, `/\\host`, URL absolut → `/dashboard`). Dulu petugas yang membuka
  tautan event dari HP tanpa sesi berakhir di dashboard. Frontend **137 passed**, build 0, lint set sama.
- **Deploy + verifikasi (2026-09-25)**: `00899ee` di gspe-ai3, restart `isentinel-api` saja (vision tidak berubah);
  `GET /alerts` 200 (bug 500 tertutup). User membuat bot + grup, menghubungkan lewat tab Notifikasi; **E2E user OK**:
  pesan uji, intrusion cam 357 (15:12, 15:24) dan absensi tercatat cam 365 (15:20) masuk grup sebagai foto + caption
  (alert `sent`, keputusan 0,0–2,8 s setelah event). Token **0×** di log API, `camera-secrets.json` `-rw-------`,
  0 error dispatcher. Rate-limit belum teramati di lapangan (tertutup tes unit). Tanpa screenshot (uji oleh user).
- **Feedback F1: rate-limit Telegram per orang**: kunci kamera + zona + tipe + `track_id`;
  severity critical tanpa batas, lainnya 2 menit, absensi tercatat tetap tanpa batas.
  Kolom `zone.rate_limit_min` tetap ada tetapi deprecated. Backend **409 passed**;
  rollback: revert perubahan ini lalu restart API.
- **Feedback F2: caption rapi**: judul tebal berbahasa Inggris (`INTRUSION`, `ATTENDANCE — CHECK IN/OUT`,
  `UNKNOWN FACE`, tipe baru → huruf besar), satu data per baris (Nama/Kamera/Zona/Waktu/Level), tautan klip di akhir;
  `parse_mode=HTML` dengan escape nilai, panjang tiap nilai dibatasi (tanpa memotong tag). Backend **411 passed**;
  rollback: revert perubahan ini lalu restart API.
- **Feedback F5: label snapshot**: kotak orang di snapshot behavior berlabel jenis kejadian (`INTRUSION`/`LOITERING`/
  `RUNNING`, tipe baru huruf besar) — bukan `ID n`; snapshot absensi diberi nama karyawan (atau `Unknown` oranye
  untuk wajah tak dikenal) oleh backend setelah pencocokan (Pillow, best-effort) → foto Telegram ikut berlabel.
  Pipeline wajah vision tidak berubah. Backend **415**, vision **205** passed;
  rollback: revert perubahan ini lalu restart API **dan** vision-node.
- **Feedback F3/F4**: Inbox menampilkan **nama zona** (zona terhapus → `#id`); Deteksi & Model mengganti tombol Reset
  override dengan tautan **"Atur zona →"** yang membuka Zona Deteksi dengan kamera itu terpilih (`?camera=`).
  Frontend **139 passed**, build 0, lint set sama; rollback: revert perubahan ini.
- **Fix review: snapshot absensi yang datang belakangan tetap berlabel**: pesan media (topik
  `isentinel/events/media`) yang mengisi `snapshot_path` setelah `handle_face_event` kini memicu label ulang
  (`attendance.annotate_event_snapshot` dari payload tersimpan: nama karyawan, atau `Unknown` oranye bila
  `no_match`). Dulu subset absensi dengan snapshot telat terkirim ke Telegram tanpa label (F5 bolong).
  Backend **418 passed** (3 tes regresi); rollback: revert perubahan ini lalu restart API.
- **Dev-deps backend**: `numpy` masuk `[dev]` (dipakai `test_attendance_logic.py`, dulu hanya terbawa lewat paket
  `vision`). Catatan env: venv backend lokal sempat dibangun ulang tool review (`uv`) → editable `vision` hilang;
  dipulihkan `uv pip install -e "vision[dev]"`. Backend 418, vision 205, frontend 139.
- **Deploy + verifikasi refining (2026-09-25 17:24)**: `fce11ae` di gspe-ai3, restart `isentinel-api` + `vision-node`
  (`started 1 worker(s)`, 0 traceback). **E2E user OK**: dua orang satu zona → dua pesan, orang sama ≤ 2 menit →
  rate_limited, format pesan per baris + judul Inggris, label foto (jenis kejadian / nama karyawan), nama zona di Inbox,
  tautan Atur zona. Data alert sejak deploy: intrusion warning 5 sent + 2 rate_limited, loitering 1 sent, attendance
  1 sent; token 0× di log API.

### Zona UX (2026-09-25)

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
- **Fix pesan error zona**: pesan "kamera sudah punya zona absensi aktif dengan arah lain" hanya muncul bila
  backend memang menolak karena konflik arah; 422 lain memakai pesan simpan generik. Frontend **127 passed**.
- **Bersih-bersih**: CSS `.det-chip` yang tak terpakai dibuang dari `theme.scss` (chip analyzer sudah dihapus dari
  halaman Deteksi & Model).
- **Dokumen**: README (aturan "deteksi hanya berjalan di kamera yang punya zona aktif" + chip analyzer tidak
  dipakai), ROADMAP (baris **ZU** + catatan halaman Gate Absensi dihapus), dan runbook `attendance-face-first`
  disinkronkan — tanpa perubahan kode.
- **Fix review M1: Status AI jujur**: kolom menghitung hanya zona yang benar-benar dijalankan vision — zona visual
  (behaviors kosong) dan gate absensi tanpa arah tidak dihitung (dulu tertulis "Aktif" walau tanpa worker). Tes
  diperluas dulu (merah). + 2 tes backend jalur PATCH konflik arah (ubah tipe ke absensi, ubah arah gate aktif).
  Backend **370**, frontend **127** passed, build 0, lint set sama.
- **Deploy + verifikasi (2026-09-25)**: `5d785a6` di gspe-ai3, restart `isentinel-api` lalu `vision-node` (tanpa
  migrasi). Vision `started 7 worker(s)` → **1 worker** (cam 363, zona 15 kini jalan walau chip lama
  `['attendance']`); CPU proses vision **70,7 % → ~5 %** (±6 menit setelah start), RSS **3,43 → 1,53 GB**, memori
  GPU1 924 → 436 MiB; ring clip cam363 aktif, 0 error log. **E2E user OK**: tab Gate hilang (`?tab=gates` →
  Kamera), event intrusion cam 363, Clip off per behavior, Status AI, konflik arah absensi, 390 px. Tanpa
  screenshot evidence (uji dilakukan user).

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
