# Zona UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Semua aturan deteksi diatur di satu tempat (Zona Deteksi): deteksi hanya jalan di kamera yang punya zona aktif, Snapshot/Clip per behavior, halaman Gate Absensi dihapus, dan Deteksi & Model hanya berisi parameter model.

**Architecture:** Vision node mengabaikan mask `camera.analyzers`, membaca flag media per behavior (fallback flag zona), dan tidak membuat worker untuk kamera tanpa zona aktif. Backend memvalidasi flag per behavior + konflik arah zona absensi (422) dan berhenti mengirim `analyzers`. Frontend: baris behavior dengan toggle Snapshot/Clip di `ZonesPage`, tab Gate dihapus, `DetectionPage` tanpa chip dengan kolom Status AI.

**Tech Stack:** Python 3.11 (vision + FastAPI/SQLAlchemy/Pydantic v2), pytest; React 19 + TypeScript + Carbon, Vitest + Testing Library.

**Spec:** `docs/superpowers/specs/2026-09-25-zone-config-ux-design.md`

## Global Constraints

- Branch `feat/zone-config-ux` (sudah ada, dari `main` @ `2ddd209`; spec di `21826e7`).
- **Tanpa AI attribution** di commit/kode/docs (`AGENTS.md` §9 menimpa trailer default apa pun).
- Tanpa migrasi DB, tanpa dependensi baru. Kolom `camera.analyzers` dibiarkan (deprecated, tidak dibaca).
- Pipeline wajah R5b (`vision/vision/face_worker.py`, FaceGateWorker, crop + snapshot selalu, tanpa clip) **tidak diubah**.
- Semua string UI lewat `frontend/src/app/i18n.tsx`, kedua bahasa (`id` dan `en`). Mobile 390 px tanpa overflow.
- Setiap task: commit Conventional Commits + satu bullet di `CHANGELOG.md` bagian `### Zona UX (2026-09-25 – …)` (dibuat di Task 1, di atas `### Pendaftaran kamera sederhana (2026-09-24 – 2026-09-25)`).
- Baseline `main` `2ddd209`: backend **363 passed**; vision **200 passed, 3 deselected**; frontend **129 passed**; build exit 0; lint = set rule+file lama.
- Server `gspe-ai3`: baca bebas; deploy/restart butuh izin user (Task 6).

## Deviasi dari spec (disengaja)

1. **Tabel Deteksi & Model memuat semua kamera** (bukan hanya kamera berzona seperti sekarang) — kolom Status AI baru bermakna bila kamera tanpa zona juga tampil ("Tidak jalan (tanpa zona aktif)").
2. **Label toggle zona dipendekkan** menjadi "Snapshot" / "Clip" karena kini tampil per baris behavior.
3. **Pesan konflik arah di UI dipicu oleh 422 saat menyimpan zona Absensi** (satu-satunya 422 yang mungkin dari form absensi: arah selalu terisi oleh UI).

## Review Focus

1. **Zona lama tanpa key per behavior** (data server saat ini) harus tetap memakai flag zona: event intrusion zona 15 tetap punya clip. Tes: Task 1 `test_behavior_media_falls_back_to_zone_flags`, Task 3 `toggle behavior mengikuti flag zona lama`.
2. **Mengaktifkan kembali zona absensi yang nonaktif** di kamera yang sudah punya gate aktif arah lain → 422, dan zona tetap nonaktif di DB (tidak setengah tersimpan). Tes: Task 2 `test_attendance_direction_conflict_rejected_on_patch`.
3. **Kamera dengan zona behavior aktif tetapi `camera.analyzers=['attendance']`** (cam 363 di server) harus tetap menjalankan YOLO. Tes: Task 1 `test_behavior_zone_runs_yolo_even_when_camera_mask_excludes_it`.
4. **Kamera tanpa zona aktif** tidak membuka stream sama sekali (bukan hanya tanpa analyzer) — hemat koneksi dan GPU. Tes: Task 1 `test_camera_without_active_zone_gets_no_worker` (assert `urls == []`).
5. **URL lama `?tab=gates`** (bookmark) tidak error, jatuh ke tab Kamera. Tes: Task 4 `old gates URL falls back to cameras`.

---

### Task 1: Vision — zona aktif = AI aktif, media per behavior

**Files:**
- Modify: `vision/vision/node.py` (`_make_analyzers`, `_start_workers`)
- Modify: `vision/vision/config.py:15` (komentar `analyzers` deprecated)
- Test: `vision/tests/test_node.py`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Produces: event behavior membawa `snapshot`/`clip` dari item behavior (fallback `zone.snapshot/clip`); `VisionNode._start_workers` tidak membuat worker/recorder/ring dan tidak memanggil `source_factory` untuk kamera tanpa analyzer behavior dan tanpa gate (kecuali `emit_person_detect`).

- [ ] **Step 1: Tulis/ubah tes (gagal)**

Di `vision/tests/test_node.py`:
- Ganti `test_make_analyzers_from_behaviors_master_filters` dengan:

```python
def test_camera_analyzers_mask_is_ignored():
    """Zona = aturan: chip kamera lama tidak boleh mematikan behavior zona."""
    cam = {"camera_id": 1, "source_url": "test://1", "zones": [BEHAVIOR_ZONE],
           "analyzers": ["attendance"]}
    node = _node_with(cam)
    cams = node._cameras_from_config({"cameras": [cam]})
    kinds = sorted(type(a).__name__ for a in node._make_analyzers(cams[0]))
    assert kinds == ["IntrusionAnalyzer", "LoiteringAnalyzer"]
```

- Hapus `test_make_analyzers_empty_master_means_no_analyzer` (perilaku yang dihapus).
- Tambahkan (setelah `test_legacy_zone_without_behaviors_still_builds_analyzers`):

```python
def test_behavior_media_flags_override_zone():
    zone = {**BEHAVIOR_ZONE, "snapshot": True, "clip": True,
            "behaviors": [{"kind": "intrusion", "trigger_seconds": 0, "clip": False},
                          {"kind": "loitering", "trigger_seconds": 30, "snapshot": False}]}
    cam = {"camera_id": 1, "source_url": "test://1", "zones": [zone]}
    node = _node_with(cam)
    media = {type(a).__name__: a.media for a in node._make_analyzers(node._cameras_from_config({"cameras": [cam]})[0])}
    assert media == {"IntrusionAnalyzer": {"snapshot": True, "clip": False},
                     "LoiteringAnalyzer": {"snapshot": False, "clip": True}}


def test_behavior_media_falls_back_to_zone_flags():
    zone = {**BEHAVIOR_ZONE, "snapshot": False, "clip": False,
            "behaviors": [{"kind": "intrusion", "trigger_seconds": 0}]}
    cam = {"camera_id": 1, "source_url": "test://1", "zones": [zone]}
    node = _node_with(cam)
    [az] = node._make_analyzers(node._cameras_from_config({"cameras": [cam]})[0])
    assert az.media == {"snapshot": False, "clip": False}
```

- Tambahkan (setelah `test_attendance_only_camera_runs_face_worker_without_yolo`):

```python
def test_camera_without_active_zone_gets_no_worker(tmp_path):
    inactive = {**BEHAVIOR_ZONE, "active": False}
    for zones in ([], [inactive]):
        _, workers, urls, det_calls = _wired_node(tmp_path, zones)
        assert workers == [] and urls == [] and det_calls == []


def test_behavior_zone_runs_yolo_even_when_camera_mask_excludes_it(tmp_path):
    _, workers, urls, det_calls = _wired_node(tmp_path, [BEHAVIOR_ZONE], analyzers=["attendance"])
    assert [type(w).__name__ for w in workers] == ["CameraWorker"]
    assert urls == ["rtsp://h:8554/cam_363"]
    assert det_calls == [363]
```

- [ ] **Step 2: Jalankan, pastikan gagal**

Run: `backend/.venv/bin/python -m pytest vision/tests/test_node.py -q`
Expected: FAIL — mask masih memfilter; media per behavior tidak terbaca; kamera tanpa zona masih mendapat `CameraWorker`.

- [ ] **Step 3: Implementasi**

`vision/vision/node.py` — di `_make_analyzers` ganti awal loop:

```python
        out = []
        for z in cam.zones:
            for b in behaviors_of(z):
                kind = b.get("kind")
                if kind == "attendance":
                    continue  # FaceGateWorker owns this zone
                # zona = satu-satunya aturan: mask camera.analyzers (lama) tidak dibaca lagi.
                # Media per behavior; zona lama tanpa key per behavior → flag zona.
                media = {"snapshot": b.get("snapshot", z.get("snapshot", True)),
                         "clip": b.get("clip", z.get("clip", True))}
                spec = dict(z)
```

(hapus baris `media = {...}` lama di level zona dan blok `if cam.analyzers is not None and kind not in cam.analyzers: continue`; sisa cabang intrusion/loitering/running tetap).

`_start_workers` — ganti isi loop `for cam in cameras:` sampai sebelum `log.info(...)`:

```python
        for cam in cameras:
            analyzers = self._make_analyzers(cam)
            gates = attendance_zones(cam) if self.face is not None else []
            run_yolo = bool(analyzers) or self.cfg.emit_person_detect
            if not run_yolo and not gates:
                continue  # tanpa zona aktif: live view saja (go2rtc), tanpa inferensi
            recorder = None
            if self.cfg.api_key:  # production: upload blobs to backend
                from .recorder import Recorder
                ring = None
                if run_yolo and self._wants_clip(analyzers):
                    from . import clipring
                    ring = clipring.ClipRing(cam.camera_id, main_stream_url(cam.source_url),
                                             self.cfg.clip_ring_dir)
                    ring.start()
                recorder = Recorder(cam.camera_id, self.cfg, self.transport, clip_ring=ring)
            if run_yolo:
                w = CameraWorker(cam, self.detector_factory, self.transport,
                                 threading.Event(), self.cfg.node_id,
                                 analyzers=analyzers, recorder=recorder,
                                 emit_person_detect=self.cfg.emit_person_detect,
                                 motion=cam.motion)
                w.source = self.source_factory(cam)
                w.start()
                self._workers.append(w)
            if gates:
                fw = FaceGateWorker(cam.camera_id, gates, self.face, self.transport,
                                    self.cfg.node_id, self._face_settings,
                                    recorder=recorder, motion=cam.motion)
                fw.source = self.source_factory(
                    cam.model_copy(update={"source_url": main_stream_url(cam.source_url)}))
                fw.start()
                self._workers.append(fw)
```

(Bandingkan dengan versi `main`: hanya kondisi start yang berubah; argumen konstruktor worker sama persis. Bila versi `main` berbeda di detail argumen, pertahankan argumen `main`.)

`vision/vision/config.py:15` — komentar menjadi `# deprecated: diabaikan (zona = satu-satunya aturan)`.

- [ ] **Step 4: Jalankan, pastikan lulus**

Run: `backend/.venv/bin/python -m pytest vision/tests -q -m "not gpu"`
Expected: semua passed, 3 deselected. Bila ada tes lama yang mengandalkan kamera tanpa zona tetap punya worker **tanpa** `emit_person_detect=True`, ubah ekspektasinya ke perilaku baru dan sebutkan di ringkasan.

- [ ] **Step 5: CHANGELOG + commit**

Di `CHANGELOG.md`, di atas `### Pendaftaran kamera sederhana (2026-09-24 – 2026-09-25)`:

```markdown
### Zona UX (2026-09-25 – …)

- **Vision: zona aktif = AI aktif**: mask `camera.analyzers` tidak dibaca lagi; kamera tanpa zona aktif tidak
  mendapat worker (stream tidak dibuka, tanpa YOLO → hemat GPU); flag Snapshot/Clip dibaca per behavior dengan
  fallback flag zona (zona lama berperilaku sama). Vision **<angka> passed**.
```

```bash
git add vision/vision/node.py vision/vision/config.py vision/tests/test_node.py CHANGELOG.md
git commit -m "feat(vision): zona aktif = AI aktif + snapshot/clip per behavior"
```

---

### Task 2: Backend — flag per behavior, konflik arah, config push tanpa `analyzers`

**Files:**
- Modify: `backend/app/schemas/zone.py` (`_validate_behaviors`)
- Modify: `backend/app/api/zones.py` (`create_zone`, `update_zone`, helper baru)
- Modify: `backend/app/services/config_push.py:88`
- Modify: `backend/app/models/camera.py` (komentar kolom `analyzers`)
- Test: `backend/tests/test_zones_api.py`, `backend/tests/test_config_push.py`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Produces: item `behaviors` boleh memuat `snapshot: bool`, `clip: bool` (selain itu 422); `POST/PATCH /api/v1/zones` → 422 `"camera already has an active attendance zone with another direction"`; config node tanpa key `analyzers`.

- [ ] **Step 1: Tulis/ubah tes (gagal)**

Tambahkan di akhir `backend/tests/test_zones_api.py`:

```python
GATE_BEHAVIORS = [{"kind": "attendance", "trigger_seconds": 0}]


def _gate(client, h, cam_id, direction, active=True, name="g"):
    return client.post("/api/v1/zones", json={
        **VALID, "camera_id": cam_id, "name": name, "type": "attendance",
        "direction": direction, "behaviors": GATE_BEHAVIORS, "active": active,
    }, headers=h)


def test_behavior_media_flags_roundtrip_and_validation(client):
    h = _admin_headers(client)
    cam = _camera(client, h)
    behaviors = [{"kind": "intrusion", "trigger_seconds": 0, "clip": False},
                 {"kind": "loitering", "trigger_seconds": 30, "snapshot": False}]
    r = client.post("/api/v1/zones", json={**VALID, "camera_id": cam["id"], "type": "behavior",
                                           "behaviors": behaviors}, headers=h)
    assert r.status_code == 200 and r.json()["behaviors"] == behaviors
    bad = client.post("/api/v1/zones", json={**VALID, "camera_id": cam["id"], "type": "behavior",
                                             "behaviors": [{"kind": "intrusion", "clip": "no"}]}, headers=h)
    assert bad.status_code == 422


def test_attendance_direction_conflict_rejected_on_create(client):
    h = _admin_headers(client)
    cam = _camera(client, h)
    assert _gate(client, h, cam["id"], "entry").status_code == 200
    assert _gate(client, h, cam["id"], "entry", name="g2").status_code == 200  # arah sama boleh
    conflict = _gate(client, h, cam["id"], "exit", name="g3")
    assert conflict.status_code == 422
    assert "another direction" in conflict.json()["detail"]
    assert _gate(client, h, cam["id"], "exit", active=False, name="g4").status_code == 200  # nonaktif tidak dihitung


def test_attendance_direction_conflict_rejected_on_patch(client):
    h = _admin_headers(client)
    cam = _camera(client, h)
    assert _gate(client, h, cam["id"], "entry").status_code == 200
    exit_gate = _gate(client, h, cam["id"], "exit", active=False, name="keluar").json()
    r = client.patch(f"/api/v1/zones/{exit_gate['id']}", json={"active": True}, headers=h)
    assert r.status_code == 422
    assert client.get(f"/api/v1/zones/{exit_gate['id']}", headers=h).json()["active"] is False
    ok = client.patch(f"/api/v1/zones/{exit_gate['id']}", json={"active": True, "direction": "entry"}, headers=h)
    assert ok.status_code == 200


def test_attendance_gates_on_different_cameras_do_not_conflict(client):
    h = _admin_headers(client)
    a, b = _camera(client, h, "cam-a"), _camera(client, h, "cam-b")
    assert _gate(client, h, a["id"], "entry").status_code == 200
    assert _gate(client, h, b["id"], "exit").status_code == 200
```

Di `backend/tests/test_config_push.py`: ganti `assert cam["analyzers"] == ["intrusion"]` dan `assert cam["analyzers"] is None ...` menjadi `assert "analyzers" not in cam`.

- [ ] **Step 2: Jalankan, pastikan gagal**

Run: `cd backend && .venv/bin/python -m pytest tests/test_zones_api.py tests/test_config_push.py -q`
Expected: FAIL — `clip: "no"` diterima, konflik tidak ditolak, `analyzers` masih ada.

- [ ] **Step 3: Implementasi**

`backend/app/schemas/zone.py` — di `_validate_behaviors`, setelah validasi `speed`:

```python
        for flag in ("snapshot", "clip"):
            if flag in b and not isinstance(b[flag], bool):
                raise ValueError(f"{flag} must be a boolean")
```

dan docstring: `"""behaviors = [{"kind", "trigger_seconds", [speed_limit_mps], [snapshot], [clip]}]."""`.

`backend/app/api/zones.py` — helper di bawah `_config_push`:

```python
_ATTENDANCE_TYPES = ("absensi", "attendance")


def _check_direction_conflict(db: Session, zone: Zone) -> None:
    """Satu kamera: zona absensi aktif hanya boleh satu arah (satu FaceGateWorker per kamera)."""
    if zone.type not in _ATTENDANCE_TYPES or not zone.active:
        return
    q = db.query(Zone).filter(
        Zone.camera_id == zone.camera_id,
        Zone.type.in_(_ATTENDANCE_TYPES),
        Zone.active.is_(True),
        Zone.direction != zone.direction,
    )
    if zone.id is not None:
        q = q.filter(Zone.id != zone.id)
    if q.first() is not None:
        db.rollback()  # buang perubahan patch yang belum di-commit
        raise HTTPException(422, "camera already has an active attendance zone with another direction")
```

`create_zone`:

```python
    zone = Zone(**body.model_dump())
    _check_direction_conflict(db, zone)
    db.add(zone); db.commit(); db.refresh(zone)
```

`update_zone` — setelah blok cek `direction` wajib, sebelum `db.commit()`: `_check_direction_conflict(db, zone)`.

`backend/app/services/config_push.py` — hapus baris `"analyzers": cam.analyzers,          # None = semua analyzer aktif`.

`backend/app/models/camera.py` — komentar kolom `analyzers`: `# deprecated: tidak dibaca (zona = satu-satunya aturan); tanpa migrasi`.

- [ ] **Step 4: Jalankan, pastikan lulus**

Run: `cd backend && .venv/bin/python -m pytest tests -q -m "not gpu" > /tmp/be.log 2>&1; grep -oE '[0-9]+ (passed|failed)[^|]*' /tmp/be.log | tail -1`
Expected: semua passed.

- [ ] **Step 5: CHANGELOG + commit**

```markdown
- **Backend**: item `behaviors` menerima `snapshot`/`clip` (bool, lainnya 422); zona absensi aktif dengan arah
  berbeda di kamera yang sama ditolak 422 saat create/patch (patch gagal tidak setengah tersimpan); config push
  tidak lagi mengirim `analyzers` (kolom dibiarkan, deprecated). Backend **<angka> passed**.
```

```bash
git add backend/app/schemas/zone.py backend/app/api/zones.py backend/app/services/config_push.py backend/app/models/camera.py backend/tests/test_zones_api.py backend/tests/test_config_push.py CHANGELOG.md
git commit -m "feat(zone): snapshot/clip per behavior + tolak konflik arah absensi"
```

---

### Task 3: Zona Deteksi — toggle Snapshot/Clip per behavior

**Files:**
- Modify: `frontend/src/api/zones.ts` (tipe `Behavior`)
- Modify: `frontend/src/features/config/ZonesPage.tsx` (hapus toggle level zona, toggle per behavior, pesan konflik)
- Modify: `frontend/src/app/i18n.tsx`
- Test: `frontend/src/__tests__/zones.test.tsx`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: flag per behavior + 422 konflik (Task 2).
- Produces: `Behavior = { kind; trigger_seconds; speed_limit_mps?; snapshot?: boolean; clip?: boolean }`; toggle ber-`id` `zone-snapshot-<kind>` / `zone-clip-<kind>`; i18n `zones.directionConflict`.

- [ ] **Step 1: Tulis tes (gagal)**

Di `frontend/src/__tests__/zones.test.tsx`:
- `stubFetch` menerima opsi `patchStatus?: number`: di cabang PATCH, bila `opts.patchStatus` ada kembalikan `{ ok: false, status: opts.patchStatus, json: () => Promise.resolve({ detail: 'x' }) }`.
- `selectZone(zones, opts = {})` meneruskan `opts` ke `stubFetch({ zones, ...opts })`.
- Tambah tes:

```tsx
test('Snapshot dan Clip diatur per behavior dan dikirim di item behaviors', async () => {
  const fetchMock = await selectZone([zoneFix({ behaviors: [
    { kind: 'intrusion', trigger_seconds: 0 }, { kind: 'loitering', trigger_seconds: 30 },
  ] })])
  expect(document.getElementById('zone-snapshot')).toBeNull() // toggle level zona dihapus
  expect(document.getElementById('zone-clip')).toBeNull()
  fireEvent.click(document.getElementById('zone-clip-intrusion')!)
  fireEvent.click(document.getElementById('zone-snapshot-loitering')!)
  fireEvent.click(screen.getByTestId('zone-save'))
  await waitFor(() => expect(patchBody(fetchMock).behaviors).toEqual([
    { kind: 'intrusion', trigger_seconds: 0, clip: false },
    { kind: 'loitering', trigger_seconds: 30, snapshot: false },
  ]))
})

test('toggle behavior mengikuti flag zona lama bila belum diatur', async () => {
  await selectZone([zoneFix({ clip: false, behaviors: [{ kind: 'intrusion', trigger_seconds: 0 }] })])
  expect(document.getElementById('zone-clip-intrusion')).toHaveAttribute('aria-checked', 'false')
  expect(document.getElementById('zone-snapshot-intrusion')).toHaveAttribute('aria-checked', 'true')
  expect(document.getElementById('zone-clip-loitering')).toBeNull() // behavior tidak dicentang → tanpa toggle
})

test('zona absensi tanpa toggle Snapshot/Clip; konflik arah menampilkan pesan', async () => {
  await selectZone(
    [zoneFix({ type: 'attendance', direction: 'exit', behaviors: [{ kind: 'attendance', trigger_seconds: 0 }] })],
    { patchStatus: 422 },
  )
  expect(document.querySelector('[id^="zone-clip"]')).toBeNull()
  expect(document.querySelector('[id^="zone-snapshot"]')).toBeNull()
  fireEvent.click(screen.getByTestId('zone-save'))
  expect(await screen.findByText('Kamera ini sudah punya zona absensi aktif dengan arah lain.')).toBeInTheDocument()
})
```

(Carbon `Toggle` memasang `id` pada tombol `role="switch"` dengan `aria-checked`; bila berbeda di versi terpasang, cari lewat `screen.getAllByRole('switch')` di dalam baris behavior dan catat deviasinya.)

- [ ] **Step 2: Jalankan, pastikan gagal**

Run: `cd frontend && npx vitest run src/__tests__/zones.test.tsx`
Expected: FAIL — `zone-clip-intrusion` tidak ada.

- [ ] **Step 3: Implementasi**

`frontend/src/api/zones.ts`:

```ts
export type Behavior = {
  kind: BehaviorKind | 'attendance'
  trigger_seconds: number
  speed_limit_mps?: number
  snapshot?: boolean // kosong = ikut flag zona (data lama)
  clip?: boolean
}
```

`frontend/src/features/config/ZonesPage.tsx`:
- Hapus kedua `<Toggle id="zone-snapshot" …/>` dan `<Toggle id="zone-clip" …/>`.
- Di dalam blok `{b && ( <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', paddingLeft: 24 }}> … )}`, setelah `NumberInput` trigger (dan speed untuk running), tambahkan:

```tsx
                              <Toggle
                                id={`zone-snapshot-${kind}`}
                                size="sm"
                                labelText={t('zones.snapshot')}
                                toggled={b.snapshot ?? selected.snapshot}
                                onToggle={(v) => setBehavior(kind, { snapshot: v })}
                              />
                              <Toggle
                                id={`zone-clip-${kind}`}
                                size="sm"
                                labelText={t('zones.clip')}
                                toggled={b.clip ?? selected.clip}
                                onToggle={(v) => setBehavior(kind, { clip: v })}
                              />
```

- Di `save`, ganti `catch { setError(t('zones.saveError')) }` dengan:

```tsx
    } catch (e) {
      const conflict = e instanceof Error && e.message.endsWith(': 422') && selected.type === 'attendance'
      setError(t(conflict ? 'zones.directionConflict' : 'zones.saveError'))
    } finally {
```

`frontend/src/app/i18n.tsx`:
- `id`: `'zones.snapshot': 'Snapshot'`, `'zones.clip': 'Clip'`, `'zones.sub': 'Zona behavior dan absensi per kamera — satu-satunya tempat mengatur deteksi'`, tambah `'zones.directionConflict': 'Kamera ini sudah punya zona absensi aktif dengan arah lain.'`.
- `en`: `'zones.snapshot': 'Snapshot'`, `'zones.clip': 'Clip'`, `'zones.sub': 'Behavior and attendance zones per camera — the only place detection is configured'`, tambah `'zones.directionConflict': 'This camera already has an active attendance zone with the other direction.'`.

- [ ] **Step 4: Jalankan, pastikan lulus**

Run: `cd frontend && npx vitest run && npx tsc -b`
Expected: semua passed (tes zona lama tetap lulus: payload tanpa key `snapshot`/`clip` bila toggle tidak disentuh).

- [ ] **Step 5: CHANGELOG + commit**

```markdown
- **Zona Deteksi**: toggle Snapshot/Clip level zona dihapus; tiap behavior tercentang punya toggle Snapshot dan
  Clip (default mengikuti flag zona lama), dikirim sebagai key di item `behaviors`; zona absensi tanpa toggle
  media; konflik arah → "Kamera ini sudah punya zona absensi aktif dengan arah lain.". Frontend **<angka> passed**.
```

```bash
git add frontend/src/api/zones.ts frontend/src/features/config/ZonesPage.tsx frontend/src/app/i18n.tsx frontend/src/__tests__/zones.test.tsx CHANGELOG.md
git commit -m "feat(zone): toggle snapshot/clip per behavior di Zona Deteksi"
```

---

### Task 4: Hapus halaman Gate Absensi

**Files:**
- Modify: `frontend/src/features/config/ConfigurationPage.tsx`
- Delete: `frontend/src/features/config/GatesPage.tsx`, `frontend/src/__tests__/gates.test.tsx`
- Modify: `frontend/src/app/i18n.tsx` (hapus key `gates.*` yatim; ubah `configuration.sub`)
- Test: `frontend/src/__tests__/configuration.test.tsx`
- Modify: `CHANGELOG.md`

**Interfaces:** — (tab `gates` hilang dari `TABS`).

- [ ] **Step 1: Ubah tes (gagal)**

Di `frontend/src/__tests__/configuration.test.tsx`:
- Semua `renderConfiguration('/configuration?tab=gates')` → `'/configuration?tab=zones'`; semua `{ name: 'Gate Absensi', selected: true }` → `{ name: 'Zona Deteksi', selected: true }`; `toHaveTextContent('?tab=gates')` → `'?tab=zones'`.
- Teks sub: `'Kamera, zona, gate absensi, dan retensi dalam satu tempat'` → `'Kamera, zona, model deteksi, dan retensi dalam satu tempat'`.
- Tambah:

```tsx
test('old gates URL falls back to cameras and the Gate tab is gone', async () => {
  stubFetch()
  renderConfiguration('/configuration?tab=gates')
  expect(await screen.findByRole('tab', { name: 'Kamera', selected: true })).toBeInTheDocument()
  expect(screen.queryByRole('tab', { name: 'Gate Absensi' })).not.toBeInTheDocument()
})
```

(Nama tab Kamera = nilai `t('cameras.title')`; bila berbeda dari "Kamera", pakai teks itu.)

- [ ] **Step 2: Jalankan, pastikan gagal**

Run: `cd frontend && npx vitest run src/__tests__/configuration.test.tsx`
Expected: FAIL — tab Gate Absensi masih ada.

- [ ] **Step 3: Implementasi**

`ConfigurationPage.tsx`: hapus `import GatesPage from './GatesPage'`; `TABS = ['cameras', 'zones', 'detection', 'storage', 'nodes'] as const`; hapus `gates: 'gates.title'` dari `TAB_LABEL`; hapus `<TabPanel>{tab === 'gates' && <GatesPage />}</TabPanel>`.

Hapus `GatesPage.tsx` dan `__tests__/gates.test.tsx`.

`i18n.tsx`: hapus semua key `gates.*` di `id` dan `en` yang tidak lagi dirujuk (`grep -rn "'gates\." src --include=*.tsx` hanya boleh menyisakan i18n itu sendiri sebelum dihapus); `configuration.sub` → id `'Kamera, zona, model deteksi, dan retensi dalam satu tempat'`, en `'Cameras, zones, detection model, and retention in one place'`. Ubah juga `zones.attendanceHint` bila menyebut Gate: id `'Gambar poligon di area tempat wajah terlihat, bukan lantai. Event terbit setelah beberapa frame wajah yang jelas (atur di Deteksi & Model → Advanced).'` sudah benar — biarkan.

- [ ] **Step 4: Jalankan, pastikan lulus**

Run: `cd frontend && npx vitest run && npm run build`
Expected: semua passed (jumlah turun sebanyak tes `gates.test.tsx` yang dihapus, naik 1), build 0.

- [ ] **Step 5: CHANGELOG + commit**

```markdown
- **Halaman Gate Absensi dihapus**: zona absensi dibuat/diubah di Zona Deteksi (tipe Absensi, arah, aktif);
  kolom SNAPSHOT/CLIP Gates memang no-op (pipeline wajah selalu crop + snapshot, tanpa clip). `?tab=gates` lama
  jatuh ke tab Kamera. Frontend **<angka> passed**.
```

```bash
git add -A frontend/src/features/config frontend/src/__tests__ frontend/src/app/i18n.tsx CHANGELOG.md
git commit -m "feat(config): hapus halaman Gate Absensi — semua zona di Zona Deteksi"
```

---

### Task 5: Deteksi & Model = parameter model + Status AI

**Files:**
- Modify: `frontend/src/features/config/DetectionPage.tsx`
- Modify: `frontend/src/app/i18n.tsx`
- Test: `frontend/src/__tests__/detection.test.tsx`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: `listZones()` (sudah dipanggil halaman ini).
- Produces: kolom Status AI (`data-testid="ai-status-<cameraId>"`), kartu model wajah.

- [ ] **Step 1: Ubah tes (gagal)**

Di `frontend/src/__tests__/detection.test.tsx`:
- Tes `detection tab updates analyzer and global motion settings` → ganti nama menjadi `detection tab saves per-camera fps and global motion settings`; ganti langkah klik chip `intrusion` dengan mengubah AI FPS:

```tsx
  await waitFor(() => expect(document.querySelector('#fps-1')).not.toBeNull())
  await userEvent.type(document.querySelector('#fps-1') as HTMLInputElement, '8')
  await waitFor(() => {
    const patch = calls.find((c) => c.url.endsWith('/cameras/1') && c.init?.method === 'PATCH')
    expect(JSON.parse(String(patch!.init!.body))).toEqual({ ai_fps: 8 })
  })
```

- Hapus tes `chip attendance tidak ditampilkan tapi tetap tersimpan saat chip lain di-toggle`.
- Ganti tes `tabel hanya memuat kamera yang punya zona, chip ringkas, …` dengan:

```tsx
test('tabel memuat semua kamera dengan Status AI dari zona aktif, tanpa chip analyzer', async () => {
  const cams = [camera, { ...camera, id: 2, name: 'CAM-02' }, { ...camera, id: 3, name: 'CAM-03', enabled: false }]
  const zones = [
    { id: 9, camera_id: 1, name: 'Z', type: 'behavior', polygon: [], behaviors: [], trigger_seconds: 0, active: true },
    { id: 10, camera_id: 1, name: 'G', type: 'attendance', polygon: [], behaviors: [], trigger_seconds: 0, active: true },
    { id: 11, camera_id: 2, name: 'Off', type: 'behavior', polygon: [], behaviors: [], trigger_seconds: 0, active: false },
  ]
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    const body = url.includes('/detector-settings') ? settings
      : url.includes('/zones') ? zones
      : url.includes('/cameras') ? cams
      : { id: 1, username: 'admin', role: 'admin' }
    return { ok: true, status: 200, json: async () => body }
  }))
  render(<I18nProvider><MemoryRouter initialEntries={['/configuration?tab=detection']}><ConfigurationPage /></MemoryRouter></I18nProvider>)

  expect(await screen.findByTestId('ai-status-1')).toHaveTextContent('Aktif · 2 zona')
  expect(screen.getByTestId('ai-status-2')).toHaveTextContent('Tidak jalan (tanpa zona aktif)')
  expect(screen.getByTestId('ai-status-3')).toHaveTextContent('Kamera nonaktif')
  expect(document.querySelectorAll('.det-chip')).toHaveLength(0)
  expect(screen.getByText('InsightFace buffalo_l')).toBeInTheDocument()
  expect(screen.getByText('lepas track setelah 3 s')).toBeInTheDocument()
  expect((document.querySelector('#fps-1') as HTMLInputElement).placeholder).toBe('5')
})

test('reset override tidak lagi mengirim analyzers', async () => {
  const calls: { url: string; init?: RequestInit }[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, init })
    const body = url.includes('/detector-settings') ? settings : url.includes('/zones') ? [zone]
      : url.includes('/cameras') ? [camera] : { id: 1, username: 'admin', role: 'admin' }
    return { ok: true, status: 200, json: async () => body }
  }))
  render(<I18nProvider><MemoryRouter initialEntries={['/configuration?tab=detection']}><ConfigurationPage /></MemoryRouter></I18nProvider>)
  await userEvent.click(await screen.findByRole('button', { name: 'Reset override' }))
  await waitFor(() => {
    const patch = calls.find((c) => c.url.endsWith('/cameras/1') && c.init?.method === 'PATCH')
    expect(JSON.parse(String(patch!.init!.body))).toEqual({ ai_fps: null, confidence: null, motion_enabled: null })
  })
})
```

(`camera` fixture punya `enabled: true`; kamera 3 di-override `enabled: false`.)

- [ ] **Step 2: Jalankan, pastikan gagal**

Run: `cd frontend && npx vitest run src/__tests__/detection.test.tsx`
Expected: FAIL — `ai-status-1` tidak ada, chip masih dirender.

- [ ] **Step 3: Implementasi**

`frontend/src/features/config/DetectionPage.tsx`:
- Hapus `KINDS`, `CHIP_KINDS` beserta komentarnya; `DetectionPatch = Pick<CameraPayload, 'ai_fps' | 'confidence' | 'motion_enabled'>`.
- State + load:

```tsx
  const [cameras, setCameras] = useState<Camera[]>([])
  const [activeZones, setActiveZones] = useState<Map<number, number>>(new Map())
  // ...
  useEffect(() => {
    // semua kamera tampil; Status AI = jumlah zona aktif (zona aktif = AI aktif)
    Promise.all([listCameras(), getDetectorSettings(), listZones()])
      .then(([cams, value, zones]) => {
        const counts = new Map<number, number>()
        for (const z of zones) if (z.active) counts.set(z.camera_id, (counts.get(z.camera_id) ?? 0) + 1)
        setCameras(cams)
        setActiveZones(counts)
        setSettings(value)
      })
      .catch(() => {})
  }, [])
```

- Helper di dalam komponen (setelah `if (!settings) return null`):

```tsx
  const aiStatus = (camera: Camera) => {
    if (!camera.enabled) return t('detection.statusDisabled')
    const n = activeZones.get(camera.id) ?? 0
    return n > 0 ? t('detection.statusActive').replace('{n}', String(n)) : t('detection.statusIdle')
  }
```

- Kartu: ganti kartu tracker dan tambah kartu wajah:

```tsx
        <div className="det-tile"><small>{t('detection.tracker')}</small><strong>ByteTrack</strong><span>{t('detection.trackerHint')}</span></div>
        <div className="det-tile"><small>{t('detection.faceModel')}</small><strong>InsightFace buffalo_l</strong><span>SCRFD + ArcFace</span></div>
```

- Header tabel: `<tr><th>{t('detection.camera')}</th><th>AI FPS</th><th>{t('detection.confidence')}</th><th>{t('detection.status')}</th><th /></tr>`.
- Baris: hapus `active`/`hidden` dan seluruh `<td>` chip; ganti dengan `<td data-testid={`ai-status-${camera.id}`}>{aiStatus(camera)}</td>`; tombol Reset → `patch(camera, { ai_fps: null, confidence: null, motion_enabled: null })`.

`frontend/src/app/i18n.tsx` — `id`:

```ts
    'detection.status': 'STATUS AI',
    'detection.statusActive': 'Aktif · {n} zona',
    'detection.statusIdle': 'Tidak jalan (tanpa zona aktif)',
    'detection.statusDisabled': 'Kamera nonaktif',
    'detection.trackerHint': 'lepas track setelah 3 s',
    'detection.faceModel': 'MODEL WAJAH',
    'detection.hint': 'Deteksi hanya berjalan di kamera yang punya zona aktif. Atur zona di tab Zona Deteksi · kolom kosong = nilai global.',
```

`en`:

```ts
    'detection.status': 'AI STATUS',
    'detection.statusActive': 'Active · {n} zones',
    'detection.statusIdle': 'Not running (no active zone)',
    'detection.statusDisabled': 'Camera disabled',
    'detection.trackerHint': 'drops a track after 3 s',
    'detection.faceModel': 'FACE MODEL',
    'detection.hint': 'Detection only runs on cameras with an active zone. Set zones in the Detection Zones tab · empty field = global value.',
```

Hapus key `detection.analyzers` (id + en) bila tidak dirujuk lagi.

- [ ] **Step 4: Jalankan, pastikan lulus**

Run: `cd frontend && npx vitest run && npm run build && npm run lint`
Expected: semua passed; build 0; lint = set rule+file lama. Cek 390 px (`npm run dev`, `/configuration?tab=detection` dan `?tab=zones`): `document.documentElement.scrollWidth <= 390`.

- [ ] **Step 5: CHANGELOG + commit**

```markdown
- **Deteksi & Model = parameter model**: chip analyzer dihapus; tabel memuat semua kamera dengan kolom
  **Status AI** ("Aktif · N zona" / "Tidak jalan (tanpa zona aktif)" / "Kamera nonaktif"); kartu model wajah
  (InsightFace buffalo_l); teks tracker diperbaiki ("lepas track setelah 3 s"); Reset tidak mengirim
  `analyzers`. Frontend **<angka> passed**, build 0, lint set sama.
```

```bash
git add frontend/src/features/config/DetectionPage.tsx frontend/src/app/i18n.tsx frontend/src/__tests__/detection.test.tsx CHANGELOG.md
git commit -m "feat(detection): halaman parameter model + kolom Status AI, tanpa chip analyzer"
```

---

### Task 6: Dokumen, suite penuh, deploy + verifikasi (langkah ⚠ butuh izin user)

**Files:**
- Modify: `README.md` (bagian zona/konfigurasi bila menyebut Gate Absensi atau chip analyzer), `ROADMAP.md`, `DESIGN.md` bila menyebut Gate Absensi
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Dokumen**

- `grep -rn "Gate Absensi\|Attendance Gates\|analyzer aktif\|ANALYZER AKTIF\|tab=gates" README.md DESIGN.md docs/runbooks` → perbarui teks: zona absensi diatur di Zona Deteksi; deteksi hanya jalan di kamera dengan zona aktif.
- `ROADMAP.md` tabel ringkasan sebelum `| E | Edge Jetson …`: `| ZU | Zona UX (zona = aturan, Gate Absensi dihapus, Snapshot/Clip per behavior) | [~] lokal selesai, PENDING deploy + verifikasi | — | spec + plan 2026-09-25 | |`.

- [ ] **Step 2: Suite penuh**

```bash
cd backend && .venv/bin/python -m pytest tests -q -m "not gpu" > /tmp/be.log 2>&1; grep -oE '[0-9]+ (passed|failed)[^|]*' /tmp/be.log | tail -1; cd ..
backend/.venv/bin/python -m pytest vision/tests -q -m "not gpu" | tail -1
cd frontend && npx vitest run | tail -3 && npm run build > /dev/null; echo build=$?; npm run lint | tail -2; cd ..
```

Expected: semua passed; build 0; lint set sama.

- [ ] **Step 3: Commit dokumen**

```bash
git add README.md ROADMAP.md DESIGN.md docs/runbooks CHANGELOG.md
git commit -m "docs(zone): zona = satu-satunya aturan deteksi, Gate Absensi dihapus"
```

- [ ] **Step 4 ⚠: Ukur sebelum deploy (baca-saja, boleh tanpa izin)**

```bash
ssh gspe-ai3 'journalctl -u vision-node --since "-2h" --no-pager | grep "started .* worker" | tail -1; nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv,noheader; top -bn1 | grep -m1 isentinel-vision'
```

Simpan angka "sebelum".

- [ ] **Step 5 ⚠: Deploy (minta izin user dulu)**

```bash
git push -u origin feat/zone-config-ux
ssh gspe-ai3 'cd /home/gspe-ai3/project_cv/I-Sentinel && git fetch -q && git checkout -q feat/zone-config-ux && git pull -q --ff-only \
  && kill $(cat /sys/fs/cgroup/system.slice/isentinel-api.service/cgroup.procs) \
  && kill $(cat /sys/fs/cgroup/system.slice/vision-node.service/cgroup.procs); sleep 20; curl -s localhost:8000/api/v1/health; \
  journalctl -u vision-node --since "-30s" --no-pager | grep "started .* worker" | tail -1'
```

Expected: health ok; jumlah worker turun (kamera tanpa zona aktif tidak lagi punya worker). Ukur ulang GPU/CPU seperti Step 4.

- [ ] **Step 6: Verifikasi bersama user**

1. Tab Gate Absensi hilang; `?tab=gates` membuka tab Kamera.
2. Zona 15 cam 363 (intrusion aktif, chip lama `['attendance']`) → berjalan di depan kamera ≥ 2 s menghasilkan event intrusion + clip tanpa menyentuh chip apa pun.
3. Matikan Clip pada behavior intrusion zona 15 → event berikutnya tanpa clip (snapshot tetap).
4. Deteksi & Model: Status AI cam 363 "Aktif · 1 zona", cam tanpa zona "Tidak jalan (tanpa zona aktif)".
5. Zona absensi: mengaktifkan dua arah berbeda di satu kamera → pesan konflik.
6. 390 px tanpa overflow; screenshot ke `docs/evidence/zone-ux-*.png`.

- [ ] **Step 7: CHANGELOG + ROADMAP + commit**

Bullet "Deploy + verifikasi" dengan angka nyata (worker/GPU sebelum-sesudah, hasil langkah 1–6); ROADMAP ZU → `[x]` bila user OK.

```bash
git add docs/evidence/zone-ux-* CHANGELOG.md ROADMAP.md
git commit -m "docs(zone): evidence deploy + verifikasi zona UX"
```

Setelah user E2E OK: merge `--no-ff` ke `main` (butuh izin), server kembali ke `main`.
