# I-Sentinel — Fase 3: Loitering, Running, Alerting Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Analyzer loitering + running aktif dengan kalibrasi per kamera; alerting foundation: tabel alert, rate-limit anti-spam, dan pengiriman Telegram yang graceful-gagal bila token/chat belum dikonfigurasi. Bukti: demo loitering & running → event + baris alert tersimpan (status benar), rate-limit terbukti, inbox menampilkan badge alert.

**Prioritas user (dicatat):** fondasi Telegram dulu — token env + fungsi kirim + status di DB. **Integrasi chatID = low priority** (CRUD chat target & delivery nyata menyusul; tanpa konfigurasi harus tidak error, status `not_configured`).

**Architecture:** 2 analyzer baru mengikuti API existing (`Analyzer.on_frame` + registry). Kalibrasi px→m disimpan per kamera (kolom baru, nullable). Alerting service backend: consume event → evaluasi aturan (aktif, severity, rate-limit) → tulis `alert` row (sent|failed|rate_limited|not_configured) → kirim Telegram bila token+chat tersedia (retry 3×) → WS broadcast agar inbox badge update.

**Tech Stack:** existing + stdlib urllib (Telegram Bot API), tidak ada dep baru.

**Spec:** `docs/plans/2026-09-08-isentinel-design.md` §4–5 · Master: `docs/plans/00-master.md` · Brief: `docs/plans/04-fase-3-analyzers-alerting.md`

## Global Constraints

- Lihat master plan §Global Constraints — semua berlaku.
- Zero-secret: TELEGRAM_BOT_TOKEN hanya dari env; TIDAK pernah masuk DB/log/commit; chat_id di DB boleh (bukan secret).
- Analyzer tanpa kalibrasi TIDAK boleh menebak: running butuh `meters_per_pixel` — null → analyzer running dilewati + log info sekali per kamera (bukan spam log).
- Rate-limit key = `camera_id:zone_id:type`, window menit dari `zone.rate_limit_min` (default 5).
- Semua I/O eksternal (Telegram) tolerant: gagal → status `failed`, tidak pernah menggagalkan ingest.
- Tidak ada pengiriman Telegram nyata di test (mock urllib); tanpa token/chat → `not_configured` (bukan error).

---

### Task 1: Loitering analyzer (vision)

**Files:**
- Create: `vision/vision/analyzers/loitering.py`
- Modify: `vision/vision/analyzers/__init__.py` (registry), `vision/vision/node.py` (zone type → analyzer mapping)
- Test: `vision/tests/test_loitering.py`

**Interfaces:**
- Consumes: zone dict (id, type="restricted"→? NO: loitering dipakai di zona mana pun yang punya param `loiter_seconds>0`) — RULING: config push menambah field `loiter_seconds` (int, 0=off) & `speed_limit_mps` (float, 0=off) per zona (Task 3 backend); analyzer menerima keduanya dari zone dict dengan default aman.
- Produces: `LoiteringAnalyzer(zone: dict)` — track di dalam polygon: akumulasi dwell (dtk frame dengan ts); emit sekali ketika dwell ≥ loiter_seconds: payload {"zone_name", "track_id", "dwell_s", "bbox_norm"}; reset akumulasi saat track keluar polygon atau hilang; re-entry → akumulasi baru → bisa emit lagi (dengan rate-limit backend yang membatasi).
- Konfigurasi zona: `loiter_seconds: int` di payload zone config; node map: zona dengan `loiter_seconds > 0` → LoiteringAnalyzer (+ IntrusionAnalyzer hanya jika type=="restricted" — kedua analyzer boleh aktif bersamaan).

- [ ] **Step 1: Failing test** — (a) track masuk polygon, 5 frame × 2 dtk = 10 dtk < 15 → tidak emit; (b) lanjut sampai 16 dtk → emit 1×; (c) lanjut 30 dtk lagi → tetap 1 emit; (d) keluar polygon → dwell reset; masuk lagi 16 dtk → emit ke-2; (e) track hilang dari daftar → state dibersihkan.
- [ ] **Step 2: Run — verify fail** (`cd vision && .venv/Scripts/python.exe -m pytest tests/test_loitering.py -v`)
- [ ] **Step 3: Implement** (state `_dwell: dict[track_id, float]` = durasi akumulatif; per frame: untuk track di polygon hitung delta ts (clamp agar ts non-monotonic tidak negatif); `_emitted: set[track_id]` cegah emit ganda sampai keluar).
- [ ] **Step 4: Run — pass** + full vision suite.
- [ ] **Step 5: Commit** — `feat: loitering analyzer (dwell per zone)`

---

### Task 2: Running analyzer (vision, butuh kalibrasi)

**Files:**
- Create: `vision/vision/analyzers/running.py`
- Modify: `vision/vision/analyzers/__init__.py`, `vision/vision/node.py` (map `speed_limit_mps>0` → RunningAnalyzer; lewati bila `meters_per_pixel` null), `vision/vision/config.py` (CameraCfg + meters_per_pixel)
- Test: `vision/tests/test_running.py`

**Interfaces:**
- Produces: `RunningAnalyzer(zone: dict, meters_per_pixel: float)` — kecepatan = `|Δcentroid| / Δt × meters_per_pixel` (m/s) memakai EMA velocity track (atan langsung okay v1: hitung dari selisih centroid antar frame analyzer) ; emit bila speed > `speed_limit_mps`: payload {"zone_name", "track_id", "speed_mps", "bbox_norm"}; cooldown per track 5 dtk (hindari emit tiap frame saat pelari cepat terus-terusan).
- node.py: analyzer dibuat hanya jika `cam.meters_per_pixel is not None` dan `zone.speed_limit_mps > 0`; else log info sekali: "running analyzer skipped camera X (no calibration)". Kalibrasi cara hitung: user ukur 1 objek diketahui (mis. lebar pintu 0.9 m = N px) → meters_per_pixel = 0.9/N → diisi via API (Task 3).

- [ ] **Step 1: Failing test** — (a) track bergerak 0.01 norm/dtk @ mpp=10 (≈0.1 m/s) di bawah limit 2.0 → tidak emit; (b) 0.3 norm/dtk → ≈3 m/s > limit → emit dengan speed_mps ±benar; (c) cooldown: frame berikutnya masih cepat → tidak emit lagi sebelum 5 dtk; (d) mpp None → analyzer tidak dibuat.
- [ ] **Step 2: Run — verify fail** → **Step 3: Implement** → **Step 4: pass** + suite
- [ ] **Step 5: Commit** — `feat: running analyzer (calibrated m/s)`

---

### Task 3: Backend — zone loiter/speed fields + camera calibration + alert model

**Files:**
- Create: `backend/alembic/versions/0004_alerting.py`, `backend/app/models/alert.py`
- Modify: `backend/app/models/zone.py` (+loiter_seconds int default 0, +speed_limit_mps float default 0), `backend/app/models/camera.py` (+meters_per_pixel float nullable), `backend/app/schemas/{zone,camera}.py`, `backend/app/services/config_push.py` (kirim field baru + meters_per_pixel per kamera), `backend/app/models/__init__.py`
- Test: `backend/tests/test_alert_model.py` (migrasi fields via SQLite create_all + validasi schema)

**Interfaces:**
- Produces:
  - zone: `loiter_seconds: int = 0` (0=off), `speed_limit_mps: float = 0` (0=off)
  - camera: `meters_per_pixel: float | None` (null = belum dikalibrasi)
  - `Alert(id, event_id FK event.id (unique), camera_id, zone_id nullable, type, severity, status: sent|failed|rate_limited|not_configured, error nullable, chat_id nullable, created_at)` — unique per event (1 event = maks 1 alert row; rate-limited pun tercatat).
  - config_push: zone dict menyertakan 2 field baru; camera dict menyertakan meters_per_pixel.
- Migration 0004 hand-written (down_revision 0003).

- [ ] **Step 1: Failing test** — schema zone menerima loiter_seconds/speed_limit_mps (validasi ≥0); camera PATCH meters_per_pixel; Alert unique event_id.
- [ ] **Step 2: verify fail** → **Step 3: implement + migration** → **Step 4: pass** (full suite)
- [ ] **Step 5: Commit** — `feat: alert model + zone analyzer params + camera calibration`

---

### Task 4: Alerting service (rate-limit + Telegram foundation)

**Files:**
- Create: `backend/app/services/alerting.py`
- Modify: `backend/app/services/events_consumer.py` (hook: setelah ingest created → `await/run alerting.handle(db, event)`), `backend/app/core/config.py` (+telegram_bot_token ada? verifikasi; +alert_min_severity: str = "warning")
- Test: `backend/tests/test_alerting.py` (freeze time via monkeypatch, mock urllib)

**Interfaces:**
- Produces:
  - `should_alert(db, event) -> tuple[bool, str]` — rules: severity ≥ alert_min_severity (info < warning < critical); zone aktif & zona.telegram (jika zone ada); rate-limit: ada Alert row untuk key (camera:zone:type) dalam `rate_limit_min` terakhir dengan status in (sent, not_configured, failed)? RULING: rate-limit menghitung SEMUA alert row pada key+window (apapun statusnya) — sederhana dan anti-spam.
  - `handle(db, event) -> Alert | None` — jika should_alert: kirim (bila token+chat aktif) → tulis Alert(status) → hub.broadcast({"kind":"alert", ...}).
  - `send_telegram(text: str, photo_path: str | None) -> tuple[str, str|None]` — token dari settings; chat dari tabel telegram_chats aktif (model Fase 2? TIDAK ADA — RULING: tabel `telegram_chat` dibuat Task 4 ini juga: id, label, chat_id unique, active bool) ; tanpa token ATAU tanpa chat aktif → return ("not_configured", None) tanpa network call; else POST sendPhoto (bila snapshot) atau sendMessage via urllib, timeout 10s, retry 3× (2^attempt sleep), return ("sent"|"failed", error).
- Analysis: severity ordering helper `SEVERITY_ORDER = {"info": 0, "warning": 1, "critical": 2}`.

- [ ] **Step 1: Failing test** — (a) event info severity → no alert (below min); (b) critical + no token → Alert not_configured, urllib NOT called; (c) critical + token + chat + urllib mock ok → status sent, Alert row ada, broadcast dipanggil; (d) event kedua dalam window → rate_limited (row ditulis, urllib tidak dipanggil); (e) setelah window (freeze time +6 mnt) → alert lagi; (f) urllib error → failed + retry 3x terbukti (call count).
- [ ] **Step 2: verify fail** → **Step 3: implement + telegram_chat model & migration (bundle di 0004)** → **Step 4: pass** (full suite)
- [ ] **Step 5: Commit** — `feat: alerting service (rate-limit, telegram foundation)`

---

### Task 5: Alerts API + UI (badge, tab Notifikasi minimal)

**Files:**
- Create: `backend/app/api/alerts.py` (GET /api/v1/alerts?event_id, PATCH /api/v1/telegram/chats placeholder? RULING: chats CRUD di SKIP fase ini — low priority; cukup GET /api/v1/telegram/status → {configured: bool, active_chats: int})
- Modify: `backend/app/main.py`, `frontend/src/features/events/EventsPage.tsx` (badge status alert per event: TELEGRAM TERKIRIM/RATE-LIMITED/NOT CONFIGURED dari GET /alerts?event_id event terpilih / list menyertakan status), `frontend/src/api/alerts.ts`, i18n
- Test: `backend/tests/test_alerts_api.py`, `frontend/src/__tests__/alerts.test.tsx`

**Interfaces:**
- Produces: GET /api/v1/alerts?event_id=&limit= (auth) → list AlertOut; frontend: badge di detail event + kolom status di list (fetch alerts untuk event yang tampil, map by event_id); tab Notifikasi: chip status "Telegram: belum dikonfigurasi" / "siap (N chat)" — READ-ONLY (CRUD menyusul).

- [ ] **Step 1: Failing test** — API list filter event_id; frontend: detail menampilkan badge RATE-LIMITED bila alert row rate_limited; status chip not_configured.
- [ ] **Step 2: verify fail** → **Step 3: implement** → **Step 4: pass** (backend + vitest + build)
- [ ] **Step 5: Commit** — `feat: alerts api + inbox badge + telegram status chip`

---

### Task 6: Bring-up verifikasi di server (controller)

- [ ] Deploy + migration 0004 di server (`alembic upgrade head`)
- [ ] Update zona test: set `loiter_seconds=15`, `speed_limit_mps=2.5`; set camera 5 `meters_per_pixel` (ukur dari snapshot: estimasi kasar 1080p lebar pintu — catat angkanya)
- [ ] Restart vision-node → verifikasi analyzer aktif di log
- [ ] Demo: orang berdiam di zona → loitering event; orang berjalan cepat → running event (bila tidak memungkinkan, turunkan limit sementara — catat sebagai bukti fungsional)
- [ ] Verifikasi rate-limit: ≥2 event sama dalam window → 1 alert sent/not_configured + sisanya rate_limited di tabel
- [ ] Cek badge di inbox browser (screenshot)
- [ ] Catat bukti di plan + ROADMAP → merge + changelog 0.4.0

---

## Fase 3 — Definition of Done

1. Semua checkbox `[x]` dengan bukti (log, angka, screenshot, baris DB).
2. Test hijau: backend + vision (CPU) + vitest + build.
3. Demo: loitering + running event terbit; alert rows dengan status benar; rate-limit terbukti; tanpa token Telegram = `not_configured` (bukan error).
4. Merge `feat/fase-3-alerting` → `main`, tag `v0.4.0`, changelog, server sync.

## Risiko & catatan

- Kalibrasi meters_per_pixel kasar → angka speed ±30% (bukti dicatat apa adanya; knob per kamera).
- Telegram tanpa chatID = expected state fase ini; delivery nyata diuji saat chatID disiapkan user (low priority).
- Analyzer rate: 24 kamera × 5fps = tetap aman (kapasitas terukur ~590 fps).
