# R4 — Dwell trigger, WS auth fix, Events tab redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** (1) WS realtime bbox sampai ke browser (cookie auth fallback), (2) trigger dwell per zona — snapshot+clip baru jalan setelah orang N detik di zona (menyelesaikan miss snapshot-vs-clip & crop kosong), (3) detail Events diredesign per mockup `mockup-ui/03-events.html` (tabstrip Clip | Snapshot | Face crop), (4) rekap attendance terisi setelah crop benar.

**Architecture:** `ws_events` menerima auth dari query token ATAU cookie (fix latent: WS selalu ditolak karena JWT httpOnly). Zona baru `dwell_seconds` (migration 0013, default 0): face_gate hanya emit saat track sudah dalam zona ≥ dwell_seconds (diukur dari first-seen-in-zone), sehingga snapshot/clip/crop diambil saat orang masih di frame. Events UI: tabstrip per mockup — media tab (Clip/Snapshot/Face crop) mengganti tumpukan 3 media; face crop tampil di tab sendiri untuk attendance.

**Tech Stack:** existing — SQLAlchemy migration expand-only, face_gate analyzer, EventsPage, ZoneEditor/GatesPage, i18n.

**Branch:** `feat/events-dwell-crop` (stack di atas `feat/live-view-debugger`)

---

### Task 1: WS cookie auth fallback (fix bbox overlay)

**Files:**
- Modify: `backend/app/api/events.py:117-126` (`ws_events`)
- Test: `backend/tests/test_events_ws.py` (baru, kecil)

**Desain:** `token = ws.query_params.get("token")` → bila kosong/invalid → baca cookie `COOKIE` (nama dari `app.api.deps`) via `ws.cookies` → decode → bila tetap invalid, close(1008).

- [ ] **Step 1: test** — TestClient `websocket_connect` tanpa query token tapi dengan cookie JWT valid → hub menerima koneksi (hub.active bertambah); tanpa cookie & tanpa token → ditolak 1008.
- [ ] **Step 2: implement**:

```python
@router.websocket("/api/v1/ws/events")
async def ws_events(ws: WebSocket):
    token = ws.query_params.get("token", "") or ws.cookies.get(COOKIE, "")
    if not decode_token(token):
        await ws.close(code=1008)
        return
```

(Import COOKIE dari app.api.deps.)

- [ ] **Step 3: tests + commit** `fix(backend): WS auth fallback cookie — buka jalur realtime untuk UI`

### Task 2: zone.dwell_seconds (backend + config push)

**Files:**
- Migration: `backend/alembic/versions/0013_zone_dwell_seconds.py` (Integer default 0)
- Modify: `backend/app/models/zone.py`, `backend/app/schemas/zone.py` (3 kelas), `backend/app/services/config_push.py`
- Test: `backend/tests/test_config_push.py`

- [ ] **Step 1: test** — build_node_config zone payload bawa `dwell_seconds`; PATCH zone menerima field.
- [ ] **Step 2: implement** (pola identik `clip` di R2).
- [ ] **Step 3: commit** `feat(backend): zone.dwell_seconds — trigger event setelah N detik di zona`

### Task 3: Vision — face_gate hormati dwell

**Files:**
- Modify: `vision/vision/analyzers/face_gate.py` (dwell logic)
- Modify: `vision/vision/node.py` (`_make_analyzers` → pass dwell; ATAU baca dari zone dict di analyzer ctor — face_gate sudah menerima zone dict, cukup `self.dwell = float(zone.get("dwell_seconds", 0))`)
- Test: `vision/tests/test_face_gate.py`

**Desain:** FaceGateAnalyzer menyimpan `first_seen: dict[tid -> ts]` saat track pertama terlihat DI DALAM polygon; emit hanya saat `ts - first_seen >= dwell`. Track keluar → reset first_seen (dan _inside sudah di-reset). Dwell 0 → perilaku lama (emit langsung). Cooldown 10s tetap.

- [ ] **Step 1: test** — dwell=3: track masuk zona di t=0 → tidak emit; masih di dalam di t≥3 → emit sekali. dwell=0 → emit langsung.
- [ ] **Step 2: implement + tests pass; regresi vision; commit** `feat(vision): dwell zone — event terbit setelah N detik di dalam zona`

### Task 4: Events UI tabstrip (mockup 03)

**Files:**
- Modify: `frontend/src/features/events/EventsPage.tsx` (detail panel → tabstrip)
- Modify: `frontend/src/app/theme.scss` (ev-tabstrip/ev-tab per mockup 03)
- Modify: `frontend/src/app/i18n.tsx`
- Test: `frontend/src/__tests__/events.test.tsx`

**Desain (mockup):** panel detail: `ev-tabstrip` — tab: `events.tab.detail` (Detail), `events.tab.clip` (Clip), `events.tab.snapshot` (Snapshot), `events.tab.crop` (Face crop, hanya bila payload.crop_path). Tab aktif = border bawah biru (#4589ff), inactive abu. Konten:
- Detail: metadata grid existing (tanpa media).
- Clip: video player + tombol unduh; placeholder bila kosong.
- Snapshot: img snapshot (bbox+ID terbakar).
- Face crop: img crop beranotasi — hanya untuk attendance; disabled tab (abu) bila tidak ada crop_path.
Default tab aktif = Detail. State reset saat event terpilih berganti.

- [ ] **Step 1: test** — tab strip tampil 3/4 tab; klik tab Snapshot → img snapshot; tab Face crop untuk attendance → img crop; event tanpa crop → tab disabled.
- [ ] **Step 2: implement; `npx vitest run`, `npm run build`; commit** `feat(events-ui): tabstrip media per mockup 03 — clip/snapshot/face-crop`

### Task 5: Zone editor field dwell (UI)

**Files:**
- Modify: `frontend/src/features/config/ZonesPage.tsx` (input number `dwell_seconds`, tampil untuk semua type; helper text "0 = langsung")
- Modify: `frontend/src/features/config/GatesPage.tsx` (attendance gates: tampilkan dwell per gate — kolom kecil atau di select area; minimal: number stepper)
- Modify: `frontend/src/api/zones.ts` (field)
- i18n + test

- [ ] **Step 1: test gagal → implement → vitest+build; commit** `feat(zones-ui): setting dwell seconds per zona`

### Task 6: Cleanup + deploy + verifikasi lapangan

- [ ] Hapus event person_detect sisa #4625 (beserta blob — tidak ada media).
- [ ] Deploy stack ke gspe-ai3: checkout branch, migration 0013, restart API+vision, re-push config.
- [ ] Set dwell_seconds=3 pada zona absensi aktif (Lorong 1 cam358? — cek zona user; konfirmasi ke user zona mana) via API.
- [ ] Verifikasi lapangan (user): lewat gate → event terbit setelah 3 detik → snapshot/crop berisi orang → attendance_event terisi → rekap attendance muncul.
- [ ] Update checkpoint + CHANGELOG.

## Self-Review

- User spec: dwell configurable per zona ✓ (default 0), events UI tab per mockup 03 ✓, crop jelas (dwell menahan orang di frame saat crop; debugger overlay utk verifikasi geometry) ✓, WS cookie fix membuka bbox realtime ✓.
- Rekap attendance: tidak ada kode baru — otomatis terisi saat match sukses; diverifikasi di Task 6.
- Placeholder: tidak ada; semua langkah konkret.
