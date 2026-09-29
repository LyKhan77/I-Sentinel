# Monitoring Resource S1 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Halaman System › Monitoring (semua user) yang menampilkan kesehatan kamera, inferensi AI, hardware node/server dan layanan saat ini, plus deteksi node offline/pulih yang andal (event + Telegram + banner persisten) dan perbaikan LWT retained.

**Architecture:** Vision memperluas heartbeat (statistik per worker kamera, inferensi per jendela, host `/proc`, GPU suhu/daya, backlog MQTT) dan menimpa LWT retained dengan `online` saat connect. Backend: `node_health` menjadi satu-satunya jalur transisi status node (event `system` + broadcast + Telegram) dengan `NodeHealthMonitor` latar; `monitoring.snapshot` mengagregasi DB + go2rtc + status layanan menjadi `GET /api/v1/monitoring`. Frontend: `MonitoringPage` (polling 10 s), `NodeOfflineBanner` (AppShell + TV), notifikasi mengenali event pulih.

**Tech Stack:** Python 3.11 (FastAPI, SQLAlchemy 2, paho-mqtt, httpx, pytest), vision stdlib + NVML, React 19 + TypeScript + Carbon + Vitest.

**Spec:** `docs/superpowers/specs/2026-09-29-monitoring-s1-design.md`

## Global Constraints

- Tanpa dependensi baru, **tanpa migrasi DB** (field baru masuk JSON `node.hw` / `node.modules`).
- Vision tetap importable tanpa CUDA; host stats hanya stdlib (`/proc`, `shutil`); non-Linux → `null`.
- Ambang tetap (S1): heartbeat timeout **35 s**, cek monitor **15 s**, `FRAME_STALE_S = 30`, `STALL_S = 10`,
  `START_GRACE_S = 30`, `LOW_FPS_RATIO = 0.8`, `RECONNECT_WARN = 3`, `GPU_TEMP_WARN_C = 85`,
  `VRAM_WARN_PCT = RAM_WARN_PCT = CPU_WARN_PCT = 90`, `SWEEP_STALE_H = 26`, `SERVICE_CACHE_S = 10`,
  `heartbeat_late` > 20 s.
- `node_health.mark_offline` / `mark_online` = **satu-satunya** jalur perubahan `node.status` (LWT, heartbeat MQTT,
  heartbeat HTTP internal, monitor, endpoint mark-stale). `GET /nodes` tidak mengubah status.
- Event node: `system`, payload `{"node", "reason"}`; offline `warning` `reason ∈ {"lwt","timeout"}`, pulih `info`
  `reason: "online"`. `unknown → online` tanpa event.
- `GET /api/v1/monitoring` untuk **semua user login** (viewer juga); menu Monitoring tanpa `adminOnly`.
- Zero-secret: token Telegram tidak pernah di log/response.
- Frontend: REST hanya lewat `src/api/*`, string lewat `i18n.tsx` (id + en), Carbon + `theme.scss`, 390 px tanpa
  overflow horizontal halaman.
- Commit Conventional Commits **tanpa** atribusi AI (AGENTS.md §9). Prefix shell dengan `rtk`. Jangan `uv sync` /
  `uv lock`.
- Baseline `main` `7656c13` / branch `53500ff`: backend 491, vision 223 (3 deselected), frontend 203, build 0.

## Review Focus

1. **API restart tidak boleh membuat event "offline" palsu** — LWT retained `online` dari vision + backend
   mengabaikan payload non-offline (tes Task 2 & 3).
2. **Satu event + satu Telegram per transisi** walau LWT dan timeout sama-sama terjadi, atau heartbeat berulang
   saat sudah online (tes Task 3).
3. **Heartbeat vision lama / field hilang / tipe ngawur** tidak membuat handler atau `snapshot()` crash
   (tes Task 3 & 4).
4. **Config reload me-restart worker** (counter frame kembali 0) tidak menghasilkan fps negatif (tes Task 1).
5. **Pemeriksaan layanan yang gagal/lambat** (go2rtc mati, DB error) tidak membuat endpoint 500 dan di-cache 10 s
   (tes Task 4).

---

## File Structure

| File | Tanggung jawab |
|---|---|
| Modify `vision/vision/pipeline/source.py` | Statistik `FrameSource.stats()` (state, umur frame, reconnect 1 jam) |
| Modify `vision/vision/node.py` | Counter worker, `_camera_stats`, jendela detector, heartbeat baru |
| Modify `vision/vision/face_worker.py` | Counter frame + `pending()` |
| Modify `vision/vision/pipeline/detector.py` | `window_max_ms` |
| Modify `vision/vision/hardware.py` | `host_stats()`, GPU `temp_c`/`power_w` |
| Modify `vision/vision/transport/mqtt.py` | LWT `online` retained saat connect, `backlog()` |
| Create `backend/app/services/node_health.py` | Transisi status node, event, Telegram, `check`, `NodeHealthMonitor` |
| Create `backend/app/services/host_stats.py` | CPU/RAM host dari `/proc` |
| Create `backend/app/services/monitoring.py` | `snapshot()` + aturan kesehatan + cek layanan |
| Create `backend/app/schemas/monitoring.py` | Kontrak response |
| Create `backend/app/api/monitoring.py` | `GET /api/v1/monitoring` |
| Modify `backend/app/services/telegram.py` | `send_text()` |
| Modify `backend/app/services/disk_alert.py` | Pakai `telegram.send_text` |
| Modify `backend/app/services/events_consumer.py` | LWT/heartbeat lewat `node_health`, flag `connected` |
| Modify `backend/app/services/go2rtc.py` | `probe()` |
| Modify `backend/app/api/events.py`, `api/nodes.py`, `models/node.py`, `schemas/camera.py`, `main.py` | Pemanggil, `last_seen`, router + monitor |
| Create `frontend/src/api/monitoring.ts` | Klien + tipe |
| Create `frontend/src/features/monitoring/MonitoringPage.tsx`, `health.ts` | Halaman + label/warna |
| Create `frontend/src/components/NodeOfflineBanner.tsx` | Banner node offline |
| Modify `frontend/src/main.tsx`, `app/AppShell.tsx`, `features/live/LiveTvPage.tsx`, `app/i18n.tsx`, `app/theme.scss`, `api/cameras.ts` | Route/menu/banner/i18n/gaya |
| Modify `frontend/src/features/notifications/{labels.ts,EventAlertsProvider.tsx,NotificationBell.tsx,EventToasts.tsx}` | Event pulih |

---

### Task 1: Vision — statistik per kamera

**Files:**
- Modify: `vision/vision/pipeline/source.py`
- Modify: `vision/vision/node.py` (`CameraWorker.__init__`/`run`, `VisionNode.__init__`, method baru `_camera_stats`)
- Modify: `vision/vision/face_worker.py` (`FaceGateWorker.__init__`/`run`, method `pending`)
- Test: `vision/tests/test_source.py`, `vision/tests/test_node.py`

**Interfaces:**
- Produces:
  - `FrameSource(url, target_fps=5.0, open_capture=None, clock=time.monotonic)`; `FrameSource.stats() -> {"state": str, "last_frame_age_s": float | None, "reconnects_1h": int}`; seam internal `_on_frame()`, `_on_fail()`, `_on_reconnect(opened: bool)` dipanggil reader loop.
  - `CameraWorker.frames: int`, `CameraWorker.motion_skipped: int`; `FaceGateWorker.frames: int`, `FaceGateWorker.pending() -> int`.
  - `VisionNode._camera_stats(now: float) -> list[dict]` (entri: `id, worker, state, fps, target_fps, last_frame_age_s, reconnects_1h, motion_skip_pct`).

- [ ] **Step 1: Tes `FrameSource.stats()` (gagal)**

Tambahkan di `vision/tests/test_source.py`:

```python
from vision.pipeline.source import FrameSource


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def _src(clock):
    src = FrameSource("rtsp://x/cam_1", 5.0, clock=clock)
    src._started_mono = clock()  # start() tanpa thread reader: seam yang sama dipakai reader loop
    return src


def test_stats_starting_then_streaming_then_stalled():
    clock = Clock()
    src = _src(clock)
    assert src.stats() == {"state": "starting", "last_frame_age_s": None, "reconnects_1h": 0}
    src._on_frame()
    clock.t += 2
    assert src.stats()["state"] == "streaming" and src.stats()["last_frame_age_s"] == 2.0
    clock.t += 9  # 11 s tanpa frame: RTSP macet tanpa error read
    assert src.stats()["state"] == "stalled"


def test_stats_no_frame_after_grace_is_reconnecting():
    clock = Clock()
    src = _src(clock)
    clock.t += 31
    assert src.stats()["state"] == "reconnecting"


def test_stats_reconnect_window_1h():
    clock = Clock()
    src = _src(clock)
    src._on_frame()
    src._on_fail()
    assert src.stats()["state"] == "reconnecting"
    src._on_reconnect(True)
    clock.t += 1800
    src._on_fail()
    src._on_reconnect(True)
    src._on_frame()
    assert src.stats() == {"state": "streaming", "last_frame_age_s": 0.0, "reconnects_1h": 2}
    clock.t += 1801  # reconnect pertama lewat 1 jam
    src._on_frame()
    assert src.stats()["reconnects_1h"] == 1
```

Run: `rtk backend/.venv/bin/python -m pytest vision/tests/test_source.py -q -k stats`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'clock'`.

- [ ] **Step 2: Implementasi `FrameSource`**

Di `source.py`: tambahkan `from collections import deque` dan konstanta setelah `RECONNECT_START_S`:

```python
STALL_S = 10.0            # terbuka tapi tanpa frame selama ini = RTSP macet
START_GRACE_S = 30.0      # belum ada frame sejak start: masih "starting" selama ini
RECONNECT_WINDOW_S = 3600.0
```

`__init__` mendapat parameter `clock=time.monotonic` dan field:

```python
        self._clock = clock
        self._started_mono: float | None = None
        self._last_frame_mono: float | None = None
        self._failing = False
        self._reconnects: deque[float] = deque()
```

Seam + stats (method baru di kelas):

```python
    def _on_frame(self) -> None:
        self._last_frame_mono = self._clock()
        self._failing = False

    def _on_fail(self) -> None:
        self._failing = True

    def _on_reconnect(self, opened: bool) -> None:
        self._reconnects.append(self._clock())
        self._failing = not opened

    def stats(self) -> dict:
        """Kesehatan sumber untuk heartbeat: state, umur frame terakhir, reconnect 1 jam terakhir."""
        now = self._clock()
        while self._reconnects and now - self._reconnects[0] > RECONNECT_WINDOW_S:
            self._reconnects.popleft()
        age = None if self._last_frame_mono is None else round(now - self._last_frame_mono, 1)
        if self._failing:
            state = "reconnecting"
        elif age is None:
            started = self._started_mono is not None and now - self._started_mono < START_GRACE_S
            state = "starting" if started else "reconnecting"
        elif age > STALL_S:
            state = "stalled"
        else:
            state = "streaming"
        return {"state": state, "last_frame_age_s": age, "reconnects_1h": len(self._reconnects)}
```

Hubungkan ke reader: di `start()` setelah `self._cap = self._open()` tambahkan `self._started_mono = self._clock()`;
di `_read_loop` cabang `if ok:` panggil `self._on_frame()` sebelum `with self._cond`; di cabang gagal panggil
`self._on_fail()` sebelum `time.sleep(delay)`; `_reconnect()` menjadi:

```python
    def _reconnect(self) -> bool:
        self._cap.release()
        self._cap = self._open()
        opened = self._cap.isOpened()
        self._on_reconnect(opened)
        return opened
```

Run tes Step 1 → PASS; `rtk backend/.venv/bin/python -m pytest vision/tests/test_source.py -q` → PASS semua.

- [ ] **Step 3: Tes counter worker + `_camera_stats` (gagal)**

Di `vision/tests/test_node.py` tambahkan (memakai helper `_wired_node`, `ATTENDANCE_ZONE`, `BEHAVIOR_ZONE` yang
sudah ada; kamera 363):

```python
def test_camera_stats_per_worker_fps_window_and_restart(tmp_path):
    node, workers, *_ = _wired_node(tmp_path, [ATTENDANCE_ZONE, BEHAVIOR_ZONE])
    node._workers = workers
    det = next(w for w in workers if isinstance(w, CameraWorker))
    face = next(w for w in workers if not isinstance(w, CameraWorker))

    first = node._camera_stats(100.0)
    assert sorted((c["id"], c["worker"]) for c in first) == [(363, "detect"), (363, "face")]
    assert all(c["fps"] is None for c in first)  # jendela pertama belum ada pembanding

    det.frames, det.motion_skipped, face.frames = 50, 20, 40
    stats = {c["worker"]: c for c in node._camera_stats(110.0)}
    assert stats["detect"]["fps"] == 5.0 and stats["face"]["fps"] == 4.0
    assert stats["face"]["motion_skip_pct"] is None

    det.frames = 3  # config reload: worker baru, counter mulai dari 0
    stats = {c["worker"]: c for c in node._camera_stats(120.0)}
    assert stats["detect"]["fps"] is None  # bukan negatif
```

Bila `_wired_node` tidak mengembalikan worker dengan `source` punya `stats()`, entri tetap ada dengan
`state = None` (lihat implementasi) — tes di atas tidak mengecek `state`.

Tambahkan juga tes motion skip:

```python
def test_camera_stats_motion_skip_pct(tmp_path):
    node, workers, *_ = _wired_node(tmp_path, [BEHAVIOR_ZONE])
    node._workers = workers
    det = next(w for w in workers if isinstance(w, CameraWorker))
    det.motion_gate = object()  # gate aktif
    node._camera_stats(0.0)
    det.frames, det.motion_skipped = 40, 30
    assert node._camera_stats(10.0)[0]["motion_skip_pct"] == 75.0
```

Run: `rtk backend/.venv/bin/python -m pytest vision/tests/test_node.py -q -k camera_stats`
Expected: FAIL — `AttributeError: ... has no attribute '_camera_stats'`.

- [ ] **Step 4: Implementasi counter + `_camera_stats`**

`CameraWorker.__init__`: tambahkan `self.frames = 0` dan `self.motion_skipped = 0`. Di `run()`, tepat setelah
`if self.stop_event.is_set(): break` tambahkan `self.frames += 1`; di cabang motion gate (sebelum
`tracker.update([], frame.ts)`) tambahkan `self.motion_skipped += 1`.

`FaceGateWorker.__init__`: `self.frames = 0`. Di `run()`, setelah `if frame is None: continue` (baris sesudah
`next_frame`) tambahkan `self.frames += 1`. Method baru:

```python
    def pending(self) -> int:
        """Jumlah event wajah yang menunggu finalisasi media (heartbeat: antrean face)."""
        return self._pending_events.qsize()
```

`VisionNode.__init__` (dekat `self._workers`): `self._cam_prev: dict[tuple[int, str], tuple[int, int, float]] = {}`.

Method baru di `VisionNode`:

```python
    def _camera_stats(self, now: float) -> list[dict]:
        """Satu entri per worker (detect / face): kesehatan sumber + fps & skip motion di jendela heartbeat."""
        out = []
        for w in list(self._workers):
            kind = "detect" if isinstance(w, CameraWorker) else "face"
            key = (w.camera_id, kind)
            frames, skipped = getattr(w, "frames", 0), getattr(w, "motion_skipped", 0)
            prev = self._cam_prev.get(key)
            self._cam_prev[key] = (frames, skipped, now)
            fps = skip = None
            # prev None = jendela pertama; frames < prev = worker baru setelah config reload
            if prev is not None and frames >= prev[0] and now > prev[2]:
                df = frames - prev[0]
                fps = round(df / (now - prev[2]), 1)
                if kind == "detect" and getattr(w, "motion_gate", None) is not None and df > 0:
                    skip = round((skipped - prev[1]) / df * 100, 1)
            src = getattr(w, "source", None)
            s = src.stats() if src is not None and hasattr(src, "stats") else {}
            out.append({"id": w.camera_id, "worker": kind, "state": s.get("state"), "fps": fps,
                        "target_fps": getattr(src, "target_fps", None),
                        "last_frame_age_s": s.get("last_frame_age_s"),
                        "reconnects_1h": s.get("reconnects_1h"), "motion_skip_pct": skip})
        return out
```

Run: `rtk backend/.venv/bin/python -m pytest vision/tests -q -m "not gpu"` → PASS.

- [ ] **Step 5: Commit**

```bash
rtk git add vision/vision/pipeline/source.py vision/vision/node.py vision/vision/face_worker.py vision/tests/test_source.py vision/tests/test_node.py
rtk git commit -m "feat(vision): statistik kesehatan sumber dan fps per worker kamera"
```

---

### Task 2: Vision — heartbeat diperluas + LWT online

**Files:**
- Modify: `vision/vision/hardware.py`, `vision/vision/pipeline/detector.py`, `vision/vision/node.py`
  (`_detector_module_info`, `_face_module_info`, `_heartbeat_loop`), `vision/vision/transport/mqtt.py`
- Test: `vision/tests/test_hardware.py`, `vision/tests/test_node.py`, `vision/tests/test_transport.py`

**Interfaces:**
- Consumes: `_camera_stats(now)` (Task 1), `FaceGateWorker.pending()` (Task 1).
- Produces (heartbeat JSON, dipakai Task 3/4):
  - top-level `cameras: list[dict]` (bentuk Task 1), `mqtt_backlog: int | None`
  - `hw.host = {cpu_pct, ram_used_mb, ram_total_mb, disk_used_pct, disk_free_gb}`; `hw.gpus[*].temp_c`, `power_w`
  - `modules.detector` + `ms_avg`, `ms_max`, `infer_fps`; `modules.face` + `queue`
  - `hardware.host_stats(data_dir: str, proc_root: str = "/proc") -> dict`
  - `MqttTransport.backlog() -> int`; LWT topic mendapat `{"status":"online"}` retained saat connect.

- [ ] **Step 1: Tes host stats (gagal)**

Di `vision/tests/test_hardware.py`:

```python
from vision import hardware


def _proc(tmp_path, stat_line, avail_kb=4_000_000, total_kb=16_000_000):
    (tmp_path / "stat").write_text(stat_line + "\ncpu0 1 1 1 1 0 0 0 0\n")
    (tmp_path / "meminfo").write_text(f"MemTotal: {total_kb} kB\nMemFree: 1 kB\nMemAvailable: {avail_kb} kB\n")
    return str(tmp_path)


def test_host_stats_cpu_delta_ram_disk(tmp_path, monkeypatch):
    monkeypatch.setattr(hardware, "_prev_cpu", None)
    root = _proc(tmp_path, "cpu  100 0 100 800 0 0 0 0 0 0")
    first = hardware.host_stats(str(tmp_path), proc_root=root)
    assert first["cpu_pct"] is None  # butuh dua sampel
    assert first["ram_total_mb"] == 15625 and first["ram_used_mb"] == 11719
    assert 0 <= first["disk_used_pct"] <= 100 and first["disk_free_gb"] > 0
    _proc(tmp_path, "cpu  200 0 200 900 0 0 0 0 0 0")  # +200 busy, +100 idle
    assert hardware.host_stats(str(tmp_path), proc_root=root)["cpu_pct"] == 66.7


def test_host_stats_without_proc_is_null(tmp_path, monkeypatch):
    monkeypatch.setattr(hardware, "_prev_cpu", None)
    s = hardware.host_stats(str(tmp_path), proc_root=str(tmp_path / "missing"))
    assert s["cpu_pct"] is None and s["ram_total_mb"] is None and s["disk_free_gb"] is not None
```

Run: `rtk backend/.venv/bin/python -m pytest vision/tests/test_hardware.py -q -k host_stats`
Expected: FAIL — `AttributeError: module 'vision.hardware' has no attribute 'host_stats'`.

- [ ] **Step 2: Implementasi `host_stats` + GPU suhu/daya**

Tambahkan di `hardware.py` (import `os`, `shutil` di atas modul):

```python
_prev_cpu: tuple[int, int] | None = None  # (busy, total) jiffies sampel sebelumnya


def _cpu_pct(proc_root: str) -> float | None:
    global _prev_cpu
    try:
        with open(os.path.join(proc_root, "stat")) as f:
            parts = f.readline().split()
        vals = [int(v) for v in parts[1:9]]  # user nice system idle iowait irq softirq steal
    except (OSError, ValueError, IndexError):
        return None
    idle = vals[3] + vals[4]
    total = sum(vals)
    prev, _prev_cpu = _prev_cpu, (total - idle, total)
    if prev is None or total <= prev[1]:
        return None
    return round((total - idle - prev[0]) / (total - prev[1]) * 100, 1)


def _ram_mb(proc_root: str) -> tuple[int | None, int | None]:
    info = {}
    try:
        with open(os.path.join(proc_root, "meminfo")) as f:
            for line in f:
                key, _, rest = line.partition(":")
                info[key] = int(rest.split()[0])
    except (OSError, ValueError, IndexError):
        return None, None
    if "MemTotal" not in info or "MemAvailable" not in info:
        return None, None
    total = round(info["MemTotal"] / 1024)
    return round((info["MemTotal"] - info["MemAvailable"]) / 1024), total


def host_stats(data_dir: str, proc_root: str = "/proc") -> dict:
    """CPU % (selisih antar panggilan), RAM, disk data_dir. Stdlib saja; field tak tersedia → None."""
    used, total = _ram_mb(proc_root)
    disk_pct = disk_free = None
    try:
        path = os.path.expanduser(data_dir)
        u = shutil.disk_usage(path if os.path.isdir(path) else os.path.dirname(path) or ".")
        disk_pct = round(u.used / u.total * 100, 1) if u.total else None
        disk_free = round(u.free / 1024 ** 3, 1)
    except OSError:
        pass
    return {"cpu_pct": _cpu_pct(proc_root), "ram_used_mb": used, "ram_total_mb": total,
            "disk_used_pct": disk_pct, "disk_free_gb": disk_free}
```

Di `collect_gpu_info`, sebelum `gpus.append({...})`:

```python
            temp_c = power_w = None
            try:
                temp_c = pynvml.nvmlDeviceGetTemperature(h, pynvml.NVML_TEMPERATURE_GPU)
            except Exception:
                pass
            try:
                power_w = round(pynvml.nvmlDeviceGetPowerUsage(h) / 1000, 1)  # mW → W
            except Exception:
                pass
```

dan tambahkan `"temp_c": temp_c, "power_w": power_w,` ke dict GPU. Bila `test_hardware.py` punya fake `pynvml`
dengan assertion dict GPU persis, tambahkan kedua field (fake tanpa fungsi itu → `None`).

Run Step 1 → PASS.

- [ ] **Step 3: Tes heartbeat + transport (gagal)**

Di `vision/tests/test_node.py`, **ubah** `test_heartbeat_reports_face_module_and_distinct_cameras` menjadi:

```python
def test_heartbeat_reports_modules_cameras_host_and_backlog(tmp_path):
    node, workers, *_ = _wired_node(tmp_path, [ATTENDANCE_ZONE, BEHAVIOR_ZONE])
    face = node._face_module_info()
    assert face["loaded"] is True and face["queue"] == 0
    node._workers = workers
    node.transport.backlog = lambda: 4
    def publish_once(hb):
        node.transport.heartbeats.append(hb)
        node.stop_event.set()
    node.transport.publish_heartbeat = publish_once
    node._heartbeat_loop()
    hb = node.transport.heartbeats[0]
    assert sorted((c["id"], c["worker"]) for c in hb["cameras"]) == [(363, "detect"), (363, "face")]
    assert hb["mqtt_backlog"] == 4
    assert set(hb["hw"]["host"]) == {"cpu_pct", "ram_used_mb", "ram_total_mb", "disk_used_pct", "disk_free_gb"}
    assert {"ms_avg", "ms_max", "infer_fps"} <= set(hb["modules"]["detector"])
```

Tambahkan tes jendela detector:

```python
def test_detector_window_avg_max_fps(tmp_path, monkeypatch):
    from vision.pipeline.detector import PersonDetector
    node, *_ = _wired_node(tmp_path, [BEHAVIOR_ZONE])
    monkeypatch.setattr(node, "_default_detector", True)
    monkeypatch.setattr(PersonDetector, "detect_ms_total", 100.0)
    monkeypatch.setattr(PersonDetector, "detect_n", 10)
    monkeypatch.setattr(PersonDetector, "window_max_ms", 0.0)
    first = node._detector_module_info(now=0.0)
    assert first["ms_avg"] is None and first["infer_fps"] is None
    PersonDetector.detect_ms_total, PersonDetector.detect_n, PersonDetector.window_max_ms = 400.0, 40, 25.0
    info = node._detector_module_info(now=10.0)
    assert info["ms_avg"] == 10.0 and info["infer_fps"] == 3.0 and info["ms_max"] == 25.0
    assert PersonDetector.window_max_ms == 0.0  # direset per jendela
```

Di `vision/tests/test_transport.py`:

```python
def test_on_connect_overwrites_retained_lwt_with_online(transport):
    transport._on_connect(transport._client, None, None, 0, None)
    lwt = [p for p in transport._client.published if p[0] == "isentinel/nodes/test-node/lwt"]
    assert lwt and json.loads(lwt[-1][1]) == {"status": "online"}
    assert lwt[-1][2] == 1 and lwt[-1][3] is True  # qos 1, retained → menimpa offline lama


def test_backlog_reports_queue_size(transport):
    transport._client.publish_rc = 1  # broker putus → masuk antrean
    transport.publish_event({"event_id": "x"})
    assert transport.backlog() == 1
```

(Sesuaikan urutan tuple `published` dengan `FakeClient.publish` yang ada — `(topic, payload, qos, retain)`.)

Run: `rtk backend/.venv/bin/python -m pytest vision/tests -q -m "not gpu" -k "heartbeat or detector_window or on_connect or backlog"`
Expected: FAIL (field/method belum ada).

- [ ] **Step 4: Implementasi**

`detector.py`: di kelas `PersonDetector` tambahkan `window_max_ms = 0.0` (class-level, sebelah `detect_n`); di
`detect()` ganti blok penghitung menjadi:

```python
        ms = (time.perf_counter() - t0) * 1000
        PersonDetector.detect_ms_total += ms
        PersonDetector.detect_n += 1
        PersonDetector.window_max_ms = max(PersonDetector.window_max_ms, ms)
```

`mqtt.py`:

```python
    def _on_connect(self, client, userdata, flags, reason_code, properties):
        client.subscribe(self._config_topic, qos=1)
        # LWT offline di-retain broker: timpa dengan "online" agar backend yang subscribe ulang
        # (mis. API restart) tidak membaca offline lama sebagai node mati.
        client.publish(f"isentinel/nodes/{self.cfg.node_id}/lwt", json.dumps({"status": "online"}),
                       qos=1, retain=True)
        self._flush(client)

    def backlog(self) -> int:
        """Event yang masih di antrean disk (broker putus / belum terkirim)."""
        return self._queue.size()
```

`node.py`:
- `__init__`: `self._det_prev: tuple[float, int, float] | None = None`.
- `_detector_module_info(self, now: float | None = None)`:

```python
    def _detector_module_info(self, now: float | None = None) -> dict:
        """modules.detector: device, model, ms/frame kumulatif (kompatibel) + jendela sejak heartbeat lalu."""
        now = time.monotonic() if now is None else now
        model = getattr(self, "_detector_settings", {}).get("model") or self.cfg.detector_model
        total, n = PersonDetector.detect_ms_total, PersonDetector.detect_n
        ms = round(total / n, 1) if self._default_detector and n else None
        prev, self._det_prev = self._det_prev, (total, n, now)
        ms_avg = infer_fps = None
        if prev is not None and n > prev[1] and now > prev[2]:
            ms_avg = round((total - prev[0]) / (n - prev[1]), 1)
            infer_fps = round((n - prev[1]) / (now - prev[2]), 1)
        ms_max = round(PersonDetector.window_max_ms, 1) if PersonDetector.window_max_ms else None
        PersonDetector.window_max_ms = 0.0
        return {"device": self.cfg.detector_device or "auto", "model": os.path.basename(model),
                "ms_per_frame": ms, "detect_n": n, "ms_avg": ms_avg, "ms_max": ms_max,
                "infer_fps": infer_fps}
```

- `_face_module_info`: tambahkan `"queue": sum(w.pending() for w in self._workers if isinstance(w, FaceGateWorker))`.
- `_heartbeat_loop`:

```python
    def _heartbeat_loop(self):
        while not self.stop_event.is_set():
            now = time.monotonic()
            try:
                cpu = os.getloadavg()[0]  # field lama (kompatibel); host.cpu_pct = persen sebenarnya
            except (AttributeError, OSError):
                cpu = None
            backlog = getattr(self.transport, "backlog", None)
            hb = {"ts": _iso(time.time()), "cpu_percent": cpu, "gpu_mem": None,
                  "cameras": self._camera_stats(now),
                  "mqtt_backlog": backlog() if callable(backlog) else None}
            hw = hardware.collect_gpu_info() or {}
            hw["host"] = hardware.host_stats(self.cfg.data_dir)
            hb["hw"] = hw
            hb["modules"] = {"detector": self._detector_module_info(now),
                             "face": self._face_module_info()}
            self.transport.publish_heartbeat(hb)
            self.stop_event.wait(self.cfg.heartbeat_s)
```

Perbarui tes lama yang mengecek dict persis `_face_module_info()` / `_detector_module_info()` (`test_node.py:438`,
`test_hardware.py:112`) agar memeriksa field yang relevan, bukan dict penuh.

Run: `rtk backend/.venv/bin/python -m pytest vision/tests -q -m "not gpu"` → PASS (≥ 223 + tes baru).

- [ ] **Step 5: Commit**

```bash
rtk git add vision/
rtk git commit -m "feat(vision): heartbeat membawa host, GPU suhu/daya, jendela inferensi, backlog; LWT online retained"
```

---

### Task 3: Backend — `node_health` (offline/pulih) + penyimpanan heartbeat

**Files:**
- Create: `backend/app/services/node_health.py`
- Modify: `backend/app/services/telegram.py` (tambah `send_text`), `backend/app/services/disk_alert.py`
- Modify: `backend/app/services/events_consumer.py` (LWT, heartbeat, `connected`)
- Modify: `backend/app/api/events.py` (heartbeat HTTP, mark-stale), `backend/app/api/nodes.py`,
  `backend/app/models/node.py` (hapus `mark_stale_nodes`), `backend/app/schemas/camera.py` (`NodeOut.last_seen`),
  `backend/app/main.py` (start/stop monitor)
- Test: `backend/tests/test_node_health.py` (baru), `backend/tests/test_events_consumer.py`,
  `backend/tests/test_nodes_internal.py`, `backend/tests/test_disk_alert.py`, `backend/tests/conftest.py`

**Interfaces:**
- Produces:
  - `telegram.send_text(db, text: str) -> bool`
  - `node_health.HEARTBEAT_TIMEOUT_S = 35`, `CHECK_INTERVAL_S = 15`
  - `node_health.mark_offline(db, node, reason: str, now=None, send=None) -> bool`
  - `node_health.mark_online(db, node, now=None, since=None, send=None) -> bool`
  - `node_health.check(db, now=None, send=None) -> int`
  - `node_health.monitor: NodeHealthMonitor` (`start()`, `stop()`, `interval_s`)
  - `events_consumer.connected: threading.Event`
  - `NodeOut.last_seen: datetime | None`

- [ ] **Step 1: Tes `node_health` (gagal)**

Buat `backend/tests/test_node_health.py`:

```python
from datetime import datetime, timedelta, timezone

import pytest

from app.models.event import Event
from app.models.node import Node
from app.services import node_health
from app.ws.hub import hub

T0 = datetime(2026, 9, 29, 8, 0, tzinfo=timezone.utc)


@pytest.fixture
def sent(monkeypatch):
    out = {"ws": [], "tg": []}
    async def fake_broadcast(payload):
        out["ws"].append(payload)
    monkeypatch.setattr(hub, "broadcast", fake_broadcast)
    return out


def _send(out):
    return lambda db, text: out["tg"].append(text) or True


def _node(db, status="online", seen=T0):
    n = Node(name="server", status=status, last_seen=seen)
    db.add(n)
    db.commit()
    return n


def _system(db):
    return db.query(Event).filter_by(type="system").order_by(Event.id).all()


def test_timeout_marks_offline_once_with_event_ws_and_telegram(db, sent):
    _node(db, seen=T0)
    assert node_health.check(db, now=T0 + timedelta(seconds=30), send=_send(sent)) == 0
    assert node_health.check(db, now=T0 + timedelta(seconds=40), send=_send(sent)) == 1
    assert node_health.check(db, now=T0 + timedelta(seconds=60), send=_send(sent)) == 0  # sudah offline
    [ev] = _system(db)
    assert ev.severity == "warning" and ev.payload == {"node": "server", "reason": "timeout"}
    assert len(sent["ws"]) == 1 and sent["ws"][0]["type"] == "system"
    assert len(sent["tg"]) == 1 and "server" in sent["tg"][0] and "offline" in sent["tg"][0]


def test_lwt_then_timeout_single_transition(db, sent):
    n = _node(db, seen=T0)
    assert node_health.mark_offline(db, n, "lwt", now=T0, send=_send(sent)) is True
    assert node_health.check(db, now=T0 + timedelta(minutes=5), send=_send(sent)) == 0
    assert len(_system(db)) == 1 and len(sent["tg"]) == 1


def test_online_after_offline_emits_recovered(db, sent):
    n = _node(db, status="offline", seen=T0)
    now = T0 + timedelta(minutes=12)
    assert node_health.mark_online(db, n, now=now, since=T0, send=_send(sent)) is True
    assert n.status == "online"
    [ev] = _system(db)
    assert ev.severity == "info" and ev.payload == {"node": "server", "reason": "online"}
    assert "pulih" in sent["tg"][0] and "12" in sent["tg"][0]  # durasi offline
    assert node_health.mark_online(db, n, now=now, send=_send(sent)) is False  # sudah online


def test_unknown_to_online_no_event(db, sent):
    n = _node(db, status="unknown", seen=None)
    assert node_health.mark_online(db, n, now=T0, send=_send(sent)) is False
    assert n.status == "online" and _system(db) == [] and sent["tg"] == []


def test_without_telegram_transition_still_recorded(db, sent):
    n = _node(db)
    assert node_health.mark_offline(db, n, "lwt", now=T0, send=lambda db, t: False) is True
    assert n.status == "offline" and len(_system(db)) == 1


def test_monitor_runs_check_and_stops(monkeypatch):
    calls = []
    monkeypatch.setattr(node_health, "check", lambda db: calls.append(db) or 0)
    m = node_health.NodeHealthMonitor(interval_s=0.01)
    m.start()
    import time
    deadline = time.monotonic() + 2
    while not calls and time.monotonic() < deadline:
        time.sleep(0.01)
    m.stop()
    assert calls and not m._thread.is_alive()
```

Run: `rtk bash -c "cd backend && .venv/bin/python -m pytest tests/test_node_health.py -q"`
Expected: FAIL — `ImportError: cannot import name 'node_health'`.

- [ ] **Step 2: `telegram.send_text` + `node_health.py`**

`telegram.py` — tambahkan (dipindah dari `disk_alert._send`):

```python
def send_text(db, text: str) -> bool:
    """Teks ke grup aktif. Tanpa token/grup → False tanpa mengirim. Tidak pernah raise; tanpa token di log."""
    token = get_token()
    chat = active_chat(db)
    if not token or chat is None:
        return False
    status, error = deliver(token, chat.chat_id, text, retries=1)
    if status != "sent":
        logger.warning("telegram system message failed: %s", error)
    return status == "sent"
```

(Pastikan `logger` modul `telegram.py` ada; bila belum, `logger = logging.getLogger(__name__)`.)

`disk_alert.py`: hapus `_send`, ganti default `send = send or telegram.send_text`. Di `tests/test_disk_alert.py`
ubah `test_default_send_skips_when_telegram_not_configured` agar memanggil `telegram.send_text(db, "x")`.

Buat `backend/app/services/node_health.py`:

```python
"""Status node vision: satu jalur transisi online ↔ offline (event system + WS + Telegram) dan monitor latar.

Offline terdeteksi dari LWT MQTT (crash/putus) atau heartbeat yang terlambat > HEARTBEAT_TIMEOUT_S (stop rapi,
hang). Hanya perpindahan status yang membuat event dan pesan, jadi LWT + timeout tidak dobel.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import uuid
from datetime import datetime, timedelta, timezone

from app.core.db import SessionLocal
from app.models.node import Node
from app.schemas.event import EventOut
from app.services import telegram
from app.services.ingest import ingest_event
from app.ws.hub import hub

logger = logging.getLogger(__name__)

HEARTBEAT_TIMEOUT_S = 35
CHECK_INTERVAL_S = 15


def _aware(dt: datetime | None) -> datetime | None:
    """SQLite mengembalikan datetime naive (UTC)."""
    return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt


def _emit(db, node: Node, severity: str, reason: str, now: datetime) -> None:
    status, ev = ingest_event(db, {
        "event_id": str(uuid.uuid4()), "type": "system", "node_id": node.id, "severity": severity,
        "ts_event": now.isoformat(), "payload": {"node": node.name, "reason": reason},
    })
    if status == "created" and ev is not None:
        try:
            asyncio.run(hub.broadcast(EventOut.model_validate(ev).model_dump(mode="json")))
        except Exception:
            logger.exception("node event broadcast failed for %s", node.name)


def _duration(delta: timedelta) -> str:
    minutes = int(delta.total_seconds() // 60)
    return f"{minutes} menit" if minutes < 120 else f"{minutes // 60} jam {minutes % 60} menit"


def mark_offline(db, node: Node, reason: str, now: datetime | None = None, send=None) -> bool:
    """online/unknown → offline: event warning + Telegram. False bila sudah offline."""
    if node.status == "offline":
        return False
    now = now or datetime.now(timezone.utc)
    node.status = "offline"
    db.commit()
    _emit(db, node, "warning", reason, now)
    (send or telegram.send_text)(db, f"⚠️ Node {node.name} offline ({reason}) — deteksi AI berhenti")
    return True


def mark_online(db, node: Node, now: datetime | None = None, since: datetime | None = None,
                send=None) -> bool:
    """offline → online: event info + Telegram "pulih". unknown → online tanpa event. False bila tanpa event."""
    was = node.status
    if was == "online":
        return False
    now = now or datetime.now(timezone.utc)
    node.status = "online"
    db.commit()
    if was != "offline":
        return False
    _emit(db, node, "info", "online", now)
    since = _aware(since)
    took = f" — offline {_duration(now - since)}" if since else ""
    (send or telegram.send_text)(db, f"✅ Node {node.name} pulih{took}")
    return True


def check(db, now: datetime | None = None, send=None) -> int:
    """Node online dengan heartbeat lebih tua dari timeout → offline (reason timeout)."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=HEARTBEAT_TIMEOUT_S)
    stale = db.query(Node).filter(Node.status == "online", Node.last_seen < cutoff).all()
    return sum(mark_offline(db, n, "timeout", now=now, send=send) for n in stale)


class NodeHealthMonitor:
    """Thread latar: check() tiap interval_s; menunggu satu interval sebelum cek pertama."""

    def __init__(self, interval_s: float = CHECK_INTERVAL_S, session_factory=SessionLocal):
        self.interval_s = interval_s
        self._session_factory = session_factory
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="node-health")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def _loop(self) -> None:
        while not self._stop.wait(self.interval_s):
            db = self._session_factory()
            try:
                check(db)
            except Exception:
                logger.warning("node health check failed", exc_info=True)
            finally:
                db.close()


monitor = NodeHealthMonitor()
```

Catatan: `ingest_event` menerima `node_id` int (lihat `services/ingest.py:18-21`); bila ia hanya meresolusi nama,
kirim `node.name`. `Node.last_seen < cutoff` di SQLite membandingkan naive vs aware — bila tes gagal karena itu,
bandingkan dengan `cutoff.replace(tzinfo=None)` saat dialect SQLite, atau filter di Python (`_aware(n.last_seen) <
cutoff`) — pilih yang lulus di SQLite dan Postgres, catat deviasinya.

Run: `rtk bash -c "cd backend && .venv/bin/python -m pytest tests/test_node_health.py tests/test_disk_alert.py -q"` → PASS.

- [ ] **Step 3: Tes pemanggil (gagal)**

`tests/test_events_consumer.py` — ganti `test_lwt_sets_node_offline_and_system_event` dan tambahkan:

```python
def test_lwt_offline_marks_node_once(db, broadcast, monkeypatch):
    from app.services import telegram
    monkeypatch.setattr(telegram, "send_text", lambda db, t: True)
    db.add(Node(name="server", status="online"))
    db.commit()
    handle_message(db, "isentinel/nodes/server/lwt", b'{"status":"offline"}')
    handle_message(db, "isentinel/nodes/server/lwt", b'{"status":"offline"}')  # retained dikirim ulang
    node = db.query(Node).filter_by(name="server").one()
    assert node.status == "offline"
    ev = db.query(ec.Event).one()
    assert ev.type == "system" and ev.severity == "warning"
    assert ev.payload == {"node": "server", "reason": "lwt"}
    assert broadcast and broadcast[-1]["type"] == "system"


def test_lwt_online_payload_ignored(db, broadcast):
    db.add(Node(name="server", status="online"))
    db.commit()
    handle_message(db, "isentinel/nodes/server/lwt", b'{"status":"online"}')
    handle_message(db, "isentinel/nodes/server/lwt", b"")  # retained dihapus
    assert db.query(Node).filter_by(name="server").one().status == "online"
    assert db.query(ec.Event).count() == 0


def test_heartbeat_after_offline_emits_recovered_and_stores_runtime(db, broadcast, monkeypatch):
    from app.services import telegram
    monkeypatch.setattr(telegram, "send_text", lambda db, t: True)
    db.add(Node(name="vision-1", status="offline"))
    db.commit()
    hb = {"ts": datetime.now(timezone.utc).isoformat(), "mqtt_backlog": 2,
          "cameras": [{"id": 3, "worker": "detect", "state": "streaming", "fps": 5.0}],
          "hw": {"gpus": [], "host": {"cpu_pct": 10.0}},
          "modules": {"detector": {"device": "auto", "model": "m"}}}
    handle_message(db, "isentinel/nodes/vision-1/heartbeat", json.dumps(hb).encode())
    handle_message(db, "isentinel/nodes/vision-1/heartbeat", json.dumps(hb).encode())
    node = db.query(Node).filter_by(name="vision-1").one()
    assert node.status == "online"
    assert node.modules["cameras"][0]["state"] == "streaming" and node.modules["mqtt_backlog"] == 2
    assert node.hw["host"]["cpu_pct"] == 10.0
    [ev] = db.query(ec.Event).all()
    assert ev.payload == {"node": "vision-1", "reason": "online"}


def test_heartbeat_legacy_camera_ids_normalized(db, broadcast):
    db.add(Node(name="vision-1"))
    db.commit()
    hb = {"ts": "x", "cameras": [1, 2], "modules": {"detector": {"device": "auto"}}}
    handle_message(db, "isentinel/nodes/vision-1/heartbeat", json.dumps(hb).encode())
    node = db.query(Node).filter_by(name="vision-1").one()
    assert node.modules["cameras"] == [{"id": 1}, {"id": 2}]
```

`tests/test_nodes_internal.py` — ganti `test_mark_stale_flips_old_node` (hapus; tercakup `test_node_health`),
pertahankan `test_mark_stale_endpoint` (tetap `{"marked": 1}`), dan ganti `test_nodes_list_runs_sweeper` dengan:

```python
def test_nodes_list_does_not_change_status_and_has_last_seen(client, db):
    from app.models.node import Node
    db.add(Node(name="old-node", status="online",
                last_seen=datetime.now(timezone.utc) - timedelta(seconds=60)))
    db.commit()
    tok = client.post("/api/v1/auth/login", json={"username": "admin", "password": "boot123"}).json()["token"]
    rows = client.get("/api/v1/nodes", headers={"Authorization": f"Bearer {tok}"}).json()
    old = next(n for n in rows if n["name"] == "old-node")
    assert old["status"] == "online"  # deteksi offline milik monitor, bukan GET
    assert old["last_seen"] is not None
```

Tambahkan tes heartbeat HTTP:

```python
def test_http_heartbeat_recovers_offline_node(client, db, monkeypatch):
    from app.models.node import Node
    from app.models.event import Event
    from app.services import telegram
    monkeypatch.setattr(telegram, "send_text", lambda db, t: True)
    node = db.get(Node, 1)
    node.status = "offline"
    db.commit()
    assert client.post("/internal/nodes/1/heartbeat", json=_hb_body(), headers=_hb_headers()).status_code == 200
    db.expire_all()
    assert db.get(Node, 1).status == "online"
    assert db.query(Event).filter_by(type="system").one().payload["reason"] == "online"
```

`tests/conftest.py` — fixture autouse agar monitor latar tidak menyentuh DB nyata selama tes:

```python
@pytest.fixture(autouse=True)
def _quiet_node_monitor(monkeypatch):
    from app.services import node_health
    monkeypatch.setattr(node_health.monitor, "interval_s", 3600)
```

Run: `rtk bash -c "cd backend && .venv/bin/python -m pytest tests/test_events_consumer.py tests/test_nodes_internal.py -q"`
Expected: FAIL (handler lama).

- [ ] **Step 4: Implementasi pemanggil**

`events_consumer.py`:
- import `from app.services import node_health`, `import threading` (bila belum), dan konstanta modul
  `connected = threading.Event()  # status koneksi consumer ke broker (monitoring)`.
- Cabang heartbeat menjadi:

```python
        elif topic.startswith("isentinel/nodes/") and topic.endswith("/heartbeat"):
            name = topic.split("/")[2]
            node = db.query(Node).filter_by(name=name).first()
            if node is None:
                logger.warning("heartbeat for unknown node %r", name)
                return
            since = node.last_seen
            node.last_seen = datetime.now(timezone.utc)
            if isinstance(data.get("hw"), dict):
                node.hw = data["hw"]
            if isinstance(data.get("modules"), dict):
                modules = dict(data["modules"])
                modules["cameras"] = _cameras(data.get("cameras"))
                if isinstance(data.get("mqtt_backlog"), int):
                    modules["mqtt_backlog"] = data["mqtt_backlog"]
                node.modules = modules
            db.commit()
            node_health.mark_online(db, node, since=since)
```

  dengan helper modul:

```python
def _cameras(raw) -> list[dict]:
    """Heartbeat baru: [{id, worker, state, ...}]; lama: [id] → [{"id": id}] (tanpa statistik)."""
    if not isinstance(raw, list):
        return []
    out = []
    for c in raw:
        if isinstance(c, dict) and isinstance(c.get("id"), int):
            out.append(c)
        elif isinstance(c, int) and not isinstance(c, bool):
            out.append({"id": c})
    return out
```

- Cabang LWT menjadi:

```python
        elif topic.startswith("isentinel/nodes/") and topic.endswith("/lwt"):
            if data.get("status") != "offline":
                return  # "online" dari node (menimpa retained) / payload kosong
            name = topic.split("/")[2]
            node = db.query(Node).filter_by(name=name).first()
            if node is None:
                logger.warning("LWT for unknown node %r", name)
                return
            node_health.mark_offline(db, node, "lwt")
```

  Periksa bagaimana `handle_message` mem-parse payload di atas cabang ini: payload kosong (`b""`, retained dihapus)
  harus berakhir `return` tanpa exception bocor (sudah dibungkus `try/except` luar — pastikan tidak ada log error
  berisik; bila `json.loads(b"")` melempar sebelum cabang, tangani `data = {}` untuk topik LWT).
- `EventConsumer._on_connect`: `connected.set()` sebelum subscribe; tambahkan
  `client.on_disconnect = self._on_disconnect` di `_run` dan method
  `def _on_disconnect(self, client, userdata, flags, reason_code, properties): connected.clear()`.

`api/events.py`:
- import `from app.services import node_health` dan hapus import `mark_stale_nodes`.
- heartbeat HTTP: ganti `node.status = "online"` dengan simpan `since = node.last_seen`, set `last_seen`,
  `db.commit()`, lalu `node_health.mark_online(db, node, since=since)`.
- mark-stale: `return {"status": "ok", "marked": node_health.check(db)}`.

`api/nodes.py`: hapus `mark_stale_nodes` dari import dan dari `list_nodes`.
`models/node.py`: hapus fungsi `mark_stale_nodes` (+ import `timedelta` bila tak terpakai). Cari pemakai lain:
`rtk grep -rn mark_stale_nodes backend` harus kosong.
`schemas/camera.py`: `NodeOut` + `last_seen: datetime | None = None` (import `datetime`).
`main.py` lifespan: setelah `disk_monitor.start()` tambahkan
`from app.services.node_health import monitor as node_monitor` + `node_monitor.start()`; di `finally` panggil
`node_monitor.stop()` sebelum `disk_monitor.stop()`.

Run: `rtk bash -c "cd backend && .venv/bin/python -m pytest tests -q -m 'not gpu'"` → PASS semua.

- [ ] **Step 5: Commit**

```bash
rtk git add backend/
rtk git commit -m "feat(nodes): monitor kesehatan node — event offline/pulih, Telegram, abaikan LWT non-offline"
```

---

### Task 4: Backend — `GET /api/v1/monitoring`

**Files:**
- Create: `backend/app/services/host_stats.py`, `backend/app/services/monitoring.py`,
  `backend/app/schemas/monitoring.py`, `backend/app/api/monitoring.py`
- Modify: `backend/app/services/go2rtc.py` (`probe`), `backend/app/main.py` (router)
- Test: `backend/tests/test_monitoring.py` (baru)

**Interfaces:**
- Consumes: `node.hw` / `node.modules` (Task 3), `events_consumer.connected` (Task 3), `retention.disk_usage`,
  `storage_settings.get`, `telegram.get_token/active_chat`, `Alert`, `Setting("retention_last_sweep")`.
- Produces: `monitoring.snapshot(db, now=None) -> dict` (bentuk spec §3.2), `monitoring.reset_cache()`,
  `go2rtc.probe() -> tuple[set[str] | None, float]`, `host_stats.cpu_pct(proc_root="/proc")`,
  `host_stats.ram_mb(proc_root="/proc")`; endpoint `GET /api/v1/monitoring` → `MonitoringOut`.

- [ ] **Step 1: Tes (gagal)**

Buat `backend/tests/test_monitoring.py`:

```python
from datetime import datetime, timedelta, timezone

import pytest

from app.models.camera import Camera
from app.models.node import Node
from app.models.setting import Setting
from app.services import monitoring

NOW = datetime(2026, 9, 29, 8, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _services(monkeypatch):
    """Layanan eksternal dipalsukan: go2rtc sehat dengan stream cam_1/cam_2, MQTT terhubung."""
    monitoring.reset_cache()
    monkeypatch.setattr(monitoring.go2rtc, "probe", lambda: ({"cam_1", "cam_1_main", "cam_2"}, 3.0))
    monitoring.events_consumer.connected.set()
    yield
    monitoring.events_consumer.connected.clear()
    monitoring.reset_cache()


def _node(db, **over):
    n = Node(name="server", status="online", last_seen=NOW - timedelta(seconds=3),
             hw={"gpus": [{"idx": 0, "name": "RTX", "util_pct": 50, "vram_used_mb": 1000,
                           "vram_total_mb": 12000, "temp_c": 60, "power_w": 100.0}],
                 "host": {"cpu_pct": 20.0, "ram_used_mb": 1000, "ram_total_mb": 8000,
                          "disk_used_pct": 50.0, "disk_free_gb": 100.0}},
             modules={"detector": {"model": "m.engine", "device": "auto", "ms_avg": 8.0, "ms_max": 12.0,
                                   "infer_fps": 40.0},
                      "face": {"loaded": True, "queue": 0}, "mqtt_backlog": 0, "cameras": []})
    for k, v in over.items():
        setattr(n, k, v)
    db.add(n)
    db.commit()
    return n


def _cam(db, id, node=None, enabled=True):
    c = Camera(id=id, name=f"CAM-{id:02d}", host="1.2.3.4", node_id=node.id if node else None,
               enabled=enabled, ai_fps=5.0)
    db.add(c)
    db.commit()
    return c


def _stat(id, **over):
    s = {"id": id, "worker": "detect", "state": "streaming", "fps": 5.0, "target_fps": 5.0,
         "last_frame_age_s": 0.3, "reconnects_1h": 0, "motion_skip_pct": 50.0}
    s.update(over)
    return s


def _with_cams(node, db, stats):
    node.modules = {**node.modules, "cameras": stats}
    db.commit()


def _cam_row(snap, id):
    return next(c for c in snap["cameras"] if c["id"] == id)


def test_healthy_camera_and_summary(db):
    n = _node(db)
    _cam(db, 1, n)
    _with_cams(n, db, [_stat(1)])
    snap = monitoring.snapshot(db, now=NOW)
    assert _cam_row(snap, 1)["health"] == "ok" and _cam_row(snap, 1)["issues"] == []
    assert snap["nodes"][0]["health"] == "ok"
    assert snap["summary"]["cameras"]["ok"] == 1


@pytest.mark.parametrize("stat, issue, health", [
    ({"state": "reconnecting"}, "no_frames", "critical"),
    ({"state": "stalled"}, "no_frames", "critical"),
    ({"last_frame_age_s": 31.0}, "no_frames", "critical"),
    ({"fps": 3.0}, "low_fps", "warning"),
    ({"reconnects_1h": 3}, "reconnects", "warning"),
])
def test_camera_rules(db, stat, issue, health):
    n = _node(db)
    _cam(db, 1, n)
    _with_cams(n, db, [_stat(1, **stat)])
    row = _cam_row(monitoring.snapshot(db, now=NOW), 1)
    assert row["health"] == health and issue in row["issues"]


def test_starting_camera_not_low_fps(db):
    n = _node(db)
    _cam(db, 1, n)
    _with_cams(n, db, [_stat(1, state="starting", fps=0.0, last_frame_age_s=None)])
    assert _cam_row(monitoring.snapshot(db, now=NOW), 1)["health"] == "ok"


def test_face_and_detect_workers_merged_worst(db):
    n = _node(db)
    _cam(db, 1, n)
    _with_cams(n, db, [_stat(1), _stat(1, worker="face", state="stalled")])
    row = _cam_row(monitoring.snapshot(db, now=NOW), 1)
    assert row["health"] == "critical" and row["ai"]["state"] == "stalled"


def test_camera_missing_from_heartbeat_not_running(db):
    n = _node(db)
    _cam(db, 1, n)
    _with_cams(n, db, [])
    assert "not_running" in _cam_row(monitoring.snapshot(db, now=NOW), 1)["issues"]


def test_legacy_heartbeat_no_data(db):
    n = _node(db)
    _cam(db, 1, n)
    _with_cams(n, db, [{"id": 1}])
    row = _cam_row(monitoring.snapshot(db, now=NOW), 1)
    assert row["health"] == "warning" and "no_data" in row["issues"]


def test_node_offline_makes_cameras_critical(db):
    n = _node(db, status="offline")
    _cam(db, 1, n)
    _with_cams(n, db, [_stat(1)])
    snap = monitoring.snapshot(db, now=NOW)
    assert snap["nodes"][0]["health"] == "critical" and "offline" in snap["nodes"][0]["issues"]
    assert "node_offline" in _cam_row(snap, 1)["issues"]
    assert snap["summary"]["health"] == "critical"


def test_camera_without_node_and_disabled(db):
    _node(db)
    _cam(db, 2)              # tidak dianalisis: hanya cek stream go2rtc (cam_2 ada)
    _cam(db, 3)              # cam_3 tidak ada di go2rtc
    _cam(db, 4, enabled=False)
    snap = monitoring.snapshot(db, now=NOW)
    assert _cam_row(snap, 2)["ai"] is None and _cam_row(snap, 2)["health"] == "ok"
    assert _cam_row(snap, 3)["issues"] == ["stream_missing"]
    assert _cam_row(snap, 4)["health"] == "disabled"
    assert snap["summary"]["cameras"]["disabled"] == 1


@pytest.mark.parametrize("patch, issue", [
    ({"hw": {"gpus": [{"idx": 0, "temp_c": 90, "vram_used_mb": 1, "vram_total_mb": 10}], "host": {}}}, "gpu_hot"),
    ({"hw": {"gpus": [{"idx": 0, "temp_c": 50, "vram_used_mb": 95, "vram_total_mb": 100}], "host": {}}}, "vram_high"),
    ({"hw": {"gpus": [], "host": {"ram_used_mb": 95, "ram_total_mb": 100}}}, "ram_high"),
    ({"hw": {"gpus": [], "host": {"cpu_pct": 95.0}}}, "cpu_high"),
    ({"last_seen": NOW - timedelta(seconds=25)}, "heartbeat_late"),
])
def test_node_rules(db, patch, issue):
    _node(db, **patch)
    node = monitoring.snapshot(db, now=NOW)["nodes"][0]
    assert node["health"] == "warning" and issue in node["issues"]


def test_node_mqtt_backlog_warning(db):
    n = _node(db)
    n.modules = {**n.modules, "mqtt_backlog": 5}
    db.commit()
    assert "mqtt_backlog" in monitoring.snapshot(db, now=NOW)["nodes"][0]["issues"]


def test_garbage_json_does_not_crash(db):
    _node(db, hw={"gpus": "x", "host": 5}, modules={"cameras": "junk", "detector": 3})
    snap = monitoring.snapshot(db, now=NOW)
    assert snap["nodes"][0]["gpus"] == [] and snap["nodes"][0]["host"]["cpu_pct"] is None


def test_services_ok_and_failures(db, monkeypatch):
    _node(db)
    db.add(Setting(key="retention_last_sweep", value={"at": (NOW - timedelta(hours=2)).isoformat()}))
    db.commit()
    svc = {s["key"]: s for s in monitoring.snapshot(db, now=NOW)["services"]}
    assert svc["database"]["health"] == "ok" and svc["go2rtc"]["health"] == "ok"
    assert svc["mqtt"]["health"] == "ok" and svc["retention"]["health"] == "ok"
    assert svc["telegram"]["health"] == "unknown"  # belum dikonfigurasi di tes

    monitoring.reset_cache()
    monkeypatch.setattr(monitoring.go2rtc, "probe", lambda: (None, 5000.0))
    monitoring.events_consumer.connected.clear()
    db.query(Setting).filter_by(key="retention_last_sweep").one().value = {"at": (NOW - timedelta(hours=30)).isoformat()}
    db.commit()
    svc = {s["key"]: s for s in monitoring.snapshot(db, now=NOW)["services"]}
    assert svc["go2rtc"]["health"] == "critical" and svc["mqtt"]["health"] == "critical"
    assert svc["retention"]["health"] == "warning"


def test_services_cached_10s(db, monkeypatch):
    calls = []
    monkeypatch.setattr(monitoring.go2rtc, "probe", lambda: calls.append(1) or (set(), 1.0))
    monitoring.snapshot(db, now=NOW)
    monitoring.snapshot(db, now=NOW + timedelta(seconds=5))
    assert len(calls) == 1
    monitoring.snapshot(db, now=NOW + timedelta(seconds=11))
    assert len(calls) == 2


def test_endpoint_viewer_ok_and_requires_login(client, viewer_headers):
    assert client.get("/api/v1/monitoring").status_code == 401
    r = client.get("/api/v1/monitoring", headers=viewer_headers)
    assert r.status_code == 200
    body = r.json()
    assert {"generated_at", "summary", "server", "nodes", "cameras", "services"} <= set(body)
```

Periksa di `tests/conftest.py` bahwa fixture `client` dan `viewer_headers` tersedia untuk file baru (bila `client`
didefinisikan per file seperti `test_events_api.py`, salin fixture `client` itu ke file ini; `viewer_headers`
memakai `client`). `Camera(...)` butuh field wajib model — lengkapi sesuai `models/camera.py` bila `name/host`
saja tidak cukup.

Run: `rtk bash -c "cd backend && .venv/bin/python -m pytest tests/test_monitoring.py -q"`
Expected: FAIL — `ImportError: cannot import name 'monitoring'`.

- [ ] **Step 2: `go2rtc.probe` + `host_stats`**

`go2rtc.py`:

```python
def probe() -> tuple[set[str] | None, float]:
    """(nama stream, latensi ms) — None bila go2rtc tidak bisa dihubungi (monitoring)."""
    t0 = time.perf_counter()
    try:
        with _client() as c:
            r = c.get("/api/streams")
        ms = round((time.perf_counter() - t0) * 1000, 1)
        return (set(r.json().keys()) if r.is_success else None), ms
    except Exception:
        return None, round((time.perf_counter() - t0) * 1000, 1)
```

(import `time` di atas modul.)

`backend/app/services/host_stats.py`:

```python
"""CPU/RAM host API dari /proc (stdlib).

# ponytail: logika sama dengan vision/vision/hardware.py host_stats — sengaja diduplikasi kecil karena vision
# tidak boleh bergantung pada backend dan sebaliknya; satukan bila ada paket bersama.
"""
from __future__ import annotations

import os

_prev_cpu: tuple[int, int] | None = None


def cpu_pct(proc_root: str = "/proc") -> float | None:
    global _prev_cpu
    try:
        with open(os.path.join(proc_root, "stat")) as f:
            vals = [int(v) for v in f.readline().split()[1:9]]
    except (OSError, ValueError, IndexError):
        return None
    idle, total = vals[3] + vals[4], sum(vals)
    prev, _prev_cpu = _prev_cpu, (total - idle, total)
    if prev is None or total <= prev[1]:
        return None
    return round((total - idle - prev[0]) / (total - prev[1]) * 100, 1)


def ram_mb(proc_root: str = "/proc") -> tuple[int | None, int | None]:
    info = {}
    try:
        with open(os.path.join(proc_root, "meminfo")) as f:
            for line in f:
                key, _, rest = line.partition(":")
                info[key] = int(rest.split()[0])
    except (OSError, ValueError, IndexError):
        return None, None
    if "MemTotal" not in info or "MemAvailable" not in info:
        return None, None
    return round((info["MemTotal"] - info["MemAvailable"]) / 1024), round(info["MemTotal"] / 1024)
```

Tambahkan tes kecil `test_host_stats_proc` di `test_monitoring.py` dengan file `/proc` palsu di `tmp_path`
(pola sama dengan tes vision Task 2: sampel pertama `None`, kedua `66.7`; RAM `11719/15625`).

- [ ] **Step 3: `monitoring.py`**

```python
"""Snapshot kesehatan untuk halaman Monitoring: kamera, node, layanan, server (kondisi saat ini, S1).

Aturan & ambang tetap (S3 akan membuatnya bisa diatur). Data node dari heartbeat terakhir di node.hw /
node.modules; tipe JSON divalidasi defensif karena berasal dari node.
"""
from __future__ import annotations

import time as _time
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.core.config import settings
from app.models.alert import Alert
from app.models.camera import Camera
from app.models.node import Node
from app.models.setting import Setting
from app.services import events_consumer, go2rtc, host_stats, retention, storage_settings, telegram
from app.services.node_health import _aware

FRAME_STALE_S = 30
LOW_FPS_RATIO = 0.8
RECONNECT_WARN = 3
GPU_TEMP_WARN_C = 85
VRAM_WARN_PCT = RAM_WARN_PCT = CPU_WARN_PCT = 90
HEARTBEAT_LATE_S = 20
SWEEP_STALE_H = 26
SERVICE_CACHE_S = 10

RANK = {"ok": 0, "unknown": 0, "warning": 1, "critical": 2}
STATE_RANK = {"streaming": 0, "starting": 1, None: 1, "stalled": 2, "reconnecting": 3}

_cache: dict = {"at": None, "services": None}


def reset_cache() -> None:
    _cache.update(at=None, services=None)


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _dict(v) -> dict:
    return v if isinstance(v, dict) else {}


def _list(v) -> list:
    return v if isinstance(v, list) else []


def _worst(*levels: str) -> str:
    return max(levels, key=lambda h: RANK[h]) if levels else "ok"


def _merge_workers(entries: list[dict]) -> dict | None:
    """Gabung entri detect/face satu kamera: kondisi terburuk. None bila tanpa statistik (heartbeat lama)."""
    stats = [e for e in entries if "state" in e]
    if not stats:
        return None
    worst = max(stats, key=lambda e: STATE_RANK.get(e.get("state"), 1))

    def ratio(e):
        fps, target = _num(e.get("fps")), _num(e.get("target_fps"))
        return fps / target if fps is not None and target else None

    ratios = [(ratio(e), e) for e in stats if ratio(e) is not None]
    slowest = min(ratios, key=lambda p: p[0])[1] if ratios else worst
    ages = [_num(e.get("last_frame_age_s")) for e in stats if _num(e.get("last_frame_age_s")) is not None]
    recon = [_num(e.get("reconnects_1h")) or 0 for e in stats]
    skips = [_num(e.get("motion_skip_pct")) for e in stats if _num(e.get("motion_skip_pct")) is not None]
    return {"state": worst.get("state"), "fps": _num(slowest.get("fps")),
            "target_fps": _num(slowest.get("target_fps")),
            "last_frame_age_s": max(ages) if ages else None, "reconnects_1h": max(recon) if recon else 0,
            "motion_skip_pct": skips[0] if skips else None}


def _camera_row(cam: Camera, node: Node | None, entries: list[dict] | None, streams: set[str] | None) -> dict:
    row = {"id": cam.id, "name": cam.name, "location": cam.location, "node_id": cam.node_id,
           "node_name": node.name if node else None, "enabled": bool(cam.enabled), "issues": [],
           "ai": None, "stream": {"registered": None if streams is None else f"cam_{cam.id}" in streams}}
    if not cam.enabled:
        row["health"] = "disabled"
        return row
    crit, warn = [], []
    if streams is not None and f"cam_{cam.id}" not in streams:
        warn.append("stream_missing")
    if cam.node_id is not None:
        if node is None or node.status == "offline":
            crit.append("node_offline")
        elif entries is None or not entries:
            crit.append("not_running")
        else:
            ai = _merge_workers(entries)
            row["ai"] = ai
            if ai is None:
                warn.append("no_data")
            else:
                age = ai["last_frame_age_s"]
                if ai["state"] in ("reconnecting", "stalled") or (age is not None and age > FRAME_STALE_S):
                    crit.append("no_frames")
                elif (ai["state"] != "starting" and ai["fps"] is not None and ai["target_fps"]
                        and ai["fps"] < LOW_FPS_RATIO * ai["target_fps"]):
                    warn.append("low_fps")
                if ai["reconnects_1h"] >= RECONNECT_WARN:
                    warn.append("reconnects")
    row["issues"] = crit + warn
    row["health"] = "critical" if crit else "warning" if warn else "ok"
    return row


def _node_row(node: Node, now: datetime) -> dict:
    hw, mods = _dict(node.hw), _dict(node.modules)
    host = _dict(hw.get("host"))
    gpus = [g for g in _list(hw.get("gpus")) if isinstance(g, dict)]
    seen = _aware(node.last_seen)
    age = round((now - seen).total_seconds(), 1) if seen else None
    det, face = _dict(mods.get("detector")), _dict(mods.get("face"))
    backlog = _num(mods.get("mqtt_backlog"))
    issues, crit = [], False
    if node.status == "offline":
        issues.append("offline")
        crit = True
    else:
        if age is not None and age > HEARTBEAT_LATE_S:
            issues.append("heartbeat_late")
        if any((_num(g.get("temp_c")) or 0) >= GPU_TEMP_WARN_C for g in gpus):
            issues.append("gpu_hot")
        if any(_num(g.get("vram_total_mb")) and (_num(g.get("vram_used_mb")) or 0) / g["vram_total_mb"] * 100
               >= VRAM_WARN_PCT for g in gpus):
            issues.append("vram_high")
        used, total = _num(host.get("ram_used_mb")), _num(host.get("ram_total_mb"))
        if used is not None and total and used / total * 100 >= RAM_WARN_PCT:
            issues.append("ram_high")
        if (_num(host.get("cpu_pct")) or 0) >= CPU_WARN_PCT:
            issues.append("cpu_high")
        if backlog:
            issues.append("mqtt_backlog")
    host_keys = ("cpu_pct", "ram_used_mb", "ram_total_mb", "disk_used_pct", "disk_free_gb")
    return {"id": node.id, "name": node.name, "status": node.status,
            "last_seen": seen.isoformat() if seen else None, "age_s": age,
            "health": "critical" if crit else "warning" if issues else "ok", "issues": issues,
            "host": {k: _num(host.get(k)) for k in host_keys},
            "gpus": [{"idx": _num(g.get("idx")), "name": g.get("name") if isinstance(g.get("name"), str) else None,
                      **{k: _num(g.get(k)) for k in ("util_pct", "vram_used_mb", "vram_total_mb", "temp_c", "power_w")}}
                     for g in gpus],
            "inference": {
                "detector": {"model": det.get("model") if isinstance(det.get("model"), str) else None,
                             "device": det.get("device") if isinstance(det.get("device"), str) else None,
                             **{k: _num(det.get(k)) for k in ("ms_avg", "ms_max", "infer_fps")}},
                "face": {"loaded": face.get("loaded") if isinstance(face.get("loaded"), bool) else None,
                         "queue": _num(face.get("queue"))},
                "mqtt_backlog": backlog}}


def _services(db, now: datetime) -> tuple[list[dict], set[str] | None]:
    if _cache["at"] is not None and now - _cache["at"] < timedelta(seconds=SERVICE_CACHE_S):
        return _cache["services"]
    out = []
    t0 = _time.perf_counter()
    try:
        db.execute(text("SELECT 1"))
        out.append({"key": "database", "health": "ok", "detail": None,
                    "latency_ms": round((_time.perf_counter() - t0) * 1000, 1)})
    except Exception as e:
        out.append({"key": "database", "health": "critical", "detail": type(e).__name__, "latency_ms": None})
    streams, ms = go2rtc.probe()
    out.append({"key": "go2rtc", "health": "ok" if streams is not None else "critical",
                "detail": f"{len(streams)} stream" if streams is not None else "unreachable", "latency_ms": ms})
    out.append({"key": "mqtt", "health": "ok" if events_consumer.connected.is_set() else "critical",
                "detail": None, "latency_ms": None})
    sweep = db.get(Setting, "retention_last_sweep")
    at = _dict(sweep.value if sweep else None).get("at")
    try:
        at_dt = _aware(datetime.fromisoformat(at)) if isinstance(at, str) else None
    except ValueError:
        at_dt = None
    stale = at_dt is None or now - at_dt > timedelta(hours=SWEEP_STALE_H)
    out.append({"key": "retention", "health": "warning" if stale else "ok",
                "detail": at_dt.isoformat() if at_dt else None, "latency_ms": None})
    if not telegram.get_token() or telegram.active_chat(db) is None:
        out.append({"key": "telegram", "health": "unknown", "detail": "not_configured", "latency_ms": None})
    else:
        last = db.query(Alert).filter(Alert.status.in_(("sent", "failed"))).order_by(Alert.id.desc()).first()
        queued = db.query(Alert).filter_by(status="queued").count()
        out.append({"key": "telegram", "health": "warning" if last is not None and last.status == "failed" else "ok",
                    "detail": f"{last.status if last else '—'} · queued {queued}", "latency_ms": None})
    usage = retention.disk_usage(settings.storage_root)
    over = usage["percent"] >= storage_settings.get(db)["disk_alert_percent"]
    out.append({"key": "disk", "health": "warning" if over else "ok", "detail": f"{usage['percent']}%",
                "latency_ms": None})
    _cache.update(at=now, services=(out, streams))
    return out, streams


def snapshot(db, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    services, streams = _services(db, now)
    nodes = db.query(Node).order_by(Node.name).all()
    by_id = {n.id: n for n in nodes}
    per_node: dict[int, dict[int, list[dict]]] = {}
    for n in nodes:
        entries: dict[int, list[dict]] = {}
        for c in _list(_dict(n.modules).get("cameras")):
            if isinstance(c, dict) and isinstance(c.get("id"), int):
                entries.setdefault(c["id"], []).append(c)
        per_node[n.id] = entries
    cams = []
    for cam in db.query(Camera).order_by(Camera.name).all():
        node = by_id.get(cam.node_id) if cam.node_id is not None else None
        entries = per_node.get(cam.node_id, {}).get(cam.id) if node is not None else None
        cams.append(_camera_row(cam, node, entries, streams))
    node_rows = [_node_row(n, now) for n in nodes]
    used, total = host_stats.ram_mb()
    disk = retention.disk_usage(settings.storage_root)

    def count(rows, keys=("ok", "warning", "critical")):
        return {k: sum(1 for r in rows if r["health"] == k) for k in keys}

    summary = {"cameras": count(cams, ("ok", "warning", "critical", "disabled")),
               "nodes": count(node_rows), "services": count([s for s in services if s["health"] != "unknown"])}
    summary["health"] = _worst(*[r["health"] for r in cams if r["health"] != "disabled"],
                               *[r["health"] for r in node_rows],
                               *[s["health"] for s in services if s["health"] != "unknown"])
    return {"generated_at": now.isoformat(), "summary": summary,
            "server": {"cpu_pct": host_stats.cpu_pct(), "ram_used_mb": used, "ram_total_mb": total,
                       "disk_used_pct": disk["percent"], "disk_free_gb": round(disk["free"] / 1024 ** 3, 1)},
            "nodes": node_rows, "cameras": cams, "services": services}
```

Catatan: `_aware` diimpor dari `node_health` (satu helper). Bila `Camera.location` tidak ada di model (lokasi lewat
relasi grup), gunakan atribut lokasi yang dipakai `CameraOut` — cek `schemas/camera.py` dan catat.

- [ ] **Step 4: Schema + router**

`backend/app/schemas/monitoring.py` — model Pydantic sesuai spec §3.2: `HostOut`, `GpuOut`, `DetectorOut`,
`FaceOut`, `InferenceOut`, `NodeHealthOut`, `CameraAiOut`, `CameraStreamOut`, `CameraHealthOut`,
`ServiceOut`, `SummaryOut`, `MonitoringOut` (semua field numerik `float | None`/`int | None`, `health: str`,
`issues: list[str]`). `MonitoringOut` field: `generated_at: datetime`, `summary`, `server: HostOut`,
`nodes: list[NodeHealthOut]`, `cameras: list[CameraHealthOut]`, `services: list[ServiceOut]`.

`backend/app/api/monitoring.py`:

```python
from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.core.db import get_db
from app.schemas.monitoring import MonitoringOut
from app.services import monitoring

router = APIRouter(prefix="/api/v1/monitoring", tags=["monitoring"])


@router.get("", response_model=MonitoringOut)
def get_monitoring(user=Depends(get_current_user), db=Depends(get_db)):
    """Kesehatan kamera, node, layanan, server saat ini (semua user login; read-only)."""
    return monitoring.snapshot(db)
```

Daftarkan router di `main.py` bersama router lain.

Run: `rtk bash -c "cd backend && .venv/bin/python -m pytest tests -q -m 'not gpu'"` → PASS semua.

- [ ] **Step 5: Commit**

```bash
rtk git add backend/
rtk git commit -m "feat(monitoring): endpoint kesehatan kamera, node, layanan, dan server"
```

---

### Task 5: Frontend — halaman Monitoring

**Files:**
- Create: `frontend/src/api/monitoring.ts`, `frontend/src/features/monitoring/MonitoringPage.tsx`,
  `frontend/src/features/monitoring/health.ts`
- Modify: `frontend/src/main.tsx` (route + `SEGMENT_TO_KEY`), `frontend/src/app/AppShell.tsx` (menu),
  `frontend/src/app/i18n.tsx`, `frontend/src/app/theme.scss`
- Test: `frontend/src/__tests__/monitoring.test.tsx` (baru), `frontend/src/__tests__/shell.test.tsx` (menu)

**Interfaces:**
- Consumes: `GET /api/v1/monitoring` (Task 4).
- Produces: `getMonitoring(): Promise<Monitoring>`; tipe `Health = 'ok' | 'warning' | 'critical' | 'unknown' | 'disabled'`,
  `Monitoring`, `MonNode`, `MonCamera`, `MonService`; `health.ts`: `HEALTH_ORDER`, `issueKey(code): TKey`,
  `healthKey(h): TKey`, `stateKey(s): TKey`, `serviceKey(k): TKey`.

- [ ] **Step 1: Tes (gagal)**

Buat `frontend/src/__tests__/monitoring.test.tsx`:

```tsx
import { act, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import '@testing-library/jest-dom/vitest'
import { I18nProvider } from '../app/i18n'
import MonitoringPage from '../features/monitoring/MonitoringPage'

const cam = (id: number, health: string, issues: string[] = [], over = {}) => ({
  id, name: `CAM-${id}`, location: 'Gudang', node_id: 1, node_name: 'server', enabled: health !== 'disabled',
  health, issues,
  ai: { state: 'streaming', fps: 5, target_fps: 5, last_frame_age_s: 0.3, reconnects_1h: 0, motion_skip_pct: 40 },
  stream: { registered: true }, ...over,
})

const DATA = {
  generated_at: '2026-09-29T08:00:00Z',
  summary: { health: 'critical', cameras: { ok: 1, warning: 1, critical: 1, disabled: 0 },
             nodes: { ok: 1, warning: 0, critical: 0 }, services: { ok: 5, warning: 1, critical: 0 } },
  server: { cpu_pct: 20, ram_used_mb: 4000, ram_total_mb: 16000, disk_used_pct: 65, disk_free_gb: 300 },
  nodes: [{ id: 1, name: 'server', status: 'online', last_seen: '2026-09-29T07:59:57Z', age_s: 3, health: 'ok',
            issues: [], host: { cpu_pct: 41, ram_used_mb: 9000, ram_total_mb: 64000, disk_used_pct: 65, disk_free_gb: 310 },
            gpus: [{ idx: 0, name: 'RTX 4090', util_pct: 55, vram_used_mb: 5000, vram_total_mb: 24000, temp_c: 61, power_w: 120 }],
            inference: { detector: { model: 'yolo26s.engine', device: 'auto', ms_avg: 7.9, ms_max: 15.2, infer_fps: 48 },
                         face: { loaded: true, queue: 0 }, mqtt_backlog: 0 } }],
  cameras: [cam(1, 'ok'), cam(2, 'critical', ['no_frames'], { ai: { state: 'stalled', fps: 0, target_fps: 5, last_frame_age_s: 45, reconnects_1h: 2, motion_skip_pct: null } }),
            cam(3, 'warning', ['low_fps'])],
  services: [{ key: 'database', health: 'ok', detail: null, latency_ms: 1.2 },
             { key: 'retention', health: 'warning', detail: null, latency_ms: null }],
}

let reply: () => Promise<unknown>
beforeEach(() => {
  reply = async () => ({ ok: true, status: 200, json: () => Promise.resolve(DATA) })
  vi.stubGlobal('fetch', vi.fn(async (url: string) =>
    String(url).includes('/monitoring') ? reply() : { ok: false, status: 404, json: () => Promise.resolve(null) }))
})
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

const renderPage = () => render(
  <I18nProvider><MemoryRouter><MonitoringPage /></MemoryRouter></I18nProvider>)

test('ringkasan, node, dan kamera urut kritis → peringatan → sehat', async () => {
  renderPage()
  expect(await screen.findByTestId('mon-summary')).toHaveTextContent('Kritis')
  expect(screen.getByTestId('mon-node-1')).toHaveTextContent('RTX 4090')
  expect(screen.getByTestId('mon-node-1')).toHaveTextContent('61')
  expect(screen.getByTestId('mon-server')).toBeInTheDocument()
  const rows = screen.getAllByTestId(/^mon-cam-\d+$/)
  expect(rows.map((r) => r.dataset.testid)).toEqual(['mon-cam-2', 'mon-cam-3', 'mon-cam-1'])
  expect(within(rows[0]).getByText('Tidak ada frame')).toBeInTheDocument()
})

test('filter "Hanya bermasalah" menyembunyikan kamera sehat', async () => {
  renderPage()
  await screen.findByTestId('mon-cam-1')
  await userEvent.click(screen.getByTestId('mon-only-issues'))
  expect(screen.queryByTestId('mon-cam-1')).toBeNull()
  expect(screen.getByTestId('mon-cam-2')).toBeInTheDocument()
})

test('polling 10 s; fetch gagal → pesan error, data lama tetap tampil', async () => {
  vi.useFakeTimers()
  renderPage()
  await act(async () => { await vi.advanceTimersByTimeAsync(0) })
  expect(screen.getByTestId('mon-cam-1')).toBeInTheDocument()
  reply = async () => ({ ok: false, status: 500, json: () => Promise.resolve(null) })
  await act(async () => { await vi.advanceTimersByTimeAsync(10_000) })
  expect(screen.getByTestId('mon-error')).toBeInTheDocument()
  expect(screen.getByTestId('mon-cam-1')).toBeInTheDocument()
})
```

Tambahkan di `shell.test.tsx` tes bahwa item menu "Monitoring" ada untuk user viewer (ikuti pola tes admin-only
yang sudah ada di file itu: stub `/auth/me` role `viewer`, pastikan link `Monitoring` → `/monitoring` tampil dan
"Konfigurasi" tidak).

Run: `rtk bash -c "cd frontend && npx vitest run src/__tests__/monitoring.test.tsx"`
Expected: FAIL — import `MonitoringPage` tidak ditemukan.

- [ ] **Step 2: API + helper label**

`frontend/src/api/monitoring.ts`:

```ts
import { apiFetch } from './client'

export type Health = 'ok' | 'warning' | 'critical' | 'unknown' | 'disabled'
export type HostStats = { cpu_pct: number | null; ram_used_mb: number | null; ram_total_mb: number | null
  disk_used_pct: number | null; disk_free_gb: number | null }
export type MonGpu = { idx: number | null; name: string | null; util_pct: number | null; vram_used_mb: number | null
  vram_total_mb: number | null; temp_c: number | null; power_w: number | null }
export type MonNode = { id: number; name: string; status: string; last_seen: string | null; age_s: number | null
  health: Health; issues: string[]; host: HostStats; gpus: MonGpu[]
  inference: { detector: { model: string | null; device: string | null; ms_avg: number | null; ms_max: number | null
    infer_fps: number | null }; face: { loaded: boolean | null; queue: number | null }; mqtt_backlog: number | null } }
export type MonCamera = { id: number; name: string; location: string | null; node_id: number | null
  node_name: string | null; enabled: boolean; health: Health; issues: string[]
  ai: { state: string | null; fps: number | null; target_fps: number | null; last_frame_age_s: number | null
    reconnects_1h: number; motion_skip_pct: number | null } | null
  stream: { registered: boolean | null } }
export type MonService = { key: string; health: Health; detail: string | null; latency_ms: number | null }
export type Counts = { ok: number; warning: number; critical: number; disabled?: number }
export type Monitoring = { generated_at: string
  summary: { health: Health; cameras: Counts; nodes: Counts; services: Counts }
  server: HostStats; nodes: MonNode[]; cameras: MonCamera[]; services: MonService[] }

export async function getMonitoring(): Promise<Monitoring> {
  const res = await apiFetch('/monitoring')
  if (!res.ok) throw new Error(`monitoring failed: ${res.status}`)
  return res.json()
}
```

`frontend/src/features/monitoring/health.ts`:

```ts
import type { TKey } from '../../app/i18n'
import type { Health } from '../../api/monitoring'

export const HEALTH_ORDER: Record<Health, number> = { critical: 0, warning: 1, unknown: 2, ok: 3, disabled: 4 }
export const healthKey = (h: Health): TKey => `mon.health.${h}` as TKey
export const issueKey = (code: string): TKey => `mon.issue.${code}` as TKey
export const stateKey = (s: string | null): TKey => `mon.state.${s ?? 'none'}` as TKey
export const serviceKey = (k: string): TKey => `mon.service.${k}` as TKey
/** Angka tak tersedia → "—". */
export const fmt = (v: number | null | undefined, unit = '', digits = 0) =>
  v == null ? '—' : `${v.toFixed(digits)}${unit}`
```

- [ ] **Step 3: i18n**

Tambahkan di dict `id` (dekat `nav.configuration`) dan `en` — kunci sama:

```
'nav.monitoring': 'Monitoring' / 'Monitoring'
'mon.title': 'Monitoring Resource' / 'Resource Monitoring'
'mon.subtitle': 'Kesehatan kamera, inferensi AI, hardware, dan layanan — diperbarui tiap 10 detik' /
  'Camera, AI inference, hardware, and service health — refreshed every 10 seconds'
'mon.updated': 'Diperbarui {time}' / 'Updated {time}'
'mon.error': 'Gagal memuat data monitoring — menampilkan data terakhir' / 'Failed to load monitoring data — showing last data'
'mon.overall': 'Status keseluruhan' / 'Overall status'
'mon.cameras': 'Kamera' / 'Cameras'
'mon.nodes': 'Node' / 'Nodes'
'mon.services': 'Layanan' / 'Services'
'mon.server': 'Server pusat' / 'Central server'
'mon.onlyIssues': 'Hanya bermasalah' / 'Issues only'
'mon.col.name' 'Kamera'/'Camera', 'mon.col.location' 'Lokasi'/'Location', 'mon.col.node' 'Node'/'Node',
'mon.col.health' 'Status'/'Status', 'mon.col.state' 'Sumber AI'/'AI source', 'mon.col.fps' 'FPS (aktual/target)'/'FPS (actual/target)',
'mon.col.age' 'Frame terakhir'/'Last frame', 'mon.col.reconnects' 'Reconnect 1 jam'/'Reconnects 1h',
'mon.col.skip' 'Skip motion'/'Motion skip', 'mon.col.stream' 'Stream live'/'Live stream'
'mon.cpu' 'CPU', 'mon.ram' 'RAM', 'mon.disk' 'Disk', 'mon.gpu' 'GPU', 'mon.vram' 'VRAM', 'mon.temp' 'Suhu'/'Temp',
'mon.power' 'Daya'/'Power', 'mon.infer' 'Inferensi'/'Inference', 'mon.inferMs' 'ms rata-rata / maks'/'ms avg / max',
'mon.inferFps' 'fps inferensi'/'inference fps', 'mon.faceQueue' 'Antrean wajah'/'Face queue',
'mon.backlog' 'Backlog MQTT'/'MQTT backlog', 'mon.heartbeat' 'Heartbeat {s} dtk lalu'/'Heartbeat {s}s ago',
'mon.noNodes' 'Belum ada node terdaftar'/'No nodes registered', 'mon.noCameras' 'Tidak ada kamera'/'No cameras'
'mon.stream.yes' 'Terdaftar'/'Registered', 'mon.stream.no' 'Tidak terdaftar'/'Missing'
'mon.health.ok' 'Sehat'/'Healthy', 'mon.health.warning' 'Peringatan'/'Warning', 'mon.health.critical' 'Kritis'/'Critical',
'mon.health.unknown' 'Tidak diketahui'/'Unknown', 'mon.health.disabled' 'Nonaktif'/'Disabled'
'mon.state.streaming' 'Streaming', 'mon.state.starting' 'Memulai'/'Starting', 'mon.state.reconnecting' 'Menyambung ulang'/'Reconnecting',
'mon.state.stalled' 'Macet'/'Stalled', 'mon.state.none' '—'
'mon.issue.node_offline' 'Node offline', 'mon.issue.not_running' 'Tidak berjalan di node'/'Not running on node',
'mon.issue.no_frames' 'Tidak ada frame'/'No frames', 'mon.issue.low_fps' 'FPS rendah'/'Low FPS',
'mon.issue.reconnects' 'Sering reconnect'/'Frequent reconnects', 'mon.issue.stream_missing' 'Stream live tidak terdaftar'/'Live stream missing',
'mon.issue.no_data' 'Belum ada data (vision lama)'/'No data (old vision)', 'mon.issue.offline' 'Offline',
'mon.issue.heartbeat_late' 'Heartbeat terlambat'/'Late heartbeat', 'mon.issue.gpu_hot' 'GPU panas'/'GPU hot',
'mon.issue.vram_high' 'VRAM hampir penuh'/'VRAM nearly full', 'mon.issue.ram_high' 'RAM hampir penuh'/'RAM nearly full',
'mon.issue.cpu_high' 'CPU tinggi'/'High CPU', 'mon.issue.mqtt_backlog' 'Event tertahan di node'/'Events queued on node'
'mon.service.database' 'Database', 'mon.service.go2rtc' 'go2rtc (live view)', 'mon.service.mqtt' 'Broker MQTT'/'MQTT broker',
'mon.service.retention' 'Sweep retensi'/'Retention sweep', 'mon.service.telegram' 'Telegram', 'mon.service.disk' 'Disk storage'
```

(Tulis sebagai entri TypeScript biasa `'key': 'teks',`; teks tunggal = sama untuk id & en.)

- [ ] **Step 4: `MonitoringPage.tsx`**

```tsx
import { useEffect, useState } from 'react'
import { InlineNotification, Tag, Toggle } from '@carbon/react'
import { useT } from '../../app/i18n'
import { getMonitoring, type Health, type HostStats, type MonCamera, type Monitoring } from '../../api/monitoring'
import { fmt, HEALTH_ORDER, healthKey, issueKey, serviceKey, stateKey } from './health'

export const POLL_MS = 10_000
const TAG: Record<Health, 'green' | 'warm-gray' | 'red' | 'gray' | 'cool-gray'> = {
  ok: 'green', warning: 'warm-gray', critical: 'red', unknown: 'gray', disabled: 'cool-gray',
}

function HealthTag({ h }: { h: Health }) {
  const { t } = useT()
  return <Tag type={TAG[h]} size="sm" className={`mon-tag mon-tag--${h}`}>{t(healthKey(h))}</Tag>
}

function HostLines({ host }: { host: HostStats }) {
  const { t } = useT()
  const ram = host.ram_used_mb != null && host.ram_total_mb
    ? `${(host.ram_used_mb / 1024).toFixed(1)} / ${(host.ram_total_mb / 1024).toFixed(1)} GB` : '—'
  return (
    <dl className="mon-kv">
      <dt>{t('mon.cpu')}</dt><dd>{fmt(host.cpu_pct, ' %')}</dd>
      <dt>{t('mon.ram')}</dt><dd>{ram}</dd>
      <dt>{t('mon.disk')}</dt><dd>{fmt(host.disk_used_pct, ' %')} · {fmt(host.disk_free_gb, ' GB', 1)}</dd>
    </dl>
  )
}

/** System › Monitoring: kondisi saat ini (S1). Polling 10 s; gagal → data terakhir tetap tampil. */
export default function MonitoringPage() {
  const { t, locale } = useT()
  const [data, setData] = useState<Monitoring | null>(null)
  const [failed, setFailed] = useState(false)
  const [onlyIssues, setOnlyIssues] = useState(false)

  useEffect(() => {
    let alive = true
    const load = () => getMonitoring()
      .then((d) => { if (alive) { setData(d); setFailed(false) } })
      .catch(() => { if (alive) setFailed(true) })
    load()
    const timer = setInterval(load, POLL_MS)
    return () => { alive = false; clearInterval(timer) }
  }, [])

  const cams: MonCamera[] = (data?.cameras ?? [])
    .filter((c) => !onlyIssues || c.health === 'warning' || c.health === 'critical')
    .sort((a, b) => HEALTH_ORDER[a.health] - HEALTH_ORDER[b.health] || a.name.localeCompare(b.name))

  return (
    <div className="mon-page">
      <h1 className="mon-title">{t('mon.title')}</h1>
      <p className="en-muted">{t('mon.subtitle')}</p>
      {failed && <div data-testid="mon-error"><InlineNotification kind="error" lowContrast hideCloseButton title={t('mon.error')} /></div>}
      {data && (
        <>
          <section className="mon-summary" data-testid="mon-summary">
            <div className={`mon-tile mon-tile--${data.summary.health}`}>
              <span>{t('mon.overall')}</span>
              <strong>{t(healthKey(data.summary.health))}</strong>
              <small>{t('mon.updated').replace('{time}', new Date(data.generated_at).toLocaleTimeString(locale))}</small>
            </div>
            {(['cameras', 'nodes', 'services'] as const).map((k) => (
              <div key={k} className="mon-tile">
                <span>{t(`mon.${k}`)}</span>
                <strong>{data.summary[k].ok}</strong>
                <small>
                  {t('mon.health.warning')} {data.summary[k].warning} · {t('mon.health.critical')} {data.summary[k].critical}
                </small>
              </div>
            ))}
          </section>

          <section className="mon-nodes">
            {data.nodes.length === 0 && <p className="en-muted">{t('mon.noNodes')}</p>}
            {data.nodes.map((n) => (
              <article key={n.id} className="st-card" data-testid={`mon-node-${n.id}`}>
                <header className="mon-card__head">
                  <h3 className="st-card__title">{n.name}</h3>
                  <HealthTag h={n.health} />
                </header>
                {n.age_s != null && <p className="en-muted">{t('mon.heartbeat').replace('{s}', n.age_s.toFixed(0))}</p>}
                <HostLines host={n.host} />
                {n.gpus.map((g) => (
                  <dl key={g.idx ?? 0} className="mon-kv">
                    <dt>{t('mon.gpu')} {g.idx}</dt><dd>{g.name ?? '—'} · {fmt(g.util_pct, ' %')}</dd>
                    <dt>{t('mon.vram')}</dt><dd>{fmt(g.vram_used_mb)} / {fmt(g.vram_total_mb, ' MB')}</dd>
                    <dt>{t('mon.temp')}</dt><dd>{fmt(g.temp_c, ' °C')} · {fmt(g.power_w, ' W')}</dd>
                  </dl>
                ))}
                <dl className="mon-kv">
                  <dt>{t('mon.infer')}</dt>
                  <dd>{n.inference.detector.model ?? '—'} · {n.inference.detector.device ?? '—'}</dd>
                  <dt>{t('mon.inferMs')}</dt>
                  <dd>{fmt(n.inference.detector.ms_avg, '', 1)} / {fmt(n.inference.detector.ms_max, ' ms', 1)}</dd>
                  <dt>{t('mon.inferFps')}</dt><dd>{fmt(n.inference.detector.infer_fps, '', 1)}</dd>
                  <dt>{t('mon.faceQueue')}</dt><dd>{fmt(n.inference.face.queue)}</dd>
                  <dt>{t('mon.backlog')}</dt><dd>{fmt(n.inference.mqtt_backlog)}</dd>
                </dl>
                {n.issues.length > 0 && (
                  <ul className="mon-issues">{n.issues.map((i) => <li key={i}>{t(issueKey(i))}</li>)}</ul>
                )}
              </article>
            ))}
            <article className="st-card" data-testid="mon-server">
              <h3 className="st-card__title">{t('mon.server')}</h3>
              <HostLines host={data.server} />
            </article>
          </section>

          <section className="st-card">
            <header className="mon-card__head">
              <h3 className="st-card__title">{t('mon.cameras')}</h3>
              <Toggle id="mon-only-issues" data-testid="mon-only-issues" size="sm" labelText={t('mon.onlyIssues')}
                toggled={onlyIssues} onToggle={setOnlyIssues} />
            </header>
            {cams.length === 0 ? <p className="en-muted">{t('mon.noCameras')}</p> : (
              <div className="mon-table-wrap">
                <table className="mon-table">
                  <thead>
                    <tr>
                      {(['name', 'location', 'node', 'health', 'state', 'fps', 'age', 'reconnects', 'skip', 'stream'] as const)
                        .map((c) => <th key={c}>{t(`mon.col.${c}`)}</th>)}
                    </tr>
                  </thead>
                  <tbody>
                    {cams.map((c) => (
                      <tr key={c.id} data-testid={`mon-cam-${c.id}`}>
                        <td>{c.name}</td>
                        <td>{c.location ?? '—'}</td>
                        <td>{c.node_name ?? '—'}</td>
                        <td>
                          <HealthTag h={c.health} />
                          {c.issues.map((i) => <span key={i} className="mon-issue">{t(issueKey(i))}</span>)}
                        </td>
                        <td>{c.ai ? t(stateKey(c.ai.state)) : '—'}</td>
                        <td>{c.ai ? `${fmt(c.ai.fps, '', 1)} / ${fmt(c.ai.target_fps, '', 1)}` : '—'}</td>
                        <td>{c.ai ? fmt(c.ai.last_frame_age_s, ' s', 1) : '—'}</td>
                        <td>{c.ai ? c.ai.reconnects_1h : '—'}</td>
                        <td>{c.ai ? fmt(c.ai.motion_skip_pct, ' %') : '—'}</td>
                        <td>{c.stream.registered == null ? '—' : t(c.stream.registered ? 'mon.stream.yes' : 'mon.stream.no')}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <section className="st-card">
            <h3 className="st-card__title">{t('mon.services')}</h3>
            <ul className="mon-services">
              {data.services.map((s) => (
                <li key={s.key} data-testid={`mon-svc-${s.key}`}>
                  <span>{t(serviceKey(s.key))}</span>
                  <HealthTag h={s.health} />
                  <span className="en-muted">{[s.detail, s.latency_ms != null ? `${s.latency_ms} ms` : null].filter(Boolean).join(' · ')}</span>
                </li>
              ))}
            </ul>
          </section>
        </>
      )}
    </div>
  )
}
```

Catatan: `t(\`mon.${k}\`)` dan `t(\`mon.col.${c}\`)` — cast `as TKey` bila TypeScript menolak template literal.

- [ ] **Step 5: Route, menu, gaya**

`main.tsx`: import `MonitoringPage from './features/monitoring/MonitoringPage'`; child AppShell
`{ path: 'monitoring', element: <MonitoringPage /> }`; `SEGMENT_TO_KEY` + `monitoring: 'nav.monitoring'`
(perluas union tipe kunci).

`AppShell.tsx`: import ikon `Activity` dari `@carbon/icons-react`; grup `nav.group.system` menjadi
`items: [{ to: '/monitoring', key: 'nav.monitoring', icon: Activity }, { to: '/configuration?tab=cameras', key: 'nav.configuration', icon: Settings, adminOnly: true }]`.

`theme.scss` (akhir file):

```scss
/* Monitoring Resource: ringkasan, kartu node, tabel kamera, layanan. */
.mon-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.mon-title {
  font-weight: 300;
}

.mon-summary {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 1px;
  background: var(--cds-border-subtle);
}

.mon-tile {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 16px;
  background: var(--cds-layer-01);
  border-inline-start: 4px solid transparent;

  strong {
    font-size: 28px;
    font-weight: 400;
  }

  small {
    color: var(--cds-text-secondary);
  }

  &--ok { border-inline-start-color: #42be65; }
  &--warning { border-inline-start-color: #f1c21b; }
  &--critical { border-inline-start-color: #fa4d56; }
}

.mon-nodes {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 16px;
}

.mon-card__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: wrap;
}

.mon-kv {
  display: grid;
  grid-template-columns: max-content 1fr;
  gap: 4px 12px;
  margin-block: 8px;
  font-size: 13px;

  dt {
    color: var(--cds-text-secondary);
  }

  dd {
    overflow-wrap: anywhere;
  }
}

.mon-issues {
  margin: 8px 0 0;
  padding-inline-start: 16px;
  color: var(--cds-support-warning, #f1c21b);
  font-size: 13px;
  list-style: disc;
}

.mon-table-wrap {
  overflow-x: auto; // tabel lebar di 390 px: scroll di dalam kartu, halaman tidak overflow
}

.mon-table {
  inline-size: 100%;
  border-collapse: collapse;
  font-size: 13px;

  th,
  td {
    padding: 8px 12px;
    border-bottom: 1px solid var(--cds-border-subtle);
    text-align: start;
    white-space: nowrap;
  }

  th {
    color: var(--cds-text-secondary);
    font-weight: 600;
  }
}

.mon-issue {
  display: inline-block;
  margin-inline-start: 6px;
  color: var(--cds-text-secondary);
  font-size: 12px;
}

.mon-services {
  list-style: none;
  margin: 0;
  padding: 0;

  li {
    display: flex;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
    padding: 8px 0;
    border-bottom: 1px solid var(--cds-border-subtle);
  }
}
```

Run: `rtk bash -c "cd frontend && npx vitest run src/__tests__/monitoring.test.tsx src/__tests__/shell.test.tsx"` → PASS.

- [ ] **Step 6: Commit**

```bash
rtk git add frontend/src
rtk git commit -m "feat(monitoring): halaman System › Monitoring (kamera, node, server, layanan)"
```

---

### Task 6: Frontend — banner node offline + notifikasi pulih

**Files:**
- Create: `frontend/src/components/NodeOfflineBanner.tsx`
- Modify: `frontend/src/api/cameras.ts` (`CameraNode.last_seen`), `frontend/src/app/AppShell.tsx`,
  `frontend/src/features/live/LiveTvPage.tsx`, `frontend/src/app/i18n.tsx`, `frontend/src/app/theme.scss`
- Modify: `frontend/src/features/notifications/{labels.ts,EventAlertsProvider.tsx,NotificationBell.tsx,EventToasts.tsx}`
- Test: `frontend/src/__tests__/monitoring.test.tsx`, `frontend/src/__tests__/event-alerts.test.tsx`

**Interfaces:**
- Consumes: `GET /nodes` (`last_seen` dari Task 3), event `system` `reason: "online"` (Task 3).
- Produces: `NodeOfflineBanner({ tv?: boolean })` (test id `node-offline-banner`, polling `BANNER_POLL_MS = 15_000`);
  `labels.eventTitleKey(e: EventOut): TKey`, `labels.isNodeOnline(e: EventOut): boolean`.

- [ ] **Step 1: Tes (gagal)**

Di `monitoring.test.tsx`:

```tsx
import NodeOfflineBanner from '../components/NodeOfflineBanner'

test('banner node offline: tampil selama offline, hilang saat online', async () => {
  vi.useFakeTimers()
  let nodes = [{ id: 1, name: 'server', type: 'edge', status: 'offline', last_seen: '2026-09-29T07:05:00Z' }]
  vi.stubGlobal('fetch', vi.fn(async (url: string) => String(url).endsWith('/nodes')
    ? { ok: true, status: 200, json: () => Promise.resolve(nodes) }
    : { ok: false, status: 404, json: () => Promise.resolve(null) }))
  render(<I18nProvider><NodeOfflineBanner /></I18nProvider>)
  await act(async () => { await vi.advanceTimersByTimeAsync(0) })
  expect(screen.getByTestId('node-offline-banner')).toHaveTextContent('server')
  expect(screen.getByTestId('node-offline-banner')).toHaveTextContent('deteksi AI berhenti')
  nodes = [{ ...nodes[0], status: 'online' }]
  await act(async () => { await vi.advanceTimersByTimeAsync(15_000) })
  expect(screen.queryByTestId('node-offline-banner')).toBeNull()
})

test('banner: listNodes gagal → tanpa banner', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 500, json: () => Promise.resolve(null) })))
  render(<I18nProvider><NodeOfflineBanner /></I18nProvider>)
  await act(async () => {})
  expect(screen.queryByTestId('node-offline-banner')).toBeNull()
})
```

Di `event-alerts.test.tsx` (helper yang ada: `renderWith`, `send`, `ev`, `shell`, fixture LiveViewPage):

```tsx
test('event system reason online: label "pulih", menghapus chip offline node', async () => {
  renderWith(<><LiveViewPage />{shell}</>, '/live')
  expect(await screen.findByText('CAM-01')).toBeInTheDocument()
  await waitFor(() => expect(screen.getByTestId('recent')).toHaveTextContent('11,10'))
  send(ev(30, { type: 'system', camera_id: null, zone_id: null, severity: 'warning', payload: { node: 'vision-1', reason: 'lwt' } }))
  expect(screen.getByTestId('alert-chip-node')).toHaveTextContent('Node vision-1 offline')
  send(ev(31, { type: 'system', camera_id: null, zone_id: null, severity: 'info', payload: { node: 'vision-1', reason: 'online' } }))
  expect(screen.queryByTestId('alert-chip-node')).toBeNull()
  expect(screen.getByTestId('toast-31')).toHaveTextContent('Node pulih')
  expect(screen.getByTestId('toast-31')).toHaveTextContent('Node vision-1 pulih')
})
```

Run: `rtk bash -c "cd frontend && npx vitest run src/__tests__/monitoring.test.tsx src/__tests__/event-alerts.test.tsx"`
Expected: FAIL.

- [ ] **Step 2: Implementasi banner**

`api/cameras.ts`: `CameraNode` + `last_seen?: string | null`.

`frontend/src/components/NodeOfflineBanner.tsx`:

```tsx
import { useEffect, useState } from 'react'
import { InlineNotification } from '@carbon/react'
import { useT } from '../app/i18n'
import { listNodes, type CameraNode } from '../api/cameras'

export const BANNER_POLL_MS = 15_000

/** Banner persisten selama ada node vision offline (AppShell + mode TV). Gagal memuat → tanpa banner. */
export default function NodeOfflineBanner({ tv = false }: { tv?: boolean }) {
  const { t, locale } = useT()
  const [offline, setOffline] = useState<CameraNode[]>([])

  useEffect(() => {
    let alive = true
    const load = () => listNodes()
      .then((ns) => { if (alive) setOffline(ns.filter((n) => n.status === 'offline')) })
      .catch(() => { if (alive) setOffline([]) })
    load()
    const timer = setInterval(load, BANNER_POLL_MS)
    return () => { alive = false; clearInterval(timer) }
  }, [])

  if (offline.length === 0) return null
  return (
    <div className={tv ? 'node-banner node-banner--tv' : 'node-banner'} data-testid="node-offline-banner">
      {offline.map((n) => (
        <InlineNotification key={n.id} kind="error" hideCloseButton lowContrast={!tv}
          title={t('nodeBanner.title').replace('{node}', n.name)}
          subtitle={n.last_seen
            ? t('nodeBanner.since').replace('{time}', new Date(n.last_seen).toLocaleString(locale, { dateStyle: 'short', timeStyle: 'short' }))
            : t('nodeBanner.sub')} />
      ))}
    </div>
  )
}
```

i18n (id / en):
- `'nodeBanner.title'`: `'Node {node} offline — deteksi AI berhenti'` / `'Node {node} offline — AI detection stopped'`
- `'nodeBanner.since'`: `'Sejak {time}'` / `'Since {time}'`
- `'nodeBanner.sub'`: `'Periksa layanan vision di server'` / `'Check the vision service on the server'`
- `'notif.type.systemOnline'`: `'Node pulih'` / `'Node recovered'`
- `'notif.nodeOnline'`: `'Node {node} pulih'` / `'Node {node} recovered'`

`AppShell.tsx`: import banner; di `<main>` sebelum `{pwDone && ...}` render `<NodeOfflineBanner />`.
`LiveTvPage.tsx`: import banner; render `<NodeOfflineBanner tv />` tepat setelah blok toolbar (sebelum
`loadFailed`).

`theme.scss`:

```scss
/* Banner node offline: AppShell di atas konten; TV fixed di atas wall (di bawah toolbar z-index 10). */
.node-banner {
  margin-block-end: 16px;

  .cds--inline-notification {
    max-inline-size: none;
  }
}

.node-banner--tv {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  z-index: 9;
  margin: 0;
}
```

- [ ] **Step 3: Notifikasi mengenali event pulih**

`labels.ts`:

```ts
/** Event system "pulih" (node online kembali). */
export const isNodeOnline = (e: EventOut): boolean => e.type === 'system' && e.payload?.reason === 'online'

/** Judul event di lonceng/toast: system pulih punya label sendiri. */
export const eventTitleKey = (e: EventOut): TKey => (isNodeOnline(e) ? 'notif.type.systemOnline' : typeKey(e.type))
```

dan di `eventWhere`, baris system menjadi:

```ts
  if (e.type === 'system') {
    const node = String(e.payload?.node ?? '?')
    return t(isNodeOnline(e) ? 'notif.nodeOnline' : 'notif.nodeOffline').replace('{node}', node)
  }
```

`NotificationBell.tsx` & `EventToasts.tsx`: ganti `t(typeKey(e.type))` menjadi `t(eventTitleKey(e))` (import
`eventTitleKey`, hapus import `typeKey` bila tak terpakai).

`EventAlertsProvider.tsx` di `fire()` cabang system:

```ts
    if (e.type === 'system') {
      const node = String(e.payload?.node ?? '?')
      setNodes((prev) => [
        ...prev.filter((n) => n.node !== node),
        // pulih: chip offline node itu hilang; offline: chip 30 s
        ...(e.payload?.reason === 'online' ? [] : [{ eventId: e.id, node, until: now + ACTIVE_MS }]),
      ])
    }
```

Run: `rtk bash -c "cd frontend && npx vitest run"` → PASS semua.

- [ ] **Step 4: Commit**

```bash
rtk git add frontend/src
rtk git commit -m "feat(monitoring): banner node offline dan notifikasi node pulih"
```

---

### Task 7: Verifikasi penuh, dokumentasi, push

**Files:**
- Modify: `README.md`, `ROADMAP.md`, `CHANGELOG.md`, `docs/runbooks/` (baru `monitoring.md`)

- [ ] **Step 1: Suite penuh**

```bash
rtk bash -c "cd backend && .venv/bin/python -m pytest tests -q -m 'not gpu' > /tmp/be.log 2>&1; grep -oE '[0-9]+ (passed|failed)[^|]*' /tmp/be.log | tail -1"
rtk backend/.venv/bin/python -m pytest vision/tests -q -m "not gpu"
rtk bash -c "cd frontend && npx vitest run && npm run build && npm run lint"
```

Expected: backend > 491, vision > 223 (3 deselected), frontend > 203, build 0, lint tanpa error baru (set rule+file
sama selain warning `only-export-components` pada file yang meng-export konstanta, bila ada). Durasi suite backend
tidak naik berarti (monitor node di-nonaktifkan lewat fixture conftest).

- [ ] **Step 2: Cek visual**

`npm run dev` dengan stub API (atau backend lokal) → `/monitoring` di 1440 px dan 390 px: halaman tanpa overflow
horizontal (`document.documentElement.scrollWidth <= innerWidth`), tabel kamera scroll di dalam kartu; banner
node offline di AppShell dan `/live/tv`. Simpan screenshot `docs/evidence/2026-09-29-monitoring-*.png`. Matikan
server dev.

- [ ] **Step 3: Dokumentasi**

- `README.md`: bagian baru **Monitoring Resource** (isi halaman, sumber data heartbeat 10 s, aturan status ringkas,
  node offline/pulih → event + Telegram + banner, semua user bisa membuka).
- `docs/runbooks/monitoring.md`: arti tiap kode issue dan langkah cek (mis. `no_frames` → cek kamera/NVR & go2rtc;
  `not_running` → cek zona aktif/config push; `mqtt_backlog` → cek broker; node offline → `systemctl status
  isentinel-vision` / journal), serta catatan LWT retained.
- `ROADMAP.md`: baris **MO1** setelah `NT`:
  `| MO1 | Monitoring Resource S1 (kesehatan kamera/AI/hardware/layanan + node offline/pulih) | [ ] menunggu deploy + verifikasi user | — | spec + plan 2026-09-29; restart vision + API, tanpa migrasi | — |`
- `CHANGELOG.md`: entri teratas `### Monitoring Resource S1 (2026-09-29)` berisi konteks, perubahan (termasuk fix
  LWT retained dengan bukti 2 event palsu di server), file, bukti suite (angka nyata), dampak (heartbeat lebih besar,
  1 thread monitor, cek layanan di-cache 10 s), rollback.

- [ ] **Step 4: Commit + push (berhenti di sini)**

```bash
rtk git add README.md ROADMAP.md CHANGELOG.md docs/runbooks/monitoring.md docs/evidence
rtk git commit -m "docs(monitoring): README, runbook, ROADMAP, CHANGELOG Monitoring S1"
rtk git push -u origin feat/monitoring-s1
```

Deploy (restart vision + API), uji lapangan, dan merge dilakukan sesi perencana — **jangan** deploy atau merge.
