# Spec — Pengaturan LLM di UI (tab "AI Integration")

Status: **DISETUJUI di chat (2026-10-05)**, menunggu review spec tertulis.
Branch: `feat/ai-integration-settings` (dari `feat/ai-event-caption` @ `00e682e`; bergantung pada fitur itu, merge setelahnya).
Spec induk: `docs/superpowers/specs/2026-10-02-ai-event-caption-ask-design.md`.

---

## 1. Latar

Permintaan user (2026-10-05): konfigurasi API LLM yang sekarang hanya lewat `${DATA_DIR}/secrets/llm.env`
(butuh SSH + recreate `api`) dapat diatur dari UI, **hanya admin**, di tab baru bernama **"AI Integration"**
pada halaman Konfigurasi. Pemicu nyata: alamat endpoint LLM berubah saat server pindah jaringan, dan harus
bisa dicoba tanpa SSH.

## 2. Temuan kode

| # | Temuan | Lokasi | Dampak |
|---|---|---|---|
| 1 | Semua konsumen membaca `settings.llm_*` saat dipanggil, kecuali dua nilai yang dibuat sekali saat impor: `llm_client._semaphore` (`llm_concurrency`) dan antrean `AiWorker` (`ai_queue_max`) | `llm_client.py:31`, `ai_worker.py:28` | Semua field bisa diubah saat berjalan **kecuali** konkurensi dan ukuran antrean (tetap env, butuh recreate) |
| 2 | Pola rahasia: token Telegram di `secret_store` (file 0600 di luar `storage_root`), tidak pernah di-echo, hanya flag `configured`; setelan lain di tabel `setting`; semua `require_admin`; validasi sebelum efek samping | `api/telegram.py`, `services/telegram.py` | Ditiru untuk LLM |
| 3 | Pola nilai env sebagai fallback: baris `setting` menimpa env sampai admin menyimpan | `services/storage_settings.py` | Prioritas DB > env > default |
| 4 | Tab Konfigurasi: daftar `TABS` di `ConfigurationPage.tsx`; non-admin hanya melihat `storage`, tab lain tidak di-mount | `ConfigurationPage.tsx` | Tab baru otomatis tersembunyi untuk non-admin |
| 5 | `clean_error` meredaksi hanya `settings.llm_api_key` | `llm_client.py:34` | Tes koneksi memakai kunci dari form → redaksi harus menerima kunci tambahan |
| 6 | `Settings.model_fields_set` membedakan field yang diisi dari env dan field default | pydantic-settings | Sumber nilai ("env" vs "default") dapat ditampilkan |

## 3. Keputusan user

| Topik | Keputusan |
|---|---|
| Penempatan | **Tab baru** di Konfigurasi, bernama **"AI Integration"** (bukan kartu di Deteksi & Model) |
| Akses | **Hanya admin** (backend dan UI) |
| Prioritas nilai | DB (disimpan admin) > env (`llm.env`) > default kode; kolom kosong = kembali ke env |
| Kunci API | `secret_store`, tulis-saja; tidak pernah dikembalikan |

## 4. Tujuan dan kriteria sukses

**Tujuan:** admin dapat mengaktifkan/mematikan AI, mengganti URL/model/kunci, menyetel parameter, dan mencoba
koneksi dari UI tanpa SSH atau recreate container.

**Kriteria sukses** (diuji):
1. `GET/PUT /api/v1/ai/settings` dan `POST /api/v1/ai/settings/test`: 401 tanpa login, **403 untuk viewer**, 200 untuk admin.
2. Kunci API tidak pernah ada di respons, log, tabel `setting`, atau pesan galat (termasuk galat tes koneksi).
3. Perubahan URL/model/kunci/enabled/timeout/`max_tokens`/kuota/throttle/`extra_body` berlaku pada panggilan berikutnya tanpa restart.
4. Mengosongkan sebuah field mengembalikannya ke nilai env/default.
5. Tes koneksi memakai nilai form **tanpa menyimpan**; kunci kosong di form memakai kunci tersimpan.
6. Setelan yang ditolak (422) tidak mengubah apa pun (validasi sebelum efek samping).
7. Tab "AI Integration" tidak muncul dan tidak memanggil API untuk non-admin; 390 px tanpa overflow; semua string di `i18n.tsx` (`id` dan `en`).
8. Tes yang ada tidak diubah; perilaku tanpa setelan DB identik dengan sekarang.

**Non-tujuan:** penemuan daftar model dari endpoint, endpoint berbeda per kamera/zona, failover multi-endpoint,
riwayat rotasi kunci, mengubah konkurensi/ukuran antrean saat berjalan.

## 5. Desain

### 5.1 Penyimpanan
- Tabel `setting`, key `llm`, JSON berisi hanya field yang di-override admin: `enabled`, `api_url`, `model`, `max_tokens`,
  `timeout_caption_s`, `timeout_ask_s`, `ask_rate_per_min`, `caption_min_interval_s`, `extra_body`. Field yang tidak ada = ikut env/default. **Tanpa migrasi.**
- Kunci API: `secret_store` key `llm_api_key` (fallback env `LLM_API_KEY`).

### 5.2 Layanan `app/services/llm_config.py`
- Saat impor menyimpan salinan nilai awal `settings.llm_*` (`_BASE`) dan `_ENV_SET = set(settings.model_fields_set)`.
- `apply(db) -> None`: untuk tiap field, bila ada di baris `setting` maka `setattr(settings, "llm_<field>", nilai)`, selain itu
  kembalikan `_BASE`; kunci dari `secret_store` atau `_BASE`. Dipanggil saat startup (`lifespan`) dan setelah `PUT`.
  `# ponytail:` mengubah singleton `settings` (satu proses API; tidak aman untuk multi-worker, per-worker perlu muat ulang dari DB).
- `view(db) -> dict`: nilai efektif per field, `sources` (`db|env|default`), `key_configured: bool`, serta `restart_only: {concurrency, queue_max}` (nilai env, hanya baca).
- `save(db, values: dict, *, api_key: str | None, clear_api_key: bool) -> None`: validasi lengkap lebih dulu, lalu tulis `setting`/`secret_store`, commit, `apply`.
  Nilai `None` pada field menghapus override.
- `test_connection(db, values: dict, api_key: str | None) -> dict`: bangun `llm_client.Connection` dari nilai efektif + override form; panggilan 1 teks saja
  ("Balas satu kata: ok"), panggilan 2 dengan gambar JPEG sintetis 64×64; hasil `{ok, vision_ok, latency_ms, model, error}`; timeout 30 s per panggilan; `error` diredaksi (kunci form dan kunci tersimpan).
- Validasi: `api_url` http(s) ≤ 255; `model` ≤ 64; `enabled=true` mensyaratkan URL dan model terisi (efektif); `max_tokens` 100–8000;
  `timeout_*` 5–600; `ask_rate_per_min` 1–60; `caption_min_interval_s` 0–3600; `extra_body` objek JSON ≤ 2000 karakter tanpa kunci `messages`, `model`, `max_tokens`, `stream`.

### 5.3 `llm_client`
`Connection(url, api_key, model, extra_body, max_tokens)` + `current_connection()` (dari `settings`); `chat(messages, *, timeout, client=None, connection=None)`;
`clean_error(text, *secrets)` meredaksi `settings.llm_api_key` dan rahasia tambahan. Perilaku default tidak berubah.

### 5.4 API (`app/api/ai_settings.py`, `app/schemas/ai_settings.py`), semuanya `require_admin`
- `GET /api/v1/ai/settings` → `{enabled, api_url, model, max_tokens, timeout_caption_s, timeout_ask_s, ask_rate_per_min, caption_min_interval_s, extra_body, key_configured, sources, restart_only}`.
- `PUT /api/v1/ai/settings` (parsial, `exclude_unset`; `null` = hapus override; `api_key: str` mengganti kunci; `clear_api_key: true` menghapusnya) → respons seperti GET.
- `POST /api/v1/ai/settings/test` (body: field di atas + `api_key` opsional) → hasil §5.2.
- Perubahan dicatat di log: `user:<id>` dan **nama** field yang berubah, tanpa nilai.
- `GET /api/v1/ai/status` (semua pengguna login) tetap tanpa URL/model/kunci.

### 5.5 Frontend
- `ConfigurationPage`: `TABS` ditambah `'ai'` setelah `'notifications'`; label `configuration.tabAi` = **"AI Integration"** (id dan en).
- `features/config/AiIntegrationPage.tsx`, `api/aiSettings.ts`. Bagian **Koneksi**: `Toggle` aktif, `TextInput` URL dan model, `PasswordInput` kunci (kosong; keterangan "tersimpan" + tombol hapus kunci), tombol **Tes koneksi** (hasil: OK/vision OK/latensi/galat). Bagian **Lanjutan** (accordion): angka dan `extra_body`; lencana sumber (Env/DB/Default); catatan "konkurensi dan antrean: ubah lewat env, butuh restart". Tombol Simpan mengirim hanya field yang berubah.
- Carbon + token tema; 390 px tanpa overflow.

## 6. Penanganan galat dan keamanan
- Validasi gagal → 422 tanpa efek samping; `secret_store` gagal tulis → 500 "failed to store key" (tanpa nilai).
- Tes koneksi gagal → 200 dengan `ok:false` dan `error` terredaksi (bukan 5xx).
- URL ditentukan admin dan menerima snapshot serta kunci: diterima by design (hanya admin); skema selain http(s) ditolak.
- `setting` tidak pernah memuat kunci; `GET` tidak mengembalikan kunci; frontend tidak pernah menyimpan kunci di state setelah dikirim.

## 7. Pengujian
- Backend `test_llm_config.py`: prioritas env → DB → hapus → env; kunci dari `secret_store`; `apply` memulihkan `_BASE`; seluruh aturan validasi; `sources`.
- `test_ai_settings_api.py`: 401/403/200; respons tidak memuat kunci; PUT parsial dan `null`; `clear_api_key`; 422 tanpa efek samping; `enabled` butuh URL+model; tes koneksi (`httpx.MockTransport`: ok, vision ditolak, timeout terredaksi, nilai form tidak menyimpan, kunci kosong memakai kunci tersimpan); `lifespan` memanggil `apply`.
- `test_llm_client.py`: `connection` override dan `clean_error` dengan rahasia tambahan.
- Frontend `ai-integration.test.tsx`: tab tersembunyi untuk non-admin (tanpa panggilan API), render nilai, kunci tidak pernah terisi, simpan hanya field berubah, hasil tes koneksi, galat 403/422.

## 8. Rollout dan rollback
Tanpa migrasi. Deploy: `git pull` + `./docker/setup.sh` (rebuild `api` dan `web`). Rollback: `git revert`; `llm.env` tetap berlaku sebagai nilai awal. "Reset ke env": kosongkan field lalu simpan.

## 9. Risiko terbuka
| Risiko | Mitigasi |
|---|---|
| Mengubah singleton `settings` (satu proses) | Dicatat sebagai `ponytail:`; uvicorn berjalan satu proses |
| Konkurensi/antrean tidak hot-reload | Ditampilkan hanya-baca dengan keterangan |
| URL berbahaya oleh admin | Admin-only; hanya http(s) |
| Dua sumber nilai membingungkan | Lencana sumber per field di UI |

## 10. Dokumen yang diperbarui
`README.md`, `ARCHITECTURE.md`, `WORKFLOW.md`, `DESIGN.md`, `ROADMAP.md`, `CHANGELOG.md`, `docs/RUNBOOK.md` (UI sebagai cara utama; `llm.env` sebagai nilai awal), `AGENTS.md` bila struktur berubah.
