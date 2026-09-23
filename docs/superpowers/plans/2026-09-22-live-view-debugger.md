# Live View Debugger + person_detect cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Klik tile Live View membuka modal debug (stream + overlay zona & bbox person realtime), deteksi person dipublikasikan via MQTT→WS, event `person_detect` tidak lagi masuk DB (flag debug dimatikan) dan data lamanya dihapus.

**Architecture:** Vision node publish deteksi per frame ke MQTT `isentinel/detections/{node_id}` (QoS 0, payload `{camera_id, ts, boxes:[{id, bbox_norm, conf}]}`; ~5 msg/s per kamera). Backend `events_consumer` subscribe topic itu → `hub.broadcast()` ke WS `/api/v1/ws/events` sebagai `{type: "detections", ...}`. Frontend: klik tile → Carbon Modal berisi `<video-stream>` + `<canvas>` overlay (ukuran mengikuti elemen video); toggle "Show zones" (semua zona kamera + label type, warna per zona) dan "Show bbox person" (kotak + ID realtime). Fokus-layar-lama (big-on-top) diganti modal. `person_detect`: env debug kembali `false`, data lama dihapus (DB + blob).

**Tech Stack:** existing — paho-mqtt (vision + backend consumer), WebSocket hub existing (`app/ws/hub.py` + `useWs.ts`), go2rtc `<video-stream>`, Canvas 2D, Carbon Modal.

**Branch:** `feat/live-view-debugger` (stack di atas `feat/media-capture-toggles`)

---

### Task 1: Vision publish detections stream

**Files:**
- Modify: `vision/vision/transport/__init__.py` / modul transport MQTT (tambah `publish_detections`)
- Modify: `vision/vision/node.py` (worker loop: kirim per frame bila ada deteksi)
- Test: `vision/tests/test_transport.py`

**Desain:** Payload dikirim di worker loop TEPAT setelah `detections = detector.detect(...)`, hanya bila ada deteksi (hemat). QoS 0. Bounding box dinormalisasi (0–1) konsisten dengan bbox_norm existing. Track id dari ByteTrack.

- [ ] **Step 1: Write the failing test**

```python
def test_publish_detections_topic_and_payload():
    t = MqttTransport(NodeSettings(node_id="n1"), on_config=lambda d: None)
    t.publish_detections(7, [{"id": 1, "bbox_norm": [0.1, 0.1, 0.5, 0.6], "conf": 0.9}])
    # fake client: capture publish calls
    assert last_topic == "isentinel/detections/n1"
    assert last_payload["camera_id"] == 7
    assert last_payload["boxes"][0]["id"] == 1
```

(Ikuti pola fake client yang sudah ada di test_transport.py — bila transport punya fake/pipeline test; monkeypatch `client.publish`.)

- [ ] **Step 2: Run** `cd vision && python -m pytest tests/test_transport.py -q -m "not gpu"` → FAIL (method belum ada)

- [ ] **Step 3: Implement**

`transport`: 

```python
def publish_detections(self, camera_id: int, boxes: list[dict]) -> None:
    """Deteksi realtime utk debugger Live View. QoS 0, fire-and-forget."""
    payload = json.dumps({"camera_id": camera_id, "ts": time.time(),
                          "boxes": boxes}).encode()
    self._publish("isentinel/detections/" + self.node_id, payload, qos=0)
```

(Ikuti pola `publish_event` existing — nama private helper menyesuaikan file.)

`node.py` worker loop — setelah tracker:

```python
                    if detections and self.transport is not None:
                        boxes = [{"id": t.id, "bbox_norm": [round(v, 4) for v in t.bbox],
                                  "conf": round(getattr(d, "conf", 1.0), 3)}
                                 for t, d in zip(tracks, detections)]
                        if boxes:
                            self.transport.publish_detections(cam_id, boxes)
```

(Kunci: `tracks` sudah hasil ByteTrack; simpan mapping det→track saat dibuat — cek urutan di run loop, `tracks` dari tracker fed detections; sesuaikan agar id+box konsisten.)

- [ ] **Step 4: Run tests + regresi** `python -m pytest tests -q -m "not gpu"` → PASS
- [ ] **Step 5: Commit** `feat(vision): publish deteksi realtime via MQTT utk debugger live`

### Task 2: Backend relay detections → WebSocket

**Files:**
- Modify: `backend/app/services/events_consumer.py` (subscribe topic + forward)
- Modify: `backend/app/ws/hub.py` bila butuh broadcast generik
- Test: `backend/tests/test_ws_hub.py` atau test consumer baru kecil

**Desain:** callback topic `isentinel/detections/+` → parse JSON → `hub.broadcast({"type": "detections", "camera_id": ..., "boxes": ...})`. Hub.broadcast sudah generik (dict) — verifikasi.

- [ ] **Step 1: test** — consumer on_message dgn topic detections → hub.broadcast dipanggil dgn payload {type: detections, camera_id, boxes}. (monkeypatch hub)
- [ ] **Step 2: implement** minimal: di `_run` tambah `client.message_callback_add("isentinel/detections/+", self._on_detections)`; `_on_detections` parse + broadcast (never raises).
- [ ] **Step 3: regresi backend; commit** `feat(backend): relay deteksi realtime ke WebSocket`

### Task 3: Frontend — modal debugger Live View

**Files:**
- Modify: `frontend/src/features/live/LiveViewPage.tsx` (klik tile → modal, bukan big-on-top)
- Modify: `frontend/src/api/useWs.ts` (hook deteksi) atau komponen baru
- Create: overlay component di dalam LiveViewPage (canvas)
- Modify: `frontend/src/app/i18n.tsx` (keys `live.showZones`, `live.showBbox`, `live.debugTitle`)
- Test: `frontend/src/__tests__/liveview.test.tsx`

**Desain:**

- Modal Carbon `size="lg"` (full besar): `<CameraTile big>` di dalamnya (stream `<video-stream>` sama) + 2 Toggle + canvas absolute overlay di container yang sama dengan video.
- Canvas sizing: container `position:relative`, canvas absolute inset-0; koordinat polygon/box dinormalisasi (0–1) × ukuran video element (clientWidth/Height). Rerender tiap deteksi WS.
- Show zones: `listZones()` filter `camera_id === cam.id && active` — polygon + label `z.name (type)`; warna: absensi hijau, restricted merah, lain abu.
- Show bbox: WS message `type: "detections"` → filter camera_id → kotak + label `ID n` (warna oranye).
- WS: `useWs.ts` — perluas onMessage supaya callback menerima pesan apa pun; komponen memfilter `type === "detections"`.

- [ ] **Step 1: test gagal** — klik tile → modal tampil (bukan div big); toggle zones → canvas tergambar (assert via canvas element + data-testid); WS detections → boxes tergambar (panggil handler manual).
- [ ] **Step 2: implement**; hapus state `focusId`/blok big-on-top, ganti `setFocusId` → `openDebug(cam)`.
- [ ] **Step 3: `npx vitest run`, `npm run build`; commit** `feat(live): modal debugger — overlay zona & bbox person realtime`

### Task 4: person_detect cleanup + flag off

**Files:**
- Server ops (script via SSH, BUKAN kode): hapus `events type='person_detect'` + alert + blob; set `VISION_EMIT_PERSON_DETECT=false` di `vision.env`; restart vision + re-push config.
- Modify: `CHANGELOG.md`, `docs/runbooks/events-cleanup.md` (tambah kasus per-type)

**Desain:** kode `emit_person_detect` tetap ada (default false) sebagai alat debug — tidak pernah masuk produksi. 

- [ ] **Step 1: script hapus** (pola runbook): delete alert → delete event → rm blob (clips/snapshots) untuk `type='person_detect'`; laporkan jumlah.
- [ ] **Step 2: matikan flag** env → false; restart vision (SIGKILL — SIGTERM hang, catat di runbook restart: `kill -9` fallback), re-push config.
- [ ] **Step 3: commit runbook + CHANGELOG** `docs: person_detect debug-only + cleanup runbook`

### Task 5: Deploy + verifikasi lapangan

- [ ] Deploy branch ke gspe-ai3 (stack: media-capture-toggles → live-view-debugger), migration tidak ada (bukan DB change), restart API + vision, re-push config.
- [ ] Verifikasi: WS detections mengalir (curl WS atau buka Live View → modal → toggle bbox → kotak muncul saat orang lewat), zona tergambar di modal.
- [ ] Update checkpoint + CHANGELOG.

## Self-Review

- Spesifikasi user: modal mengganti big-on-top ✓; tile tetap hidup ✓; toggle zones (semua zona + label) ✓; toggle bbox realtime WS ✓; debugger hanya di modal ✓; person_detect tidak masuk event (env off) ✓; hapus data person_detect ✓.
- Placeholder: Task 1 test mengikuti pola fake client existing — eksekutor baca test_transport.py dulu (di-plan eksplisit).
- Type: payload key konsisten `bbox_norm`, `id`, `conf`; WS `type: "detections"` dipakai sama di backend & frontend.
