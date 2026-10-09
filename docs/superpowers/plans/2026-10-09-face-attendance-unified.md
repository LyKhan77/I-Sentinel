# Keselarasan Algoritma Absensi (Tahap 2) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mode absensi `unified` (saklar di UI, bawaan `legacy`) memakai algoritma identitas intrusion: gerbang relatif, K frame terbaik, jendela pendek, dan `match_strict`; replay offline tersedia untuk bukti sebelum saklar dibalik.

**Architecture:** `FaceSettings` membawa `attendance_mode` dan `attendance_window_s` dari baris `detector_setting` (config push). `FaceGateWorker` memilih jalur `unified` per frame; event membawa `payload.policy = "unified"`, dan API memilih `match_strict` berdasarkan payload itu, bukan berdasarkan baris DB (keputusan konsisten per event). Logika peringkat K terbaik diekstrak dari `IdentCollector` menjadi `BestK` yang dipakai bersama.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, Alembic, pydantic v2; Python vision node; React 19 + Carbon, Vitest.

**Spec:** `docs/superpowers/specs/2026-10-09-face-params-unify-design.md` (§5 tahap 2, §7 bukti; koreksi 2026-10-09 pada aturan pengiriman dan nilai awal jendela sudah ada di spec). Tahap 1 sudah live di `main` (`82036de`).

## Global Constraints

- Nilai awal persis: `face_attendance_mode` `legacy` (hanya `legacy` atau `unified`), `face_attendance_window_s` 1.5 (rentang 0.5–3.0).
- Mode `legacy` tidak boleh berubah perilaku: tes `vision/tests/test_face_worker.py` dan `backend/tests/test_attendance_*.py` lama lulus tanpa perubahan; payload dan `_funnel` legacy tetap persis (tes `test_funnel_counts_rejects_per_gate_code` mengunci kamus `rejects` lima kunci: kunci `pitch` hanya boleh muncul bila terjadi, lewat `.get`).
- Gerbang `unified` per wajah: di dalam poligon zona, lebar ≥ `ident.min_width_px`, skor ≥ `min_det_score`, yaw ≤ `max_yaw`, pitch ≤ `ident.max_pitch`; tanpa gerbang blur absolut dan tanpa gerbang `low_quality`. Peringkat kandidat `f.score × blur_score(aligned)`; embed hanya bila mengalahkan K terbaik (`ident.best_k`).
- Pengiriman `unified`: tepat sekali per track, ketika `attendance_window_s` berlalu sejak kandidat pertama (diperiksa pada tiap frame yang diproses) atau track hilang dengan ≥ 1 kandidat. **K kandidat terkumpul tidak memicu pengiriman.**
- Payload `unified`: `policy: "unified"`, `face_stats.frames` = jumlah kandidat tersimpan, `face_stats.collect_s` (kandidat pertama → kirim), `face_stats.zone_s` (wajah pertama di zona → kirim); embedding = `aggregate` berbobot kualitas. API menyimpan `payload.face_margin` bila ada.
- `ambiguous` diperlakukan seperti `no_match`: tanpa baris absensi, `match_reason = "ambiguous"`, snapshot berlabel "Unknown", UI menampilkannya sebagai tidak dikenal.
- Teks UI lewat `src/app/i18n.tsx` (`id` dan `en`), Carbon, 390 px tanpa overflow.
- Commit Conventional Commits berbahasa Indonesia, **tanpa atribusi AI** (AGENTS.md §9), commit tetap lokal. Suite berurutan, bukan paralel. Tanpa secret, IP, atau nama karyawan nyata.
- Executor tidak menyentuh server, tidak menjalankan skrip replay pada data nyata, dan berhenti di commit lokal + laporan.

## Review Focus

- Satu event per track: jendela habis lalu track hilang tidak boleh mengirim dua kali; track hilang sebelum jendela mengirim satu kali.
- Campuran versi: payload `unified` ke API tanpa tahap 2 tetap menghasilkan keputusan (legacy); payload tanpa `policy` ke API tahap 2 memakai `match_vector`; mode di DB tidak memengaruhi event yang sudah dikirim.
- Mengubah saklar atau jendela merestart worker wajah kamera terkait (perbandingan `FaceSettings`), bukan kamera tanpa worker wajah; track yang sedang dalam jendela saat itu hilang (diterima, dicatat di runbook).
- Wajah 60–79 px dan wajah buram (blur < 120) diterima di `unified` tetapi ditolak di `legacy` (tes pembeda).
- Hasil `ambiguous` tidak membuat baris absensi atau alert, dan label snapshot/Inbox/Live konsisten.

---

### Task 1: Kolom DB, API setelan, dan config push untuk mode absensi

**Files:**
- Create: `backend/alembic/versions/0025_face_attendance_mode.py`, `backend/tests/test_migration_0025.py`
- Modify: `backend/app/models/detector_setting.py`, `backend/app/schemas/detector_setting.py`, `backend/app/api/detector_settings.py`, `backend/app/core/config.py`, `backend/app/services/config_push.py`, `backend/tests/test_detector_settings_api.py`, `backend/tests/test_config_push.py`

**Interfaces:**
- Produces: kolom `DetectorSetting.face_attendance_mode` (String(16), NOT NULL, `server_default` `'legacy'`) dan `face_attendance_window_s` (Float, `server_default` 1.5); `Settings.face_attendance_mode = "legacy"`, `Settings.face_attendance_window_s = 1.5`; blok `cfg["face"]` mendapat `"attendance_mode"` dan `"attendance_window_s"`; skema PUT `face_attendance_mode: Literal["legacy", "unified"]`, `face_attendance_window_s: float = Field(ge=0.5, le=3.0)`.

- [ ] **Step 1: Tes (gagal dulu).** `test_migration_0025.py` meniru `test_migration_0024.py` (baris lama mendapat `legacy` dan 1.5, dua siklus, downgrade). `test_detector_settings_api.py`: perluas `VALUES`; GET tanpa baris → `legacy` dan 1.5; round-trip PUT/GET; `face_attendance_mode: "x"` → 422; jendela 0.4 dan 3.1 → 422 dan baris tak berubah; jendela 3.0 diterima. `test_config_push.py`: ubah kamus `face` yang diharapkan (tambah dua key) dan tambah tes baris dengan `unified` / 2.0.
- [ ] **Step 2: Implement** migrasi `0025` (`down_revision = "0024"`, `batch_alter_table` untuk downgrade), kolom model, field skema, `_effective()`, `Settings`, dan `build_node_config`.
- [ ] **Step 3:** `cd backend && .venv/bin/python -m pytest tests/test_migration_0025.py tests/test_detector_settings_api.py tests/test_config_push.py -q` → PASS.
- [ ] **Step 4: Commit** `feat(backend): kolom mode dan jendela absensi di detector_setting (0025)`.

### Task 2: `BestK` bersama dan `FaceSettings` mode absensi

**Files:**
- Modify: `vision/vision/face_quality.py`, `vision/vision/intrusion_face.py`, `vision/tests/test_face_quality.py`

**Interfaces:**
- Produces di `face_quality.py`: `class BestK` dengan `__init__(self, k: int)`, `beats(self, rank: float) -> bool` (True bila belum penuh atau `rank` **lebih besar** dari peringkat terendah), `add(self, rank: float, quality: float, vector: list[float]) -> None` (membuang peringkat terendah bila melebihi k), properti `items -> list[tuple[float, float, list[float]]]`, `__len__`; `FaceSettings.attendance_mode: str = "legacy"` dan `attendance_window_s: float = 1.5` dengan `from_config` (mode selain `legacy`/`unified` atau hilang → `legacy`).

- [ ] **Step 1: Tes (gagal dulu)** di `test_face_quality.py`: `BestK(2)`: tiga `add` dengan peringkat 3, 1, 2 menyisakan {3, 2}; `beats(2)` False saat penuh dan terendah 2 (sama tidak mengalahkan), `beats(2.1)` True; `beats` True saat belum penuh; `items` berisi tuple `(rank, quality, vector)`. `FaceSettings.from_config({"attendance_mode": "unified", "attendance_window_s": 2.5})`; mode `"x"` → `legacy`; tanpa key → nilai awal; `FaceSettings` dengan mode berbeda tidak sama (`!=`).
- [ ] **Step 2: Implement** `BestK` dan dua field `FaceSettings`; ganti `_IdentState.kept` (list) di `intrusion_face.py` dengan instance `BestK` (dibuat dengan `settings.ident.best_k` saat `_IdentState` dibuat) dan pakai `beats`/`add`/`items` di `_reject_or_keep` dan `_message`. **Refaktor murni:** seluruh `vision/tests/test_intrusion_face.py` dan `test_intrusion_face_workers.py` lulus tanpa diubah.
- [ ] **Step 3:** `cd vision && ../backend/.venv/bin/python -m pytest tests/test_face_quality.py tests/test_intrusion_face.py tests/test_intrusion_face_workers.py -q` → PASS.
- [ ] **Step 4: Commit** `refactor(vision): BestK bersama dan pengaturan mode absensi di FaceSettings`.

### Task 3: Jalur `unified` di `FaceGateWorker`

**Files:**
- Modify: `vision/vision/face_worker.py`, `vision/tests/test_face_worker.py`, `vision/tests/test_config_apply_per_camera.py`

**Interfaces:**
- Consumes: `BestK`, `FaceSettings.attendance_mode`, `.attendance_window_s`, `.ident` (Task 2); `pitch_dev` dari `intrusion_face.py`.
- Produces: `_TrackState` mendapat `keeper: BestK | None = None`, `first_ts: float | None = None`, `emit_ts: float = 0.0`, `unified: bool = False`; metode `_gate_unified(self, f, w: int, h: int) -> tuple[str | None, dict | None]` (kode gagal `zone|small|score|yaw|pitch` atau `None`, plus zona), `_accumulate_unified(self, tid, f, zone, aligned, q: float, blur: float, frame) -> None`, `_emit_due(self, now: float) -> None`.

- [ ] **Step 1: Tes (gagal dulu)** di `test_face_worker.py`, memakai `run_worker`, `face()`, `FakeFaces` yang ada dan `FaceSettings(attendance_mode="unified", attendance_window_s=...)`: (a) **tidak ada event sebelum jendela**: frame 10 fps, jendela 1.0, 15 frame lolos → event baru terbit pada frame ke-11 atau sesudahnya (≥ 1.0 dtk sejak kandidat pertama, tidak lebih awal), satu event, `payload.policy == "unified"`, `face_stats.frames <= best_k`, `collect_s >= 1.0`; (b) **track hilang sebelum jendela** (3 frame lalu kosong, jendela 3.0) → satu event; (c) **tepat sekali**: event tidak terbit dua kali saat jendela habis lalu track hilang; (d) **pembeda legacy/unified**: wajah 70 px dengan `aligned` buram (blur < 120) → `legacy` 0 event, `unified` 1 event; (e) wajah 50 px → `unified` 0 event dengan label `small`; wajah ber-pitch tinggi → label `pitch` dan `take_funnel()["rejects"]["pitch"] > 0`; di `legacy` kamus `rejects` tetap lima kunci; (f) **peringkat**: urutan wajah `[halus]*5 + [tajam]` (pakai `aligned` bergantian seperti pola `SequenceEmbedder` di `test_intrusion_face.py`) → embed dipanggil untuk frame tajam yang mengalahkan salah satu, `frames == best_k`. `test_config_apply_per_camera.py`: tiru `test_face_settings_change_restarts_only_cameras_with_a_face_worker` untuk perubahan `face.attendance_mode` dan `face.attendance_window_s`.
- [ ] **Step 2: Implement.** Di `_process` pilih jalur per frame dengan `self.settings.attendance_mode == "unified"`: gerbang via `gate_code(f, w, h, self.zones, replace(settings, min_width_px=ident.min_width_px, blur_min=0.0))` ditambah cek pitch; `align` + `blur_score` hanya sebagai peringkat; `self._funnel["rejects"][code] = self._funnel["rejects"].get(code, 0) + 1` (kunci baru hanya bila terjadi); kandidat lolos → `_accumulate_unified` (embed hanya bila `keeper.beats(rank)`, `first_ts` diisi pada kandidat pertama, `best` frame/crop dipilih berdasar `q` seperti legacy). Panggil `_emit_due(frame.ts)` setelah akumulasi di `_process` dan emisi track hilang di `_expire` untuk state `unified`. `_finalize_event` menambah `policy`, `collect_s`, `zone_s` hanya untuk state `unified`; embedding dari `aggregate(vectors, weights)` atas `keeper.items`. Jalur `legacy` tidak disentuh.
- [ ] **Step 3:** `cd vision && ../backend/.venv/bin/python -m pytest tests -q -m "not gpu"` → PASS (tes lama tanpa perubahan).
- [ ] **Step 4: Commit** `feat(vision): jalur absensi unified (gerbang relatif, K terbaik, jendela pendek)`.

### Task 4: Keputusan API untuk event `unified` dan tampilan `ambiguous`

**Files:**
- Modify: `backend/app/services/attendance.py`, `backend/tests/test_attendance_api.py`, `frontend/src/features/live/LiveWall.tsx`, `frontend/src/features/events/EventsPage.tsx`, `frontend/src/__tests__/liveview.test.tsx`, `frontend/src/__tests__/events.test.tsx`

**Interfaces:**
- Consumes: `face.match_strict(vector, quality=None, policy=None)`, `face_policy.load(db)`.

- [ ] **Step 1: Tes (gagal dulu)** di `test_attendance_api.py` (ikuti fixture berkas itu): (a) event `unified` dengan dua karyawan yang selisih top-1/top-2 < margin → `match_reason == "ambiguous"`, tanpa baris `AttendanceEvent`, `employee_id is None`; (b) event `unified` dengan skor di atas ambang dan margin cukup → tercatat, `payload.face_margin` terisi; (c) event `unified` dengan `face_quality = 0.1` tetap diputuskan (tanpa `low_quality`); (d) event tanpa `policy` memakai `match_vector` (perilaku lama, `low_quality` tetap berlaku); (e) mode di DB `legacy` tetapi payload `unified` → `match_strict`, dan sebaliknya (payload menentukan); (f) snapshot event `ambiguous` berlabel "Unknown" (pakai pola tes `annotate_event_snapshot` yang ada). Frontend: `liveview.test.tsx` dan `events.test.tsx` (tambahan saja): event `match_reason: 'ambiguous'` tampil sebagai tidak dikenal, sama seperti `no_match`.
- [ ] **Step 2: Implement** di `handle_face_event`: `unified = payload.get("policy") == "unified"`; bila embedding ada: `policy = face_policy.load(db)` lalu `face.match_strict(embedding, None, policy)` (unified) atau `face.match_vector(embedding, payload.get("face_quality"), policy)`; `payload["face_margin"] = round(res.margin, 3)` bila `res.margin is not None`; label Unknown untuk `no_match` **dan** `ambiguous` di `handle_face_event` serta `annotate_event_snapshot`. Frontend: tambah `|| match_reason === 'ambiguous'` pada kedua kondisi `no_match || low_quality` (`LiveWall.tsx` ±baris 344, `EventsPage.tsx` ±baris 259).
- [ ] **Step 3:** `cd backend && .venv/bin/python -m pytest tests/test_attendance_api.py tests/test_attendance_logic.py tests/test_events_consumer.py -q` lalu `cd frontend && env -u NODE_ENV npx vitest run src/__tests__/liveview.test.tsx src/__tests__/events.test.tsx` → PASS.
- [ ] **Step 4: Commit** `feat: keputusan absensi unified lewat match_strict dan hasil ambiguous`.

### Task 5: Saklar mode dan jendela di kartu "Pengenalan wajah"

**Files:**
- Modify: `frontend/src/api/detection.ts`, `frontend/src/features/config/DetectionPage.tsx`, `frontend/src/app/i18n.tsx`, `frontend/src/__tests__/detection.test.tsx`

**Interfaces:**
- Consumes: field REST `face_attendance_mode: 'legacy' | 'unified'` dan `face_attendance_window_s: number` (Task 1); komponen `InfoTip` dan pembungkus `TipField` yang ada.

- [ ] **Step 1: Tes (gagal dulu)** di `detection.test.tsx`: stub `settings` memuat dua field; grup baru "Mode absensi" tampil dengan `Toggle` `#face-attendance-mode` (mati bila `legacy`) dan `NumberInput` `#face-attendance-window` (`min` 0.5, `max` 3); menyalakan toggle lalu simpan → body PUT memuat `face_attendance_mode: "unified"` dan `face_attendance_window_s`; kedua kontrol punya ikon info (`Info: …`) dengan penjelasan; label `en` tersedia. Perbarui hanya entri TIPS milik tes sendiri yang teksnya berubah di Step 2.
- [ ] **Step 2: Implement.** Tipe `DetectorSettings` + dua field; grup **Mode absensi** (sebelum "Absensi (lama)") berisi `Toggle` ("Algoritma absensi baru (unified)") dan jendela; `save()` mengirim keduanya. Kunci i18n `id`/`en` untuk label, judul grup, dan tooltip; perbarui tooltip yang dulu "Hanya identitas" (lebar identitas, pitch, K, margin, judul grup Identitas) menjadi "identitas; absensi bila mode absensi baru menyala", dan tooltip grup "Absensi (lama)" menyebut hanya berlaku di mode lama. Tooltip jendela absensi: arti, nilai awal 1,5 dtk, naik = lebih banyak frame tetapi event lebih lambat.
- [ ] **Step 3:** `cd frontend && env -u NODE_ENV npx vitest run src/__tests__/detection.test.tsx` lalu `npx vitest run`, `npm run lint`, `npm run build` → PASS. Verifikasi tampilan 390 px dan 1280 px (screenshot ke `docs/evidence/`, gitignored): tanpa overflow horizontal, tooltip di dalam layar.
- [ ] **Step 4: Commit** `feat(frontend): saklar mode absensi dan jendela di kartu Pengenalan wajah`.

### Task 6: Skrip replay offline

**Files:**
- Create: `backend/scripts/face_replay.py`, `backend/tests/test_face_replay.py`

**Interfaces:**
- Produces di `face_replay.py` (fungsi murni, tanpa GPU): `classify(legacy_employee_id: int | None, strict: MatchResult) -> str` dengan hasil `same|flipped|lost|ambiguous|gained|both_none` (`legacy` dikenali & `strict` karyawan sama = `same`, karyawan lain = `flipped`, `strict.reason == "ambiguous"` = `ambiguous`, `strict` tak cocok = `lost`; `legacy` tak dikenali & `strict` cocok = `gained`, selain itu `both_none`); `summarize(rows: list[dict]) -> dict` (hitungan per kategori, `same_pct` atas event yang dikenali legacy, daftar `event_id` untuk `flipped`, `ambiguous`, dan `gained`); `main(argv)` dengan `--days` (bawaan 14), `--limit` (bawaan 200), `--sleep` (bawaan 0.2 dtk) yang membaca event absensi ber-`crop_path`, meng-embed crop lewat `face.engine`, memanggil `face.match_strict(vector, None, face_policy.load(db))`, dan mencetak ringkasan (ID event dan ID karyawan saja; tanpa nama, tanpa embedding). Mengatur `OMP_NUM_THREADS=2` sebelum memuat model.

- [ ] **Step 1: Tes (gagal dulu)** `test_face_replay.py` (ikuti cara `test_camera_management_migrate.py` memuat skrip): `classify` untuk keenam kategori dengan `MatchResult` nyata; `summarize` menghitung `same_pct` benar (mis. 3 `same`, 1 `flipped`, 1 `lost` → 60.0) dan tidak membagi nol saat tidak ada event dikenali legacy; `main` dengan embedder dan gallery palsu (monkeypatch) pada DB SQLite berisi dua event memberi ringkasan yang diharapkan dan tidak mencetak embedding.
- [ ] **Step 2: Implement** skrip; docstring teratas menyebut cara menjalankan di container `api` dengan `nice -n 19 taskset -c 0-3` dan bahwa pengguna harus diberi tahu dulu.
- [ ] **Step 3:** `cd backend && .venv/bin/python -m pytest tests/test_face_replay.py -q` → PASS.
- [ ] **Step 4: Commit** `feat(backend): skrip replay offline untuk membandingkan keputusan legacy dan strict`.

### Task 7: Dokumen, runbook, dan suite penuh

**Files:**
- Modify: `docs/runbooks/attendance.md`, `ARCHITECTURE.md`, `WORKFLOW.md` (§12), `README.md`, `ROADMAP.md`, `CHANGELOG.md`

- [ ] **Step 1: Runbook `attendance.md`** bagian baru "Mode absensi unified": (a) arti mode dan jendela, (b) cara menjalankan replay (perintah, batas CPU, syarat lolos spec §7.1: ≥ 98% `same`, 0 `flipped`, daftar `ambiguous` dan `gained` dinilai manual), (c) protokol uji lapangan kategori A–D dan kriteria spec §7.2, (d) query ukur kecepatan dan hasil (persentil `payload->'face_stats'->>'zone_s'`, hitungan `match_reason`, margin) dengan catatan "belum divalidasi di Postgres; sesi perencanaan memvalidasi di server", (e) cara membalik saklar dan rollback (toggle ke lama, instan, tanpa deploy), (f) catatan bahwa track yang sedang dalam jendela hilang saat saklar dibalik.
- [ ] **Step 2: Dokumen lain:** `ARCHITECTURE.md` (blok `face` baru, `payload.policy`, keputusan API per payload), `WORKFLOW.md` §12 (dua jalur absensi), `README.md`, `ROADMAP.md` (baris `FPU`: kode tahap 2 selesai di branch, saklar `legacy`, bukti replay dan lapangan menunggu), `CHANGELOG.md` (konteks, berkas, bukti, dampak, rollback).
- [ ] **Step 3: Suite penuh berurutan** dan tempel hasilnya ke `CHANGELOG.md`: backend `-m "not gpu and not llm"`, vision `-m "not gpu"`, `pytest docker/tests -q`, `npx vitest run`, `npm run build`, `npm run lint` (bandingkan pasangan file-rule dengan `temp/logs/face-params-unify/baseline-lint.txt`).
- [ ] **Step 4: Commit** `docs: mode absensi unified, runbook replay dan uji lapangan`, lalu berhenti dan serahkan laporan (tanpa push).
