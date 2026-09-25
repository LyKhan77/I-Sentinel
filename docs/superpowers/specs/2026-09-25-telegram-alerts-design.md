# Spec — Integrasi bot Telegram untuk alert

Status: **DISETUJUI di chat (2026-09-25)**, menunggu review spec tertulis.
Branch: `feat/telegram-alerts` (dari `main` @ `053df42`).
Checkpoint: `.cooper/context/next-features.md`.

---

## 1. Latar

Usulan user: *"fitur Integrasi bot Telegram kapan? masuk rencana prioritas mana?"* → disepakati **prioritas pertama**
(sebelum User management dan Retention UI): alert keamanan adalah requirement spec awal
(`docs/plans/2026-09-08-isentinel-design.md` §1 "alerting Telegram") dan saat ini kejadian hanya terlihat bila ada
yang membuka Inbox.

### Fondasi Fase 3 yang sudah ada (`main` @ `053df42`)

| Ada | Lokasi |
|---|---|
| Gate severity (`ALERT_MIN_SEVERITY`), flag `zone.telegram`, rate-limit per kamera+zona+tipe (`zone.rate_limit_min`) | `backend/app/services/alerting.py` `should_alert` |
| Kirim teks `sendMessage` ke chat aktif pertama, retry 3× backoff | `alerting.py` `_post`, `send_telegram` |
| Tabel `telegram_chat(label, chat_id, active)`, log `alert(event_id, camera_id, zone_id, type, severity, status, error, chat_id)` | `models/telegram_chat.py`, `models/alert.py` |
| `GET /api/v1/telegram/status` → `{configured, active_chats}`; chip status alert di Inbox | `api/telegram.py`, `EventsPage.tsx` |
| Setting key-value JSON | `models/setting.py` |
| File rahasia 0600 (`secret_store`) dari fitur pendaftaran kamera | `services/secret_store.py` |

### Temuan (kode + server, baca-saja)

| # | Temuan | Lokasi |
|---|---|---|
| 1 | Token di server kosong, 0 chat → `{"configured": false, "active_chats": 0}`; server menjangkau `api.telegram.org` (302, 0,55 s). | `.env`, API |
| 2 | Alert diputuskan **saat event masuk**, snapshot baru datang ±0,5 s kemudian lewat topik media → `sendPhoto` tak bisa ditempel di titik yang sama. | `events_consumer.py:59` |
| 3 | Kirim **sinkron** di thread konsumen MQTT (retry + `sleep`) → Telegram lambat/putus menahan ingest semua event. | `alerting.handle` |
| 4 | `alerting.handle` dipanggil **sebelum** `attendance.handle_face_event` → `match_reason` belum ada saat keputusan. | `events_consumer.py:57-66` |
| 5 | Toggle Telegram di Zona Deteksi disabled ("tersedia di Fase 3"). | `ZonesPage.tsx` |
| 6 | **Bug**: `GET /api/v1/alerts` → 500, `AlertOut.camera_id: int` padahal ada alert lama `camera_id = null`. | `schemas/alert.py:8` |
| 7 | Inbox tidak punya deep-link ke satu event. | `EventsPage.tsx` |

## 2. Keputusan user

| # | Keputusan |
|---|---|
| K1 | Penerima = **satu grup petugas**; anggota diatur di Telegram. Didaftarkan lewat UI: "Deteksi grup" → pilih → pesan uji. |
| K2 | Isi = **foto snapshot + caption**. Klip **tidak** dikirim; caption memberi info "lihat klip di aplikasi" + tautan. |
| K3 | Pemicu = **toggle Telegram per behavior, default off**, berlaku untuk **semua** tipe deteksi termasuk attendance dan behavior yang ditambah kemudian. |
| K4 | Attendance: kirim hanya **absensi tercatat** dan **wajah tidak dikenal**; lewati cooldown / sudah absen. |
| K5 | Token + grup diatur di **tab baru "Notifikasi"** di Konfigurasi; token disimpan lewat `secret_store`, tidak pernah ditampilkan lagi. |

## 3. Desain

### 3.1 Gerbang (`alerting.should_alert`)

- **Toggle per behavior**: item `zone.behaviors` boleh memuat `telegram: bool` (validator sama dengan
  `snapshot`/`clip`). Behavior yang dicari = item dengan `kind == event.type`. Nilai = `item.telegram` bila ada,
  selain itu `zone.telegram` (saat ini false di semua zona). Event tanpa zona → tidak dikirim.
- **`ALERT_MIN_SEVERITY` tidak lagi menjadi gerbang** (attendance ber-severity `info`); setting dibiarkan,
  deprecated.
- **Attendance** (`event.type == "attendance"`): kirim bila `payload.match_reason == "matched"` (absensi tercatat)
  atau `payload.employee_id is None and payload.match_reason == "no_match"` (wajah tidak dikenal). Alasan lain
  (`cooldown`, `already_in`, `low_quality`, `no_face`, `not_configured`) → tidak dikirim.
- **Rate-limit**: behavior dan wajah tidak dikenal → tetap per kamera + zona + tipe dalam `zone.rate_limit_min`
  (status `rate_limited` dicatat seperti sekarang). Absensi tercatat → **tanpa** rate-limit (duplikat sudah dicegah
  cooldown/already_in).
- `events_consumer`: urutan dibalik → `attendance.handle_face_event` dulu, baru `alerting.handle`.

### 3.2 Dispatcher asinkron (`backend/app/services/alert_dispatcher.py`, baru)

- `alerting.handle` hanya memutuskan, membuat baris `alert` dengan `status="queued"`, lalu `dispatcher.enqueue(alert.id)`
  — tidak ada I/O jaringan di thread konsumen.
- `AlertDispatcher`: satu thread daemon di proses API (start/stop di `lifespan` `app/main.py`), antrean
  `queue.Queue(maxsize=200)` (penuh → alert ditandai `failed` "queue full").
- Per alert: tunggu `event.snapshot_path` terisi maksimal **5 s** (cek DB tiap 0,5 s, sesi DB sendiri); ada →
  `sendPhoto` (multipart, file dari `storage_root`, **tidak** lewat URL publik); tidak ada / file hilang →
  `sendMessage` teks. Retry 3× backoff 1/2/4 s. Hasil → `alert.status = sent | failed | not_configured`,
  `alert.error` (maks 255 char, **tanpa token**).
- Token/grup belum diatur → `not_configured` tanpa panggilan jaringan.

### 3.3 Klien Telegram (`backend/app/services/telegram.py`, baru; stdlib `urllib`)

- `get_token()`: `secret_store.get("telegram_bot_token")`, fallback `settings.telegram_bot_token` (env).
- `set_token(token)`: validasi format `^\d+:[A-Za-z0-9_-]{30,}$`, lalu `getMe` → gagal → 422 "token ditolak Telegram";
  sukses → `secret_store.put`.
- `send_message(chat_id, text)`, `send_photo(chat_id, jpeg_bytes, caption)` (multipart), `get_updates()` → daftar unik
  `{chat_id, title, type}` dari `message.chat` / `my_chat_member.chat` bertipe `group`/`supergroup`.
- Error Telegram (`description`) dan exception jaringan dipotong 250 char; URL berisi token **tidak pernah** masuk
  log, pesan error, atau response.

### 3.4 Caption (`telegram.format_caption(event, camera, zone, app_url)`)

```
🚨 Intrusi — Lorong Server · zona Lorong-15
25 Sep 2026 11:42:07 WIB · severity warning
Klip video: lihat di aplikasi → http://192.168.2.133:5173/events?event=1234
```
- Label tipe: `intrusion` Intrusi, `loitering` Berlama-lama, `running` Berlari; attendance tercatat
  "✅ {nama} — Absen masuk/keluar {HH:MM} · {kamera}", tidak dikenal "⚠️ Wajah tidak dikenal — {kamera} · {zona}";
  tipe lain → nama tipe apa adanya (fallback generik untuk behavior baru).
- Waktu dalam zona waktu lokal server (`datetime.astimezone()`), format `%d %b %Y %H:%M:%S %Z`.
- Baris tautan hanya bila `app_url` terisi. Caption ≤ 1024 char (batas Telegram `sendPhoto`).

### 3.5 Setelan + API (`backend/app/api/telegram.py`, admin kecuali `/status`)

- Setting DB key `telegram` = `{"chat_id": str|null, "chat_title": str|null, "app_url": str|null}`; tabel
  `telegram_chat` dipakai sebagai satu baris aktif (grup terpilih) agar kompatibel dengan kode/tes lama.
- `GET /api/v1/telegram/settings` → `{has_token, chat_id, chat_title, app_url, last_alert: {status, error, created_at}|null}`.
- `PUT /api/v1/telegram/settings` body `{token?, chat_id?, chat_title?, app_url?}` (token write-only).
- `POST /api/v1/telegram/discover` → `{"chats": [{chat_id, title, type}]}` (butuh token).
- `POST /api/v1/telegram/test` → kirim "✅ Tes I-Sentinel — bot terhubung ke grup ini" ke grup terpilih; `{status, error}`.
- `GET /api/v1/telegram/status` tetap.
- `schemas/alert.py`: `camera_id: int | None` (fix 500).

### 3.6 Frontend

- **Tab "Notifikasi"** (`frontend/src/features/config/NotificationsPage.tsx`, tab `notifications` di Konfigurasi,
  sebelum Penyimpanan): (1) token — `PasswordInput` + Simpan; bila tersimpan tampil "Token tersimpan ✓" + Ganti;
  (2) grup — petunjuk "Tambahkan bot ke grup petugas, lalu kirim satu pesan di grup" + **Deteksi grup** + daftar
  pilih (radio) + Simpan; (3) **URL aplikasi** — default `window.location.origin`; (4) **Kirim pesan uji** + status
  alert terakhir.
- **Zona Deteksi**: baris behavior mendapat toggle **Telegram** (id `zone-telegram-<kind>`) di samping Snapshot/Clip;
  zona Absensi mendapat satu toggle Telegram yang menulis `telegram` di item behavior `attendance`. Toggle level zona
  disabled + key `zones.telegramFase3` dihapus. Default tampilan = `item.telegram ?? zone.telegram` (false).
- **Inbox**: `?event=<id>` memilih event itu (dan rentang "Semua waktu" bila event di luar rentang default).
- i18n `id` + `en` untuk semua string baru.

## 4. Penanganan error

| Kondisi | Perilaku |
|---|---|
| Token/grup belum diatur | alert `not_configured`, tanpa jaringan |
| Token salah saat disimpan | 422 "token ditolak Telegram" (dari `getMe`), token lama tetap |
| Telegram/internet putus | retry 3× di dispatcher → `failed` + pesan; ingest event tidak tertahan |
| Snapshot tidak datang ≤ 5 s / file hilang | kirim teks saja |
| Antrean penuh (200) | alert `failed` "queue full" |
| Bot dikeluarkan dari grup | `failed` dengan `description` Telegram (mis. "bot was kicked"); terlihat di tab Notifikasi |
| `getUpdates` tanpa grup | daftar kosong + petunjuk kirim pesan di grup |

## 5. Pengujian

- `test_alerting.py`: gerbang per behavior (fallback `zone.telegram`), attendance matched/no_match dikirim,
  cooldown/already_in/low_quality tidak; rate-limit behavior tetap, attendance matched tanpa rate-limit; urutan consumer
  (attendance sebelum alert); `handle` tidak memanggil jaringan (enqueue saja).
- `test_alert_dispatcher.py` (Telegram di-mock): tunggu snapshot lalu `sendPhoto`; timeout → `sendMessage`; retry lalu
  `failed`; `not_configured`; antrean penuh.
- `test_telegram.py`: `format_caption` (behavior, attendance tercatat/tidak dikenal, fallback tipe, tanpa app_url, ≤1024);
  `get_updates` parsing grup unik; token tidak muncul di pesan error.
- `test_telegram_api.py`: settings GET tanpa token; PUT token → `getMe` di-mock, 422 bila ditolak; discover; test;
  non-admin 403; 422 tidak menggemakan token; `GET /alerts` dengan `camera_id` null → 200.
- Validator `behaviors` menerima `telegram` bool.
- Frontend: tab Notifikasi (simpan token, deteksi+pilih grup, pesan uji), toggle Telegram per behavior + absensi,
  deep-link `?event=`, 390 px.
- Baseline `main` `053df42`: backend 370, vision 204 (3 deselected), frontend 127, build 0, lint set sama.

## 6. Verifikasi lapangan (butuh izin user)

Deploy API (restart; vision tidak berubah). User membuat bot di @BotFather + grup petugas; di tab Notifikasi: simpan
token → deteksi grup → pesan uji. Nyalakan Telegram pada intrusion zona 15 cam 363 → berdiri di zona → foto + caption
masuk grup ≤ 5 s, tautan membuka event di Inbox (dari LAN). Attendance (bila zona absensi diaktifkan): absen tercatat
dan wajah tidak dikenal terkirim; absen ulang (cooldown) tidak.

## 7. Di luar scope

Klip video ke Telegram; beberapa grup / filter per penerima; perintah bot (`/status` dll); jam kerja/senyap; webhook;
tautan publik di luar LAN.

## 8. Rollback

`git revert` + restart API. Tanpa migrasi DB (flag `telegram` per behavior di JSON, setting di tabel `setting`).
Token di `secret_store` tetap tersimpan (tidak dipakai kode lama kecuali env).
