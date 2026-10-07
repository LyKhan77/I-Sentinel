# Node Apply Config Per Camera Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Config push hanya memulai ulang worker kamera yang berubah, tidak semua kamera.

**Architecture:** `VisionNode.apply_config` membandingkan `CameraCfg` baru dengan `_applied` (state yang diterapkan) dan hanya menghentikan/memulai kamera yang berbeda; setelan global yang berubah, pertama kali, atau galat tak terduga tetap restart penuh. `run()` menguras antrean config dan memakai snapshot terakhir. Semua di `vision/vision/node.py`.

**Tech Stack:** Python 3.11, pytest, threading; tanpa dependensi baru.

**Spec:** `docs/superpowers/specs/2026-10-07-node-apply-per-camera-design.md` (baca dulu; plan memakai nomor bagian spec). Branch: `feat/node-apply-per-camera`.

## Global Constraints

- Tanda tangan publik tetap: `apply_config(self, cfg_dict)`; `_workers` tetap `list` datar (tes mengisi dan membandingkannya).
- Tidak ada perubahan backend, kontrak MQTT, `_camera_stats`, heartbeat, atau `self.events`.
- Restart per **kamera**: worker detect dan face satu kamera dihentikan/dimulai bersama dengan `Recorder`/`ClipRing`-nya (dibagi dua worker itu).
- Log diff persis: `config applied: restarted %s, added %s, removed %s, unchanged %d` (daftar id terurut).
- Tes lama tidak diubah dan tetap lulus; tes baru di berkas baru `vision/tests/test_config_apply_per_camera.py` agar helper lama tidak tersentuh.
- Commit Conventional Commits, satu per task, **tanpa atribusi AI** (AGENTS.md §9; abaikan trailer `Co-Authored-By` bawaan). Jangan `push`.
- Tiap task menambah satu entri `CHANGELOG.md` (terbaru di atas; format entri yang ada: Konteks, Perubahan, Bukti = keluaran tes yang ditempel, Dampak, Rollback) dalam commit yang sama.
- Jangan `uv sync`, `uv lock`, atau membuat ulang venv. Jalankan suite berurutan. Tes vision: dari `vision/`, `../backend/.venv/bin/python -m pytest tests -q -m "not gpu"`.
- Deploy dan verifikasi server di luar plan ini (sesi perencanaan).

## Pre-flight

- [ ] Ukur baseline dari `vision/`: `../backend/.venv/bin/python -m pytest tests -q -m "not gpu"` (acuan perencana: `247 passed, 3 deselected, 2 warnings`) dan tempel di entri CHANGELOG Task 1. Backend dan frontend tidak disentuh.

## Review Focus

Kondisi yang tidak disebut spec tetapi paling mungkin menggigit; tiap baris punya tes di task pemiliknya.

1. Kamera yang gagal dimulai lalu config **kembali** ke nilai sebelumnya: harus dimulai, bukan dianggap "tidak berubah". (Task 2)
2. `Recorder` kamera yang tidak berubah tidak boleh ditutup. (Task 1, 2)
3. Kamera dengan `zones: []` lalu diberi zona: worker dimulai; kamera dihapus lalu ditambah lagi tanpa `confidence` tidak mewarisi `confidence` lama. (Task 2)
4. Tiga config tertumpuk di antrean: hanya yang terakhir diterapkan, dan satu pesan tunggal tetap diteruskan apa adanya. (Task 3)
5. Config pertama setelah start (node tanpa `_applied`/tanda tangan global) berperilaku seperti sekarang (restart penuh). (Task 2)

## File Structure

- Modify: `vision/vision/node.py` (`__init__`, `apply_config`, `_start_workers`, `_stop_workers`, `run`; fungsi baru `_start_camera`, `_global_signature`).
- Create: `vision/tests/test_config_apply_per_camera.py` (helper `HoldSource`, `FakeRecorder`, `node_with`, `cam_cfg`).
- Modify: `ARCHITECTURE.md` §3, `WORKFLOW.md` (baris 79 dan 92), `docs/RUNBOOK.md` (baris 76 dan 83), `ROADMAP.md`, `CHANGELOG.md`.

---

### Task 1: Pisahkan `_start_camera` dan `_stop_workers` berfilter (tanpa perubahan perilaku)

**Files:**
- Modify: `vision/vision/node.py` (`_start_workers` lines 396-432, `_stop_workers` lines 434-446, `__init__`)
- Create: `vision/tests/test_config_apply_per_camera.py`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Produces: `VisionNode._start_camera(self, cam: CameraCfg) -> None` — isi loop per kamera di `_start_workers` (analyzer, gerbang wajah, `Recorder`/`ClipRing`, `CameraWorker`, `FaceGateWorker`); `continue` lama menjadi `return`; menambahkan worker ke `self._workers`.
- Produces: `VisionNode._stop_workers(self, camera_ids: set[int] | None = None) -> list[CameraWorker | FaceGateWorker]` — `None` = semua (perilaku lama). Dengan filter: pisahkan worker kamera itu dengan **menukar** `self._workers` ke daftar sisa secara atomik, hentikan dan `join(timeout=5.0)` yang dipisahkan, tutup `Recorder` unik yang mereka pakai (pengelompokan `id(w.recorder)` yang ada); kembalikan worker yang dihentikan.
- Produces: `self._applied: dict[int, CameraCfg]` (diinisialisasi `{}` di `__init__`; `_start_workers` menimpanya dengan **semua** kamera yang diberikan, termasuk yang tanpa worker) dan `self._detector_settings = None` di `__init__` (saat ini hanya diset di `apply_config`).
- Produces (helper tes): `HoldSource` (`__iter__`/`__next__` memblok sampai `close()` lalu `StopIteration`; `next_frame(timeout=None)` mengembalikan `None` sampai ditutup lalu `StopIteration`; `close()`, `stats() -> {}`, `target_fps = 5.0`), `FakeRecorder(camera_id, cfg, transport=None, clip_ring=None)` dengan `closed: int` dan `close()` yang menaikkannya (daftar kelas `FakeRecorder.instances`), `node_with(tmp_path, monkeypatch, api_key="")` → `VisionNode` (`NodeSettings(node_id="n", cameras_json="[]", await_config=True, data_dir=str(tmp_path), api_key=api_key)`, `detector_factory=lambda cid: MockDetector([])`, `source_factory=lambda cam: HoldSource()`, transport palsu dengan `publish_event/publish_heartbeat/publish_detections/close`, `node.face = FakeFace()` bermetode `detect_faces(img) -> []`; bila `api_key` diisi, `monkeypatch.setattr("vision.recorder.Recorder", FakeRecorder)`), `cam_cfg(cid, *, ai_fps=5.0, zone_id=1, attendance=False, **extra) -> dict` (kamera dengan satu zona intrusion `trigger_seconds 0`, `snapshot True`, `clip False`; `attendance=True` menambah zona attendance `direction "entry"`; `source_url=f"rtsp://h:8554/cam_{cid}"`).

- [ ] **Step 1: Tulis tes yang gagal** di berkas baru:
  - `test_stop_workers_with_filter_stops_only_those_cameras`: `node_with(...)`; mulai dua kamera lewat `node._start_workers([CameraCfg(**...)])` memakai `node._cameras_from_config({"cameras": [cam_cfg(1), cam_cfg(2)]})`; `before = list(node._workers)`; `stopped = node._stop_workers({1})` → `{w.camera_id for w in stopped} == {1}`, semua worker kamera 1 `stop_event.is_set()`, `node._workers == [w for w in before if w.camera_id == 2]` (identitas), worker kamera 2 tidak `stop_event.is_set()`.
  - `test_stop_workers_without_filter_stops_everything`: `_stop_workers()` → `node._workers == []`, semua `stop_event` terpasang.
  - `test_filtered_stop_closes_only_the_recorder_of_stopped_cameras` (`api_key="k"`): setelah `_stop_workers({1})`, recorder kamera 1 `closed == 1` dan kamera 2 `closed == 0` (Review Focus 2). Buat dua kamera lewat `_start_workers` seperti di atas; ambil recorder dari `w.recorder`.
  - `test_start_workers_records_applied_for_every_camera`: kamera 1 dengan zona dan kamera 3 dengan `zones: []` → `set(node._applied) == {1, 3}`.
- [ ] **Step 2: Jalankan** `../backend/.venv/bin/python -m pytest tests/test_config_apply_per_camera.py -q` — Expected: FAIL (`_stop_workers() got an unexpected keyword`/`_applied` belum ada; bukan salah impor).
- [ ] **Step 3: Implementasi** sesuai Interfaces. `_start_workers` menjadi: `_stop_workers()`, `self._await_config |= bool(cameras)`, `for cam in cameras: self._start_camera(cam)`, `self._applied = {c.camera_id: c for c in cameras}`, log `started %d worker(s) for %d camera(s)` (tetap).
- [ ] **Step 4: Jalankan** tes baru dan seluruh suite vision — Expected: PASS; jumlah naik hanya karena tes baru.
- [ ] **Step 5: CHANGELOG + commit** `refactor(vision): pisahkan _start_camera dan _stop_workers berfilter`.

---

### Task 2: Diff per kamera di `apply_config`

**Files:**
- Modify: `vision/vision/node.py` (`apply_config` lines 339-394)
- Test: `vision/tests/test_config_apply_per_camera.py`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: `_start_camera`, `_stop_workers(camera_ids)`, `_applied`, helper tes dari Task 1.
- Produces: `VisionNode._global_signature(self) -> tuple` = `(tuple(sorted(self._detector_settings.items())) if self._detector_settings else None, self.cfg.detector_device, self.cfg.face_device)`; `self._global_sig: tuple | None = None` di `__init__`.
- Produces: perilaku `apply_config` (setelah blok detector/face yang ada, sebelum memulai worker), arah algoritma:
  ```
  old_face = self._face_settings
  self._face_settings = FaceSettings.from_config(cfg_dict.get("face"))
  cameras = self._cameras_from_config(cfg_dict); sig = self._global_signature()
  self._await_config = True
  if sig != self._global_sig:                  # config pertama atau setelan global berubah
      self._start_workers(cameras); self._global_sig = sig; return
  try:
      new = {c.camera_id: c for c in cameras}
      changed = {i for i, c in new.items() if self._applied.get(i) != c}
      removed = set(self._applied) - set(new)
      if self._face_settings != old_face:
          changed |= {w.camera_id for w in self._workers if isinstance(w, FaceGateWorker)} & set(new)
      added = changed - set(self._applied)
      self._stop_workers(changed | removed)
      applied = {i: new[i] for i in set(new) - changed}      # tak berubah: tetap
      for i in sorted(changed):                # gagal satu kamera tidak menghentikan yang lain
          try: self._start_camera(new[i]); applied[i] = new[i]
          except Exception: log.exception("camera %s failed to start", i)
      self._applied, self._global_sig = applied, sig
      for i in removed: self._camera_conf.pop(i, None)
      log.info("config applied: restarted %s, added %s, removed %s, unchanged %d",
               sorted(changed - added), sorted(added), sorted(removed), len(new) - len(changed))
  except Exception:
      log.exception("config diff failed; full restart")
      self._start_workers(cameras); self._global_sig = sig
  ```
  Aturan yang mengikat: kamera yang `_start_camera`-nya gagal **tidak** ada di `_applied` (agar config yang kembali ke nilai lama tetap memicu start); `_start_workers` penuh tidak berubah dan menimpa `_applied`.

- [ ] **Step 1: Tulis tes yang gagal** (memakai `node_with`, `cam_cfg`, dan `node.apply_config({...})`; ambil worker lewat `[w for w in node._workers if w.camera_id == cid]`):
  - `test_first_config_after_start_is_a_full_restart` (Review Focus 5): `node._start_workers` dengan kamera 9 (statis) lalu `apply_config` kamera 1 → worker kamera 9 berhenti dan kamera 1 berjalan.
  - `test_same_config_twice_keeps_every_worker`: dua kali `apply_config` dengan dict sama (salinan dalam) → `node._workers` identik per objek dan tidak ada `stop_event` terpasang.
  - `test_changed_camera_restarts_only_that_camera` diparametrisasi atas perubahan di kamera 1: `ai_fps` 5→10, `source_url`, `zone_id` 1→2, `confidence` 0.4→0.6, `motion` `{"enabled": True, "threshold": 25}`, `meters_per_pixel` 0.01 → worker kamera 1 baru (tidak ada yang sama dengan sebelumnya, worker lama `stop_event` terpasang); worker kamera 2 identik dan hidup.
  - `test_removed_camera_is_stopped_and_added_camera_is_started`: `{1,2}` lalu `{2,3}`.
  - `test_global_detector_change_restarts_every_camera`: `{"detector": {"model": "m.pt", "imgsz": 640}, ...}` lalu `imgsz` 960 → semua worker diganti.
  - `test_face_settings_change_restarts_only_cameras_with_a_face_worker`: kamera 1 `attendance=True`, kamera 2 tidak; `face={"min_frames": 3}` lalu `{"min_frames": 5}` → worker kamera 1 diganti, kamera 2 identik.
  - `test_failed_camera_start_does_not_block_others_and_reverted_config_restarts_it` (Review Focus 1): v1 `{1,2}`; v2 mengubah keduanya sambil `_start_camera` dipatch melempar untuk kamera 2 → kamera 1 punya worker baru, kamera 2 tidak punya worker, `2 not in node._applied`; lepas patch lalu terapkan **v1** lagi → kamera 2 punya worker (bukan dilewati sebagai "tidak berubah").
  - `test_unexpected_diff_error_falls_back_to_full_restart`: patch `node._stop_workers` agar melempar sekali bila `camera_ids is not None`; ubah kamera 1 → semua kamera punya worker baru (restart penuh) dan hidup.
  - `test_changed_camera_replaces_only_its_recorder` (`api_key="k"`): setelah ubah kamera 1, recorder lama kamera 1 `closed == 1`, kamera 2 `closed == 0` dan objek recorder kamera 2 sama. (Review Focus 2)
  - `test_camera_without_zones_starts_once_a_zone_arrives_and_readded_camera_forgets_old_confidence` (Review Focus 3): `zones: []` → tanpa worker tetapi di `_applied`; lalu dengan zona → worker ada. Kamera 1 `confidence 0.7`, dihapus, ditambah lagi tanpa `confidence` → `1 not in node._camera_conf`.
  - `test_apply_logs_restarted_added_removed_unchanged` (`caplog`): pesan memuat `restarted [1], added [3], removed [2], unchanged 0` untuk perubahan yang sesuai.
- [ ] **Step 2: Jalankan** `../backend/.venv/bin/python -m pytest tests/test_config_apply_per_camera.py -q` — Expected: FAIL pada tes diff (worker kamera lain ikut diganti, bukan galat impor).
- [ ] **Step 3: Implementasi** sesuai Interfaces dan aturan di atas; `cfg_dict.get("cameras")` tetap lewat `_cameras_from_config` (yang mengisi `_camera_conf`).
- [ ] **Step 4: Jalankan** seluruh suite vision — Expected: PASS, termasuk `test_config_apply.py`, `test_config_device.py`, `test_node.py` tanpa diubah.
- [ ] **Step 5: CHANGELOG + commit** `feat(vision): node menerapkan config per kamera yang berubah`.

---

### Task 3: Coalescing antrean config

**Files:**
- Modify: `vision/vision/node.py` (`run`, loop lines 466-474)
- Test: `vision/tests/test_config_apply_per_camera.py`
- Modify: `CHANGELOG.md`

**Interfaces:** Consumes: `_config_q`, `apply_config`. Produces: setelah `self._config_q.get(timeout=0.2)` berhasil, kuras `get_nowait()` sampai `queue.Empty` dan terapkan hanya pesan terakhir.

- [ ] **Step 1: Tulis tes yang gagal:** `test_queued_configs_are_coalesced_to_the_latest`: ganti `node.apply_config` dengan spy (`applied.append`); `put` tiga dict berbeda; jalankan `node.run` di thread `daemon`; tunggu `applied` terisi; `node.stop_event.set()`; `applied == [tiga]` (hanya yang terakhir) — Review Focus 4. Tes lama `test_node_awaiting_config_stays_alive_and_applies_config_that_arrives_late` (satu pesan tetap diteruskan apa adanya) harus tetap hijau.
- [ ] **Step 2: Jalankan** tes baru — Expected: FAIL (`applied` berisi tiga dict).
- [ ] **Step 3: Implementasi** pengurasan antrean (satu loop `while True` dengan `get_nowait`).
- [ ] **Step 4: Jalankan** seluruh suite vision — Expected: PASS.
- [ ] **Step 5: CHANGELOG + commit** `feat(vision): antrean config digabung, hanya snapshot terakhir yang diterapkan`.

---

### Task 4: Dokumen dan verifikasi akhir

**Files:**
- Modify: `ARCHITECTURE.md` §3 (node vision), `WORKFLOW.md` (baris 79 dan 92), `docs/RUNBOOK.md` (baris 76 dan 83), `ROADMAP.md`, `CHANGELOG.md`

- [ ] **Step 1: ARCHITECTURE.md §3:** tulis alur apply config: diff per `CameraCfg`, restart per kamera (detect + face + recorder), restart penuh bila model/nms/conf/imgsz/`device` detector atau `device` face berubah atau pada config pertama, `FaceSettings` berubah merestart kamera dengan worker face, antrean digabung ke snapshot terakhir, fallback ke restart penuh, log `config applied: ...`.
- [ ] **Step 2: WORKFLOW.md baris 79 dan 92 serta RUNBOOK baris 76 dan 83:** ganti klaim umum "node menerapkan/ hot-reload tanpa restart" menjadi "hanya kamera yang berubah yang dimulai ulang (stream kamera itu tersambung ulang sekitar 20–30 detik); setelan global mengulang semua kamera".
- [ ] **Step 3: ROADMAP.md:** baris siklus baru `[~] kode selesai, belum di-deploy/diuji server` dengan angka tes nyata. Jangan `[x]`.
- [ ] **Step 4: Verifikasi akhir berurutan** dan tempel keluaran di CHANGELOG: vision `../backend/.venv/bin/python -m pytest tests -q -m "not gpu"` (target: `247` + tes baru, semua lulus, `3 deselected`); backend `cd backend && .venv/bin/python -m pytest tests -q -m "not gpu and not llm"` (target `896 passed, 1 deselected`, tak tersentuh); `git diff --stat main...HEAD` hanya menyentuh berkas di File Structure + spec/plan; guard: `git diff main...HEAD -- backend frontend docker` kosong.
- [ ] **Step 5: Commit** `docs: node menerapkan config per kamera (alur apply, runbook)`. Berhenti di commit lokal.

---

## Di luar plan ini

Pembaruan analyzer di tempat, berbagi detector antar kamera, granularitas per jenis worker, deploy ke server, dan verifikasi server (edit zona satu kamera lalu pastikan kamera lain tetap `streaming`, `frames`-nya tidak mereset, `reconnects_1h` tidak naik, dan log memuat `config applied`).
