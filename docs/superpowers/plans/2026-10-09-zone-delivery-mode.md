# Tujuan Event per Behavior Zona dan Mode Uji (Plan B) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Radio tiga pilihan per behavior alert (*Inbox + Telegram*, *Hanya Inbox*, *Mode uji*) menggantikan toggle Telegram; Mode uji menekan event dan Telegram, menampilkan label di overlay Live View, dan kedaluwarsa otomatis dalam 24 jam.

**Architecture:** Kunci JSON baru `delivery`, `test_until`, `revert_to` pada `zone.behaviors[]` (tanpa migrasi). Fungsi murni `effective_delivery` di backend (Telegram) dan padanannya di node (penekanan event, berdasar jam dinding) dan UI. Server menstempel `test_until` saat uji dimulai. Node membuat label overlay `test:<tipe>` untuk track yang memicu; UI menerjemahkannya.

**Tech Stack:** FastAPI, pydantic v2; Python vision node; React 19 + Carbon, Vitest.

**Spec:** `docs/superpowers/specs/2026-10-09-inbox-zone-ux-design.md` (§6). Plan A (Events) terpisah: `docs/superpowers/plans/2026-10-09-events-ux.md`.

## Global Constraints

- `delivery` ∈ {`all`, `inbox`, `test`}; hanya untuk kind `intrusion`, `loitering`, `running`, `idle_zone`, `crowd` (behavior `attendance` dengan `delivery` → 422). `test_until` ISO-8601 UTC (hanya bila `test`), `revert_to` ∈ {`all`, `inbox`} (hanya bila `test`, bawaan `all`); kunci itu dibuang bila `delivery != "test"`.
- Tanpa `delivery`: `telegram` item (atau flag zona bila item tanpa key; zona pra-R5 `behaviors is None` memakai flag zona) true → `all`, false → `inbox`.
- Stempel server saat create/patch: bila behavior itu `test` dan (sebelumnya bukan `test`, atau `test_until` hilang/lampau/tak terbaca) → `test_until = now + 24 jam` dan `revert_to` = delivery efektif sebelumnya (`all` bila tidak ada); selain itu nilai tersimpan dipertahankan (menyimpan perubahan lain tidak memperpanjang uji).
- `effective_delivery(behavior, zone_telegram, now) -> "all" | "inbox" | "test"`: `test` dengan `now >= test_until` → `revert_to`.
- Telegram hanya bila efektif `all`. Node: behavior efektif `test` **tidak** memanggil `_merge_event`, `transport.publish_event`, `recorder.enqueue`, `registry.bind`; mencatat `flash[track_id] = (f"test:{type}", frame.ts + 6.0)`; label itu dipakai pada overlay `person` track tsb sampai kedaluwarsa. Kedaluwarsa dinilai dengan `time.time()` tanpa restart.
- UI menulis `delivery` dan `telegram = (delivery === "all")` (kompatibilitas node/API lama). Absensi tidak berubah.
- Konfirmasi (Carbon `Modal`) hanya saat memilih *Mode uji* pada zona `severity === "critical"`. Badge **UJI** (+ "sampai HH:MM") di daftar zona selama `test_until` belum lewat.
- Label overlay `test:<tipe>` → `UJI · <label tipe perilaku>` (`live.testFired`); label lain tak berubah.
- Teks UI id/en lewat `i18n.tsx`, Carbon, 390 px tanpa overflow. Commit Conventional berbahasa Indonesia, **tanpa atribusi AI**, lokal; suite berurutan; tanpa secret/IP/nama nyata.

## Review Focus

- Zona lama (tanpa `delivery`) berperilaku identik: tes lama `test_alerting.py` dan `test_zones_api.py` lulus tanpa diubah.
- Menyimpan zona (nama, polygon, dsb.) tidak memperpanjang uji yang sedang berjalan; mengganti ke uji lagi setelah kedaluwarsa memulai 24 jam baru.
- Node: behavior `test` yang kedaluwarsa kembali menerbitkan event tanpa restart; behavior lain di zona yang sama tidak terpengaruh.
- Overlay: hanya track yang memicu, ±6 dtk; tidak ada kebocoran label ke track lain atau ke event.
- Zona `critical` ke Mode uji meminta konfirmasi; membatalkan konfirmasi tidak mengubah nilai.

---

### Task 1: Validasi, efektif, dan stempel di backend

**Files:**
- Create: `backend/app/services/zone_delivery.py`, `backend/tests/test_zone_delivery.py`
- Modify: `backend/app/schemas/zone.py`, `backend/app/api/zones.py`, `backend/tests/test_zones_api.py`

**Interfaces:**
- Produces: `effective_delivery(behavior: dict, zone_telegram: bool, now: datetime | None = None) -> str`; `stamp_test_mode(new: list, old: list | None, now: datetime | None = None) -> list` (mengembalikan salinan behaviors dengan `test_until`/`revert_to` dinormalkan sesuai aturan stempel; tidak mengubah masukan); `TEST_HOURS = 24`.

- [ ] **Step 1: Tes (gagal dulu).** `test_zone_delivery.py` (murni): turunan dari `telegram` true/false/tanpa key/`behaviors is None`; `all`/`inbox` apa adanya; `test` sebelum `test_until` → `test`; tepat pada dan setelah `test_until` → `revert_to`; `revert_to` hilang → `all`; `test_until` tak terbaca → diperlakukan kedaluwarsa; stempel: dari `all` ke `test` → `test_until = now+24j`, `revert_to="all"`; dari `inbox` ke `test` → `revert_to="inbox"`; sudah `test` dengan `test_until` di masa depan → dipertahankan (tidak diperpanjang); `test` lama sudah kedaluwarsa lalu disimpan ulang sebagai `test` → stempel baru; `delivery != test` membuang kunci uji. `test_zones_api.py`: `delivery="x"` → 422; `attendance` dengan `delivery` → 422; POST dengan `test` mengisi `test_until` (±24 jam, UTC) dan `revert_to`; PATCH ganti `name` saja tidak mengubah `test_until`; PATCH `behaviors` yang sama mempertahankannya; PATCH ke `inbox` membuang kunci uji.
- [ ] **Step 2: Implement** modul, validasi di `_validate_behaviors` (nilai, kind, tipe `test_until` string ISO), dan pemanggilan `stamp_test_mode` di `create_zone` (old `None`) dan `update_zone` (old = `zone.behaviors` sebelum `setattr`) bila `behaviors` ikut diubah.
- [ ] **Step 3:** `cd backend && .venv/bin/python -m pytest tests/test_zone_delivery.py tests/test_zones_api.py -q` → PASS.
- [ ] **Step 4: Commit** `feat(backend): tujuan event per behavior (delivery) dengan Mode uji dan stempel kedaluwarsa`.

### Task 2: Telegram mengikuti tujuan efektif

**Files:**
- Modify: `backend/app/services/alerting.py`, `backend/tests/test_alerting.py`

**Interfaces:**
- Consumes: `effective_delivery` (Task 1).

- [ ] **Step 1: Tes (gagal dulu)** di `test_alerting.py` (ikuti fixture yang ada): behavior `delivery="inbox"` → `telegram_off`; `all` → dikirim; `test` yang berlaku → `telegram_off`; `test` kedaluwarsa dengan `revert_to="all"` → dikirim, `revert_to="inbox"` → tidak; item tanpa `delivery` mengikuti `telegram`/flag zona persis seperti sebelumnya (tes lama tanpa perubahan).
- [ ] **Step 2: Implement** `_telegram_on` memanggil `effective_delivery(b, zone.telegram) == "all"` untuk item yang cocok kind; cabang `behaviors is None` dan "tidak ada item cocok" tetap.
- [ ] **Step 3:** `.venv/bin/python -m pytest tests/test_alerting.py tests/test_alert_dispatcher.py -q` → PASS.
- [ ] **Step 4: Commit** `feat(backend): alert Telegram mengikuti delivery efektif behavior`.

### Task 3: Node menekan event dan menandai overlay

**Files:**
- Modify: `vision/vision/node.py`, `vision/tests/test_node.py`

**Interfaces:**
- Produces: `VisionNode._with_delivery(analyzer, behavior: dict, zone_telegram: bool)` memasang `analyzer.delivery_cfg = {"delivery", "test_until", "revert_to", "telegram"}`; fungsi modul `delivery_mode(cfg: dict | None, now_wall: float) -> str` (`test`/`all`/`inbox`, kedaluwarsa → `revert_to`); `CameraWorker._flash: dict[int, tuple[str, float]]`.

- [ ] **Step 1: Tes (gagal dulu)** di `test_node.py` (pola `_node_with`, `make_node`, `MockDetector`, `FakeTransport`; analyzer intrusion pada zona yang dimasuki satu orang; `test_until` dihitung dari `time.time()` ± 3600): (a) behavior `test` berlaku → `t.events == []` dan tidak ada `recorder.enqueue`/`registry.bind` (recorder dan registry palsu), tetapi frame berikutnya mem-publish box `person` dengan `label == "test:intrusion"` hanya untuk track pemicu; (b) label hilang setelah ±6 dtk frame; (c) `test_until` di masa lalu dengan `revert_to="all"` → event terbit normal tanpa restart; (d) `delivery="inbox"` dan `all` tetap menerbitkan event; (e) dua behavior di satu zona: yang `test` ditekan, yang `all` tetap terbit; (f) behavior tanpa `delivery` identik dengan sebelumnya (tes lama tanpa perubahan); `delivery_mode` murni mencakup kedaluwarsa dan `revert_to` hilang.
- [ ] **Step 2: Implement:** `_make_analyzers` memanggil `_with_delivery` untuk kind alert (bukan `attendance`); di `CameraWorker.run`, sebelum `_merge_event`: `if delivery_mode(getattr(az, "delivery_cfg", None), time.time()) == "test": tid = partial["payload"].get("track_id"); (bila tid ada) self._flash[tid] = (f"test:{partial['type']}", frame.ts + 6.0); continue` (event `idle_zone`/`crowd` tanpa `track_id` ditekan tanpa label); saat membangun box `person`, `label = self._flash[t.id][0]` bila `until > frame.ts`, selain itu `None` (dan buang flash basi).
- [ ] **Step 3:** `cd vision && ../backend/.venv/bin/python -m pytest tests -q -m "not gpu"` → PASS (tes lama tanpa perubahan).
- [ ] **Step 4: Commit** `feat(vision): Mode uji menekan event behavior dan menandai overlay Live View`.

### Task 4: UI zona (radio, badge, konfirmasi) dan label overlay

**Files:**
- Create: `frontend/src/features/config/zoneDelivery.ts`
- Modify: `frontend/src/api/zones.ts`, `frontend/src/features/config/ZonesPage.tsx`, `frontend/src/features/live/LiveWall.tsx`, `frontend/src/app/i18n.tsx`, `frontend/src/__tests__/zones.test.tsx`, `frontend/src/__tests__/liveview.test.tsx`, `frontend/src/app/theme.scss`

**Interfaces:**
- Produces: `Behavior.delivery?: 'all' | 'inbox' | 'test'`, `test_until?: string`, `revert_to?: 'all' | 'inbox'` di `api/zones.ts`; `zoneDelivery.ts`: `effectiveDelivery(b: Behavior, zoneTelegram: boolean, nowMs: number): 'all' | 'inbox' | 'test'` (sama dengan backend) dan `testUntil(b, nowMs): Date | null`.

- [ ] **Step 1: Tes (gagal dulu)** di `zones.test.tsx`: behavior alert menampilkan `RadioButtonGroup` tiga pilihan (id `zone-delivery-<kind>`) dan **tidak** ada `Toggle zone-telegram-<kind>`; nilai lama `telegram: true` → *Inbox + Telegram* terpilih, `false`/tanpa key → *Hanya Inbox*; memilih *Mode uji* pada zona `warning` → PATCH memuat `delivery: "test"` dan `telegram: false` tanpa dialog; pada zona `critical` membuka dialog, **Batal** tidak mengubah nilai, **Lanjut** menulis; memilih *Inbox + Telegram* menulis `delivery: "all"` dan `telegram: true`; badge **UJI** + "sampai" muncul di daftar bila `test_until` di masa depan dan hilang bila lampau (radio menampilkan `revert_to`); zona absensi tetap memakai `zone-telegram-attendance`. **Tes lama diubah** (alasan: toggle diganti radio): `Telegram per behavior default off, dikirim di item behaviors; toggle zona lama hilang` (kini radio default *Hanya Inbox*; PATCH `[{kind, trigger_seconds, delivery:'all', telegram:true}]`). `liveview.test.tsx`: box `person` berlabel `test:intrusion` tampil `UJI · Intrusi`; label lain tak berubah. `zoneDelivery` murni diuji di berkas yang sama atau berkas baru (kedaluwarsa, `revert_to`, turunan lama).
- [ ] **Step 2: Implement** tipe, `zoneDelivery.ts`, radio di blok behavior alert (menggantikan `Toggle zone-telegram-<kind>`; teks bantu satu baris per pilihan), `Modal` konfirmasi (pola `zone-delete-confirm`), badge di `zone-item` (pola `zone-badge`), pemetaan label di `DebugOverlay.boxLabel` untuk `kind: 'person'` dan awalan `test:`; kunci i18n id/en (`zones.delivery.*`, `zones.delivery.testConfirm*`, `zones.testBadge`, `live.testFired`).
- [ ] **Step 3:** `env -u NODE_ENV npx vitest run`, `npm run lint`, `npm run build` → PASS (lint tanpa warning baru per pasangan file-rule).
- [ ] **Step 4: Verifikasi tampilan** 390 px dan 1280 px (dev server Vite + API distub via Playwright, screenshot ke `docs/evidence/`, gitignored): radio, dialog, dan badge tanpa overflow; hentikan dev server.
- [ ] **Step 5: Commit** `feat(frontend): radio tujuan event, Mode uji, badge UJI, dan label overlay`.

### Task 5: Dokumen dan suite penuh

**Files:**
- Modify: `WORKFLOW.md` (§6, §10), `ARCHITECTURE.md`, `README.md`, `docs/runbooks/` (berkas zona/Telegram yang ada atau `docs/runbooks/zone-test-mode.md` baru), `ROADMAP.md`, `CHANGELOG.md`

- [ ] **Step 1:** dokumentasikan tiga tujuan event, kunci `delivery`/`test_until`/`revert_to`, aturan stempel dan kedaluwarsa, perilaku node lama, dan cara memakai Mode uji (termasuk bahwa uji menekan alert keamanan); baris ROADMAP `EUX` bagian B `[~]` (kode selesai, belum deploy/uji); CHANGELOG (konteks, berkas, bukti, dampak, rollback).
- [ ] **Step 2: Suite penuh berurutan** dan tempel hasilnya ke CHANGELOG: backend `-m "not gpu and not llm"`, vision `-m "not gpu"`, `pytest docker/tests -q`, `npx vitest run`, `npm run build`, `npm run lint`.
- [ ] **Step 3: Commit** `docs: tujuan event per behavior dan Mode uji zona`.
