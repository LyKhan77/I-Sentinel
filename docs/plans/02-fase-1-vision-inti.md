# Milestone Brief — Fase 1: Vision Inti

> Brief, bukan plan detail. Dikembangkan menjadi plan penuh (format Task/Step seperti
> `01-fase-0-skeleton.md`) SETELAH Fase 0 selesai — keputusan Fase 0 (model DB nyata,
> probe hasil aktual, layout server) akan mengubah detail di sini.

**Goal:** Person detection + tracking jalan end-to-end di 1–4 kamera nyata; event deteksi masuk DB; live view jalan di UI; dashboard tile hidup. Bukti: track person tampil stabil (overlay di live view atau log event) untuk kamera test di server.

**Prasyarat:** Fase 0 done (auth, kamera+probe, go2rtc service).

## Scope

1. **go2rtc integration** — backend menulis config stream per kamera (sub+main) dari DB; API `/cameras/{id}/live` → URL WebRTC/MSE untuk frontend.
2. **vision-node runtime** (`vision/`):
   - `pipeline/source.py` — ambil frame dari go2rtc RTSP (sub), decode, frame-skip ke AI fps per kamera.
   - `pipeline/detector.py` — YOLO11s (Ultralytics, TensorRT FP16 export) person-only.
   - `pipeline/tracker.py` — ByteTrack; tracks: id, bbox, centroid, umur, kecepatan.
   - `transport/mqtt.py` + `transport/queue.py` — publish event QoS1 + disk queue store-and-forward; heartbeat 10 s; LWT.
   - `node.py` — multi-kamera per proses (thread per kamera, model share).
3. **Backend consumer** — `services/events_consumer.py`: subscribe `isentinel/events` → insert `events` (idempotent by event_id) → broadcast WS.
4. **Models tambahan**: `event` (uuid, type, ts_event, payload JSON, dedup_key unique, camera/zone nullable), tabel `node` dipakai heartbeat.
5. **API**: `GET /api/v1/events` (filter kamera/tipe/waktu), `WS /api/v1/ws/events`.
6. **Frontend**: Dashboard tile (kamera online, event hari ini) + Live View grid (WebRTC via go2rtc; klik fokus, dblclick fullscreen) + halaman Events read-only sederhana (list + WS live).
7. **Internal API**: `POST /internal/nodes/{id}/blobs` (API key per node) — untuk crop/clip mulai Fase 2.

## Di luar scope (masuk fase lain)

Zona & analyzer (Fase 2–3), recorder clip (Fase 2), face (Fase 4), config push MQTT (Fase 2 — Fase 1 config via file/env).

## Kriteria bukti

- [ ] `pytest vision/tests -m "not gpu"` hijau (detector/tracker dengan frame sintetis; mock YOLO).
- [ ] Server: 1 kamera nyata → event `person_detect` (debug type) masuk DB < 2 s dari gerakan; heartbeat node tampil di dashboard.
- [ ] 4 kamera → GPU memori tercatat, FPS inferensi per kamera ≥ target (log).
- [ ] Live view 4 tile jalan di browser (WebRTC), latency < 1 s.
- [ ] Demo direkam/catat di plan.

## Risiko & mitigasi

- Decode substream varian codec → go2rtc transcode opsi per kamera (config), bukan kode custom.
- TensorRT export butuh mesin GPU → build engine di gspe-ai3 sekali, commit script `vision/scripts/export_engine.py` (bukan file engine).
- MQTT auth → bootstrap.sh buat user mosquitto + NODE_API_KEY di .env.
