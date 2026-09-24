# Spec — Event clip pre-buffer (clip insiden dari mainstream)

Status: **DISETUJUI di chat (2026-09-24)**, menunggu review spec tertulis.
Branch: `feat/event-clip-prebuffer` (dari `main` @ `bab61a9`).
Checkpoint: `.cooper/context/next-features.md`.

---

## 1. Latar

Keluhan lapangan: *"rekaman sering menyimpan kejadiannya setelah snapshot. jadi kebanyakan orang yang
terdeteksi keburu hilang."* Spec awal (`docs/plans/2026-09-08-isentinel-design.md` §1–2) meminta clip
**dari mainstream** dengan **pre/post buffer**; keduanya belum terpenuhi.

### Kode sekarang

- `Recorder._save_clip` (`vision/vision/recorder.py:167`) menarik
  `go2rtc /api/stream.mp4?src=cam_<id>&duration=record_clip_s` **setelah** event diambil dari antrean.
  `cam_<id>` = **substream**. Tidak ada pre-buffer.
- Antrean recorder per kamera sekuensial: snapshot + clip + upload satu event selesai dulu (~30 s)
  sebelum event berikutnya diproses. Snapshot ikut tertahan ~30 s.
- `FrameRing` (40 JPEG substream) hanya dipakai snapshot.
- Backend `events_consumer` (`backend/app/services/events_consumer.py:75`) sudah menerima update media
  parsial per kolom (`clip_path` / `snapshot_path` terpisah).
- Retensi aman untuk path clip yang dipakai beberapa event: sweep orphan memakai set `referenced`
  (`backend/app/services/retention.py:126`).
- `frame.ts` di pipeline = `time.monotonic()`; konversi ke wall clock ada di `node._iso`
  (`vision/vision/node.py:31`).

### Pengukuran di server `gspe-ai3` (2026-09-24, baca-saja)

| Ukuran | Hasil |
|---|---|
| Clip selesai ditulis vs `ts_event` (30 event) | 30,0–30,3 s; beruntun cam 364: 38,9 / 44,5 / 55,9 s |
| Durasi isi clip (diminta 30 s) | 25,3–29,8 s |
| Substream | 640×480 @25, keyframe tiap 3,3–5 s (sampel 10 s → 6–7 s video) |
| Mainstream | 1920×1080 @25, keyframe tiap 1–2 s |
| Bitrate mainstream | ~350 kbps (cam 357/362/363), ~2 Mbps (cam 364) |
| Konsumen `cam_*_main` di go2rtc | 0 (mainstream hanya on-demand) |
| Server | 20 core, `/dev/shm` 63 GB kosong, disk bebas 313 GB, `ffmpeg` tersedia |
| Jarak event keamanan terdekat (cam 357, 21 intrusion) | 44 s |

**Akar masalah:** (1) tidak ada pre-buffer; (2) clip menunggu keyframe substream (hilang 1–5 s);
(3) event beruntun mengantre.

### Pembanding: Frigate (`/Users/leekhan/project/frigate`)

- Buffer: ffmpeg `-f segment -segment_time 10 -c copy` ke `/tmp/cache` tmpfs
  (`frigate/ffmpeg_presets.py:440`) — pola yang sama dipakai di sini.
- Unit clip: *review segment* per kamera (aktivitas pertama → aktivitas selesai), jendela
  `[start − pre_capture, end + post_capture]`, default 5/5 s (`frigate/config/camera/record.py:54`).
  Beberapa objek/event digabung ke satu review item.

## 2. Keputusan user

| # | Keputusan |
|---|---|
| K1 | Sumber clip = **mainstream 1080p** (`cam_<id>_main`). Diterima: 1 sesi RTSP main selalu terbuka per kamera yang punya zona clip. |
| K2 | Pre **10 s**, post **15 s**, global lewat env vision node (tanpa UI, tanpa config push). |
| K3 | Pendekatan **A**: ring segmen ffmpeg `-c copy` di tmpfs, fallback ke jalur live lama. |
| K4 | Unit clip = **insiden per kamera** (seperti review segment Frigate): 1 orang / 1 kejadian → 1 clip; event yang terjadi selama insiden terbuka berbagi file clip yang sama. |
| K5 | Clip berakhir **15 s setelah track insiden terakhir terlihat**, bukan jendela tetap dari trigger; batas 120 s. |
| K6 | Snapshot tetap per event (bbox + ID track) dan dikirim segera, tidak menunggu clip. |
| K7 | Attendance / `FaceGateWorker` (R5b) tidak disentuh: tanpa clip, tanpa ring. |

## 3. Desain

### 3.1 `vision/vision/clipring.py` (baru)

`ClipRing(camera_id, src_url, ring_dir)` — satu per kamera ber-clip.

- `start()`: subprocess
  `ffmpeg -nostdin -loglevel error -rtsp_transport tcp -i <src_url> -map 0:v:0 -c copy -an
  -f segment -segment_time 2 -segment_format mpegts -reset_timestamps 1 -strftime 1
  <ring_dir>/cam<id>/%s.ts`.
  `src_url = main_stream_url(cam.source_url)` (helper yang sudah ada, `node.py:50`).
  Nama file = epoch wall-clock saat segmen dibuka (segmen selalu mulai di keyframe).
- `segments()` → `[(start_epoch, path)]` terurut; segmen terakhir (masih ditulis) dikecualikan
  kecuali `include_open=True` saat finalisasi paksa.
- `select(segments, t0, t1)` — **fungsi murni**: segmen terakhir dengan `start ≤ t0` sampai segmen
  terakhir dengan `start < t1`. Kosong bila tidak ada segmen yang menutupi `t0..t1` sama sekali.
- `cut(t0, t1, out_path) -> (path | None, covered_s)`: `select`, tulis daftar concat, jalankan
  `ffmpeg -f concat -safe 0 -i list.txt -c copy -movflags +faststart out.mp4`. Kembalikan `None` bila
  segmen tidak menutupi `ts` event.
- `prune(keep_from)`: hapus segmen dengan `start < keep_from − 4 s` (sisakan satu segmen penutup).
- Watchdog (thread ringan, tiap 2 s): proses mati **atau** tidak ada segmen baru > 10 s → kill +
  restart dengan backoff 1 → 2 → 4 … maks 30 s; log warning sekali per episode.
- `ffmpeg` tidak ada di PATH → log error sekali, ring nonaktif (`available=False`).
- `close()`: terminate ffmpeg (tunggu 3 s, lalu kill), hapus `ring_dir/cam<id>`.

### 3.2 `Recorder` → pengelola insiden per kamera (`vision/vision/recorder.py`)

State: paling banyak **satu insiden terbuka** per kamera:
`Incident(start, events: list[event], tracks: set[int], last_active)`.

- `enqueue(ev)` (dipanggil worker, non-blocking):
  - Snapshot: bila `ev["snapshot"] is not False` → masuk antrean kerja `snapshot` (simpan + upload +
    `publish_media({event_id, snapshot_path})`) segera.
  - Clip: bila `ev["clip"] is not False`:
    - tidak ada insiden terbuka → buka: `start = wall(ts) − CLIP_PRE_S`, `tracks = {track_id}`;
    - ada → tempel event, tambah `track_id`, `last_active = max(last_active, wall(ts))`.
- `touch(track_ids, ts)` (dipanggil worker tiap frame inferensi): untuk track yang ada di
  `incident.tracks`, `last_active = wall(ts)`.
- Thread recorder (tetap satu thread per kamera) memproses antrean snapshot dan memeriksa insiden
  tiap ≤ 0,5 s. Insiden **ditutup** bila
  `now ≥ min(start + CLIP_MAX_S, last_active + CLIP_POST_S) + 1 s`.
  Saat ditutup:
  1. `ring.cut(start, end)` → `outbox/<event_id pertama>.mp4`;
  2. hasil `None` / ring tidak ada → fallback `_save_clip` lama (live `stream.mp4` dari
     `cam_<id>_main`, `duration = CLIP_POST_S`);
  3. upload sekali (`kind=clip`);
  4. `publish_media({event_id, clip_path})` untuk **setiap** event insiden.
- Event yang datang setelah insiden ditutup membuka insiden baru.
- Event dengan `clip: false` tidak membuka dan tidak bergabung ke insiden.
- `wall(ts)`: konversi monotonic → epoch, dipindah dari `node._iso` ke helper bersama
  (`node._iso` memakainya; perilaku `_iso` tidak berubah).
- `close()`: insiden terbuka difinalisasi segera dengan segmen yang ada (`include_open=True`), lalu
  `ring.close()`.
- `FrameRing`, `_save_snapshot`, `_draw_track_box`, `upload_bytes` (dipakai face gate) tidak berubah.

### 3.3 `node.py`

- `CameraWorker.run`: setelah `tracker.update`, panggil `self.recorder.touch([t.id for t in tracks], frame.ts)`.
- `_start_workers`: `Recorder` menerima `ring` hanya bila `CameraWorker` dibuat **dan**
  (ada analyzer dengan `media["clip"]` true **atau** `emit_person_detect`). Recorder milik kamera
  gate-only tetap tanpa ring.
- `FaceGateWorker` tidak berubah.

### 3.4 Config (`vision/vision/config.py`, `deploy/vision.env.example`)

| Env | Default | Ganti |
|---|---|---|
| `CLIP_PRE_S` | 10 | baru |
| `CLIP_POST_S` | 15 | menggantikan `record_clip_s` (dihapus) |
| `CLIP_MAX_S` | 120 | baru |
| `CLIP_RING_DIR` | `/dev/shm/isentinel` | baru (Jetson/host tanpa `/dev/shm` bisa diarahkan ke tmpfs lain) |

### 3.5 Frontend (kecil)

- `EventsPage.tsx` tab Clip: bila `clip_path` kosong **dan** umur event < 3 menit **dan** tipe bukan
  attendance → placeholder "Clip sedang direkam…"; selain itu tetap `events.clipUnavailable`.
- i18n: `zones.clip` → "Rekam clip event" / "Record event clip" (hapus "30 detik").

### 3.6 Backend

Tidak ada perubahan.

## 4. Anggaran sumber daya

- CPU: ffmpeg `-c copy` tanpa decode — diukur saat verifikasi (target < 1 % core per kamera).
- tmpfs: segmen disimpan sejak `min(start insiden terbuka, now − CLIP_PRE_S) − 4 s`. Terburuk
  (insiden 120 s @ 2 Mbps) ≈ 35 MB per kamera; normal (≈ 30 s @ 350 kbps) ≈ 1,5 MB.
- Disk clip: 25 s @ 350 kbps ≈ 1,1 MB; @ 2 Mbps ≈ 6 MB.
- NVR: +1 sesi RTSP mainstream permanen per kamera ber-clip (saat ini 1 kamera: 357).

## 5. Penanganan error (ringkas)

| Kondisi | Perilaku |
|---|---|
| `ffmpeg` tidak ada | log error sekali; semua clip lewat fallback live |
| ffmpeg crash / stall > 10 s | watchdog restart dengan backoff ≤ 30 s |
| Segmen tidak menutupi `ts` event | fallback live |
| Segmen menutupi sebagian | clip dari segmen yang ada + log `covered_s` |
| Upload gagal (3 retry) | clip tidak dipublikasi (perilaku sama seperti sekarang) |
| Config push / node stop | insiden terbuka difinalisasi dengan segmen yang ada, ring ditutup |
| Motion gate melewati frame (orang diam) | `touch` tidak jalan → insiden bisa tutup lebih cepat; dibatasi `force_interval_s` gate yang sudah ada |

## 6. Pengujian (tanpa GPU/RTSP, `vision/tests/`)

- `test_clipring.py`: `select` (batas `t0`/`t1`, celah, kosong, segmen terbuka); `prune`; perintah
  ffmpeg dibangun benar (subprocess di-mock); watchdog me-restart proses mati (jam palsu).
- `test_recorder.py` (diperbarui): dengan jam palsu dan ring palsu —
  2 event satu kamera → 1 `cut`, 1 upload, 2 `publish_media` dengan `clip_path` sama;
  `touch` memperpanjang insiden; cap `CLIP_MAX_S` dipatuhi; event setelah tutup → insiden baru;
  snapshot dipublikasi sebelum clip; `cut` → `None` memanggil fallback; `clip: false` tidak
  membuka insiden; `close()` memfinalisasi insiden terbuka.
- `test_node*.py`: ring hanya dibuat bila ada analyzer `clip` true; kamera gate-only tanpa ring;
  worker memanggil `touch`.
- Frontend `events.test.tsx`: placeholder "sedang direkam" vs "tidak tersedia".
- Baseline yang harus tetap hijau: backend 339 passed; vision 177 passed / 3 deselected;
  frontend 118 passed, build 0, lint = set rule+file lama.

## 7. Verifikasi lapangan (setelah deploy, butuh izin user)

1. Deploy branch ke `gspe-ai3`, restart vision node.
2. `ls /dev/shm/isentinel/cam357` → segmen 2 s bergulir; `ps` ffmpeg; CPU/RAM per proses.
3. go2rtc `/api/streams`: `cam_357_main` punya 1 konsumen permanen.
4. Picu intrusion di zona 6 cam 357: clip 1080p, orang terlihat **sebelum** masuk zona, durasi
   ≈ 10 s + lama di zona + 15 s (ffprobe).
5. Dua orang / dua event beruntun → 1 file clip, dua event menunjuk path yang sama.
6. Snapshot muncul di Inbox dalam beberapa detik (bukan ~30 s).
7. Evidence (ffprobe, screenshot Inbox, angka CPU/tmpfs) ke `docs/evidence/`.

## 8. Di luar scope

- Clip attendance (R5b sengaja tanpa clip).
- UI untuk pre/post/max; config push nilai clip.
- Toggle Snapshot/Clip **per behavior** dan perapian UX zona → spec terpisah `feat/zone-config-ux`
  (lihat §10). Recorder hanya membaca `ev["clip"]`, jadi tidak bergantung pada sumber flag.
- Retensi/cleanup per rentang tanggal (fitur no. 3), User management (fitur no. 2).
- Telegram `sendPhoto`.

## 9. Rollback

`git revert` commit branch; hapus env `CLIP_*` (default kode lama tidak membutuhkannya); restart vision
node — ffmpeg ring berhenti bersama proses, `/dev/shm/isentinel` dihapus di `close()` atau manual.
Tidak ada migrasi DB; clip lama tetap bisa diputar.

## 10. Catatan untuk spec berikutnya (sudah disepakati arah, belum di-spec)

Urutan: **clip pre-buffer → zona UX → User management → Retention UI**.

Zona UX (`feat/zone-config-ux`) — "Zona = aturan, Kamera = mesin":
- Temuan: 4 lapis saklar (kamera enabled, chip analyzer kamera sebagai *mask* `node.py:282`,
  behavior zona, zona active). Bukti: zona 6 cam 357 aktif dengan 3 behavior, tetapi
  `camera.analyzers = ['attendance']` → behavior di-skip tanpa peringatan di halaman Zona.
- Kolom CLIP di Gate Absensi no-op (`face_worker.py:284` selalu `clip_path: None`).
- Hint "semua analyzer mati = hemat GPU" tidak sesuai kode: `node.py:382` tetap menjalankan
  `CameraWorker` bila kamera tidak punya gate.
- Arah: Zona Deteksi = satu-satunya tempat aturan behavior (hanya zona `type=behavior`), dengan
  **toggle Snapshot/Clip per behavior** (key baru di item JSON `zone.behaviors`, fallback ke
  `zone.snapshot/clip`; toggle level zona dihapus dari UI); Gate Absensi punya editor zona sendiri
  (reuse `ZoneEditor`), kolom CLIP dihapus; Deteksi & Model = mesin per kamera + satu toggle
  "Analitik AI" (`analyzers null ↔ []`) yang benar-benar menghentikan worker; banner di Zona bila
  Analitik AI kamera OFF; normalisasi data `analyzers` lama.
