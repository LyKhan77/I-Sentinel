# Inventaris Behavior Deteksi & Event (kondisi saat ini)

Referensi kondisi nyata per **2026-09-22** (branch `feat/events-dwell-crop`, server
`gspe-ai3`). Dokumen ini memetakan **apa yang men-trigger apa**, bukan rencana
perubahan. Dipakai sebagai bahan pembahasan penataan arsitektur.

---

## 1. Peta alur

```
RTSP kamera (NVR)
  └─ go2rtc  ── cam_<id>      (substream 640x480  → deteksi)
                cam_<id>_main (main stream 1920x1080 → crop wajah, on-demand)
     │
     ├─ vision node (per kamera: 1 thread worker)
     │     source → YOLO detektor → ByteTrack → analyzers per zona
     │     └─ event partial → crop/snapshot/clip → MQTT publish
     │
     ├─ MQTT  isentinel/events/<node>        (event)
     │        isentinel/detections/<node>    (bbox realtime, debug)
     │        isentinel/heartbeat/<node>     (status + hw)
     │
     └─ backend (FastAPI)
           events_consumer (MQTT subscribe)
             ├─ ingest_event()      → tabel `event`  (dedup by event_id/dedup_key)
             ├─ alerting.handle()   → gate severity+zona+rate-limit → Telegram → tabel `alert`
             ├─ attendance.handle_face_event() → match → `attendance_event` → `attendance_day`
             └─ hub.broadcast()     → WebSocket /api/v1/ws/events → UI realtime
```

Blob media (clip/snapshot/crop) diunggah node → `POST /internal/nodes/.../blobs`
→ disimpan di `STORAGE_ROOT/{snapshots,clips,crops}` (path relatif di DB).

---

## 2. Detektor & model

| Item | Nilai sekarang | Sumber |
|---|---|---|
| Model deteksi | `yolo26s.engine` (TensorRT FP16, `nms=False`, `conf=0.4`, `imgsz=640`) | `config_push.build_node_config` ← DB node/env |
| Device detektor | `cuda:1` (pin per-node) | `node.detector_device` (server: `cuda:1`) |
| Device face | `cuda:2` | `node.face_device` |
| Tracker | ByteTrack (id per track, lintas frame) | `vision/pipeline/tracker.py` |
| Input deteksi | **substream** `cam_<id>` 640x480 @ `ai_fps` | `vision.node` |
| Face embedder | InsightFace `buffalo_l`, jalan **di node** (Opsi B) | `vision/vision/face.py` |
| Face match | cosine vs gallery server, `face_match_threshold=0.40`, `face_min_quality=0.5` | `backend/app/core/config.py` |

`ai_fps` node = `DEFAULT_FPS = 5.0` fps (lihat `config_push.py`). Setiap kamera = 1 worker
thread; analyzer dibuat **per zona** (`_make_analyzers`), bukan per kamera.

---

## 3. Analyzer: kondisi trigger (inti)

Semua analyzer menerima `(ts, tracks, frame_w, frame_h)` per frame dan memakai
**centroid track** (`point_in_polygon`, ray casting) kecuali disebut lain.
`ts` = waktu frame (detik epoch).

| Analyzer | Syarat aktif | Trigger (tepatnya) | Emit ulang | Payload khas |
|---|---|---|---|---|
| **intrusion** | zona `type=restricted` | transisi **luar→dalam** polygon | hanya setelah keluar lalu masuk lagi (`_inside` di-reset tiap frame; track hilang = keluar) | `zone_name, track_id, bbox_norm` |
| — schedule | zona punya `schedule` | `_schedule_active`: hari ISO cocok **dan** `start ≤ HH:MM ≤ end` (tz server). Di luar jendela: emit dimatikan **dan `_inside` dibekukan** → track yang masih di dalam saat jendela tutup **tidak** emit saat jendela berikut buka | — | — |
| **loitering** | zona `loiter_seconds > 0` | akumulasi dwell track di dalam polygon ≥ `loiter_seconds` | sekali per kunjungan (`_emitted`); keluar polygon → reset dwell+emitted | `dwell_s, track_id, bbox_norm` |
| — gap | — | delta antar frame > `MAX_DELTA_S=10s` → akumulasi dwell **restart dari 0** | — | — |
| **running** | zona `speed_limit_mps > 0` **dan** kamera punya `meters_per_pixel` | kecepatan EMA (`alpha=0.4`) `> speed_limit_mps` **dan** centroid di dalam polygon | cooldown `5s` per track (selama masih cepat + di dalam zona) | `speed_mps, track_id, bbox_norm` |
| — kecepatan | — | m/s = `hypot(Δx_norm·frame_w, Δy_norm·frame_h) · meters_per_pixel / Δt` (sumbu x/y dikembalikan ke piksel masing-masing) | — | — |
| **face_gate** | zona `type=absensi` **dan** `direction ∈ {entry,exit,in,out}` | track masuk polygon, lalu **tetap di dalam ≥ `dwell_seconds`** (R4) → baru emit. `dwell_seconds=0` = emit saat masuk | cooldown `10s` per track; kunjungan yang tersedot cooldown tidak emit sama sekali (walau dwell lewat) | `direction, track_id, bbox_norm, needs_crop=True` → node lampirkan `crop_path`, `embedding`, `face_quality`, `face_bbox` |
| **person_detect** | flag debug node `VISION_EMIT_PERSON_DETECT=true` (server: **false**) | **semua** track baru (id belum pernah terlihat), tanpa zona | sekali per id track | `track_id, bbox_norm` |

Catatan penting soal `dwell_seconds` vs `loiter_seconds` — dua konsep dwell yang
berbeda dan hidup berdampingan:

- `loiter_seconds` = *memicu event* loitering (tujuan: alarm).
- `dwell_seconds` = *menahan* emit face_gate agar orang masih di frame saat
  media diambil (tujuan: kualitas crop).

---

## 4. Media per event

| Media | Sumber frame | Trigger | Toggle | Catatan |
|---|---|---|---|---|
| **snapshot** | **ring buffer memori** (40 frame substream terakhir yang di-encode worker) → frame terakhir + bbox `ID n` dibakar (warna = severity) | setiap event, default aktif | per zona `snapshot` | frame ≈ **waktu deteksi** → orang ada di frame |
| **clip** | go2rtc `api/stream.mp4?src=cam_<id>&duration=record_clip_s` | setiap event, default aktif | per zona `clip` | **hanya POST-event** (`record_clip_s=30`); pre-roll tidak didukung go2rtc 1.9.9 |
| **crop wajah** | fetch **live** `cam_<id>_main` (go2rtc `api/frame.jpeg`) → `crop_upper_body` (pad 20 %, ambil 60 % atas) → embed + anotasi nama/score | khusus `face_gate` (`needs_crop`) | tidak ada toggle | fallback ke frame substream lokal kalau main stream gagal |

Semua media diunggah via queue disk-backed (retry 3×); gagal upload → event tetap
terbit tanpa `clip_path`/`snapshot_path`/`crop_path` (graceful).

---

## 5. Dedup, rate limit, alerting

| Lapis | Mekanisme | Nilai |
|---|---|---|
| Dedup event | `dedup_key = "<cam>:<type>:<track_id>:<int(ts/10)>"` (10 s bucket) + `event_id` UUID; kolom DB **unique** | `DEDUP_BUCKET_S=10` |
| Rate limit Telegram | query `alert` terakhir untuk (camera, zone, type) dalam jendela `zone.rate_limit_min` menit | default zona **5 menit** |
| Ambang severity | `_severity(event) ≥ ALERT_MIN_SEVERITY` | `.env` server default `warning` |
| Toggle per zona | `zone.telegram` harus true | server sekarang: kolom ada, UI menyebut "Fase 3" |
| Status alert | `sent` / `rate_limited` / `failed` / `not_configured` disimpan di tabel `alert` + badge di UI | `sendMessage` teks saja (sendPhoto deferred) |

`rate_limited` tetap dicatat sebagai baris `alert` (tanpa kirim), sehingga UI bisa
membedakan "kena limit" dari "gagal kirim".

---

## 6. Rantai attendance (absensi)

> **R5b status (lokal, PENDING verifikasi lapangan):** rantai di bawah ini masih
> deskripsi Fase 4 (face_gate analyzer lama). R5b menggantinya: pengirim event
> attendance kini **face worker** (`vision/vision/face_worker.py`, wajah di
> `cuda:2`); crop diambil dari frame mainstream node; event tanpa `crop_path`
> tetap match bila payload punya embedding; cooldown backend kini karyawan+arah
> ±5 menit lintas kamera (ATTENDANCE_COOLDOWN_MIN); embedding dibuang dari
> payload event pada jalur normal (migration 0016 purge yang lama). Tabel ini
> diperbarui penuh setelah verifikasi lapangan.

```
event type=attendance (dari face_gate)
  └─ butuh payload.crop_path  ─── tidak ada → skip ("tanpa crop_path")
  └─ butuh payload.direction ∈ {entry,exit}  ── tidak valid → skip
  └─ match:
        payload.embedding ada → face.match_vector(embedding, face_quality)
        tidak ada            → face.match_crop(db, file crop)  (embed di server)
        ├─ quality < face_min_quality (0.5) → reason "low_quality"
        ├─ skor terbaik < face_match_threshold (0.40) → "no_match"
        └─ cocok → annotate crop (nama + skor) + INSERT attendance_event
  └─ recompute_day(employee, tanggal):
        first_entry = min(entry), last_exit = max(exit) hari itu
        status: ontime | late (toleransi shift) | waiting | no_exit (setelah
        jam shift + no_exit_grace_min=60) | absent (tanpa entry)
  └─ rekap: attendance_day → API /attendance/... → CSV export/import
```

Konsekuensi yang mudah terlewat:

- **Tanpa match → tidak ada baris `attendance_event`** (payload event hanya diberi
  `match_reason`). Jadi "rekap kosong" bisa berarti tiga hal berbeda: crop kosong,
  wajah tidak terdeteksi, atau wajah terdeteksi tapi bukan karyawan ter-enroll.
- Zona `absensi` punya tombol **active** terpisah; zona non-aktif tidak dikirim ke
  node sama sekali (config push hanya kirim `active=True`).
- Satu kamera idealnya satu arah (UI memberi badge KONFLIK bila satu kamera punya
  >1 zona absensi aktif dengan arah berbeda).

---

## 7. Tipe event yang terdaftar tapi belum ada pengirim

`ALLOWED_TYPES = {intrusion, loitering, running, attendance, person_detect, system}`.
`system` diterima backend tetapi **tidak ada kode node/backend yang mengirimnya**
(kandidat untuk event operasional: node start, config apply, kamera offline).

---

## 8. Kondisi server hari ini (bukti, 2026-09-22)

| Fakta | Nilai |
|---|---|
| Kamera enabled | 358 Lorong 1, 360 Meeting Room, 362 Tangga 2, 363 Lorong Server |
| Stream go2rtc | `cam_358/360/362/363` (+ `_main`), `consumers=1` per subtream |
| Zona absensi | 9 `Absence Server` cam363 entry **active**, dwell **3** (baru di-set) · 8 cam358 entry `active=False` · 7 cam362 exit `active=False` · 6 cam357 `active=False` (kamera off) |
| Event attendance pasca-deploy | 6 event (12:33–13:29) semua `cam 363`, punya `crop_path` |
| `attendance_event` | **0** — belum ada match; `employee` = 1 (Angly) dengan 5 embedding |
| `attendance_day` | 2 baris lama (14–15 Sep) |
| Crop #4647 | benar: `face_quality=0.78`, embedding 512 dim, ada wajah |
| Crop #4650 | **salah: hanya lantai/dinding** (tidak ada `face_quality`/`embedding`) |
| Snapshot #4650 | benar: orang terlihat + bbox `ID 4` terbakar |

---

## 9. Temuan / inkonsistensi kandidat penataan

1. **Crop wajah bisa "lantai" walau dwell sudah benar.** Snapshot diambil dari
   ring frame substream (**waktu deteksi**), sedangkan crop diambil dari fetch
   **live** main stream (keyframe go2rtc bisa 2–4 s basi). Untuk orang yang
   berjalan, bbox "sekarang" dipetakan ke piksel "beberapa detik lalu" → crop
   berisi lantai. Terbukti: 1 dari 6 crop benar, sisanya tidak; snapshot selalu
   benar. Fix arah: ambil crop dari frame yang sama dengan deteksi (substream,
   resolusi kecil) ATAU pelihara ring main-stream ber-timestamp per kamera
   absensi agar bisa dipilih frame terdekat dengan `ts` deteksi.
2. **Dua semantik dwell** (`loiter_seconds` vs `dwell_seconds`) tanpa dokumentasi
   tunggal → mudah salah pakai di UI/ops.
3. **Tidak ada konsep "best-shot" per kunjungan**: satu kunjungan = satu event
   (media diambil sekali saat emit). Kalau crop/face gagal, event itu hangus
   (tidak ada percobaan kedua dalam kunjungan yang sama).
4. **`match_reason` tidak tampil di UI** — operator tidak tahu kenapa absensi
   kosong (no_face / low_quality / no_match). Data sudah ada di payload event.
5. **Aturan "satu arah per kamera" hanya validasi UI**, tidak ada constraint
   backend; data dari API/script bisa melanggar.
6. **Zona aktif vs kamera aktif tidak saling menjaga**: zona `absensi` aktif di
   kamera `enabled=False` tetap tersimpan (contoh: zona 6 cam357) — dulu muncul
   sebagai "gate" yang tidak mungkin jalan.
7. **Clip tanpa pre-roll** (batasan go2rtc 1.9.9): klip event selalu mulai dari
   frame setelah event → konteks "sebelum" hilang. Dwell membantu, tapi durasi
   tetap tidak simetris.
8. **Event `system` belum ada pengirim**; juga belum ada event untuk kondisi
   operasional (kamera mati, node restart, config apply) padahal tabel `alert`
   dan UI sudah mampu menampilkannya.
9. **person_detect** masih terdaftar sebagai tipe produksi di `ALLOWED_TYPES`
   padahal resminya debug-only (flag `VISION_EMIT_PERSON_DETECT`, default false).
10. **`ai_fps` seragam 5 fps** untuk semua kamera; tidak ada override per
   kamera, padahal beban deteksi bergantung kamera (LORONG vs TANGGA).

## 10. Terminologi R5a + motion gate (terpasang 2026-09-22)

Kosakata zona yang berlaku sekarang (menggantikan `restricted`/`free`/`absensi`):

| Lama | Sekarang |
|---|---|
| `zone.type = restricted \| free` | `zone.type = behavior` |
| `zone.type = absensi` | `zone.type = attendance` |
| `zone.dwell_seconds` (satu per zona) | `behaviors[].trigger_seconds` (satu per behavior) |
| `zone.loiter_seconds` | dilebur ke `trigger_seconds` behavior `loitering` |
| analyzer implisit dari tipe zona | `camera.analyzers` (master) × `zone.behaviors` (area + threshold) |

**Motion gate** (`vision/vision/motion.py`): inferensi YOLO hanya jalan saat frame
bergerak; objek diam tetap dicek tiap `force_interval_s`. Setelan global ada di
tabel `detector_setting` dan ditala lewat tab **Deteksi & Model → Advanced**,
bukan `.env` — precedence **DB > env**.

Terukur di `gspe-ai3` (5 kamera, `ai_fps=5`, 2026-09-22), dari `detect_n` di
heartbeat node:

| Keadaan | Pemanggilan detektor |
|---|---|
| gate ON | 2,41 /detik dan 4,13 /detik (dua sampel 60 s) |
| gate OFF | 25,00 /detik (= 5 kamera × 5 fps, plafon teoretis) |

Hemat ≈ 84–90% inferensi. Saat diam, laju turun ke ≈ `1/force_interval_s` per
kamera (0,5/detik) — yaitu jalur force-interval, bukan gate yang macet.

### Batas yang diketahui: `force_interval_s × ai_fps ≤ ByteTracker.max_age`

> **R5b status:** temuan ini ditutup di R5b Task 1 (`f9ee6be`) — track basi
> di-expire **sebelum** matching, sehingga gap melewati `max_age` tidak lagi
> menghidupkan ID lama (tes invarian umur vs gap). Seksi di bawah tetap
> dipertahankan sebagai catatan sebelum perbaikan.

`max_age = 15` dihitung **per frame**, sementara gap gate = `force_interval_s ×
ai_fps`. Pada setelan terpasang aman (2,0 × 5 = 10 ≤ 15), tapi menaikkan AI FPS
lewat tab Deteksi & Model merusak deteksi perilaku secara diam-diam:

| `ai_fps` | gap (frame) | track objek diam |
|---|---|---|
| 5 | 10 | hidup |
| 8 | 16 | **mati — id berganti tiap gap** |
| 10 | 20 | **mati** |
| 15 | 30 | **mati** |

Akibatnya timer `trigger_seconds` (loitering/intrusion) ter-reset terus dan
event tidak pernah terbit untuk orang yang berdiri diam. Schema API mengizinkan
`ai_fps` s/d 25, jadi ini bisa dipicu admin tanpa peringatan. Perbaikan yang
disarankan: ubah `ByteTracker.max_age` menjadi berbasis waktu (detik), bukan
hitungan frame. Dijaga oleh
`vision/tests/test_motion_gate.py::test_static_track_survives_the_gated_gap_at_deployed_settings`.

### Kesegaran frame (diperbaiki 2026-09-23, `ddf8599`)

Sebelumnya `FrameSource` membaca satu frame tiap `1/ai_fps` dari stream yang lebih
cepat, sehingga yang diproses adalah antrean buffer yang makin tua. Terukur di cam 363
(substream 15 fps, dibaca 5 fps): lag **+19,8 s setelah 30 s** dan terus naik. cam 362
dan 364 tidak punya substream (1080p 25 fps), jadi lebih parah. Semua analyzer, overlay
debugger, dan timer `trigger_seconds` berjalan di atas video lama, sementara crop main
stream diambil live. Akibatnya crop attendance meleset (lantai kosong → `no_face`).

Kini reader thread per kamera menguras stream pada fps aslinya dan hanya menyimpan
frame terbaru. Di stream nyata cam 363 selisih waktu tetap konstan selama 30 s.
Biayanya CPU vision-node naik dari ~23% ke ~64% dari satu core, karena semua frame
di-decode. Error `h264 error while decoding` turun dari 36 ke ≤8 per 5 menit.
