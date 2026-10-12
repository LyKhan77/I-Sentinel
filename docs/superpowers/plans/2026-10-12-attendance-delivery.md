# Radio Tujuan Event dan Mode Uji untuk Absensi — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Behavior absensi memakai radio tiga pilihan yang sama dengan behavior alert (*Inbox + Telegram* / *Hanya Inbox* / *Mode uji*); Mode uji menekan event, media, dan rekap absensi serta menandai box wajah di Live View.

**Architecture:** Backend hanya memperluas daftar kind yang boleh membawa `delivery`. Node memindahkan `delivery_mode` ke modul netral `delivery.py` dan `FaceGateWorker._emit` menekan event bila efektif `test`. UI memakai komponen `DeliveryRadio` bersama dan label overlay `test:<tipe>` diterjemahkan untuk semua kind box.

**Tech Stack:** FastAPI, pydantic v2; Python vision node; React 19 + Carbon, Vitest.

**Spec:** `docs/superpowers/specs/2026-10-12-attendance-delivery-design.md`. Dasar: `docs/superpowers/plans/2026-10-09-zone-delivery-mode.md` (sudah di `main`).

## Global Constraints

- `delivery`, `test_until`, `revert_to` pada behavior `attendance` mengikuti aturan yang sama dengan behavior alert (stempel 24 jam server, kedaluwarsa kembali ke `revert_to`, kunci uji dibuang bila bukan `test`, `telegram = (delivery === "all")` ditulis UI).
- Mode uji absensi: **tanpa** `publish_event`, tanpa unggah snapshot/crop, tanpa baris absensi, track ditandai `done` (tidak diulang), flash `("test:attendance", ts + 6.0)` pada box wajah track itu; kedaluwarsa dinilai `time.time()` tanpa restart. Zona legacy tanpa `behaviors` atau tanpa `delivery` berperilaku identik dengan sebelumnya.
- `take_funnel()` dan kamus `rejects` di `FaceGateWorker` **tidak berubah** (tes lama mengunci kunci persis).
- Telegram absensi hanya bila efektif `all`; logika `matched`/`already_in`/`detected`, `telegram_unknown`, dan `attendance_skipped` tidak berubah. `Catat absensi` (`record`) tetap.
- UI: `zone-telegram-attendance` dihapus; `zone-telegram-unknown` tampil hanya saat efektif *Inbox + Telegram* (nilai lama `telegram: true` terbaca *Inbox + Telegram*); radio absensi `id` `zone-delivery-attendance-<all|inbox|test>`; konfirmasi hanya zona `critical`; badge UJI mencakup absensi.
- Teks UI id/en lewat `i18n.tsx`, Carbon, 390 px tanpa overflow. Commit Conventional berbahasa Indonesia, **tanpa atribusi AI**, lokal; suite berurutan; tanpa secret/IP/nama nyata. Tanpa migrasi.

## Review Focus

- Zona absensi tanpa `delivery` (data lama) tidak berubah perilaku, termasuk Telegram dan rekap; tes lama `face_worker`/`alerting`/`attendance` lulus tanpa diubah.
- Mode uji tidak meninggalkan baris absensi, event, atau unggahan media; kedaluwarsa menerbitkan event normal tanpa restart.
- Refaktor `delivery_mode` ke `delivery.py` murni: semua tes `test_node.py` yang ada lulus tanpa diubah.
- Label `test:attendance` muncul pada box wajah yang benar dan tidak menimpa label identitas intrusion.
- Dua tes `zones.test.tsx`/`test_zones_api.py` yang disebut plan adalah satu-satunya perubahan pada tes lama.

---

### Task 1: Backend mengizinkan `delivery` untuk absensi

**Files:**
- Modify: `backend/app/services/zone_delivery.py`, `backend/app/schemas/zone.py`, `backend/tests/test_zones_api.py`, `backend/tests/test_zone_delivery.py`, `backend/tests/test_alerting.py`

**Interfaces:**
- Produces: `DELIVERY_KINDS = ("intrusion", "loitering", "running", "idle_zone", "crowd", "attendance")` menggantikan `ALERT_KINDS`.

- [ ] **Step 1: Tes (gagal dulu).** `test_zones_api.py`: **ubah tes lama** `test_zone_delivery_validation` (alasan: keputusan baru): baris "absensi punya record/telegram_unknown sendiri — delivery ditolak" menjadi "absensi menerima delivery"; tambah `test_attendance_zone_test_mode_is_stamped` (POST zona absensi dengan `delivery: "test"` → `test_until` ±24 jam UTC dan `revert_to: "all"`; PATCH `inbox` membuang kunci uji). `test_alerting.py` (ikuti `GATE_ON`/`_zone`/`_event`): behavior `attendance` dengan `delivery="inbox"` → `telegram_off` untuk event `matched`; `delivery="test"` berlaku → `telegram_off`; `test` kedaluwarsa dengan `revert_to="all"` → `(True, "")` untuk `matched`; `delivery="all"` + `telegram_unknown=False` untuk `no_match` → `attendance_skipped` (perilaku lama); behavior tanpa `delivery` identik (tes lama tanpa perubahan).
- [ ] **Step 2: Implement** `DELIVERY_KINDS` di `zone_delivery.py` (hapus `ALERT_KINDS`), perbarui impor dan pesan galat di `schemas/zone.py` ("delivery is only valid for ... behaviors" → untuk kind di `DELIVERY_KINDS`).
- [ ] **Step 3:** `cd backend && .venv/bin/python -m pytest tests/test_zone_delivery.py tests/test_zones_api.py tests/test_alerting.py -q` → PASS.
- [ ] **Step 4: Commit** `feat(backend): behavior absensi menerima delivery dan Mode uji`.

### Task 2: Node menekan event absensi pada Mode uji

**Files:**
- Create: `vision/vision/delivery.py`
- Modify: `vision/vision/node.py`, `vision/vision/face_worker.py`, `vision/tests/test_face_worker.py`, `vision/tests/test_node.py`

**Interfaces:**
- Produces di `delivery.py`: `wall_of(value) -> float | None`, `delivery_mode(cfg: dict | None, now_wall: float) -> str` (isi dan perilaku persis seperti `node.delivery_mode` sekarang), `delivery_cfg_for(behavior: dict, zone_telegram: bool) -> dict` (kunci `delivery`, `test_until`, `revert_to`, `telegram`), `zone_attendance_cfg(zone: dict) -> dict | None` (cfg behavior `attendance` pada dict zona; `None` bila `behaviors` kosong/`None` atau tak ada behavior itu). `node.py` mengimpor semuanya dan tetap mengekspor `delivery_mode`; `VisionNode._with_delivery` memakai `delivery_cfg_for`.

- [ ] **Step 1: Tes (gagal dulu).** `test_node.py` (tambahan): `from vision.delivery import ...` murni — `delivery_mode` (kedaluwarsa, `revert_to`, turunan dari `telegram`), `delivery_cfg_for`, `zone_attendance_cfg` (zona dengan dan tanpa behavior absensi, `behaviors=None`); `from vision.node import delivery_mode` tetap valid. `test_face_worker.py` (tambahan; pola `run_worker`/`FaceGateWorker(363, [ZONE], ...)` dengan `ZONE` yang diberi `behaviors=[{"kind": "attendance", "delivery": "test", "test_until": <wall+3600>, "revert_to": "all"}]`, `FakeFaces`, `FakeTransport`, `FakeRecorder`): (a) tiga frame lolos gerbang → `t.events == []`, `recorder.uploads == []`, dan `eng.embed_calls` tetap sesuai (embedding tetap dihitung); box wajah track itu berlabel `test:attendance` pada frame sesudah emisi dan kembali bukan label itu setelah ±6 dtk; (b) tiga frame lagi pada track yang sama tidak menghasilkan event (track `done`); (c) `test_until` di masa lalu dengan `revert_to="all"` → event terbit normal; (d) zona tanpa `delivery` → event normal (tes lama tanpa perubahan); (e) mode `unified` (`FaceSettings(attendance_mode="unified")`) juga tertekan dengan label yang sama; (f) `take_funnel()` tidak punya kunci baru.
- [ ] **Step 2: Implement** `delivery.py` (pindahkan `_wall_of` dan `delivery_mode` dari `node.py`; `node.py` mengimpor dan mempertahankan nama `delivery_mode`); di `FaceGateWorker`: `self._flash: dict[int, tuple[str, float]]`; di awal `_emit(tid, st)`: `cfg = zone_attendance_cfg(st.zone)`; bila `delivery_mode(cfg, time.time()) == "test"`: `st.done = True`, `self._flash[tid] = ("test:attendance", self._last_frame_ts + 6.0)`, `return` (sebelum menghitung agregat, antrean media, atau `publish_event`); pada pembuatan `boxes` per track pakai `ident_label or self._flash_label(tr.id, frame.ts) or code or f"{q:.2f}"` dan buang entri basi tiap frame di `_process`.
- [ ] **Step 3:** `cd vision && ../backend/.venv/bin/python -m pytest tests -q -m "not gpu"` → PASS (tes lama tanpa perubahan).
- [ ] **Step 4: Commit** `feat(vision): Mode uji absensi menekan event dan menandai box wajah`.

### Task 3: UI radio absensi, badge, dan label overlay

**Files:**
- Create: `frontend/src/features/config/DeliveryRadio.tsx`
- Modify: `frontend/src/features/config/ZonesPage.tsx`, `frontend/src/features/live/LiveWall.tsx`, `frontend/src/app/i18n.tsx`, `frontend/src/__tests__/zones.test.tsx`, `frontend/src/__tests__/liveview.test.tsx`

**Interfaces:**
- Produces: `DeliveryRadio({ kind, behavior, zoneTelegram, nowMs, rev, onChoose })` (`kind: BehaviorKind | 'attendance'`, `onChoose(value: Delivery)`); memakai `effectiveDelivery` dan kunci i18n `zones.delivery.*` yang ada.

- [ ] **Step 1: Tes (gagal dulu).** `zones.test.tsx`: **ubah tes lama** `zona absensi punya satu toggle Telegram pada behavior attendance` (alasan: toggle diganti radio) menjadi: zona absensi tanpa `delivery` → radio `zone-delivery-attendance-inbox` terpilih, **tidak** ada `zone-telegram-attendance`; memilih *Inbox + Telegram* dan simpan → PATCH `[{kind:'attendance', trigger_seconds:0, delivery:'all', telegram:true}]`; tambahan: *Mode uji* pada zona `critical` meminta konfirmasi (Batal tidak mengubah), pada `warning` langsung menulis `delivery:'test'` dan `telegram:false`; badge UJI muncul untuk zona absensi yang diuji; `zone-telegram-unknown` tidak tampil saat efektif `inbox`/`test` dan tampil saat `all` (dua tes Unknown lama lulus tanpa diubah). `liveview.test.tsx`: box `kind: 'face'` berlabel `test:attendance` tampil `UJI · Absensi` (nama wajah tidak menimpanya); label gerbang lain tak berubah.
- [ ] **Step 2: Implement** `DeliveryRadio.tsx` dengan markup radio dari blok behavior alert (pindahkan, jangan duplikat; `key` memuat `rev`, `valueSelected = effectiveDelivery(...)`, teks bantu dari `zones.delivery.<nilai>Hint`); `ZonesPage` memakai komponen itu di blok behavior alert dan blok absensi (menggantikan `Toggle zone-telegram-attendance`); handler pilihan untuk absensi lewat `patchSelected` pada behavior `attendance` (`delivery`, `telegram: value === 'all'`, `test_until`/`revert_to` dikosongkan), konfirmasi `critical` memakai alur `pendingTest` yang ada; `zoneTestLabel` mencakup `attendance`; `LiveWall.boxLabel` menerjemahkan `test:<tipe>` untuk semua kind box (cek awalan lebih dulu dari nama dan kode gerbang); teks bantu `allHint` disesuaikan untuk absensi (i18n id/en).
- [ ] **Step 3:** `cd frontend && env -u NODE_ENV npx vitest run src/__tests__/zones.test.tsx src/__tests__/liveview.test.tsx`, lalu `npx vitest run`, `npm run lint`, `npm run build` → PASS (lint tanpa warning baru per pasangan file-rule).
- [ ] **Step 4: Verifikasi tampilan** 390 px dan 1280 px untuk zona absensi (dev server Vite + API distub via Playwright; screenshot ke `docs/evidence/`, gitignored); `scrollWidth == innerWidth`; hentikan dev server.
- [ ] **Step 5: Commit** `feat(frontend): radio tujuan event dan Mode uji untuk absensi, label UJI pada box wajah`.

### Task 4: Dokumen dan suite penuh

**Files:**
- Modify: `WORKFLOW.md` (§6, §12), `docs/runbooks/zone-test-mode.md`, `ARCHITECTURE.md`, `README.md`, `ROADMAP.md`, `CHANGELOG.md`

- [ ] **Step 1:** dokumentasikan radio absensi, semantik Mode uji absensi (tanpa event, media, atau rekap; beda dengan Catat absensi yang masih menampilkan event "terdeteksi"; tidak menampilkan nama karena pencocokan di API), kedaluwarsa dan `revert_to`, serta perilaku node lama; baris ROADMAP `EUX` ditambah catatan perluasan ke absensi (`[~]`: kode selesai, belum deploy/uji); CHANGELOG (konteks, berkas, bukti, dampak, rollback `git revert`).
- [ ] **Step 2: Suite penuh berurutan** dan tempel hasilnya ke CHANGELOG: backend `-m "not gpu and not llm"`, vision `-m "not gpu"`, `pytest docker/tests -q`, `npx vitest run`, `npm run build`, `npm run lint` (pembanding `temp/logs/face-params-unify/baseline-lint.txt`).
- [ ] **Step 3: Commit** `docs: radio tujuan event dan Mode uji untuk absensi`.
