# GPU Hardware Probe per Node (+ Task 9: detector device pin)

Status: MENUNGGU VALIDASI USER
Tanggal: 2026-09-17
Desain disetujui user di chat (multi-GPU + per-process attribution + fail-fast pin).

## Latar belakang

- Heartbeat vision-node mengirim `{ts, cpu_percent, gpu_mem: None, cameras}` —
  `gpu_mem` placeholder kosong sejak Fase 1; backend consumer buang isi payload
  (hanya set status/last_seen).
- Server bersama: GPU0 dipakai OCR stack + proses lain (vLLM 11.4+5.4 GB,
  isaacsim 3 GB); GPU 1–2 (5080) bebas pasca llama pindah. Admin butuh melihat
  GPU mana aman, dan memastikan detektor tidak menyentuh GPU milik project lain.
- Task 9 (plan Fase 5) menambah `VISION_DETECTOR_DEVICE` — menjadi knob yang
  dilaporkan fitur ini.

## Tujuan

Node vision melaporkan hardware GPU + assignment modul via heartbeat; backend
menyimpan & menyajikan; UI menampilkan kartu per node dengan semua GPU +
proses pemakainya + badge pin detektor.

## Perubahan

### 1. Vision — `vision/vision/node.py` + `vision/vision/hardware.py` (baru)
- `_heartbeat_loop`: kumpulkan hw via helper `collect_gpu_info()`:
  `{"gpus": [{"idx", "name", "vram_used_mb", "vram_total_mb", "util_pct",
  "processes": [{"pid", "name", "user", "mem_mb"}]}], "python_vram_mb"}`.
- Implementasi `hardware.py` dengan `pynvml` (dep baru `nvidia-ml-py`), graceful
  fallback `{}` bila pynvml/NVIDIA tidak ada (JVM edge/WSL) — heartbeat tetap jalan.
- `modules.detector`: `{"device", "model", "ms_per_frame"}` — device dari
  `settings.detector_device` ("" = auto → UI tampil badge warning).

### 2. Task 9 (gabung) — `vision/vision/config.py`, `pipeline/detector.py`, `node.py`
- `NodeSettings.detector_device: str = ""` (env `VISION_DETECTOR_DEVICE`).
- `PersonDetector.__init__(..., device="")`; `predict()` meneruskan `device`
  hanya bila set.
- **Fail-fast**: node menolak start bila pin tidak valid (device tidak ditemukan)
  — log ERROR + exit, bukan silent fallback ke GPU lain.

### 3. Backend — `backend/app/api/nodes.py`, `events_consumer.py`, model Node
- Migration `0009_node_hw_json`: kolom `node.hw` (JSON, nullable).
- Heartbeat consumer: simpan `payload["hw"]` + `payload["modules"]` ke node (jika ada).
- `GET /api/v1/nodes` mengembalikan `hw` + `modules`.
- Kompatibel: heartbeat lama tanpa hw → kolom tetap null, status tetap update.

### 4. Frontend — `DashboardPage.tsx` (kartu node)
- Daftar GPU per node: nama, VRAM used/total, util %, daftar proses pemakai.
- Badge detektor: `PINNED cuda:1` / `AUTO (tidak dipin)` peringatan kuning.
- i18n id+en; tanpa emoji, corner 0px, tema g100.

## Test

- vision: test heartbeat payload berisi hw (pynvml mock), test fail-fast device
  tidak valid, test test_detector.py (Task 9: device diteruskan / dikosongkan).
- backend: test heartbeat consumer menyimpan hw; test nodes API mengembalikan hw;
  heartbeat tanpa hw kompatibel.
- frontend: vitest kartu node render GPU + badge pin.
- Server (Playwright): kartu node tampil di dashboard dengan GPU 4090 + 2×5080
  dan daftar proses; screenshot `docs/evidence/`.

## Verifikasi

`pytest vision -q -m "not gpu"` + `pytest backend -q -m "not gpu"` + vitest +
`npm run build` + alembic upgrade head (server) + restart vision + Playwright.

## Rollback

`git revert` + `alembic downgrade 0008` (kolom hw drop — expand-only, aman).
