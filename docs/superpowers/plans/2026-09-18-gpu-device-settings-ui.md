# UI Settings: GPU device delegasi per node (config push)

Status: MENUNGGU — kerjakan setelah `feat/gpu-hardware-probe` di-merge.
Tanggal: 2026-09-18. Keputusan user: opsi B, task terpisah (chat 2026-09-18).

## Tujuan

Admin memilih GPU index untuk detektor **per node via UI** (tab Nodes di
Configuration) — tanpa SSH/restart. Pin terkirim via config push MQTT yang
sudah ada; node hot-reload.

## Desain (disepakati via diskusi)

- UI: tab **Nodes** baru di `ConfigurationPage` (sisi tabs cameras/zones/
  gates/storage). Pilih node → dropdown GPU dari **heartbeat `node.hw`**
  (data real per node) + opsi "Auto".
- Backend: kolom `node.detector_device` (string nullable, migration 0010);
  `build_node_config()` sertakan `detector.device`; API GET/PUT nodes.
- Prioritas sumber device: **DB (config push) > env `VISION_DETECTOR_DEVICE`
  > auto**. Env = bootstrap node baru.
- Fail-fast tetap berlaku dua lapis:
  - start: pin invalid → log ERROR + exit (sudah ada, `validate_device_pin`).
  - hot-reload (`apply_config`): pin baru invalid → **reject config, node
    tetap hidup dengan device lama**, log ERROR (bukan exit — worker jangan
    mati karena salah pilih dropdown).
- Node `apply_config()` membaca `device` dari config push; `PersonDetector`
  sudah terima `device` param (branch feat/gpu-hardware-probe).
- Edge Jetson (Fase E): dropdown tetap bekerja (1 GPU, default auto) —
  tanpa kode cabang; config push sudah per-node keyed by name.

## Perubahan (estimasi)

1. Backend: migration 0010 + model + `build_node_config` + nodes API
   GET/PUT `detector_device` + validasi (cuda:N hanya; kosong = auto).
2. Vision: `apply_config` baca `cfg_dict["detector"]["device"]`, validasi
   via `hardware.validate_device_pin`, reject-and-keep bila invalid.
3. Frontend: tab Nodes — daftar node, dropdown device (dari `hw.gpus`),
   simpan → config push; badge Dashboard sudah ada (menampilkan hasil).
4. Test: backend (build config berisi device; API round-trip), vision
   (apply_config device valid/invalid), vitest (tab render + simpan).

## Verifikasi

pytest backend + vision (not gpu), vitest, build, live: pilih cuda:N di UI →
heartbeat `modules.detector.device` berubah tanpa restart; pilih cuda:999 →
node reject + log ERROR + tetap jalan.

## Rollback

git revert + alembic downgrade (drop kolom) — expand-only.
