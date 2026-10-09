# Runbook — Attendance (absensi)

Halaman **Attendance** (`/attendance`) menampilkan rekap harian (tab Harian / Rentang
tanggal / Per karyawan) dan mendukung koreksi manual oleh admin.

## Status dan batas hari

| Status | Kondisi | Durasi |
|---|---|---|
| `ontime` / `late` | entry + exit terdeteksi | exit − entry |
| `waiting` (**Di dalam**) | entry tanpa exit, belum lewat batas (atau karyawan tanpa shift) | `null` — UI menghitung live untuk hari ini |
| `no_exit` (**Tanpa exit — perlu koreksi**) | entry tanpa exit setelah batas | `null` |
| `no_entry` (**Tanpa entry — perlu koreksi**) | hanya exit terdeteksi | `null` |
| `absent` (**Tidak hadir**) | karyawan aktif ber-shift, hari kerja, tanpa deteksi, setelah batas | `null` |

- **Batas** = `tanggal + shift.end_time + NO_EXIT_GRACE_MIN` (default 60 menit, tz server/WIB).
- Karyawan **tanpa shift** tidak pernah otomatis `absent`/`no_exit` — entry tanpa exit
  tetap "Di dalam".
- List API dan CSV menampilkan **status efektif**: `waiting` yang sudah lewat batas
  langsung tampil `no_exit` walau job belum jalan; baris ber-`override_note` tidak diubah.

### Peringatan "Exit awal"

- Baris `ontime`/`late` yang `last_exit`-nya lebih dari **60 menit** sebelum `shift.end_time`
  pada tanggal baris (ambang `EXIT_EARLY_MIN`, dihitung saat API membaca — sama seperti pola
  status efektif) menampilkan chip **Exit awal** di kolom exit dan angka menitnya pada kolom
  terakhir CSV `exit_early_min`. Status, durasi, dan tile ringkasan tidak berubah: ini tanda
  untuk diperiksa, bukan status baru.
- `last_exit` adalah exit **terakhir** hari itu (exit boleh berulang, yang tercatat tetap yang
  paling akhir). Chip karena itu berarti salah satu dari dua hal, dan sistem tidak bisa
  membedakan keduanya: karyawan memang pulang awal, **atau** exit sore tidak terdeteksi
  (kamera exit terlewat, orang lewat pintu lain) sehingga yang tersisa exit makan siang.
- Menindaklanjuti: cek Inbox untuk event `attendance` arah `exit` milik karyawan pada hari itu.
  Exit sore yang tidak terdeteksi → koreksi jam keluarnya; pulang awal yang sah → cukup isi
  catatan. Keduanya lewat **Koreksi** di bawah (tombol Koreksi tampil di sel status baris berperingatan; admin juga bisa mengklik barisnya).
- Peringatan tidak muncul bila `override_note` terisi (termasuk `import`), status bukan
  `ontime`/`late`, karyawan tanpa shift, `last_exit` kosong, atau jam shift pada tanggal baris
  belum lewat saat dibaca — exit makan siang di hari berjalan tidak ikut ditandai.

## Penutupan hari otomatis (`AttendanceCloser`)

- Thread latar di proses API: `close_due` tiap **15 menit** (`CLOSE_INTERVAL_S = 900`),
  **run pertama segera saat start** (catch-up **7 hari ke belakang**, `CLOSE_DAYS_BACK`).
- Untuk tiap tanggal `[hari ini − 7 hari, hari ini]` dan tiap karyawan **aktif** dengan
  shift yang menjadwalkan hari itu: bila sudah lewat batas — buat baris bila belum ada
  (hasil `absent` bila tanpa event), atau hitung ulang `waiting` → `no_exit`.
- **Baris yang dikoreksi manual (`override_note` non-kosong) tidak pernah disentuh** oleh
  job ini, oleh `effective_status`, maupun oleh `close_days`.
- Exception (mis. DB sibuk) dicatat di log (`attendance close failed`); thread tetap jalan
  dan mencoba lagi interval berikutnya. Stop rapi saat API shutdown.

**Dampak deploy pertama:** saat API start setelah deploy, catch-up membuat baris
`absent` untuk hari kerja tertinggal sampai 7 hari ke belakang (untuk karyawan aktif
ber-shift yang belum punya baris) dan menutup `waiting` yang sudah lewat batas. Ini
idempoten — start ulang tidak menduplikasi baris.

### Operasional

- **Log:** `journalctl -u isentinel-api -f | grep -i "attendance close"`.
- **Jalankan manual satu hari** (internal): `POST /internal/maintenance/close-days`
  header `Authorization: Bearer $NODE_API_KEY`, body `{"date": "YYYY-MM-DD"}` —
  default kemarin bila body kosong. `close_days` juga melewati baris ber-`override_note`.
- **Restart API** (tanpa passwordless sudo): `kill $(cat /sys/fs/cgroup/system.slice/isentinel-api.service/cgroup.procs)` —
  unit `Restart=always` menjalankan ulang; catch-up 7 hari berjalan otomatis.

## Koreksi manual

1. Buka `/attendance`, klik baris (admin) atau tombol **Koreksi** pada baris
   "Tanpa exit/entry — perlu koreksi".
2. Isi status, jam masuk/keluar bila perlu, dan **catatan (wajib)** → Simpan.
3. `PATCH /api/v1/attendance/{id}` hanya menerima status
   `{ontime, late, waiting, no_exit, no_entry, absent}`; tanpa catatan → 422.
4. Baris hasil koreksi (dan baris hasil import CSV — `override_note='import'`) tidak
   ditimpa job penutupan. Event absensi **baru** untuk hari itu tetap menghitung ulang
   baris (perilaku lama; koreksi yang perlu dipertahankan harus diinput ulang setelahnya).
5. Catatan apa pun juga menghapus chip **Exit awal** pada baris itu — di daftar maupun CSV —
   karena nilainya sudah diputuskan manusia.

## Import/export CSV

- Export (`/api/v1/attendance/rekap.csv`): status **efektif**, urutan kronologis menaik.
- Kolom terakhir `exit_early_min` (menit antara exit terakhir dan jam shift selesai, kosong bila
  tidak berlaku). Import membaca per nama kolom dan mengabaikan kolom tak dikenal, jadi CSV lama
  tanpa kolom ini maupun CSV hasil ekspor baru sama-sama diterima; nilai `exit_early_min` tidak
  pernah ditulis ke database.
- Import: upsert per `(employee_code, date)`; `first_entry` kosong + `last_exit` terisi
  → status `no_entry`; `override_note` di-set `import` sehingga baris tidak ditimpa job.

## Gerbang wajah (face-first)

### Zona attendance

Zona attendance digambar di **area kepala** pada frame utama, bukan lantai. Buat
zona cukup lebar agar wajah yang berjalan berada di dalamnya **≥1 detik**
(sekitar 5 frame pada `ai_fps=5`). Pemicu tetap pusat bbox wajah di polygon;
deteksi/tracking memakai seluruh frame, tanpa ROI crop. Arah `entry`/`exit`
tetap wajib, termasuk saat **Catat absensi OFF**; zona tanpa arah diabaikan worker.

**Catat absensi** dan **Kirim wajah tidak dikenal** adalah flag behavior attendance
(`record`, `telegram_unknown`, default true). OFF pada pencatatan hanya menerbitkan
evidence `detected` di Inbox/Telegram, tidak membuat riwayat atau rekap absensi.
Dedup per karyawan+zona memakai cooldown default 5 menit; Unknown tidak di-dedup
oleh jalur ini. Saklar Telegram induk tetap menentukan pengiriman; Unknown OFF
hanya menahan alert Unknown, bukan event Inbox.

Telegram membedakan CHECK IN/OUT, SUDAH CHECK IN (jam check in pertama dan exit sejak
itu bila terlihat), serta TERDETEKSI — MASUK/KELUAR. Cooldown tetap diam. SUDAH CHECK IN hanya muncul
saat karyawan tidak terlihat ≥ cooldown (default 5 menit) lalu muncul lagi; orang yang menetap di area
kamera tidak memicu pesan berulang.
Tautan **Lihat event** membuka evidence lengkap.

### Checklist kamera gate

- Shutter **≥1/250** untuk mengurangi blur saat berjalan.
- Gunakan WDR/BLC bila pintu membelakangi cahaya.
- Pasang setinggi mata hingga sedikit di atasnya, dengan sudut wajah tidak menyamping.
- Tempatkan zona **2–4 m sebelum pintu**, dengan waktu wajah di zona ≥1 detik.
- Bila skor cocok kurang, lakukan enrollment dari kamera gate sendiri dengan foto jelas.

### Profil parameter: Kantor dan Industri

Titik awal berbasis praktik umum face recognition untuk akses/absensi, **bukan standar resmi**. Dasarnya:
default kode, angka lapangan `gspe-ai3` (2026-10-07: event sukses berlebar 111–199 px, blur ≥125; kamera
acuan 364 blur 1251–2733), dan rumus kualitas di bawah. Cakupan hanya **Kantor** (dalam ruangan, cahaya
terkendali, tanpa APD) dan **Industri** (pabrik/gudang/bengkel: cahaya tidak merata, APD, getaran, langkah
lebih cepat). Luar ruangan, malam hari, dan lalu lintas padat tidak tercakup. Setiap lokasi tetap wajib
lolos protokol uji penerimaan (di bawah) sebelum angka dianggap final.

**Rumus yang mengikat gerbang node dan API.** API menolak event bila
`kualitas = det_score × min(1, lebar/112) × (1 − yaw)` kurang dari `face_min_quality` (0,5). Frame yang lolos
gerbang node tetapi kualitasnya di bawah 0,5 menjadi event `low_quality` (tampil sebagai "Tidak dikenal",
tanpa absensi). Lebar minimum agar frame lolos kedua gerbang: `≈ 56 / (det_score × (1 − yaw))`.

| `det_score` | yaw 0,05 | yaw 0,20 |
|---|---|---|
| 0,6 | 98 px | 117 px |
| 0,7 | 84 px | 100 px |
| 0,8 | 74 px | 88 px |

Karena itu default `face_min_width_px` 80 dengan `face_min_det_score` 0,6 meloloskan frame yang pasti
ditolak API (contoh nyata: lebar 82 px, skor 0,64 → kualitas 0,45).

**Parameter yang bisa diubah di UI** (Konfigurasi → Deteksi & Model → Advanced → kartu **Pengenalan wajah**;
grup **Bersama** = skor deteksi, yaw, ambang kecocokan; grup **Identitas** = parameter identitas intrusion;
grup **Absensi (lama)** = lebar, blur, jumlah frame. Lalu
**Simpan setelan global**; berlaku untuk **semua kamera** dan seluruh jalur pencocokan, jadi bila satu situs bercampur Kantor dan
Industri, pakai kolom Industri). `ai_fps` per kamera ada di tabel kamera pada halaman yang sama.

| Parameter | Default | Kantor | Industri | Alasan |
|---|---|---|---|---|
| `face_match_threshold` (grup Bersama) | 0,40 | 0,40 | 0,40–0,45 | Dipakai absensi **dan** identitas intrusion; naikkan hanya bila terbukti ada salah-orang |
| `face_min_width_px` | 80 | 100 | 110 | Dari rumus: Kantor skor 0,7 dan yaw ≤0,20 → 100 px; Industri skor 0,65 dan yaw ≤0,20 → 108 px, dibulatkan 110 |
| `face_min_det_score` | 0,6 | 0,7 | 0,65 | Frame ragu hampir selalu `low_quality`; Industri lebih longgar karena bayangan helm menurunkan skor |
| `face_max_yaw` | 0,35 | 0,35 | 0,35 | ±30°; melonggarkan menambah risiko salah-orang, benahi sudut kamera |
| `face_blur_min` | 120 | 120 | 120 | Kamera sesuai checklist menghasilkan jauh di atas 120; jangan turunkan sebelum geometri dan shutter beres |
| `face_min_frames` | 3 | 3 | 3 | Event tetap terbit saat track hilang dengan ≥1 frame bagus; menurunkannya hanya memotong 1–2 frame |
| `ai_fps` (per kamera) | 5 | 5 | 8–10 | Industri: langkah cepat dan getaran perlu lebih banyak kesempatan frame tajam; beban GPU naik |

**Tetap pada default di Docker** (env-only: `FACE_MIN_QUALITY` dan `ATTENDANCE_COOLDOWN_MIN` tidak
diteruskan oleh `docker/compose.yml`, jadi tidak bisa diubah dari UI atau `.env` tanpa mengubah
`docker/compose.yml`): `face_min_quality` 0,5 dan cooldown 5 menit. Ambang kecocokan bukan lagi env-only:
nilai efektifnya dari baris `detector_setting` (kartu **Pengenalan wajah**, grup **Bersama**) dan berlaku pada
event berikutnya; env `FACE_MATCH_THRESHOLD` hanya cadangan bila baris belum ada. Naikkan ambang
ke 0,45 hanya bila terbukti ada salah-orang di lokasi Industri (jumlah karyawan besar,
APD).

**Kamera dan lingkungan:**

| | Kantor | Industri |
|---|---|---|
| Cahaya di wajah | ≥200 lux, tanpa cahaya dari belakang | ≥300 lux; tambah lampu wajah bila perlu; hindari matahari langsung dan bukaan terang di belakang orang |
| Shutter | ≥1/250 | ≥1/500 |
| WDR/BLC | bila pintu kaca | wajib bila ada bukaan terang |
| Tinggi dan sudut | setinggi mata hingga +20 cm, turun ≤15° | setinggi mata (bukan dari atas: brim helm menutupi wajah), turun ≤15° |
| Zona | 2–4 m sebelum pintu, wajah di zona ≥1 detik | sama; pandu jalur (garis lantai) agar orang menghadap kamera |
| APD | tidak berlaku | helm dan kacamata bening boleh selama mata terlihat; masker/respirator, kacamata gelap, dan face shield tidak didukung |
| Enrollment | 3 foto frontal; tambahan dari kamera gate bila skor kurang | 3 foto standar + foto dari kamera gate dengan APD yang dipakai sehari-hari (dengan dan tanpa helm bila bergantian) |

Ukuran target di lapangan: lebar wajah ≥110 px di titik orang melewati zona (kamera 1920×1080); bila kurang,
dekatkan kamera/zona atau pakai lensa lebih sempit sebelum menyentuh ambang.

### Membaca label gerbang di debugger

Live View → klik tile kamera attendance → modal debugger. Kotak biru (`face`)
dengan label:

- `di luar zona` — wajah terdeteksi di luar polygon zone;
- `wajah terlalu kecil` — lebar wajah < `face_min_width_px`;
- `skor rendah` — skor deteksi SCRFD < `face_min_det_score`;
- `menyamping` — yaw > `face_max_yaw`;
- `buram` — blur < `face_blur_min`.

Label berupa angka (mis. `0.82`) = lolos gerbang; angkanya skor kualitas frame itu, dan
worker sedang mengumpulkan frame bagus (default 3) sebelum menerbitkan satu event.

### Kalibrasi `face_stats`

Gunakan `face_stats` (width_px, det_score, yaw, blur, frames), label debugger, dan
corong heartbeat untuk menentukan penyebab sebelum menyetel gerbang. Perubahan
angka hanya setelah uji penerimaan server; siklus kode ini tidak mengubah default
`FaceSettings`. Ambang kecocokan dan margin kini di kartu **Pengenalan wajah** (berlaku pada event
berikutnya, tanpa deploy), sedangkan `face_min_quality` tetap env-only. Ubah `face_min_width_px` dan `face_min_det_score` **bersamaan** dengan memperhatikan
rumus kualitas di atas: menurunkan lebar saja membuat frame kecil menjadi event `low_quality`.
`face_min_quality` bukan setelan UI (lihat "Tetap pada default di Docker").

### Membaca corong di monitoring

`GET /api/v1/monitoring` (login biasa) → `cameras[].ai.funnel`. Data direset per
jendela heartbeat; heartbeat node lama tanpa corong menghasilkan null.

| Field/gejala | Arti dan langkah |
|---|---|
| `faces` | Wajah yang dilacak per frame, bukan jumlah orang unik |
| `rejects.zone` dominan | Periksa posisi polygon terhadap pusat bbox wajah |
| `rejects.small` dominan | Dekatkan zona atau evaluasi `det_size` lebih besar pada konfigurasi engine; bukan knob UI baru |
| `rejects.score` dominan | Perbaiki pencahayaan dan visibilitas wajah sebelum melonggarkan gerbang |
| `rejects.yaw` / `rejects.blur` dominan | Perbaiki sudut kamera / shutter |
| `tracks_emitted` | Track yang menerbitkan event |
| `tracks_silent` tinggi | Track masuk zona tanpa embedding lolos; periksa gerbang yang terlalu ketat |
| `ttfg_median_s` | Median waktu masuk zona hingga embedding bagus pertama; bukan latensi end-to-end |

### Pemantauan pencocokan (query siap pakai)

Jalankan di Postgres (`docker compose -f docker/compose.yml exec postgres psql -U isentinel -d isentinel`).
Kolom diverifikasi dari `backend/app/models/event.py` (`type`, `camera_id`, `ts_event`, `payload`). Kolom
`payload` bertipe `json` (bukan `jsonb`), jadi gunakan `->>` dan `IS NOT NULL`, bukan operator `?`; `round()`
butuh `numeric`, sehingga hasil `percentile_cont` di-cast. Kedua query divalidasi 2026-10-09 di Postgres
`gspe-ai3` dalam transaksi read-only (`PGOPTIONS="-c default_transaction_read_only=on"`). Ganti `interval '14 days'` sesuai kebutuhan dan `'Asia/Jakarta'` bila TZ server berbeda.

```sql
-- 1) distribusi skor kecocokan + hitungan alasan per kamera per hari (jalur absensi)
SELECT camera_id,
       (ts_event AT TIME ZONE 'Asia/Jakarta')::date             AS day,
       payload->>'match_reason'                                 AS reason,
       count(*)                                                 AS n,
       round(min((payload->>'face_score')::numeric), 3)         AS score_min,
       round((percentile_cont(0.5) WITHIN GROUP (
             ORDER BY (payload->>'face_score')::numeric))::numeric, 3) AS score_p50,
       round(max((payload->>'face_score')::numeric), 3)         AS score_max
FROM event
WHERE type = 'attendance'
  AND payload->>'face_score' IS NOT NULL
  AND ts_event >= now() - interval '14 days'
GROUP BY 1, 2, 3
ORDER BY day DESC, camera_id, reason;

-- 2) rasio alasan (matched, no_match, ambiguous, cooldown, already_in) per kamera per hari
SELECT camera_id,
       (ts_event AT TIME ZONE 'Asia/Jakarta')::date      AS day,
       coalesce(payload->>'match_reason', '(kosong)')    AS reason,
       count(*)                                          AS n
FROM event
WHERE type = 'attendance'
  AND ts_event >= now() - interval '14 days'
GROUP BY 1, 2, 3
ORDER BY day DESC, camera_id, n DESC;
```

Pada tahap 1 (`legacy`) absensi hanya memutuskan `matched`/`no_match` (plus `cooldown`/`already_in`
pada pencatatan); `ambiguous` baru muncul setelah tahap 2 (mode `unified`) dijalankan. Ambang dan galeri
diuji ulang bila jumlah karyawan terdaftar berlipat.

`fps` dan `motion_skip_pct` berada di objek `ai` yang sama. Motion gate tetap
update setiap frame; wajah terlihat mempertahankan pemrosesan frame diam, dan
gate kembali melewati frame saat wajah hilang. Wajah latar/poster/cermin dapat
menaikkan beban GPU; pantau sebelum tuning.

### Protokol uji penerimaan server (belum dijalankan)

1. Setelah review dan deploy berizin, gunakan kamera ideal dan **10 karyawan × 5 lintasan**.
2. Minta jalan normal tanpa menoleh atau berhenti menatap CCTV.
3. Ukur dari wajah muncul hingga event tercatat: target **≥95% tercatat benar**,
   **≤2 detik**, dan **nol salah-orang**. Catat hasil dan corong di CHANGELOG.
4. Ulangi protokol setiap perubahan ambang; jangan menyimpulkan keberhasilan dari tes fake worker.
5. Deploy memerlukan rebuild `api` dan `vision`, lalu `docker compose up -d`,
   bukan hanya restart. Tanpa migrasi; flag zona lama tetap memakai default.
   Kode ini **BELUM diuji di server nyata**. Fase 3b dua fase hanya diputuskan dari data uji.

## Mode absensi unified (tahap 2)

### Arti mode dan jendela

Dua algoritma absensi hidup berdampingan. Saklar `face_attendance_mode` ada di **Konfigurasi → Deteksi &
Model → Advanced → kartu Pengenalan wajah → grup Mode absensi** dan berlaku untuk semua kamera.

| | `legacy` (bawaan) | `unified` |
|---|---|---|
| Gerbang per wajah | lebar `face_min_width_px` (80), skor, yaw, **blur `face_blur_min`** (120) | lebar `face_ident_min_width_px` (60), skor, yaw, pitch `face_max_pitch`; **tanpa gerbang blur** |
| Kapan event terbit | setelah `face_min_frames` (3) frame lolos | setelah jendela `face_attendance_window_s` berlalu sejak vektor pertama, **atau** 0,5 dtk (`UNIFIED_GONE_S`) tanpa kandidat baru (orang pergi; tidak menunggu tracker 3 dtk), atau track hilang, dengan ≥ 1 vektor |
| Embedding | agregat berbobot semua frame lolos | agregat berbobot K frame terbaik (`face_best_k`) berperingkat `skor × ketajaman` |
| Keputusan API | `match_vector` (ambang saja) | `match_strict` (ambang 0,40 + margin 0,15); `ambiguous` = tidak dikenal |
| Payload | tanpa `policy` | `policy: "unified"` + `face_stats.collect_s` dan `zone_s` |

Jendela `face_attendance_window_s` bawaan **1,5 dtk** (rentang 0,5–3). Naik: lebih banyak frame untuk
dipilih, tetapi event lebih lambat. K kandidat terkumpul **tidak** memicu pengiriman — pemilihan frame
terbaik butuh waktu. Mengubah mode atau jendela merestart worker wajah kamera terkait; **track yang
sedang di dalam jendela saat itu hilang** (tidak ada event untuk track itu).

Keputusan API ditentukan `payload.policy` event, bukan baris DB saat event diproses: event yang sudah
dikirim tetap diputuskan dengan algoritma asalnya walau saklar dibalik di tengah jalan. Node lama
(tanpa `policy`) dan node baru selalu bisa bercampur; payload `unified` ke API tahap 1 tetap diputuskan
`legacy`, dan sebaliknya.

### Replay offline sebelum membalik saklar

Menguji ulang ambang/margin pada crop event nyata (bukan waktu jendela). Jalankan **di container `api`**,
CPU dibatasi, dan **beri tahu user dulu** (analisis di server membebani CPU):

```bash
docker compose -f docker/compose.yml exec -T api \
    nice -n 19 python -m scripts.face_replay --days 14 --limit 40 --threads 2 --max-seconds 120
```

**Batas CPU:** `taskset` dan `OMP_NUM_THREADS` tidak membatasi onnxruntime (ia memasang afinitas threadnya
sendiri; percobaan pertama 2026-10-09 memakai ±1600% CPU dan load host 50–80 walau `taskset -c 0-3`). Skrip
membatasi sesi lewat `--threads` dan berhenti sendiri pada `--max-seconds` sambil tetap mencetak ringkasan.
Mulai dengan `--limit` kecil, pantau `docker stats --no-stream` pada beberapa detik pertama, dan bila CPU
`api` melebihi ±300% hentikan dengan membatalkan perintah (jangan membiarkannya selesai).

Keluaran hanya ID (event dan karyawan) — tanpa nama, tanpa embedding. Syarat lolos spec §7.1:
`same_pct` ≥ 98 (crop yang dikenali `legacy` tetap karyawan yang sama di 0,40 / 0,15) dan `flipped` 0
(tidak ada yang pindah ke karyawan lain). Daftar `ambiguous` (beserta pasangan karyawannya) dan
`gained` (dulu `no_match`, kini cocok) dinilai manual: `ambiguous` pada karyawan mirip berarti absensi
berpotensi terlewat, `gained` bisa berarti perbaikan atau salah-orang. Skrip ini tidak menguji kecepatan
(jendela).

### Uji lapangan kategori A–D (spec §7.2)

Kamera profil C (2K, 15 fps). Catat hasil per kategori — satu angka gabungan menyembunyikan batas fisik.

| Kategori | Skenario | Syarat |
|---|---|---|
| A (penentu) | jalan normal menuju kamera tanpa berhenti, ≥ 5 karyawan × 10 lintasan | ≥ 95% tercatat, median `zone_s` ≤ 2 dtk, p95 ≤ 3 dtk, 0 salah-orang |
| B | berhenti sebentar di titik absensi | sama dengan A |
| C | menyamping atau menunduk (melihat ponsel), 5 lintasan per karyawan | dicatat sebagai batas sistem (bukan kegagalan), tetap 0 salah-orang |
| D | non-karyawan ≥ 10 lintasan (≥ 3 orang), berjalan dan berhenti | 0 tercatat |

`zone_s` (wajah pertama di zona → event dikirim) ada di `payload.face_stats` tiap event `unified`.
Hasil ditempel di `CHANGELOG.md`/`ROADMAP.md`; keputusan membalik saklar ada di tangan user.

### Mengukur kecepatan dan hasil

Query pemantauan berikut memakai kolom dari `backend/app/models/event.py`; `payload` bertipe `json`
(pakai `->`/`->>`, bukan operator `?`) dan `round()` butuh `numeric`. **Divalidasi 2026-10-09** di Postgres
`gspe-ai3` dalam transaksi read-only (`PGOPTIONS="-c default_transaction_read_only=on"`): kedua query
dieksekusi tanpa galat; query kecepatan menghasilkan 0 baris karena belum ada event `unified`.

```sql
-- 1) kecepatan event unified: distribusi zone_s dan collect_s (dtk) per kamera per hari
SELECT camera_id,
       (ts_event AT TIME ZONE 'Asia/Jakarta')::date AS day,
       count(*)                                     AS n,
       round((percentile_cont(0.5) WITHIN GROUP (
             ORDER BY (payload->'face_stats'->>'zone_s')::numeric))::numeric, 2) AS zone_s_p50,
       round((percentile_cont(0.95) WITHIN GROUP (
             ORDER BY (payload->'face_stats'->>'zone_s')::numeric))::numeric, 2) AS zone_s_p95,
       round((percentile_cont(0.5) WITHIN GROUP (
             ORDER BY (payload->'face_stats'->>'collect_s')::numeric))::numeric, 2) AS collect_s_p50
FROM event
WHERE type = 'attendance'
  AND payload->>'policy' = 'unified'
  AND payload->'face_stats'->>'zone_s' IS NOT NULL
  AND ts_event >= now() - interval '14 days'
GROUP BY 1, 2
ORDER BY day DESC, camera_id;

-- 2) hasil keputusan + margin per kamera per hari (matched/no_match/ambiguous/cooldown/already_in)
SELECT camera_id,
       (ts_event AT TIME ZONE 'Asia/Jakarta')::date      AS day,
       coalesce(payload->>'match_reason', '(kosong)')    AS reason,
       count(*)                                          AS n,
       round(min((payload->>'face_margin')::numeric), 3) AS margin_min,
       round((percentile_cont(0.5) WITHIN GROUP (
             ORDER BY (payload->>'face_margin')::numeric))::numeric, 3) AS margin_p50
FROM event
WHERE type = 'attendance'
  AND ts_event >= now() - interval '14 days'
GROUP BY 1, 2, 3
ORDER BY day DESC, camera_id, n DESC;
```

### Membalik saklar dan rollback

- **Balik ke `legacy`:** matikan **Algoritma absensi baru (unified)** di kartu Pengenalan wajah lalu
  **Simpan setelan global**. Instan, tanpa deploy atau restart; event berikutnya memakai `legacy`.
- **Rollback kode:** `git revert` commit tahap 2. Kolom DB boleh tetap ada; migrasi `0025` tidak dihapus.
- Track yang sedang di dalam jendela hilang saat saklar dibalik; ulangi lintasan bila perlu.

## Troubleshooting

| Gejala | Kemungkinan | Langkah |
|---|---|---|
| "Tidak hadir" tidak pernah muncul | Job tidak jalan (API start gagal / exception berulang) | Cek log `attendance close failed`; cek thread hidup: `py-spy dump --pid <api>` bila perlu; restart API |
| Hari ini "Tidak hadir" sebelum jam selesai shift | Bukan bug — batas = shift selesai + grace | Tunggu lewat batas atau cek `NO_EXIT_GRACE_MIN` |
| Baris dikoreksi berubah sendiri | Ada event absensi baru hari itu setelah koreksi | Input ulang koreksi (event baru memicu recompute — batasan yang diketahui) |
| Waktu tampil tidak WIB | TZ host server bukan WIB | Set TZ host (semua perbandingan memakai tz lokal server); `LOCAL_TZ` dibaca saat start |
