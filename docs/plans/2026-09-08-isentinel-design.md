# I-Sentinel — Design Spec

Tanggal: 2026-09-08 · Status: menunggu review user · Mockup: `mockup-ui/`

Sistem AI surveillance CCTV untuk area pabrik + kantor: absensi wajah entry/exit,
person detection & tracking, behavior detection (intrusi zona, loitering, lari),
zone-based rules, event clips + snapshots, alerting Telegram, web UI Carbon dark.

---

## 1. Requirements (hasil diskusi)

| Area | Keputusan |
|---|---|
| Kamera | IP/RTSP yang sudah ada; probe mainstream + substream; AI dari substream, clip dari mainstream. Min 1080p, max 4K, campuran. Target 30+ kamera |
| Behavior v1 | Intrusi zona, loitering, lari (rule-based di atas person-tracking) |
| Behavior v2 | Fall detection, PPE |
| Absensi | Enrollment sendiri (upload foto saja, min 3 pose, max 5); zona pemicu di kamera gate; entry & exit kamera terpisah (satu kamera = satu arah); <100 wajah; snapshot evidence toggle per gate; shift + status telat; status "NO EXIT" bila belum exit 1 jam setelah akhir shift; export/import CSV/Excel |
| Rekaman | Event-only (clip pre/post buffer), retensi 30 hari, auto-cleanup |
| Live view | go2rtc (WebRTC/MSE); grid + klik = fokus + double-click = fullscreen |
| Alert | Telegram + web inbox, fire-and-forget (tanpa workflow ack), rate-limit anti-spam per kamera+zona+tipe |
| User | 2 role: admin (penuh), viewer (read-only); UI bilingual ID/EN |
| Edge | Server-first; Jetson Orin Nano menyusul; store-and-forward; MQTT QoS1 + LWT |
| Infra | Dev: RTX 4090 (+2×5080, 128GB RAM, NVMe 1TB); production GPU 4090; native processes dulu, Docker menyusul setelah sistem jadi |
| UI | IBM Carbon Design dark (Gray-100), IBM Plex Sans, tanpa emoji, sidebar collapsible. Mockup disetujui di `mockup-ui/` |

Non-goals (v1): continuous recording, workflow acknowledge alert, multi-lokasi,
HR integrasi API, retraining model, DeepStream.

## 2. Arsitektur

```
                        SERVER UTAMA (GPU)
┌──────────────────────────────────────────────────────────────┐
│  go2rtc — gerbang tunggal RTSP (probe, live, source clip)    │
│    ├─▶ vision-node (Python)                                  │
│    │    decode sub @AI-fps → YOLO person (TensorRT FP16)     │
│    │    → ByteTrack → analyzers (intrusi/loitering/lari)     │
│    │    → face detect + crop best-shot (kamera gate)         │
│    │    → event MQTT QoS1 + crop/clip HTTP upload            │
│    └─▶ recorder — potong mainstream pre/post → clips/        │
│  Mosquitto — event, heartbeat/LWT, config push               │
│  FastAPI — consume event → face match (InsightFace) →        │
│    absensi → alert (Telegram+web) → REST/WS untuk UI         │
│  PostgreSQL — semua state permanen                           │
│  Disk — clips/ snapshots/ faces/ (path di DB)                │
└──────────────────────────────────────────────────────────────┘
   ▲ edge phase: vision-node+go2rtc pindah ke Jetson; pola
     komunikasi (MQTT + HTTP blob) tidak berubah
```

Keputusan kunci:
1. **go2rtc gerbang tunggal** — satu koneksi RTSP per stream per kamera; probing
   main+sub, live view (WebRTC/MSE), dan sumber clip rekaman semuanya lewat go2rtc.
2. **AI di substream @ 5 FPS default** (override per kamera di config Deteksi);
   mainstream hanya direkam saat event (pre 8s / post 30s, configurable).
3. **Face recognition di server** (InsightFace ArcFace, gallery <100 embedding):
   satu DB wajah, nol sync antar edge, biometrik terkonsentrasi (PDP). Edge hanya
   mengirim crop best-shot ~20–50 KB. Absensi tidak latensi-kritis (bukan akses pintu).
4. **MQTT QoS1 + LWT + queue disk** = store-and-forward: event tidak hilang saat
   koneksi putus; edge mati terdeteksi otomatis (LWT); timestamp asli dibawa event.
   Event UUID → idempotensi di server (unique key, duplikat QoS1 dibuang).
5. **Media = filesystem** + path di DB (MinIO/S3 hanya jika multi-server nanti).
6. **vision-node modular**: pipeline tetap (decode → detect → track → analyze →
   emit); setiap fitur visi = satu analyzer (kelas dengan interface: frame+tracks
   masuk, event keluar). Analyzer baru (fall, PPE) = tambah modul + daftar di
   registry; core tidak diubah. Registry sederhana, tanpa plugin loader eksotis.

### Skala & performa
- Server 4090: 30–40 substream × 5 FPS ≈ 150–200 inferensi/s — YOLO11s TensorRT
  FP16 640px (~3–4 ms) jauh di atas kebutuhan; decode substream kecil = ringan.
- Jetson Orin Nano (~40 TOPS): ~4–8 kamera per unit @ 5 FPS.
- Validasi beban 30+ stream sintetis (ffmpeg loop → go2rtc) di Fase 5.

## 3. Model data (PostgreSQL)

```
users            id, username, password_hash, role(admin|viewer), locale
cameras          id, name, location, rtsp_main, rtsp_sub, node_id, enabled,
                 probe_main json {res,fps,codec}, probe_sub json, status
nodes            id, name, type(server|edge), last_seen, status
zones            id, camera_id, name, type(free|restricted|absensi),
                 direction(entry|exit, utk absensi), polygon json (norm 0–1,
                 min 3 titik), schedule json, thresholds json (durasi loitering,
                 kecepatan lari), severity, rate_limit_min, snapshot bool,
                 telegram bool, active bool
employees        id, name, employee_code, shift_id, active
face_embeddings  employee_id, vector float[512], source_image_path, quality, created
shifts           id, name, start_time, end_time, tolerance_min, workdays json
attendance_events id, employee_id, camera_id, zone_id, direction,
                 ts_event (waktu di gerbang), ts_created, face_match_score,
                 snapshot_path, source(event_id)
attendance_days  employee_id, date, first_entry, last_exit, duration_min,
                 status(ontime|late|waiting|no_exit|absent), late_minutes
events           id uuid, camera_id, zone_id, type(intrusion|loitering|running|
                 attendance|system), severity, ts_event, payload json,
                 clip_path, snapshot_path, dedup_key UNIQUE, node_id
alerts           event_id, channel(telegram|web), chat_id, status(sent|failed|
                 rate_limited), error, ts
telegram_chats   id, label, chat_id, active
settings         key, value json  (rate-limit default, retensi, path storage)
```

Snapshot enrollment: min 3 foto per karyawan (pose beda), max 5; wajah belum
lengkap tidak ikut matching. Hapus data biometrik per karyawan = hapus embedding
+ foto; riwayat absensi tetap (PDP-ready).

## 4. Logika deteksi (vision-node, per analyzer)

| Analyzer | Cara kerja | Parameter |
|---|---|---|
| Intrusion | track center masuk polygon zona `restricted` dalam jadwal aktif → event | jadwal, severity |
| Loitering | track berada di zona > durasi N dtk → event; track tidak dihapus, watch lanjut; event ulang hanya bila keluar-masuk lagi | durasi dtk |
| Running | kecepatan track > threshold (m/s via skala pixel→meter per kamera, garis referensi; knob kalibrasi) → event | m/s, zona |
| Face gate | kamera gate: track masuk zona `absensi` → pilih frame dgn wajah terbesar/terjelas → crop dikirim ke server | — |

Event flow: analyzer → emit(event UUID, camera, zone, ts, payload) → MQTT
`isentinel/events` QoS1 → FastAPI consumer → face match (untuk attendance) →
DB → alert engine (rate-limit key kamera+zone+tipe; Telegram bila zone.telegram
& belum kirim dalam window; sisanya web inbox saja) → recorder diminta clip
(pre/post buffer dari mainstream via go2rtc, ditulis ke clips/, path di-update).

Zona koordinat polygon tersimpan normalisasi 0–1 (kebal perubahan resolusi
stream); vision-node denormalisasi ke resolusi substream saat runtime.
Editor UI: klik-titik minimal 3, tutup polygon dengan klik titik awal
(ring start-point), drag handle edit, klik kanan hapus titik (min 3).

## 5. Absensi

- Trigger: tracked person masuk zona bertipe `absensi` di kamera gate + wajah
  dikenali (cosine match ≥ 0.40, default InsightFace, tunable per gate) →
  attendance_event (entry/exit sesuai arah gate).
- Satu kamera gate = satu arah (validasi DB + UI, mockup menampilkan KONFLIK).
- Rekap harian (attendance_days): first_entry, last_exit, durasi, status:
  - ontime / late (≥ shift.tolerance_min) / waiting (belum exit, masih dalam
    shift+1 jam) / **no_exit** (belum exit 1 jam setelah akhir shift → durasi
    tidak dihitung) / absent (tidak ada entry sampai akhir shift+toleransi).
- Admin override manual entry/exit dengan catatan audit.
- Export CSV/XLSX + import (untuk data historis/koreksi massal).

## 6. API & UI

REST (FastAPI, JWT httpOnly cookie, bcrypt):
`/auth`, `/cameras` (+ `/probe`), `/zones`, `/nodes`, `/gates`,
`/detection-config`, `/employees` (+ enrollment), `/attendance` (+ export/import),
`/events` (+ `/media/{clip|snapshot}`), `/alerts`, `/telegram`, `/users`,
`/settings`, `/ws` (live update dashboard/events).
Media dilayani lewat API dengan auth — disk tidak diekspos langsung.

UI (React + TS + @carbon/react, theme Gray-100 dark, Plex Sans, ID/EN toggle,
sidebar collapsible, tanpa emoji — lihat `mockup-ui/`):
- **Dashboard** — tile kamera/event/edge/absensi + strip alert terbaru
- **Live View** — grid go2rtc; klik = fokus + strip thumbnail; dbl-click = fullscreen
- **Events & Alerts** — master-detail: filter + daftar kiri; detail kanan: player
  clip + bbox overlay, metadata, aksi (live, unduh, false-positive)
- **Attendance** — tab harian/rentang/per-karyawan; summary; timeline entry-exit
  vs shift (toleransi kuning); status ontime/late/waiting/no_exit/absent
- **Enrollment** — daftar karyawan + galeri wajah (upload saja, min 3/max 5,
  skor kualitas); shift; hapus biometrik
- **Configuration** — 7 tab: Kamera (wizard + probe main/sub), Zona (klik-titik
  min 3, tutup via start-point, properti: tipe/severity/jadwal/rate-limit/
  snapshot/telegram), Gate Absensi (pasang kamera↔arah, validasi), Deteksi &
  Model (global + override per kamera: AI fps, confidence, analyzer on/off),
  Notifikasi (token env, chat target, uji kirim, rate-limit default),
  Retensi & Storage (path, retensi 30 hari, cleanup, estimasi disk),
  User (role, proteksi admin terakhir)

## 7. Security

- JWT httpOnly cookie + bcrypt; role admin/viewer di semua endpoint.
- Biometrik: embedding vektor (bukan foto sebagai identitas); endpoint enrollment
  admin-only; tombol hapus biometrik per karyawan; foto sumber hanya referensi admin.
- Kredensial kamera & Telegram token via env/config file — tidak pernah di repo/DB plaintext.
- CORS ketat; media via API auth; audit sederhana (admin override absensi).

## 8. Roadmap fase (stack terkunci sejak Fase 0; kriteria bukti per fase)

| Fase | Isi | Bukti selesai |
|---|---|---|
| 0 | Skeleton: FastAPI + React + DB + auth + kamera CRUD + probe | login + tambah kamera + probe main/sub tampil |
| 1 | Vision inti: 1–4 kamera nyata; deteksi+tracking; live view go2rtc | track stabil di UI |
| 2 | Zona + intrusion + events + clips/snapshots + web inbox | event intrusion menghasilkan clip yang bisa diputar |
| 3 | Loitering + running + Telegram + rate-limit | alert masuk Telegram dengan snapshot |
| 4 | Absensi: enrollment, face match, gate, shift, telat, export/import | siklus absensi penuh di kamera gate |
| 5 | Hardening: retensi 30 hari, uji 30 stream sintetis, docs | 30+ stream stabil, beban GPU tercatat |
| (nanti) | Edge/Jetson: pindah vision-node+go2rtc ke Orin Nano | event dari Jetson masuk tanpa perubahan server |

Pengujian: unit (analyzer logic, attendance status, rate-limit, idempotensi),
integrasi (MQTT→DB→alert), E2E manual per fase. Setiap fase berakhir dengan
demo yang bisa diulang + commit.
