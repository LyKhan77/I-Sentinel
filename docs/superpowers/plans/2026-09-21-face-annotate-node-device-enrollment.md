# Testing & Refining R1 — Face Annotation, Node Device Split, Enrollment UX

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tiga fitur hasil QnA: (1) anotasi bbox wajah + identitas pada crop/snapshot event, (2) delegasi device per-analyzer di tab Node (YOLO ≠ face), (3) enrollment multi-upload + auto-crop + score + gate.

**Architecture:** Anotasi = dua lapis: node menggambar bbox wajah (SCRFD, koordinat crop) pada crop jpeg sebelum upload; backend menggambar nama + match_score pada file crop yang sama setelah match (single artifact, overwrite di tempat). Device split = config push `devices: {detector, face}` (map per-analyzer, extensible), DB `node.face_device` (migration 0011), node fail-fast + rebuild embedder saat device berubah. Enrollment = endpoint tetap 1 foto/call (frontend loop), backend menambah auto-crop wajah + dup-check; UI file input `multiple`.

**Tech Stack:** existing — cv2 (vision), opencv/PIL backend? (cek dulu: backend pakai opencv-python-headless untuk match_crop — ya, dipakai), SQLAlchemy migration expand-only, React + Carbon + i18n.

**Branches (per fitur, Conventional Commits + CHANGELOG per task):**
1. `feat/face-annotate-snapshot`
2. `feat/node-device-per-analyzer`
3. `feat/enrollment-improve`

**Data cleanup events (4491 → 5, 1 contoh per type dengan 2 media) — SUDAH DIKERJAKAN di server sebelum plan ini; dicatat di runbook + CHANGELOG, bukan bagian fitur.**

---

### Task 1: Anotasi crop — bbox wajah di node

**Branch:** `feat/face-annotate-snapshot` (base main)

**Files:**
- Modify: `vision/vision/face.py` (embed_jpeg → kembalikan juga jpeg beranotasi? TIDAK — anotasi terpisah)
- Modify: `vision/vision/node.py` (`_attach_crop`)
- Test: `vision/tests/test_node_face_embed.py`

**Desain:** node menggambar rect + label `face {det:.2f}` pada jpeg crop SEBELUM upload, koordinat `res["bbox"]` (pixel-space dalam crop). Backend lapis kedua menimpa dengan nama employee + match_score setelah match sukses. cv2 sudah dep vision.

- [ ] **Step 1: test gagal** — `_attach_crop` dengan embedder → jpeg yang di-upload berubah (byte berbeda dari input, dan bila di-decode berisi rect lebih gelap di area bbox). Simpel: recorder spy membandingkan panjang/bytes != jpeg asli + embedder fake yang menggambar rectangle hitam.

```python
def test_attach_crop_annotated_with_face_box():
    # FakeEmbedder.embed_jpeg sekarang juga menggambar: decode jpeg asli vs
    # hasil upload → piksel di (10,10)-(100,100) beda (rect digambar)
    ...
```

- [ ] **Step 2: implement** — di `_attach_crop` setelah `res` didapat:

```python
                self._draw_face_box(jpeg, res)  # ubah bytes jpeg di tempat

# method baru di CameraWorker:
def _draw_face_box(self, jpeg: bytes, res: dict) -> None:
    """Gambar rect + label 'face <det>' pada jpeg (in-place, in-memory)."""
    import cv2, numpy as np
    img = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return
    x1, y1, x2, y2 = [int(v) for v in res["bbox"]]
    cv2.rectangle(img, (x1, y1), (x2, y2), (0, 200, 0), 2)
    label = f"face {res['det_score']:.2f}"
    cv2.putText(img, label, (x1, max(12, y1 - 6)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 200, 0), 1, cv2.LINE_AA)
    ok, buf = cv2.imencode(".jpg", img)
    if ok:
        jpeg[:] = buf.tobytes()  # caller mem-upload jpeg yang sama
```

Perhatikan `_attach_crop` mengirim `jpeg` (bytes) ke `upload_bytes` — gambar sebelum upload; embedding tetap dari jpeg asli (embed dulu, gambar kemudian; urutan di kode: embed → draw → upload).

- [ ] **Step 3: tests pass + regresi** `python -m pytest tests -q -m "not gpu"`
- [ ] **Step 4: commit** `feat(vision): bbox wajah pada crop attendance`

### Task 2: Anotasi identitas — nama + score di backend

**Branch:** lanjut `feat/face-annotate-snapshot`

**Files:**
- Modify: `backend/app/services/attendance.py` (`handle_face_event`, setelah match)
- Helper: fungsi kecil `annotate_face_crop(path, name, score)` di `backend/app/services/face.py`
- Test: `backend/tests/test_attendance_logic.py`

**Desain:** setelah match sukses, buka `STORAGE_ROOT/{crop_path}`, gambar rect (bbox wajah relatif crop — ada di payload? TIDAK: bbox di node-space = crop-space, simpan `payload["face_bbox"] = res["bbox"]` di Task 1) + teks `name (0.83)` di bawah rect, overwrite file yang sama. cv2 backend: cek `pyproject` backend — jika belum ada, pakai PIL? Backend tidak punya cv2 → tambah dep kecil `pillow` ATAU gunakan crop yang di-upload node lalu backend hanya menulis teks pakai Pillow. Keputusan: **Pillow** (ringan, sudah umum di venv server via insightface deps? cek dulu; kalau sudah ada → tanpa dep baru).

- [ ] **Step 1: test** — event dengan embedding → match → file crop di temp disk berubah + berisi teks nama (verifikasi: file berubah bytes, dan payload tetap). 

```python
def test_handle_face_event_annotates_crop(tmp_path, db, monkeypatch):
    # crop file dummy di tmp_path; monkeypatch storage_root ke tmp_path
    # match_vector matched → file crop di-overwrite dan berubah
    ...
```

- [ ] **Step 2: implement** — gagal diam-diam dibolehkan (annotasi best-effort, try/except + log, jangan blok attendance).

```python
def annotate_face_crop(image_path: str, name: str, score: float) -> None:
    """Gambar nama+score pada file crop (overwrite). Best-effort — gagal = log, lanjut."""
    try:
        from PIL import Image, ImageDraw
        img = Image.open(image_path)
        from PIL import ImageDraw
        d = ImageDraw.Draw(img)
        w, h = img.size
        d.rectangle([0, 0, w - 1, h - 1], outline=(0, 200, 0), width=3)
        d.text((6, h - 20), f"{name} {score:.2f}", fill=(0, 200, 0))
        img.save(image_path)
    except Exception:
        logger.warning("annotate face crop gagal: %s", image_path, exc_info=True)
```

- [ ] **Step 3: tests + commit** `feat(backend): anotasi identitas pada crop attendance`

### Task 3: Node device per-analyzer (backend + node)

**Branch:** `feat/node-device-per-analyzer` (base main)

**Files:**
- Migration: `backend/alembic/versions/0011_node_face_device.py` (expand-only: `node.face_device` String(16) nullable)
- Modify: `backend/app/models/node.py`, `backend/app/services/config_push.py` (payload `face: {device: ...}` + tetap `detector: {device}`), `backend/app/api/nodes.py` (PUT `/nodes/{id}/device` generik? — TIDAK: tambah `PUT /nodes/{id}/face-device` mengikuti pola detector-device; validasi format `cuda:N` via hw heartbeat + empty=auto)
- Modify: `vision/vision/config.py` (baca `face.device` dari config push → `self.cfg.face_device`), `vision/vision/node.py` (`apply_config`: device face berubah → rebuild `self.face` = FaceEmbedder(root, new_device); pin invalid → reject config + log ERROR, node tetap hidup — pola detector device existing)
- Test: backend `test_nodes_api.py` (+face device endpoint & config push), vision `test_config_device.py` (face device apply/reject/rebuild)

- [ ] **Step 1: test backend gagal** — config push payload punya key `face.device`; API PUT face-device tersimpan; validasi 422 invalid.
- [ ] **Step 2: test vision gagal** — apply_config dengan face device baru → embedder di-rebuild dengan device itu; pin invalid → config ditolak, embedder lama tetap.
- [ ] **Step 3: implement** minimal sesuai pola detector-device existing (jangan generalisasi berlebihan: dua endpoint eksplisit > endpoint generik `kind` — YAGNI sampai analyzer ketiga).
- [ ] **Step 4: regresi backend + vision; commit** `feat: device delegation per-analyzer (detector + face) via config push`

### Task 4: UI tab Node — dropdown per analyzer

**Branch:** lanjut Task 3

**Files:**
- Modify: `frontend/src/api/cameras.ts` (`setNodeFaceDevice`), `frontend/src/features/config/NodesPanel.tsx` (dua Select per node + state draft per field), `frontend/src/app/i18n.tsx` (keys `nodes.deviceFace`, dst. EN/ID)
- Test: `frontend/src/__tests__/` tambah kasus NodesPanel dua dropdown + simpan

- [ ] **Step 1: test vitest gagal** — render NodesPanel dengan node ber-GPU → ada 2 Select (label "Detector device (GPU)" dan "Face recognition device"), onChange masing-masing memanggil endpoint yang benar.
- [ ] **Step 2: implement; mobile 390px tetap lulus** (dua Select di-stack vertical).
- [ ] **Step 3: `npm test`, `npm run build`; commit** `feat(ui): tab Node — pin face device terpisah dari detector`

### Task 5: Enrollment multi-upload + auto-crop + score + gate

**Branch:** `feat/enrollment-improve` (base main)

**Files:**
- Modify: `backend/app/api/enrollment.py`:
  - `POST /{employee_id}/photos/batch` (`UploadFile` list, max 5 per call) → per-file: embed → (no_face / low_quality / ok), auto-crop wajah (bbox + margin 30%, simpan file crop sebagai `source_image_path`), kembalikan per-file hasil `{ok, quality, reason, duplicate_of?}`
  - duplicate check: cosine vektor baru vs SEMUA embedding employee LAIN; warn (bukan reject) bila best ≥ `settings.face_dup_warn` (default 0.6) → sertakan `similar_to: {employee_id, score}`
- Modify: `backend/app/services/face.py`: ekstrak `_crop_face(image_path, bbox, margin)` + baca `face_dup_warn` setting di `app/core/config.py`
- Modify: `frontend/src/features/enrollment/EnrollmentPage.tsx`: input `multiple`, loop upload, list hasil per foto (crop preview + quality + status duplikat), progress "n/MIN 3 foto aktif"
- i18n keys baru EN/ID
- Test: backend `test_enrollment_api.py` (multi-upload: 2 ok + 1 no_face; dup warn), frontend `enrollment.test.tsx` (multi-select → N upload calls, score tampil)

- [ ] **Step 1: test backend gagal** — POST photos/bulk belum ada.
- [ ] **Step 2: implement** — reuse `enroll_embedding`; crop = simpan ulang file hasil crop dan jadikan source_image_path (foto mentah TIDAK disimpan).
- [ ] **Step 3: test frontend gagal → implement → `npm test`, `npm run build`**
- [ ] **Step 4: regresi penuh backend + frontend; commit** `feat(enrollment): multi-upload, auto-crop, score, gate kualitas+duplikat`

### Task 5b: Runbook + docs

- [ ] Runbook satu halaman: prosedur cleanup events (sudah dieksekusi — catat sebagai opsi operasional + SQL yang dipakai).
- [ ] CHANGELOG per branch; DESIGN.md tidak berubah (UI design doc Carbon), README struktur tidak berubah.

## Self-Review

- Spec: anotasi 2-lapis ✓ (A), trigger tetap person ✓, enrollment 3 pilihan user ✓, device split per-analyzer + extensible ✓.
- Placeholder: Task 1/2 test dibuat konkret di eksekusi (pola fixture sudah ada di test_node_face_embed.py / test_attendance_logic.py).
- Type: `payload["face_bbox"]` (node) dipakai backend Task 2; `res["bbox"]` konsisten dengan FaceEmbedder.
