# Pengaturan LLM di UI (tab "AI Integration") — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Admin dapat mengatur koneksi dan parameter LLM dari tab baru "AI Integration" di Konfigurasi (termasuk tes koneksi), tanpa SSH atau recreate container.

**Architecture:** Nilai override disimpan di tabel `setting` (key `llm`), kunci API di `secret_store`; `llm_config.apply(db)` menimpakan nilai efektif ke singleton `settings` (konsumen tidak berubah) saat startup dan setelah simpan. `llm_client` menerima `Connection` eksplisit untuk tes koneksi dengan nilai form yang belum disimpan.

**Tech Stack:** FastAPI, SQLAlchemy 2 (tanpa migrasi), `httpx`, `secret_store`; React 19 + Carbon + Vitest.

**Spec:** `docs/superpowers/specs/2026-10-05-ai-integration-settings-design.md` (baca bersama plan ini; induk: `2026-10-02-ai-event-caption-ask-design.md`). Branch: `feat/ai-integration-settings` (dari `feat/ai-event-caption` @ `00e682e`).

## Global Constraints

- Hanya admin: backend `require_admin` pada ketiga endpoint; tab tidak di-mount untuk non-admin. `GET /ai/status` tidak berubah dan tanpa URL/model/kunci.
- Kunci API hanya di `secret_store` (key `llm_api_key`); tidak pernah di tabel `setting`, respons API, log, atau pesan galat. Log perubahan memuat `user:<id>` dan **nama** field, bukan nilai.
- `settings` hanya dimutasi di `llm_config.apply`. Tanpa migrasi, tanpa dependensi baru. Konkurensi dan ukuran antrean tetap env.
- Rentang: `max_tokens` 100–8000; `timeout_caption_s`/`timeout_ask_s` 5–600; `ask_rate_per_min` 1–60; `caption_min_interval_s` 0–3600; `api_url` http(s) ≤ 255; `model` ≤ 64; `extra_body` objek JSON ≤ 2000 karakter tanpa kunci `messages`, `model`, `max_tokens`, `stream`; `enabled=true` butuh URL dan model efektif terisi.
- Frontend: REST via `src/api/*`, string di `i18n.tsx` (**`id` dan `en`**), Carbon + token tema, 390 px tanpa overflow. Label tab: **"AI Integration"** (kedua bahasa).
- Commit per task, Conventional Commits, **tanpa atribusi AI**, jangan `git push`. Tes yang ada tidak diubah (kecuali Task 3 Step 3 bila tes tab menegaskan daftar tab). Backend dari `backend/`: `pytest tests -q -m "not gpu"`.

## Review Focus

1. `PUT` dengan satu field tidak valid **bersama** `api_key` valid → tidak ada yang tersimpan (kunci tidak ditulis) — Task 1.
2. `null` pada field numerik/`enabled` menghapus override dan mengembalikan nilai env/default (bukan menyimpan null) — Task 1.
3. Viewer memanggil endpoint mana pun, termasuk tes koneksi → 403 — Task 2.
4. Server LLM yang memantulkan kunci dari form → `error` hasil tes terredaksi — Task 1.
5. Membuka halaman tidak pernah mengisi kolom kunci, dan menyimpan tanpa menyentuhnya tidak mengirim `api_key` (tidak menghapus kunci tersimpan) — Task 3.

---

### Task 1: `llm_client.Connection` dan layanan `llm_config`

**Files:**
- Modify: `backend/app/services/llm_client.py`
- Create: `backend/app/services/llm_config.py`
- Test: `backend/tests/test_llm_client.py` (tambah), `backend/tests/test_llm_config.py`

**Interfaces:**
- Consumes: `Settings.llm_*`, `models.setting.Setting`, `secret_store.get/put/delete`.
- Produces (`llm_client`):
```python
@dataclass(frozen=True)
class Connection: url: str; api_key: str; model: str; extra_body: dict; max_tokens: int
def current_connection() -> Connection                       # dari settings.llm_*
def clean_error(text: str, *secrets: str) -> str             # meredaksi settings.llm_api_key + secrets
def chat(messages, *, timeout: float, client=None, connection: Connection | None = None) -> LlmResult
```
- Produces (`llm_config`):
```python
SETTING_KEY = "llm"; KEY_NAME = "llm_api_key"
FIELDS = ("enabled","api_url","model","max_tokens","timeout_caption_s","timeout_ask_s","ask_rate_per_min","caption_min_interval_s","extra_body")
class ConfigError(ValueError): ...
def apply(db) -> None
def view(db) -> dict          # nilai efektif per FIELDS + sources{field:"db|env|default"} + key_configured + restart_only{concurrency,queue_max}
def save(db, values: dict, *, api_key: str | None = None, clear_api_key: bool = False) -> None   # ConfigError sebelum efek samping; nilai None = hapus override
def test_connection(db, values: dict, api_key: str | None = None, *, client=None) -> dict       # {ok, vision_ok, latency_ms, model, error}
```
Atribut `settings` = `"llm_" + field`. Saat impor: `_BASE` = salinan nilai awal field dan kunci; `_ENV_SET` = `settings.model_fields_set`; `_overridden: set[str]` = field yang sedang ditimpa `apply`. **`apply` hanya menyentuh field di baris `setting` dan field yang sebelumnya pernah ditimpa**; DB kosong = no-op (kode lain dan tes memonkeypatch `settings`, mis. `llm_enabled=True` sebelum lifespan `TestClient`).

- [ ] **Step 1: Tulis tes gagal**
  - `test_llm_client.py`: `test_connection_override_is_used` (`connection=Connection(...)` → request ke URL, kunci, dan model itu, bukan `settings`); `test_clean_error_redacts_extra_secrets` (`clean_error("a sk-form b", "sk-form") == "a [redacted] b"`).
  - `test_llm_config.py` (fixture: `secret_store` diarahkan ke `tmp_path` seperti `test_secret_store.py`; `apply(db)` dalam fixture teardown memulihkan `settings`):
    - `test_precedence_env_db_clear`: `save(db, {"model": "m1"})` → `settings.llm_model == "m1"`, `view["sources"]["model"] == "db"`; `save(db, {"model": None})` → nilai awal dan sumber `default`; `save(db, {"max_tokens": None, "enabled": None})` juga memulihkan (Review Focus 2).
    - `test_key_only_in_secret_store`: `save(db, {}, api_key="sk-secret")` → `secret_store.get("llm_api_key") == "sk-secret"`, `view["key_configured"] is True`, `"sk-secret"` tidak ada di `json.dumps(view(db))` maupun baris `setting`; `settings.llm_api_key == "sk-secret"`; `clear_api_key=True` → `key_configured False` dan kunci kembali ke nilai awal.
    - `test_invalid_save_has_no_side_effects` (parametrize: URL `ftp://x`, model 65 karakter, `max_tokens` 99/8001, timeout 4/601, rate 0/61, interval -1/3601, `extra_body` non-dict / berisi `messages` / > 2000 karakter, `enabled=True` tanpa URL+model): `ConfigError`; baris `setting` dan `secret_store` tidak berubah **meskipun `api_key="sk-new"` ikut dikirim** (Review Focus 1).
    - `test_apply_restores_base_when_row_removed`; `test_apply_is_noop_when_nothing_overridden` (`monkeypatch.setattr(settings, "llm_enabled", True)` lalu `apply(db)` dengan DB kosong → tetap `True`); `test_sources_env` (`_ENV_SET` memuat `llm_model` → sumber `env`).
    - `test_connection_vision_and_errors` (`httpx.MockTransport` lewat `client=`): kedua panggilan sukses → `ok` dan `vision_ok`; permintaan bergambar dijawab 400 → `ok True`, `vision_ok False`; timeout dan server yang memantulkan `sk-form` → `ok False` dan `"sk-form" not in error` (Review Focus 4); nilai form tidak tersimpan (`db.get(Setting, "llm") is None`, `settings` utuh); `api_key=None` memakai kunci tersimpan (header `Authorization`).
- [ ] **Step 2:** `cd backend && pytest tests/test_llm_client.py tests/test_llm_config.py -q` → FAIL.
- [ ] **Step 3: Implementasi.** `llm_client.chat` memakai `connection or current_connection()`; `clean_error` meredaksi kunci `settings` dan `*secrets`. `llm_config`: `apply`, `view`, validasi (aturan di Global Constraints) di dalam `save` sebelum menulis apa pun; `test_connection`: panggilan 1 teks ("Balas satu kata: ok"), panggilan 2 dengan JPEG sintetis 64×64 (Pillow), timeout 30 s, kegagalan jadi `ok:false`, bukan raise; komentar `# ponytail: mengubah singleton settings (satu proses API); multi-worker perlu muat ulang dari DB per worker`.
- [ ] **Step 4:** perintah Step 2 → PASS; `pytest tests -q -m "not gpu"` hijau penuh.
- [ ] **Step 5: Commit** `feat(ai): llm_config (override DB/secret_store) dan Connection untuk tes koneksi`

---

### Task 2: API admin dan pemuatan saat startup

**Files:**
- Create: `backend/app/api/ai_settings.py`, `backend/app/schemas/ai_settings.py`, `backend/tests/test_ai_settings_api.py`
- Modify: `backend/app/main.py` (`include_router`; `llm_config.apply(db)` di blok startup `lifespan` yang sudah ada)

**Interfaces:**
- Consumes: `llm_config.view/save/test_connection/ConfigError` (Task 1), `require_admin`.
- Produces: `GET`, `PUT` `/api/v1/ai/settings` (`AiSettingsOut`; `AiSettingsIn` semua opsional + `api_key: str | None` + `clear_api_key: bool = False`, `exclude_unset`) dan `POST /api/v1/ai/settings/test` (`AiTestIn` = field opsional + `api_key`; `AiTestOut{ok, vision_ok, latency_ms: int | None, model: str | None, error: str | None}`). `ConfigError` → 422 `detail=str(exc)`; gagal tulis `secret_store` → 500 "failed to store key". Log `llm settings updated by user:<id> fields=[...]` (tanpa nilai).

- [ ] **Step 1: Tulis tes gagal** (fixture `client` dan header seperti `test_zones_api.py`; `viewer_headers`)
  - `test_endpoints_require_admin`: ketiganya 401 tanpa login, **403 viewer** (Review Focus 3), 200 admin.
  - `test_get_never_returns_key`: setelah `PUT api_key="sk-secret"` → seluruh teks respons GET dan PUT tidak memuat `sk-secret`; `key_configured true`.
  - `test_put_partial_null_and_clear`: PUT `{"model": "m"}` mengubah hanya model; `{"model": null}` mengembalikan; `{"clear_api_key": true}` → `key_configured false`; `enabled=true` tanpa URL+model → 422 dan GET tak berubah.
  - `test_test_endpoint_passes_form_values` (patch `llm_config.test_connection` dengan fake): nilai form dan `api_key` diteruskan; hasil fake dikembalikan apa adanya.
  - `test_lifespan_applies_db_settings`: baris `setting` `llm` berisi `{"model": "dari-db"}` dibuat sebelum `TestClient(app)` dimulai → `settings.llm_model == "dari-db"`.
- [ ] **Step 2:** `pytest tests/test_ai_settings_api.py -q` → FAIL.
- [ ] **Step 3: Implementasi** router sinkron (`def`), tanpa SQL di router; `save` menerima `body.model_dump(exclude_unset=True, exclude={"api_key", "clear_api_key"})` sebagai `values`; `apply` di `lifespan` dibungkus try/except dengan `logger.warning` (kegagalan tidak boleh menghentikan startup).
- [ ] **Step 4:** → PASS; `pytest tests -q -m "not gpu"` hijau penuh.
- [ ] **Step 5: Commit** `feat(ai): API admin pengaturan LLM dan tes koneksi`

---

### Task 3: Frontend — tab "AI Integration"

**Files:**
- Create: `frontend/src/api/aiSettings.ts`, `frontend/src/features/config/AiIntegrationPage.tsx`, `frontend/src/__tests__/ai-integration.test.tsx`
- Modify: `frontend/src/features/config/ConfigurationPage.tsx` (`TABS`, `TAB_LABEL`, `panels`), `frontend/src/app/i18n.tsx` (`id` dan `en`)

**Interfaces:**
- Consumes: endpoint Task 2; pola galat `api/telegram.ts`.
- Produces (`api/aiSettings.ts`):
```ts
export type AiSettings = { enabled: boolean; api_url: string; model: string; max_tokens: number; timeout_caption_s: number; timeout_ask_s: number; ask_rate_per_min: number; caption_min_interval_s: number; extra_body: Record<string, unknown>; key_configured: boolean; sources: Record<string, 'db' | 'env' | 'default'>; restart_only: { concurrency: number; queue_max: number } }
export type AiSettingsPatch = { [K in keyof Omit<AiSettings, 'key_configured' | 'sources' | 'restart_only'>]?: AiSettings[K] | null } & { api_key?: string; clear_api_key?: boolean }
export type AiTestResult = { ok: boolean; vision_ok: boolean; latency_ms: number | null; model: string | null; error: string | null }
getAiSettings(): Promise<AiSettings>; putAiSettings(p: AiSettingsPatch): Promise<AiSettings>; testAiSettings(p: AiSettingsPatch): Promise<AiTestResult>
```
- `TABS` menjadi `['cameras','zones','detection','notifications','ai','storage','nodes','users']`; kunci i18n `configuration.tabAi` = "AI Integration" dan `aiint.*` (judul, Koneksi, Lanjutan, label field, "tersimpan", hapus kunci, Tes koneksi, hasil, lencana sumber, catatan restart, galat).

- [ ] **Step 1: Tulis tes gagal** (`ai-integration.test.tsx`; ikuti `configuration.test.tsx` untuk peran viewer/admin dan stub `fetch`)
  - `test_tab_hidden_for_viewer_without_api_calls`: viewer tidak melihat tab "AI Integration" dan tidak ada `fetch` ke `/ai/settings`; admin melihatnya.
  - `test_renders_values_and_never_prefills_key`: nilai dari GET tampil; kolom kunci kosong; `key_configured` menampilkan "tersimpan" dan tombol hapus; lencana sumber tampil; catatan "butuh restart" menampilkan `restart_only`.
  - `test_save_sends_only_changed_fields`: ubah model → body PUT hanya `{model}`; **tanpa `api_key`** bila kolom kunci tak disentuh (Review Focus 5); mengisi kunci → ikut terkirim sekali dan kolom dikosongkan setelah simpan.
  - `test_test_connection_shows_result`: tombol memanggil POST dengan nilai form; tampil OK/vision OK/latensi atau galat; 422 dan 403 menampilkan pesan.
- [ ] **Step 2:** `cd frontend && env -u NODE_ENV npx vitest run src/__tests__/ai-integration.test.tsx` → FAIL.
- [ ] **Step 3: Implementasi.** Halaman: bagian **Koneksi** (`Toggle`, `TextInput` URL dan model, `PasswordInput` kunci, tombol Tes koneksi) dan **Lanjutan** (`Accordion`: angka dan `TextArea` `extra_body` dengan validasi JSON di klien); Simpan menonaktifkan tombol saat tak ada perubahan. Bila `configuration.test.tsx` menegaskan daftar/jumlah tab, perbarui hanya penegasan itu.
- [ ] **Step 4:** → PASS; `npx vitest run`, `npm run lint` (tanpa pasangan baru), `npx tsc -b --noEmit`, `npm run build` hijau. Cek 390 px bila tooling browser tersedia (stub API); bila tidak, tulis "belum diverifikasi".
- [ ] **Step 5: Commit** `feat(ai): tab AI Integration di Konfigurasi (admin)`

---

### Task 4: Dokumen dan verifikasi akhir

**Files:**
- Modify: `README.md`, `ARCHITECTURE.md`, `WORKFLOW.md`, `DESIGN.md`, `ROADMAP.md`, `CHANGELOG.md`, `docs/RUNBOOK.md`, `AGENTS.md` (hanya bila struktur berubah)

- [ ] **Step 1: Tulis dokumen.** UI "AI Integration" sebagai cara utama; `llm.env` sebagai nilai awal/fallback; prioritas DB > env > default; konkurensi dan antrean tetap env; rollback ("Reset ke env": kosongkan field). Baris ROADMAP `[~]`. Entri CHANGELOG (konteks, berkas, bukti, dampak, rollback) bertuliskan "BELUM diuji di server/UI nyata".
- [ ] **Step 2: Verifikasi dan tempel keluaran nyata:** backend `pytest tests -q -m "not gpu"`; `pytest docker/tests -q` dari root; vision tidak disentuh (`235 passed`); frontend `npx vitest run`, `npm run lint` dibanding `temp/prompt/ai-event-caption-lint-baseline.txt` per pasangan, `npm run build`. Berurutan.
- [ ] **Step 3: Commit** `docs: pengaturan LLM di UI (AI Integration)`

## Setelah plan selesai (di luar eksekusi)

Sesi perencanaan: review, `git push`, deploy (`./docker/setup.sh`, rebuild `api` dan `web`), uji UI admin dan viewer, tes koneksi ke endpoint nyata saat terjangkau, catatan CHANGELOG/ROADMAP, merge setelah `feat/ai-event-caption`.
