# Milestone Brief — Fase 2: Zona, Events, Clips, Web Inbox

> Brief. Dikembangkan menjadi plan detail setelah Fase 1 selesai.

**Goal:** Zona digambar di UI → vision-node mengeksekusi rule intrusion → event lengkap dengan clip (mainstream) + snapshot bisa diputar di web inbox. Bukti: orang melewati zona terlarang di kamera test → alert muncul di inbox + clip 1080p diputar.

**Prasyarat:** Fase 1 done (pipeline, MQTT event, live view).

## Scope

1. **Models**: `zone` (type free|restricted|absensi, polygon JSON norm 0–1 min 3 titik, schedule JSON, severity, rate_limit_min, snapshot/telegram/active), `alert` (event, channel, status, error), `event` + kolom clip_path/snapshot_path.
2. **Config push**: topic `isentinel/config/{node_id}` (retained) — backend publish config kamera+zona+analyzer; vision-node apply on-connect & on-change (restart pipeline ringan per kamera).
3. **Vision analyzer**: `intrusion.py` (polygon point-in-test pada track centroid + jadwal) + unit test CPU (polygon util, jadwal, fake tracks).
4. **Recorder service**: subscribe event → ambil buffer mainstream via go2rtc (pre 8s / post 30s) → mp4 ke `clips/YYYY/MM/DD/`; snapshot frame terbaik; update event path. Simpan ring buffer segment go2rtc (mp4 segments) — tanpa decode penuh.
5. **Web inbox**: halaman Events master-detail sesuai mockup 03 (filter, severity dot, player clip, metadata, aksi unduh); media endpoint auth (`/api/v1/media/...` stream file).
6. **Zone editor UI**: sesuai mockup 06 tab Zona — klik-titik min 3, tutup via klik titik awal, drag handle, properti (tipe, severity, jadwal, rate-limit), koordinat ternormalisasi; frame kamera dari go2rtc snapshot.

## Kriteria bukti

- [ ] Zona dibuat via UI → config ter-push → vision log analyzer aktif.
- [ ] Intrusi simulasi → event + clip + snapshot di DB; diputar di browser.
- [ ] Polygon min-3-titik + tutup-start-point ter-enforce (unit test + manual).
- [ ] `pytest backend vision -m "not gpu"` hijau; demo di server.

## Risiko

- Segment go2rtc + concat pre/post → pakai ffmpeg concat demuxer, tanpa re-encode (ponytail: jika GOP aneh per kamera → re-encode murah 1 stream, tercatat sebagai simplification).
- Koordinat polygon vs resolusi sub — normalisasi 0–1 di DB, denormalisasi runtime (unit test wajib).
