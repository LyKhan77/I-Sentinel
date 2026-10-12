# Tujuan Wajah Tidak Dikenal (Inbox / Telegram) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Zona absensi punya radio **Wajah tidak dikenal** (*Inbox + Telegram* / *Hanya Inbox* / *Tidak dikirim*) yang menggantikan toggle `telegram_unknown`; "Tidak dikirim" membuang event wajah tidak dikenal di API.

**Architecture:** Kunci `unknown_delivery` di JSON behavior `attendance` (tanpa migrasi), dibaca lewat fungsi murni di `zone_delivery.py` oleh gerbang Telegram dan consumer MQTT. Consumer membuang event tidak dikenal sesudah pencocokan (`handle_face_event`) dan sebelum alert/AI/WS, serta membersihkan media susulan. UI memakai komponen radio baru berpola `DeliveryRadio`. Vision tidak berubah.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, pydantic v2, pytest; React 19 + Carbon, Vitest.

**Spec:** `docs/superpowers/specs/2026-10-12-unknown-face-delivery-design.md`.

## Global Constraints

- `unknown_delivery` ∈ `all` | `inbox` | `none`, hanya pada behavior `attendance`; tanpa kunci: `telegram_unknown == false` → `inbox`, selain itu `all`; `behaviors` kosong/`None` → `all`. Zona lama berperilaku persis seperti sebelumnya; tes backend lama (`test_alerting.py`, `test_zone_delivery.py`, `test_zones_api.py`, `test_events_consumer.py`) lulus tanpa diubah.
- Telegram untuk `no_match` terkirim hanya bila tujuan utama efektif `all` **dan** `unknown_delivery == "all"`; aturan `matched`/`already_in`/`detected` dan rate-limit tidak berubah.
- Buang hanya bila: `event.type == "attendance"`, `payload.employee_id` kosong, `payload.match_reason` ∈ (`no_match`, `ambiguous`, `low_quality`), dan zona `unknown_delivery == "none"`. Event dikenali, anomali (arah tidak valid, tanpa embedding dan crop), dan event yang `handle_face_event`-nya gagal tidak pernah dibuang.
- UI menulis `unknown_delivery` dan `telegram_unknown = (nilai === "all")`. Radio id `zone-unknown-<all|inbox|none>`, grup `data-testid="zone-unknown"`. Teks id/en lewat `i18n.tsx`; Carbon; 390 px tanpa overflow. `zones.telegramUnknown` dihapus.
- Tanpa migrasi, tanpa perubahan `vision/`. Commit Conventional berbahasa Indonesia, **tanpa atribusi AI**, lokal (tanpa `git push`); tanpa secret/IP/nama karyawan/ID event nyata di kode, tes, dan dokumen.

## Review Focus

- `unknown_delivery` pada `behaviors` sampah (`None`, `[None, "old"]`, item `attendance` tanpa kunci, nilai tak sah) tidak melempar dan memberi `all`. Pin: Task 1.
- Event yang pencocokannya melempar (payload tanpa `match_reason`) di zona `none` tetap tersimpan. Pin: Task 2.
- `crop_path`/`snapshot_path` yang keluar dari `storage_root` (`../`) tidak dihapus dan tidak melempar. Pin: Task 2.
- Event yang sama dikirim dua kali (QoS1) di zona `none` tidak melempar dan tidak meninggalkan baris; pesan media untuk `event_id` yang benar-benar asing tetap mencatat warning. Pin: Task 2.
- Zona tanpa item `attendance` (`behaviors: []`): memilih radio membuat item itu; menyimpan tanpa menyentuh radio tidak mengubah nilai tersimpan walau tampilan jatuh ke *Hanya Inbox*. Pin: Task 3.

---

### Task 1: Kontrak `unknown_delivery` dan gerbang Telegram

**Files:**
- Modify: `backend/app/services/zone_delivery.py`, `backend/app/schemas/zone.py`, `backend/app/services/alerting.py`
- Test: `backend/tests/test_zone_delivery.py`, `backend/tests/test_zones_api.py`, `backend/tests/test_alerting.py`

**Interfaces:**
- Produces: `UNKNOWN_DELIVERIES = ("all", "inbox", "none")` dan `unknown_delivery(behaviors: list | None) -> str` di `zone_delivery.py` (murni; mencari item `kind == "attendance"` pertama yang berupa dict).

- [ ] **Step 1: Tes (gagal dulu).**
  - `test_zone_delivery.py::test_unknown_delivery_rules` (parametrize `(behaviors, expected)`): `None`→`all`; `[]`→`all`; `[{"kind":"attendance"}]`→`all`; `unknown_delivery:"none"`→`none`; `"inbox"`→`inbox`; `telegram_unknown:False`→`inbox`; `telegram_unknown:True`→`all`; `unknown_delivery:"bogus"`→`all`; `unknown_delivery:"none"` + `telegram_unknown:True`→`none` (kunci menang); `[None,"old",{"kind":"attendance"}]`→`all`; `[{"kind":"intrusion","unknown_delivery":"none"}]`→`all`.
  - `test_zones_api.py::test_unknown_delivery_validation` (ikuti helper pembuatan zona berkas itu): zona absensi dengan `unknown_delivery` `all`/`inbox`/`none` → 201 dan tersimpan; `"bogus"` → 422; `True` → 422; `unknown_delivery` pada behavior `intrusion` → 422.
  - `test_alerting.py` (pakai `_attendance(db, behavior, telegram=...)`, `_matched`, `_event`): `test_unknown_face_telegram_matrix` (parametrize) untuk event `no_match`: `{"delivery":"all","unknown_delivery":"all"}`→`(True,"")`; `{"delivery":"all","unknown_delivery":"inbox"}` dan `"none"`→`(False,"attendance_skipped")`; `{"delivery":"inbox","unknown_delivery":"all"}`→`(False,"telegram_off")`; dan `test_matched_ignores_unknown_delivery`: `{"delivery":"all","unknown_delivery":"none"}` + event `matched`→`(True,"")`.
- [ ] **Step 2: Jalankan, pastikan gagal.** `cd backend && .venv/bin/python -m pytest tests/test_zone_delivery.py tests/test_zones_api.py tests/test_alerting.py -q` → FAIL (`unknown_delivery` belum ada, kunci belum divalidasi).
- [ ] **Step 3: Implement.** `zone_delivery.py`: tambah `UNKNOWN_DELIVERIES` dan `unknown_delivery(behaviors)` (urutan aturan: kunci sah → `telegram_unknown is False` → `all`; docstring menyebut kompatibilitas). `schemas/zone.py::_validate_behaviors`: `unknown_delivery` bila ada harus string dalam `UNKNOWN_DELIVERIES` dan hanya untuk `kind == "attendance"` (ValueError seperti pesan `delivery` yang ada). `alerting.should_alert`: ganti `not zone.behavior_flag("attendance", "telegram_unknown")` dengan `unknown_delivery(zone.behaviors) != "all"`; `Zone.behavior_flag` tidak disentuh.
- [ ] **Step 4: Jalankan tiga berkas itu** → PASS, termasuk dua tes `telegram_unknown` lama dan `test_behavior_flag_defaults` tanpa perubahan.
- [ ] **Step 5: Commit** `feat(backend): kontrak unknown_delivery dan gerbang Telegram wajah tidak dikenal`.

### Task 2: Consumer membuang event wajah tidak dikenal

**Files:**
- Modify: `backend/app/services/attendance.py`, `backend/app/services/events_consumer.py`
- Test: `backend/tests/test_events_consumer.py`

**Interfaces:**
- Consumes: `unknown_delivery` (Task 1).
- Produces di `attendance.py`: `UNKNOWN_REASONS = ("no_match", "ambiguous", "low_quality")`; `drop_unknown_event(db: Session, event: Event) -> bool`; `discard_dropped_media(data: dict) -> bool` (True bila `data["event_id"]` ada di daftar buangan; menghapus `snapshot_path`/`clip_path` pesan itu).

- [ ] **Step 1: Tes (gagal dulu)** di `test_events_consumer.py`. Fixture lokal: `storage_root` → `tmp_path / "root"` (`monkeypatch.setattr(settings, "storage_root", ...)`), zona `attendance` dengan behavior diparametrisasi, `attendance.face.match_vector` di-monkeypatch mengembalikan `face.MatchResult(None, 0.2, 0.9, reason)`, `worker.maybe_enqueue_caption` dicatat, `broadcast` dari fixture yang ada; payload event `{"direction":"entry","embedding":[0.1]*512,"face_quality":0.9,"crop_path":"crops/a.jpg"}` plus `snapshot_path="snapshots/a.jpg"`, kedua file dibuat di disk.
  - `test_unknown_face_dropped_when_zone_none` (parametrize `reason` ∈ `no_match`/`ambiguous`/`low_quality`): `Event` 0 baris, `Alert` 0 baris, `broadcast == []`, caption tak dipanggil, kedua file hilang.
  - `test_unknown_face_kept_for_inbox_all_or_unset` (parametrize `{"unknown_delivery":"inbox"}`, `{"unknown_delivery":"all"}`, `{}`): 1 baris, `len(broadcast) == 1`, file ada.
  - `test_recognized_and_anomalous_events_never_dropped` pada zona `none`: pencocokan sukses (karyawan dibuat; `MatchResult(emp.id, 0.9, 0.9, "matched")`) → baris ada; event tanpa embedding dan crop → baris ada; `direction` tidak valid → baris ada.
  - `test_failed_match_event_not_dropped`: matcher melempar → baris ada.
  - `test_unsafe_media_path_not_deleted`: `storage_root = tmp_path/"root"`, `crop_path="../outside.jpg"` dengan file di `tmp_path/"outside.jpg"` → event dibuang, file luar tetap ada, tanpa exception.
  - `test_late_media_for_dropped_event`: setelah drop, kirim `MEDIA_TOPIC` `{"event_id": <id>, "snapshot_path": "snapshots/late.jpg"}` (file ada) → file hilang dan `caplog` tanpa record warning; kirim `MEDIA_TOPIC` untuk `event_id` asing → tetap ada warning `media update for unknown event`.
  - `test_duplicate_unknown_event_dropped_twice`: payload sama dikirim dua kali → tanpa exception, `Event` 0 baris.
- [ ] **Step 2: Jalankan** `cd backend && .venv/bin/python -m pytest tests/test_events_consumer.py -q` → FAIL.
- [ ] **Step 3: Implement di `attendance.py`.** `drop_unknown_event`: kembalikan `False` kecuali kondisi pada Global Constraints terpenuhi (zona dibaca `db.get(Zone, event.zone_id)`; tanpa zona → `False`); kumpulkan path (`payload["crop_path"]`, `event.snapshot_path`, `event.clip_path`), `db.delete(event)` + `db.commit()`, tambahkan `event_id` ke `_DROPPED = deque(maxlen=512)` (komentar `# ponytail:` — daftar di memori hilang saat API restart, sapuan orphan retensi menutupnya), hapus file lewat `retention._safe_join(settings.storage_root, rel)` (lewati bila `None`; `OSError` dicatat, tidak dilempar), log info `attendance: event %s tidak dikenal dibuang (unknown_delivery=none)` (hanya `event_id`, tanpa identitas). `discard_dropped_media` memakai helper hapus yang sama.
- [ ] **Step 4: Implement di `events_consumer.handle_message`.** Sesudah blok try `attendance.handle_face_event`, panggil `attendance.drop_unknown_event(db, ev)` dalam try/except (`db.rollback()` + `logger.exception`, anggap `False`); bila `True`, `return` sebelum `alerting.handle`, caption AI, `intrusion_face`, dan `hub.broadcast`. Di cabang `MEDIA_TOPIC` saat `ev is None`: `if attendance.discard_dropped_media(data): return` sebelum warning.
- [ ] **Step 5: Jalankan** `cd backend && .venv/bin/python -c "import app.main"` (tanpa impor siklik `attendance` ↔ `retention`) lalu `.venv/bin/python -m pytest tests -q -m "not gpu and not llm"` → PASS (tes lama tanpa perubahan).
- [ ] **Step 6: Commit** `feat(backend): zona absensi membuang event wajah tidak dikenal bila tujuan "Tidak dikirim"`.

### Task 3: Radio Wajah tidak dikenal di Zona Deteksi

**Files:**
- Create: `frontend/src/features/config/UnknownFaceRadio.tsx`
- Modify: `frontend/src/api/zones.ts`, `frontend/src/features/config/zoneDelivery.ts`, `frontend/src/features/config/ZonesPage.tsx`, `frontend/src/app/i18n.tsx`
- Test: `frontend/src/__tests__/zones.test.tsx`

**Interfaces:**
- Produces: `Behavior.unknown_delivery?: 'all' | 'inbox' | 'none'` (`api/zones.ts`); `type UnknownDelivery` dan `effectiveUnknownDelivery(b: Behavior | null | undefined, main: Delivery): UnknownDelivery` (`zoneDelivery.ts`; tersimpan = `b.unknown_delivery` ?? (`b.telegram_unknown === false` ? `inbox` : `all`); `all` dengan `main !== 'all'` ditampilkan `inbox`, nilai tersimpan tidak diubah); `UnknownFaceRadio({ behavior, mainDelivery, onChoose }: { behavior: Behavior; mainDelivery: Delivery; onChoose: (v: UnknownDelivery) => void })` — `RadioButtonGroup` `name="zone-unknown"`, opsi `all` `disabled` bila `mainDelivery !== 'all'` dengan teks bantu tambahan `zones.unknown.needsTelegram`.

- [ ] **Step 1: Tes (gagal dulu)** di `zones.test.tsx` (pola `selectZone`, `attendanceZone`, `patchBody`).
  - **Ubah lima tes lama** (alasan: toggle diganti radio): (a) tes ~baris 547 → `zone-unknown-all` terpilih default; klik `zone-unknown-none` + simpan → `behaviors` `[{ kind:'attendance', trigger_seconds:0, telegram:true, unknown_delivery:'none', telegram_unknown:false }]` (zona `telegram: true`); (b) ~559 `telegram:false` → grup `zone-unknown` tampil, `zone-unknown-all` disabled, `zone-unknown-inbox` checked; (c) ~644 `delivery:'inbox'` dengan `unknown_delivery:'all'` → `zone-unknown-inbox` checked dan simpan tanpa menyentuh radio mengirim `unknown_delivery:'all'` tak berubah; (d) ~650 Mode uji berlaku → `queryByTestId('zone-unknown')` null; (e) ~657 `delivery:'all'` → `zone-unknown-all` enabled.
  - **Tambahan:** `telegram_unknown:false` + `delivery:'all'` tanpa `unknown_delivery` → `zone-unknown-inbox` checked; zona `behaviors: []` + `telegram:true` → klik `zone-unknown-none` + simpan → `[{ kind:'attendance', trigger_seconds:0, unknown_delivery:'none', telegram_unknown:false }]`; label `Wajah tidak dikenal`, `Tidak dikirim` terlihat; `zone-telegram-unknown` tidak ada lagi.
- [ ] **Step 2: Jalankan** `cd frontend && npx vitest run src/__tests__/zones.test.tsx` → FAIL.
- [ ] **Step 3: Implement.** `ZonesPage.tsx`: ekstrak `patchAttendanceBehavior(patch: Partial<Behavior>)` dari `applyAttendanceDelivery` (membuat item `attendance` bila belum ada), pakai di `applyAttendanceDelivery` dan di `onChoose` radio baru (`{ unknown_delivery: v, telegram_unknown: v === 'all' }`); ganti blok toggle `zone-telegram-unknown` dengan `<UnknownFaceRadio>` yang dirender hanya bila `effectiveDelivery(attBehavior, selected.telegram, nowMs) !== 'test'`. `i18n.tsx` (id dan en): kunci `zones.unknown.label` ("Wajah tidak dikenal"), `.all`, `.inbox`, `.none` ("Tidak dikirim"), `.allHint`, `.inboxHint`, `.noneHint` (menyebut event dibuang, tidak ada di Inbox, skor pantauan tidak tersimpan), `.needsTelegram`; hapus `zones.telegramUnknown`; ubah `zones.delivery.allHintAttendance` agar menunjuk radio **Wajah tidak dikenal** (bukan "toggle di bawah").
- [ ] **Step 4: Jalankan** `cd frontend && npx vitest run && npm run lint && npm run build` → semua lulus (lint hanya warning teks i18n lama, build exit 0).
- [ ] **Step 5: Verifikasi UI di app berjalan** pada 390 px: radio tampil tanpa overflow horizontal, `Inbox + Telegram` nonaktif saat tujuan utama *Hanya Inbox*; screenshot ke `docs/evidence/` (gitignored, tidak dikomit).
- [ ] **Step 6: Commit** `feat(frontend): radio Wajah tidak dikenal menggantikan toggle Kirim wajah tidak dikenal`.

### Task 4: Dokumen dan verifikasi akhir

**Files:**
- Modify: `WORKFLOW.md` (§6, §12; sekitar baris 96, 303, 351), `ARCHITECTURE.md` (sekitar baris 242, 259; tambah urutan consumer dengan titik buang), `README.md` (sekitar baris 463), `docs/runbooks/attendance.md` (sekitar baris 99-100; efek "Tidak dikirim" pada query pantauan `face_top_score`), `ROADMAP.md`, `CHANGELOG.md`

- [ ] **Step 1: Perbarui dokumen** sesuai spec §7: istilah toggle **Kirim wajah tidak dikenal** diganti radio **Wajah tidak dikenal**; kontrak `unknown_delivery` (+ turunan `telegram_unknown`); urutan consumer; catatan runbook bahwa zona `none` tidak punya baris `no_match` sehingga pantauan noise tidak punya data di sana. `ROADMAP.md`: entri siklus mengikuti format siklus terakhir. `CHANGELOG.md`: konteks, berkas, bukti (keluaran nyata tes dari Task 1-3), dampak, rollback; tanpa nama karyawan atau ID event nyata.
- [ ] **Step 2: Verifikasi akhir:** `cd backend && .venv/bin/python -m pytest tests -q -m "not gpu and not llm"`; `cd frontend && npx vitest run && npm run build`; `git diff main --stat -- vision` kosong. Tempel hitungan lulus ke `CHANGELOG.md`.
- [ ] **Step 3: Commit** `docs: tujuan wajah tidak dikenal per zona absensi`. Berhenti di commit lokal; deploy dan merge dilakukan di sesi perencanaan atas persetujuan user.
