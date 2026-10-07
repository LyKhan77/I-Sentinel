# Caption AI di alert Telegram — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Setelah caption AI selesai, caption alert Telegram yang sudah terkirim di-edit untuk memuat teks AI (atau teks itu langsung ikut bila sudah siap saat alert dikirim), tanpa mengubah kecepatan alert.

**Architecture:** Alert menyimpan `message_id`; fungsi idempoten `alert_ai.sync_ai_caption` dipanggil dari dua titik (setelah dispatcher menandai `sent`, dan setelah `AiWorker` menyelesaikan caption `ok`) sehingga urutan apa pun menghasilkan tepat satu penambahan. `telegram.deliver` mengembalikan `Delivery` (tuple kompatibel) berisi `message_id`.

**Tech Stack:** FastAPI, SQLAlchemy 2 + Alembic, stdlib `urllib` (klien Telegram yang ada), pytest.

**Spec:** `docs/superpowers/specs/2026-10-06-telegram-ai-caption-design.md` (baca bersama plan ini). Branch: `feat/telegram-ai-caption` (dari `main` @ `ca6d16b`).

## Global Constraints

- Alert tetap terkirim tanpa menunggu LLM; edit tidak pernah memblokir atau mengubah status alert, baris caption, atau broadcast WS.
- Token bot tidak pernah di log, galat, atau respons (pola `_call`/`_clean`). Teks AI melewati `html.escape`; caption akhir ≤ `CAPTION_MAX` (1024) dengan margin 8 karakter untuk emoji.
- Hanya alert `sent`, ber-`message_id`, dikirim sebagai foto, dan belum `ai_synced` yang di-edit. Tanpa dependensi baru. Hanya backend; frontend tidak berubah.
- Tes yang ada tidak diubah. Tes Telegram memakai hook `telegram._urlopen`/`monkeypatch` (tidak ada jaringan nyata; fixture memblokir TCP).
- Commit per task, Conventional Commits, **tanpa atribusi AI**, jangan `git push`. Backend dari `backend/`: `pytest tests -q -m "not gpu"`.

## Review Focus

1. Caption AI sudah ada saat alert dikirim → ikut di pesan awal dan **tidak** ada edit (`ai_synced=True`) — Task 2.
2. Caption selesai di antara pembentukan caption alert dan commit status `sent` → tepat satu edit — Task 2.
3. Teks AI berisi `<`, `&`, newline, atau sangat panjang bersama nilai terpanjang lain → HTML valid dan ≤ 1024 — Task 1.
4. Telegram membalas "message is not modified" → dianggap sukses; galat lain → `ai_synced` tetap false tanpa raise — Task 1 dan 2.
5. `deliver` yang dipalsukan tes sebagai tuple polos `("sent", None)` tetap berfungsi (tanpa `message_id`) — Task 2.

---

### Task 1: Data dan klien Telegram

**Files:**
- Modify: `backend/app/models/alert.py`, `backend/app/services/telegram.py`
- Create: `backend/alembic/versions/0022_alert_telegram_message.py`
- Test: `backend/tests/test_telegram.py` (tambah), `backend/tests/test_migration_0022.py`

**Interfaces:**
- Produces (`Alert`): `message_id: int | None`, `message_photo: bool | None`, `ai_synced: bool` (default False).
- Produces (`telegram.py`):
```python
class Delivery(tuple):                      # isi (status, error); == tuple polos
    message_id: int | None; photo: bool
    def __new__(cls, status: str, error: str | None, message_id: int | None = None, photo: bool = False) -> "Delivery"
# deliver(...) -> Delivery  (message_id dari result["message_id"] bila dict; photo = foto dikirim)
def edit_caption(token: str, chat_id: str, message_id: int, caption: str, *, retries: int = 2, sleep=time.sleep) -> tuple[str, str | None]
#   ("edited", None) | ("failed", galat bebas token); "message is not modified" = ("edited", None); tidak pernah raise
def format_caption(event, camera_name, zone_name, app_url, tz=None, *, ai_text: str | None = None) -> str
```

- [ ] **Step 1: Tulis tes gagal**
  - `test_migration_0022.py` (gaya `test_migration_0021.py`; tabel `alert` minimal berisi satu baris): `upgrade` menambah tiga kolom dengan baris lama `message_id` NULL dan `ai_synced` false; `downgrade` menghapusnya (`batch_alter_table`).
  - `test_telegram.py`: `test_delivery_unpacks_and_equals_plain_tuple_and_carries_message_id` (balasan `{"ok": True, "result": {"message_id": 77}}` → `status, error = deliver(...)`; `deliver(...) == ("sent", None)`; `.message_id == 77`; `.photo is True` bila foto); `test_edit_caption_posts_edit_message_caption` (URL `.../editMessageCaption`, body memuat `chat_id`, `message_id`, `caption`, `parse_mode=HTML`); `test_edit_caption_not_modified_is_success` (HTTP 400 `description: "Bad Request: message is not modified"` → `("edited", None)`); `test_edit_caption_failure_has_no_token` (galat lain, 3 percobaan, `TOKEN not in galat`).
  - `format_caption(ai_text=...)`: `test_caption_ai_line_between_rows_and_link` (urutan: baris data, `🤖 <b>AI</b>: teks`, baris kosong, tautan); `test_caption_ai_text_is_escaped_and_whitespace_folded` (`"a <b> & c\n d"` → `a &lt;b&gt; &amp; c d`); `test_caption_with_ai_stays_within_limit` (setiap nilai 120 karakter, app_url panjang, teks AI 2000 karakter → `len(text) <= 1024`, berakhir dengan `…` pada baris AI, tag HTML tidak terpotong); `test_caption_without_ai_budget_drops_line` (anggaran < 40 → tanpa baris AI); `test_caption_without_ai_text_is_unchanged` (hasil sama persis dengan sebelum perubahan, termasuk semua tes caption lama).
- [ ] **Step 2:** `cd backend && pytest tests/test_telegram.py tests/test_migration_0022.py -q` → FAIL.
- [ ] **Step 3: Implementasi.** Model `Alert` + migrasi `0022` (`revision="0022"`, `down_revision="0021"`, `server_default=sa.false()` untuk Boolean); `Delivery` dan `deliver`; `edit_caption` (pola `deliver`, `editMessageCaption`); `format_caption` dengan anggaran `CAPTION_MAX - len(teks tanpa AI) - 1 - 8`: teks mentah dipotong dulu lalu di-escape, kurangi panjang sampai hasil escape muat (`…` bila terpotong); sisa < 40 → tanpa baris AI.
- [ ] **Step 4:** perintah Step 2 → PASS; `pytest tests -q -m "not gpu"` hijau penuh (tes alert/dispatcher lama tidak berubah).
- [ ] **Step 5: Commit** `feat(telegram): message_id alert, edit_caption, dan baris AI pada format_caption (migrasi 0022)`

---

### Task 2: `alert_ai` dan integrasi dispatcher

**Files:**
- Create: `backend/app/services/alert_ai.py`, `backend/tests/test_alert_ai.py`
- Modify: `backend/app/services/alert_dispatcher.py` (`process`), `backend/tests/test_alert_dispatcher.py` (tambah)

**Interfaces:**
- Consumes: `Alert` kolom baru, `telegram.Delivery/edit_caption/format_caption` (Task 1), `EventAi`.
- Produces:
```python
def ai_text(db, event_id: int) -> str | None                       # jawaban caption ok terbaru (kind="caption") atau None
def build_caption(db, alert: Alert, ai: str | None) -> str         # pembentukan caption yang kini ada di dispatcher, + ai_text
def sync_ai_caption(db, event_id: int) -> bool                     # idempoten; tidak pernah raise
```
`sync_ai_caption` melakukan edit hanya bila: `alert.status == "sent"`, `message_id` ada, `message_photo` true, `not ai_synced`, token dan chat aktif ada, dan `ai_text` ada. Sukses → `ai_synced = True` + commit → `True`; selain itu `False` (galat Telegram dicatat tanpa nilai rahasia, `ai_synced` tetap false).

- [ ] **Step 1: Tulis tes gagal** (fixture gaya `test_alert_dispatcher.py`: kamera, zona, event, `Alert`, `TelegramChat`, `telegram.set_token`; hook `telegram._urlopen` merekam permintaan)
  - `test_alert_ai.py`: `test_guards_skip_edit` (parametrize: status bukan `sent`, tanpa `message_id`, `message_photo` false, `ai_synced` true, tanpa caption `ok`, token kosong → `False` dan nol permintaan); `test_edit_adds_ai_line_and_marks_synced`; `test_failure_does_not_raise_or_mark_synced` (HTTP 500/400 lain; `ai_synced` false; `TOKEN not in caplog.text`); `test_not_modified_is_success`; `test_second_call_is_noop` (permintaan tepat satu).
  - `test_alert_dispatcher.py`: `test_ai_text_present_at_send_is_in_first_message_and_not_edited` (baris caption `ok` dibuat sebelum `process`; `deliver` palsu merekam caption berisi `🤖 <b>AI</b>`; setelah `process`: `message_id` tersimpan, `ai_synced is True`, nol edit — Review Focus 1); `test_caption_finishing_during_send_triggers_one_edit` (`deliver` palsu menyisipkan baris caption `ok` saat dipanggil; setelah `process` tepat satu `editMessageCaption` dan `ai_synced is True` — Review Focus 2); `test_plain_tuple_deliver_still_works` (fixture lama mengembalikan `("sent", None)`: status `sent`, `message_id` None, tanpa edit — Review Focus 5).
- [ ] **Step 2:** `pytest tests/test_alert_ai.py tests/test_alert_dispatcher.py -q` → FAIL.
- [ ] **Step 3: Implementasi.** `alert_ai.py`; `process` memakai `build_caption(db, alert, ai_text(db, event.id))`; setelah `deliver` simpan `message_id = getattr(result, "message_id", None)` dan `message_photo = getattr(result, "photo", photo is not None)`, `ai_synced = bool(ai) and status == "sent"`; setelah commit status panggil `sync_ai_caption(db, event.id)` dalam `try/except` yang hanya mencatat.
- [ ] **Step 4:** → PASS; `pytest tests -q -m "not gpu"` hijau penuh.
- [ ] **Step 5: Commit** `feat(telegram): caption AI masuk ke alert (sync idempoten, dispatcher)`

---

### Task 3: Hook `AiWorker`, dokumen, verifikasi

**Files:**
- Modify: `backend/app/services/ai_worker.py`, `backend/tests/test_ai_worker.py` (tambah), `README.md`, `ARCHITECTURE.md`, `WORKFLOW.md`, `docs/RUNBOOK.md`, `AGENTS.md` (migrasi terbaru `0022`, `alert_ai` di daftar service), `CHANGELOG.md`, `ROADMAP.md`

**Interfaces:**
- Consumes: `alert_ai.sync_ai_caption` (Task 2).

- [ ] **Step 1: Tulis tes gagal** (`test_ai_worker.py`, fixture `setup` yang ada): `test_ok_caption_triggers_alert_sync` (spy pada `alert_ai.sync_ai_caption` terpanggil sekali dengan `ev.id` setelah `process` sukses; **tidak** terpanggil saat caption `failed`); `test_sync_error_does_not_change_caption_row` (spy melempar `RuntimeError` → baris tetap `ok`, `process` tidak raise, broadcast tetap terkirim).
- [ ] **Step 2:** `pytest tests/test_ai_worker.py -q` → FAIL.
- [ ] **Step 3: Implementasi** pemanggilan di `AiWorker.process` setelah commit dan broadcast: `if row.status == "ok": try: alert_ai.sync_ai_caption(db, row.event_id) except Exception: logger.exception(...)` dengan komentar `# ponytail:` (thread worker; pindah ke antrean terpisah bila Telegram lambat terbukti menunda caption).
- [ ] **Step 4:** → PASS. **Dokumen:** alur "caption AI di alert Telegram" (README bagian Alert Telegram; ARCHITECTURE; WORKFLOW §Telegram dan §8.1), catatan prasyarat `app_url` ke port web (`7700`) di RUNBOOK, baris ROADMAP `[~]`, entri CHANGELOG (konteks, berkas, bukti, dampak, rollback) bertuliskan "BELUM diuji di server/Telegram nyata".
- [ ] **Step 5: Verifikasi dan tempel keluaran nyata:** `pytest tests -q -m "not gpu"` (dari `backend/`), `pytest docker/tests -q` (root), vision tidak disentuh (`235 passed`); migrasi: `test_migration_0022.py` dua siklus.
- [ ] **Step 6: Commit** `feat(ai): AiWorker menyinkronkan caption AI ke alert Telegram` lalu `docs: caption AI di alert Telegram`.

## Setelah plan selesai (di luar eksekusi)

Sesi perencanaan: review, `git push`, deploy (`./docker/setup.sh`, rebuild `api`; migrasi `0022`), koreksi `app_url` ke `http://192.168.2.133:7700` di Konfigurasi → Notifikasi, uji alert nyata (picu loitering di zona ber-`ai_caption` dan `telegram`; periksa pesan di grup ter-edit tanpa notifikasi ganda dan urutan terbalik bila LLM cepat), catat hasil, merge.
