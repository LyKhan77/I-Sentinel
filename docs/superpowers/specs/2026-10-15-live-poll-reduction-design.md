# Live Polling & DB Pool Hardening — Design Spec

- Tanggal: 2026-10-15
- Branch: `feat/live-poll-reduction` (dari `main` @ `e544634`)
- Status: disetujui user 2026-10-15 (pool 20+20/10 detik, A2 disertakan)

## 1. Latar Belakang & Tujuan

Setelah lima jendela TV (tiga Raspberry Pi) dan satu tab browser aktif bersamaan di production, API mengalami lonjakan
`sqlalchemy.exc.TimeoutError: QueuePool limit of size 5 overflow 10 reached, connection timed out, timeout 30.00`:
147 kejadian dalam 30 menit (±09:40–10:10 WIB), mengembalikan 500 pada `/events`, `/cameras/N/live`, `/nodes`,
`/monitoring/alerts`, `/cameras/N/snapshot` (±0,4% permintaan), dan 2 kali `Error handling MQTT message on
isentinel/nodes/server/heartbeat` (konsumen MQTT memakai pool yang sama). Tidak ada kehilangan event deteksi yang
terbukti; video tidak terpengaruh (mengalir lewat go2rtc). Lonjakan mereda setelah semua jendela selesai memuat.

Ukuran (nginx `web`, 2 menit, 6 klien): 925 permintaan API (7,7/detik); 528 di antaranya `/cameras/N/live`, karena **tiap
klien mengambil `/live` untuk semua 22 kamera setiap 30 detik, tanpa memedulikan `cameras=` di URL** (kamera nonaktif ikut);
338 `/events` (dua poller per jendela TV: `EventAlertsProvider` dan `LiveWall`, masing-masing tiap 5 detik); sisanya `/nodes`,
`/monitoring/alerts`, `/cameras`, `/snapshot`. Tiap permintaan sinkron memegang satu koneksi DB; `/snapshot` memegangnya
sampai go2rtc menjawab (maks 5 detik).

Tujuan: (A) mengurangi beban polling tanpa mengubah tampilan, (B) membuat API tahan terhadap lonjakan dan melindungi
jalur ingest (MQTT) dari kelaparan koneksi.

Non-goals: endpoint batch `/cameras/live`, cache snapshot, pendinginan CPU server, kamera 6 dan RTSP timeout go2rtc,
VPN, perubahan skema DB, perubahan perilaku kiosk atau URL.
Anti-goals: tile kosong 30 detik setelah pilihan kamera berubah; perubahan respons API; pool tak terbatas.

## 2. Keputusan Desain

| Keputusan | Pilihan | Sumber |
|---|---|---|
| Urutan | A (frontend) dulu, lalu B (backend), satu branch | user: "setuju" |
| `/live` hanya untuk kamera yang tampil | ya; kamera nonaktif tidak pernah diambil | user (A) |
| Pool DB | `pool_size` 20, `max_overflow` 20, `pool_timeout` 10 detik, lewat env | user (disetujui) |
| Poller `/events` ganda per jendela | satu langganan bersama (A2), disertakan | user (disetujui) |

## 3. Perubahan

### A1 — `useLiveCameras(wanted)`
- `useLiveCameras(wanted?: number[] | null)`: `undefined`/`null` = semua kamera aktif (perilaku lama, tanpa kamera nonaktif);
  array = irisan antara kamera aktif dan `wanted`. `getLive` hanya dipanggil untuk himpunan itu.
- Saat himpunan berubah (pemilih kamera, URL), kamera yang belum punya info langsung diambil (satu kali), tanpa
  mengambil ulang yang sudah ada; refresh 30 detik hanya untuk himpunan saat ini. `listCameras` tetap tiap 30 detik
  (juga menjaga sesi bergulir).
- `LiveTvPage` mengoper ID tampil (URL `cameras=` bila ada, kalau tidak pilihan tersimpan); `LiveViewPage` mengoper
  pilihan tersimpan layar `default`.

### A2 — satu langganan event per jendela
- `EventAlertsProvider` menyediakan `subscribeEvents(cb)`; `LiveWall` memakai itu, bukan `useLiveEvents` sendiri. Satu
  poller `/events` per jendela. Perilaku outline tile (30 detik) dan alert tidak berubah.

### B1 — pool DB dapat diatur
- `Settings`: `db_pool_size: int = 20`, `db_max_overflow: int = 20`, `db_pool_timeout: float = 10.0`.
- `app/core/db.py`: `create_engine(..., pool_pre_ping=True, pool_size=..., max_overflow=..., pool_timeout=...)` hanya untuk
  dialek non-SQLite (tes memakai SQLite `StaticPool`).
- Postgres `max_connections` bawaan 100; 40 koneksi dari satu proses API aman.

### B2 — lepas koneksi sebelum menunggu go2rtc
- `camera_snapshot` mengambil data kamera yang diperlukan lalu `db.close()` sebelum `httpx.get`. Respons dan kode status
  tidak berubah.

## 4. Pengujian dan Bukti
- Frontend (vitest): `getLive` hanya untuk ID tampil dan aktif; kamera nonaktif tidak diambil; perubahan himpunan memanggil
  hanya ID baru; refresh timer hanya himpunan saat ini; `LiveTvPage?cameras=2,1` memanggil `/live` untuk 1 dan 2 saja;
  `LiveViewPage` dengan pilihan tersimpan; A2: satu poller `/events` per jendela (hitung panggilan `fetch` pada timer palsu).
- Backend (pytest): default pool 20/20/10 dan override env; engine non-SQLite memakai nilai itu; snapshot menutup sesi DB
  sebelum `httpx.get` dipanggil dan tetap menghasilkan 200/404/502 seperti sebelumnya.
- Verifikasi penuh berurutan: pytest, vitest, build, lint (baseline 1112 / 579 / build 0 / lint 24).
- Bukti production (nginx `web`, jendela 2 menit): `/live` ≈76 (5 jendela TV) dari 528; total ≈ separuh dari 925; setelah memuat
  ulang Chromium di ketiga Pi bersamaan: 0 `QueuePool limit` dalam 1 jam.

## 5. Rollout dan Rollback
- Dev dulu (`gspe-ai3`): `./docker/setup.sh` (image `web` untuk A, `api` untuk B). Production: image dibangun di dev, dikirim
  (tag cadangan `*:prev-<tanggal>`, sha256), `run-setup.sh`. API restart beberapa detik; tidak ada perubahan env wajib
  (pool memakai bawaan baru).
- Rollback: tag cadangan atau `git revert`; env `DB_POOL_SIZE` dst. dapat menimpa nilai bawaan.
