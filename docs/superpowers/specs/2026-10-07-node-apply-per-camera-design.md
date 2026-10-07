# Spec — Node menerapkan config per kamera (tanpa restart semua worker)

Status: **Draft, ruang lingkup disetujui di chat 2026-10-07**, menunggu review spec tertulis.
Branch: `feat/node-apply-per-camera` (dari `main` @ `a6b549e`).
Konteks: `ARCHITECTURE.md` §3 (node vision), `docs/superpowers/specs/2026-10-07-face-gate-refine-design.md` (temuan awal).

---

## 1. Latar

Pada uji lapangan face gate refine (2026-10-07), mengubah satu kolom AI FPS membuat worker di semua kamera
`starting`/`reconnecting` selama 30–40 detik; log `vision` mencatat 9 kali `started 5 worker(s) for 9 camera(s)`
dalam 20 menit. Penyebabnya bukan kolom FPS saja: **setiap** config push (zona, kamera, shift, detector settings,
sumber stream, profil kredensial) memulai ulang **semua** worker di node. Selama itu deteksi intrusion dan wajah di
kamera yang tidak diubah ikut terputus, clip yang sedang direkam terpotong, dan engine detector dimuat ulang per worker.

Keputusan user: restart **per kamera** (worker detect dan face kamera itu bersama), cakupan hanya diff per kamera dan
coalescing antrean. Pembaruan analyzer di tempat (tanpa restart sama sekali) ditunda.

## 2. Temuan kode

| # | Temuan | Lokasi | Dampak |
|---|---|---|---|
| 1 | `apply_config` selalu memanggil `_start_workers`, yang membuka dengan `_stop_workers()` untuk semua worker | `vision/vision/node.py:339-398` | Satu kamera berubah, semua kamera restart |
| 2 | Tiap `CameraWorker` memanggil `detector_factory(cam_id)` di `run()`, jadi engine dimuat ulang tiap restart | `node.py:130-132` | Restart semua kamera = muat N engine; restart satu kamera = satu engine |
| 3 | `Recorder.close()` menghentikan thread dan memotong clip yang sedang berjalan (`tick(force=True)`) | `vision/vision/recorder.py:339-347` | Restart memotong insiden aktif; per kamera membatasinya ke kamera yang berubah |
| 4 | Worker detect dan face satu kamera berbagi satu `Recorder` (dan `ClipRing`) | `node.py:405-431` | Granularitas aman = per kamera |
| 5 | `run()` mengambil satu pesan config per putaran tanpa menggabungkan | `node.py:466-474` | Beberapa push beruntun = beberapa restart berurutan |
| 6 | Backend selalu mengirim snapshot penuh node (retained, QoS 1), deterministik tanpa timestamp; zona diurutkan `id` | `backend/app/services/config_push.py:29-110` | Dua config yang sama persis dapat dibandingkan; snapshot terakhir cukup |
| 7 | `CameraCfg` (pydantic) memuat `source_url`, `ai_fps`, `confidence`, `motion`, `meters_per_pixel`, `zones`; kesetaraan membandingkan zona secara dalam | `vision/vision/config.py:9-17` | `cam_baru != cam_lama` cukup sebagai deteksi perubahan |
| 8 | Pengaturan yang dipakai semua worker: `_detector_settings` (model, nms, conf, imgsz), `cfg.detector_device`, embedder face (`face_device`); `FaceSettings` dibaca saat worker face dibuat | `node.py:339-394` | Perubahannya tetap restart penuh (atau restart worker face saja untuk `FaceSettings`) |
| 9 | Heartbeat membaca `list(self._workers)` dan menghitung delta per `(camera_id, kind)`; counter yang turun diperlakukan sebagai restart | `node.py:486-510` | Tidak perlu diubah |
| 10 | Tes memakai `node._workers` langsung (diisi dan dibandingkan) dan mengganti `node.apply_config` dengan spy | `vision/tests/test_node.py`, `test_config_apply.py` | `_workers` tetap daftar datar; `apply_config(cfg_dict)` tetap satu argumen |

## 3. Keputusan user

| Topik | Keputusan |
|---|---|
| Granularitas | Per kamera: worker detect dan face kamera itu dihentikan dan dimulai bersama dengan recorder-nya |
| Cakupan | Diff per kamera + coalescing antrean config; pembaruan analyzer di tempat ditunda |

## 4. Tujuan, kriteria sukses, non-tujuan

**Kriteria sukses** (tes node dengan source dan detector palsu):
1. Config yang sama dua kali: objek worker dan recorder sama dan masih hidup; tidak ada restart.
2. Ubah `zones`, `ai_fps`, `motion`, `confidence`, `source_url`, atau `meters_per_pixel` kamera A: hanya worker dan recorder A diganti; objek kamera B identik dan hidup.
3. Kamera dihapus dari config: workernya berhenti, kamera lain tidak tersentuh. Kamera baru: dimulai.
4. Setelan global berubah (model/nms/conf/imgsz detector, `device` detector, `device` face): semua worker diganti.
5. `FaceSettings` berubah: hanya kamera yang punya worker face diganti.
6. Beberapa config dalam antrean: hanya yang terakhir diterapkan (`apply_config` dipanggil sekali).
7. Satu kamera gagal dimulai: kamera lain yang berubah tetap dimulai; kamera yang gagal tidak dicatat sebagai diterapkan, sehingga dicoba lagi pada push berikutnya.
8. Galat tak terduga di logika diff: jatuh kembali ke restart penuh (perilaku sekarang).
9. Semua tes lama lulus tanpa perubahan; heartbeat dan monitoring tidak berubah.

**Non-tujuan:** perubahan backend atau kontrak MQTT; pembaruan analyzer di tempat; berbagi satu detector antar kamera (muat engine per worker tetap); granularitas per jenis worker; perubahan UI.

## 5. Desain

Semua perubahan di `vision/vision/node.py`.

**State baru pada `VisionNode`:**
- `_applied: dict[int, CameraCfg]` — config terakhir yang diterapkan per `camera_id` (termasuk kamera tanpa worker).
- `_global_sig: tuple | None` — `(tuple(sorted(_detector_settings.items())) atau None, cfg.detector_device, cfg.face_device)` saat terakhir diterapkan.
- `_face_settings` (sudah ada) dibandingkan dengan nilai sebelumnya (`FaceSettings` adalah dataclass beku).

**Fungsi:**
- `_start_camera(self, cam: CameraCfg) -> None` — isi loop per kamera di `_start_workers` (analyzer, gerbang wajah, `Recorder`/`ClipRing`, `CameraWorker`, `FaceGateWorker`); menambahkan worker ke `self._workers`. Perilaku identik dengan sekarang.
- `_start_workers(self, cameras)` — tetap restart penuh: `_stop_workers()`, lalu `_start_camera` untuk tiap kamera, mengisi `_applied`, log. Dipakai saat start awal, setelan global berubah, dan sebagai fallback.
- `_stop_workers(self, camera_ids: set[int] | None = None) -> list` — `None` = semua (perilaku lama). Dengan filter: pisahkan worker kamera itu dari `_workers` dengan menukar daftar secara atomik (heartbeat tetap melihat daftar konsisten), hentikan dan `join`, tutup recorder yang dipakai bersama (pengelompokan per `id(recorder)` yang sudah ada).
- `apply_config(self, cfg_dict)` — setelah blok detector/face yang ada, hitung `global_changed` (tanda tangan global berbeda, atau pertama kali) dan `face_settings_changed`. Bila `global_changed`: `_start_workers(cameras)`. Selain itu:
  1. `changed` = kamera dengan `_applied.get(id) != cam`; `removed` = id di `_applied` yang tidak ada lagi.
  2. Bila `face_settings_changed`: tambahkan semua kamera yang saat ini punya `FaceGateWorker` ke `changed`.
  3. `_stop_workers(changed ∪ removed)`, lalu `_start_camera` untuk tiap `changed` yang masih ada, masing-masing dibungkus `try/except` (log `exception`); yang sukses dicatat di `_applied`, yang gagal dikeluarkan dari `_applied`.
  4. Seluruh blok dibungkus `try/except`: galat tak terduga → log dan `_start_workers(cameras)`.
  5. Bersihkan `_camera_conf` untuk kamera yang dihapus.
  6. Log satu baris: `config applied: restarted [..], added [..], removed [..], unchanged N`.
- `run()` — setelah `get(timeout=0.2)` berhasil, kuras antrean dengan `get_nowait()` dan pakai pesan terakhir. Aman karena tiap pesan adalah snapshot penuh.

**Tidak berubah:** backend, kontrak MQTT, `_camera_stats`, heartbeat, `self.events`, dan tanda tangan publik (`apply_config(cfg_dict)`, `_workers` sebagai daftar datar).

## 6. Tes

`vision/tests/test_config_apply.py` (tambah; tes lama tidak diubah): satu tes per kriteria 1–8 di atas memakai `FrameSource.from_frames`, detector skrip, dan `FakeTransport` yang sudah ada. Pegang referensi objek worker dan recorder sebelum/sesudah `apply_config` dan bandingkan identitasnya. Kriteria 9: jalankan seluruh suite vision.

## 7. Dokumen

`ARCHITECTURE.md` §3 (hot-reload per kamera dan kapan restart penuh), `WORKFLOW.md` baris 79 dan 92 (node memulai ulang hanya kamera yang berubah), `docs/RUNBOOK.md` baris 76 dan 83 (hot-reload tanpa restart, kecuali setelan global), `CHANGELOG.md` per commit, dan `ROADMAP.md` (baris siklus). Tidak ada perubahan `AGENTS.md`.

## 8. Risiko dan rollback

| Risiko | Mitigasi |
|---|---|
| Kamera "tidak berubah" ternyata bergantung pada setelan global yang terlewat dari tanda tangan | Daftar setelan global dikunci di §5; fallback restart penuh; tes kriteria 4 dan 5 |
| Recorder bersama tertutup sebelum kedua worker kamera berhenti | Kedua worker kamera selalu dihentikan bersama; tes memeriksa recorder kamera B tidak ditutup |
| State `_applied` melenceng dari worker nyata setelah kegagalan sebagian | Kamera gagal dikeluarkan dari `_applied` (dicoba lagi pada push berikutnya); fallback penuh pada galat tak terduga |
| Dua push hampir bersamaan tertukar | Snapshot terakhir menang; push terakhir juga yang paling baru |

Rollback: revert commit dan rebuild `vision`; tanpa migrasi, tanpa perubahan backend.
Verifikasi di server (di luar tes): edit zona atau FPS satu kamera, lalu pantau bahwa worker kamera lain tetap
`streaming`, `frames`-nya tidak mereset, dan `reconnects_1h` tidak naik; log menampilkan baris `config applied`.

## 9. Keputusan yang saya ambil sendiri (koreksi saat review)

- Tanda tangan global **tidak** memuat `motion` atau `confidence` default: keduanya sudah ada di `CameraCfg` per kamera dan dideteksi oleh diff.
- `FaceSettings` yang berubah memulai ulang kamera dengan worker face (granularitas per kamera, bukan hanya worker face), mengikuti keputusan per kamera.
- Kamera yang gagal dimulai dikeluarkan dari `_applied`, bukan dicoba ulang dengan timer; pembaruan config berikutnya yang memicu percobaan ulang.
