# Bukti Event System Permanen Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Event `system` menyimpan kurva metrik yang membuktikannya di `payload.evidence` saat dibuat, sehingga panel Bukti menggambar grafik tanpa bergantung pada retensi 7 hari `monitoring_sample`.

**Architecture:** Backend: `minute_samples` + pembangun bukti di `health_alerts` (firing/resolved) dan `node_health` (offline) + fakta `last_seen`/`down_s`. Frontend: `parseStored` + grafik dari bukti tersimpan di `systemEvidence`/`EvidencePanel`, jalur fetch lama tetap sebagai fallback.

**Tech Stack:** FastAPI + SQLAlchemy + pytest (SQLite uji); React 19 + TS + Carbon + Vitest/Testing Library.

**Spec:** `docs/superpowers/specs/2026-10-01-events-permanent-evidence-design.md` (P1 skema v1, P2 cakupan, P3 panel memakai bukti tersimpan, P4 batas 360 titik, P5 kegagalan tidak menggagalkan event).

## Global Constraints

- Branch `feat/events-permanent-evidence` (dari `main` @ `afd95ff`). **Sebelum mulai:** pastikan bagian 1 (`feat/events-list-url-paging`) sudah ter-merge ke `main`; jalankan `rtk git merge main` di branch ini. Bila `main` belum memuatnya, hentikan dan lapor.
- Jangan `push`, jangan merge ke `main`, jangan deploy, jangan ssh ke server.
- Commit Conventional Commits berbahasa Indonesia, satu per tugas, `git add` path spesifik. **Tanpa** `Co-Authored-By` atau atribusi AI apa pun (AGENTS.md §9).
- Frontend: Carbon + kelas SCSS di `theme.scss` bila perlu, **tanpa** `style={{}}` dan hex di TSX. String lewat `src/app/i18n.tsx` (id **dan** en, paritas).
- Lint: jangan `setState` sinkron di badan `useEffect`; jangan `Date.now()` di badan render; jangan baca/tulis `ref` di badan render. Dependensi efek primitif.
- Backend: tanpa migrasi; perilaku event lama tidak berubah; pembangunan bukti dibungkus `try/except` (log, bukan raise).
- Jalankan pytest dan vitest **berurutan, tidak bersamaan**.
- Uji tidak boleh mengunci detail implementasi: assert perilaku yang terlihat.

## Review Focus

1. Kegagalan membangun bukti (query error, data aneh) tidak boleh mencegah event dibuat atau transisi alert tersimpan → Task 1 dan Task 2.
2. Panjang seri tepat dan batas 360 titik; `from` = awal menit pertama; menit tanpa sampel = `null`; nilai `camera_low_fps` dalam persen → Task 1.
3. Payload `evidence` rusak/versi lain tidak merusak panel: jatuh ke jalur lama (termasuk kedaluwarsa 7 hari) → Task 3 dan Task 4.
4. Event berumur > 7 hari dengan bukti tersimpan tetap menggambar grafik tanpa request history → Task 4.
5. Event lama (tanpa `evidence`) berperilaku persis seperti sekarang → Task 3 dan Task 4.

---

### Task 1: Backend — `minute_samples` dan bukti event health

**Files:**
- Modify: `backend/app/services/monitoring_history.py` (`minute_samples`), `backend/app/services/health_alerts.py` (`_evidence`, pemakaian di `evaluate`)
- Test: `backend/tests/test_monitoring_history.py`, `backend/tests/test_health_alerts.py`

**Interfaces:**
- Produces: `monitoring_history.minute_samples(db, node_id: int, start: datetime, end: datetime) -> dict[datetime, dict]` (baris `monitoring_sample` dengan `start <= ts < end`; kunci = awal menit UTC aware; nilai = `_dict(data)`).
- Produces: `health_alerts._evidence(db, node_id: int, rule: str, key: str, threshold: float, start: datetime, end: datetime) -> dict` mengembalikan `{"v": 1, "from": <ISO Z awal menit pertama>, "step_s": 60, "series": {"value": [<float 1 desimal | None> per menit di [start, end)]}}` dengan nilai dari `_check(rule, data_menit, key, threshold)[1]`; panjang seri ≤ 360 (bila lebih, ambil 360 menit terakhir dan sesuaikan `from`).
- Payload event `firing` dan `resolved` (bukan `closed`) memuat `evidence`: firing `start = cur − (duration_min + 30) menit`; resolved `start = max(started_at − 15 menit, cur − 360 menit)`; keduanya `end = cur`. Kegagalan `_evidence` → event tetap dibuat tanpa `evidence` dan satu log `logger.exception`. **Urutan:** bukti dihitung **sebelum** mutasi DB pada cabang itu (firing: sebelum `db.add(a)`; resolved: sebelum `update({"resolved_at": …})`); pada exception panggil `db.rollback()` lalu lanjut tanpa bukti (aman karena belum ada tulisan tertunda; di Postgres transaksi yang gagal harus di-rollback).

- [ ] **Step 1: Baseline** — dari `backend/`: `.venv/bin/python -m pytest tests -q -m "not gpu"` → catat jumlah (angka terakhir yang diketahui: 637 sebelum bagian 1; ukur sendiri setelah `merge main`).
- [ ] **Step 2: Uji gagal.** `test_monitoring_history.py`: `test_minute_samples_returns_only_window_with_minute_keys` (tiga sampel: sebelum, di dalam, tepat di `end` → hanya yang di dalam; kunci `tzinfo` UTC dan `second == 0`). `test_health_alerts.py` (pakai `_node`, `_samples`, `sent`, `_health_events`, `NOW`, `MIN` yang ada; payload event dari `_health_events(db)[i].payload`): `test_firing_event_carries_evidence_series` (rule `gpu_temp` seperti `test_gpu_temp_fires_after_full_window…`: `evidence.v == 1`, `step_s == 60`, `from` = `cur − (duration_min + 30)` menit dalam format `…Z`, panjang `series.value == duration_min + 30`, elemen untuk menit tanpa sampel `None`, elemen terakhir = suhu sampel terakhir); `test_low_fps_evidence_is_percent_of_target` (nilai seri dalam persen, bukan FPS mentah); `test_resolved_event_evidence_starts_before_alert_start` (`from` = `started_at − 15` menit, seri berakhir tepat sebelum `cur`); `test_resolved_evidence_is_capped_at_360_points` (alert dimulai 10 jam lalu → panjang 360 dan `from = cur − 360` menit); `test_closed_event_has_no_evidence`; `test_evidence_failure_does_not_block_the_event` (`monkeypatch.setattr(ha, "_evidence", boom)` → event `firing` tetap ada, payload tanpa kunci `evidence`, `HealthAlert` tersimpan). Jalankan `-k "minute_samples or evidence"` → **FAIL**.
- [ ] **Step 3: Implementasi** `minute_samples`, `_evidence`, dan penyisipan `extra={"evidence": …}` pada pemanggilan `payload(...)` firing/resolved dengan pembungkus `try/except` (log).
- [ ] **Step 4: Jalankan** `pytest tests -q -m "not gpu"` → semua lulus (baseline + jumlah uji baru); uji health lama tidak berubah.
- [ ] **Step 5: Commit**

```bash
git add backend/app/services/monitoring_history.py backend/app/services/health_alerts.py backend/tests/test_monitoring_history.py backend/tests/test_health_alerts.py
git commit -m "feat(health): event health menyimpan kurva metrik di payload.evidence"
```

---

### Task 2: Backend — bukti event node (offline/pulih)

**Files:**
- Modify: `backend/app/services/node_health.py` (`_emit`, `mark_offline`, `mark_online`)
- Test: `backend/tests/test_node_health.py`

**Interfaces:**
- Consumes: `monitoring_history.minute_samples` (Task 1).
- Produces: `_emit(db, node, severity, reason, now, extra: dict | None = None)` (payload = `{"node", "reason", **extra}`); `mark_offline` menambah `last_seen` (ISO Z dari `node.last_seen` bila ada) dan `evidence` skema §3.1 dengan seri `cpu_pct` dan `infer_fps` (nilai `data["cpu_pct"]["avg"]`, `data["infer_fps"]["avg"]` per menit, dibulatkan 1 desimal, `None` bila tak ada) untuk `[menit(now) − 30 menit, menit(now))`; bila tak satu pun sampel ada → tanpa `evidence` (tetap `last_seen`); `mark_online` menambah `down_s` = detik bulat `(now − since)` hanya bila `since` ada dan `now > since` (`since` naif dari SQLite → `_aware`). Kegagalan pembangunan bukti → event dibuat tanpa `evidence`, satu log; bukti node dibangun **sebelum** `node.status = "offline"` dan pada exception `db.rollback()` lalu lanjut.

- [ ] **Step 1: Uji gagal** (`test_node_health.py`; pakai `_node`, `_system`, `sent`, `T0`, `_send` yang ada; buat `MonitoringSample` untuk node dalam 30 menit sebelum `now` dengan `data={"cpu_pct": {"avg": 40.0}, "infer_fps": {"avg": 30.0}}`): `test_offline_event_carries_last_seen_and_cpu_fps_evidence` (payload `last_seen` = ISO Z `node.last_seen`; `evidence.series` punya `cpu_pct` dan `infer_fps` sepanjang 30; `from` = awal menit `now − 30 menit`); `test_offline_event_without_samples_has_last_seen_but_no_evidence`; `test_online_event_carries_down_s` (`mark_online(..., since=now − 5 menit)` → `down_s == 300`); `test_online_event_without_since_has_no_down_s`; `test_node_evidence_failure_does_not_block_the_event` (monkeypatch `minute_samples` melempar → event offline tetap dibuat, payload tanpa `evidence`). Jalankan `-k "evidence or down_s"` → **FAIL**.
- [ ] **Step 2: Implementasi** `_emit(..., extra)`, `mark_offline`, `mark_online`, helper pembangun bukti node (privat di modul), pembungkus `try/except` + log.
- [ ] **Step 3: Jalankan** `pytest tests -q -m "not gpu"` → lulus (uji node/health lama hijau).
- [ ] **Step 4: Commit**

```bash
git add backend/app/services/node_health.py backend/tests/test_node_health.py
git commit -m "feat(node): event offline menyimpan last_seen dan kurva CPU/FPS; event pulih mencatat down_s"
```

---

### Task 3: Frontend — bukti tersimpan di `systemEvidence`

**Files:**
- Modify: `frontend/src/features/events/systemEvidence.ts`, `frontend/src/app/i18n.tsx`
- Test: `frontend/src/__tests__/system-evidence.test.ts`

**Interfaces:**
- Produces:
  ```ts
  export type StoredEvidence = { fromMs: number; stepMs: number; series: Record<string, (number | null)[]> }
  export function parseStored(payload: Record<string, unknown> | null): StoredEvidence | null
  // ChartSeriesSpec gains: storedKey?: string
  // Evidence gains: stored: StoredEvidence | null
  ```
  `parseStored` valid bila `payload.evidence` objek dengan `v === 1`, `from` string yang terurai oleh `Date.parse`, `step_s` angka > 0, `series` objek (≥ 1 kunci) yang semua nilainya larik berisi hanya `number | null` (angka terbatas), total elemen ≤ 1000; selain itu `null`.
- Kunci i18n baru (id / en): `events.evidence.lastSeen` "Heartbeat terakhir" / "Last heartbeat"; `events.evidence.downFor` "Offline selama" / "Offline for"; `events.evidence.series.value` "Nilai" / "Value"; `events.evidence.chart.generic` "Metrik" / "Metric"; `events.evidence.hoursMinutes` "{h} jam {m} mnt" / "{h} h {m} min".

Keputusan: bila `stored` valid → `expired = false`; `window = { from: fromMs, to: fromMs + n·stepMs }` (n = panjang seri terpanjang); `charts`: health → satu `ChartSpec` (judul sesuai rule bila dikenal, selain itu `events.evidence.chart.generic`; `unit` dari `payload.unit`; `refLine` = `threshold`; satu seri `{ key: 'value', storedKey: 'value', labelKey: 'events.evidence.series.value', pick: () => [] }`); node → dua `ChartSpec` (`cpu_pct`, `infer_fps`) dengan `storedKey` sama dengan kuncinya; `nodeId` **tidak** diperlukan untuk grafik tersimpan. Tanpa `stored` → perilaku sekarang tidak berubah. Fakta tambahan: node offline dengan `last_seen` → "Heartbeat terakhir" (`new Date(last_seen).toLocaleString()`); node online dengan `down_s` (angka > 0) → "Offline selama" (`< 60` menit → `events.evidence.minutes`; ≥ 60 → `events.evidence.hoursMinutes`).

- [ ] **Step 1: Uji gagal** (`system-evidence.test.ts`; pakai `ev`, `t`, `NOW`): `parseStored` — payload valid → `{fromMs, stepMs: 60000, series}`; `v: 2`, `from` tak terurai, `step_s: 0`, seri bukan larik, elemen string, total > 1000, tanpa `evidence`, `payload` null → semua `null`. `systemEvidence` — event 10 hari dengan `evidence` valid: `expired === false`, `window` = `[from, from + n·60000]`, `charts.length === 1` dengan `refLine.v === threshold`, `stored` terisi, tetap tanpa `nodeId`; node offline + `evidence`: dua chart `cpu_pct`/`infer_fps`, fakta "Heartbeat terakhir"; node online + `down_s: 300` → "5 mnt", `down_s: 7500` → "2 jam 5 mnt"; rule tak dikenal + `evidence` → satu chart berjudul generik; `evidence` rusak pada event 10 hari → `expired === true` dan `stored === null` (jalur lama); event tanpa `evidence` → hasil sama seperti sebelum perubahan (uji lama hijau). Jalankan → **FAIL**.
- [ ] **Step 2: Implementasi** `parseStored`, perluasan `systemEvidence`/`ChartSeriesSpec`/`Evidence`, fakta tambahan, kunci i18n (id + en, paritas).
- [ ] **Step 3: Jalankan** `npx vitest run src/__tests__/system-evidence.test.ts` → PASS; `npm run build` → exit 0; `npm run lint` → pasangan tidak bertambah.
- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/events/systemEvidence.ts frontend/src/app/i18n.tsx frontend/src/__tests__/system-evidence.test.ts
git commit -m "feat(events): parse dan petakan bukti tersimpan (payload.evidence) di systemEvidence"
```

---

### Task 4: Frontend — `EvidencePanel` memakai bukti tersimpan

**Files:**
- Modify: `frontend/src/features/events/EvidencePanel.tsx`
- Test: `frontend/src/__tests__/system-evidence-panel.test.tsx`

**Interfaces:**
- Consumes: `Evidence.stored`, `ChartSeriesSpec.storedKey`, `StoredEvidence` (Task 3).

Keputusan: bila `ev.stored` → tidak ada `getMonitoringHistoryWindow`, tidak ada status loading; setiap `ChartSpec` digambar dengan seri yang titiknya `t = fromMs + i·stepMs`, nilai dari `stored.series[storedKey]` dengan `null` dilewati; `from`/`to` = `ev.window`; `markers` tetap satu penanda waktu event; tanpa `shaded`; bila semua seri kosong/`null` → catatan `events.evidence.noData`. Tanpa `stored` → jalur fetch/kedaluwarsa sekarang tidak berubah.

- [ ] **Step 1: Uji gagal** (`system-evidence-panel.test.tsx`; pakai `stubHistory`, `ev`, `renderPanel`, `NOW`): `'stored evidence draws charts without any history request'` (health `node_cpu` + `evidence`; `calls` kosong; `lc-line-value`, `lc-ref`, satu `lc-marker`); `'event older than 7 days with stored evidence still shows charts, not the expired note'`; `'nulls in the stored series create gaps'` (path memuat dua `M`); `'node offline stored evidence shows cpu and fps charts and the last-seen fact'`; `'stored evidence with only nulls shows the no-data note'`; `'malformed stored evidence falls back to the history fetch'` (`v: 2` → satu request history); `'event without evidence behaves as before'` (regresi: fetch + grafik). Jalankan → **FAIL**.
- [ ] **Step 2: Implementasi** cabang `ev.stored` di `EvidencePanel.tsx`.
- [ ] **Step 3: Jalankan** `npx vitest run src/__tests__/system-evidence-panel.test.tsx src/__tests__/events.test.tsx` → PASS; `npx vitest run` penuh → lulus; `npm run build` → exit 0; `npm run lint` → pasangan tidak bertambah.
- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/events/EvidencePanel.tsx frontend/src/__tests__/system-evidence-panel.test.tsx
git commit -m "feat(events): panel Bukti menggambar dari payload.evidence tanpa fetch dan tanpa batas 7 hari"
```

---

### Task 5: Smoke test dan dokumen

**Files:**
- Modify: `WORKFLOW.md` (§8, §14), `ARCHITECTURE.md` (skema `payload.evidence`), `docs/runbooks/monitoring.md`, `README.md` (bila relevan), `ROADMAP.md`, `CHANGELOG.md`

- [ ] **Step 1: S1 suite penuh** di commit terakhir, **berurutan**: backend `.venv/bin/python -m pytest tests -q -m "not gpu"`; frontend `npx vitest run`, `npm run build`, `npm run lint` (pasangan rule/file tidak bertambah).
- [ ] **Step 2: S2 penjaga statis:** `rtk git diff --stat main...HEAD` hanya menyentuh berkas pada daftar **Files** tiap task + dokumen Task 5 + spec/plan; `git grep -nE "style=\{\{|#[0-9a-fA-F]{6}" -- frontend/src/features/events` tidak menambah baris dibanding `main`; paritas kunci i18n id = en untuk kunci baru.
- [ ] **Step 3: S3 smoke render (tanpa screenshot):** `cd frontend && npm run dev`, Playwright MCP dengan mock `/api/v1/**` (sesi admin; `/events?` berisi event system dengan `payload.evidence` — health firing, health resolved, node offline — termasuk satu berumur 10 hari — dan satu tanpa `evidence`; `/monitoring/history?from=…` hanya untuk yang tanpa evidence). Di 1440 px dan 390 px: 0 error konsol; event berbukti tersimpan menampilkan grafik **tanpa** request ke `/monitoring/history` (cek log request mock); event 10 hari tetap menampilkan grafik; event tanpa `evidence` tetap lewat jalur lama (dan 10 hari → "Data tren hanya disimpan 7 hari"); node offline menampilkan "Heartbeat terakhir"; `scrollWidth <= innerWidth` di 390 px. Bila tak tersedia: tulis "S3 tidak dijalankan" beserta alasannya.
- [ ] **Step 4: Dokumen.** `WORKFLOW.md §8` dan `§14`: bukti event system kini permanen (disimpan saat event dibuat; event lama tetap lewat history 7 hari). `ARCHITECTURE.md`: skema `payload.evidence` v1 (health `value`; node `cpu_pct`/`infer_fps`), `last_seen`, `down_s`. `docs/runbooks/monitoring.md`: cara memeriksa `payload.evidence` dan kenapa event lama tidak punya. `ROADMAP.md`: satu baris **tanpa `[x]`**. `CHANGELOG.md`: entri dengan konteks, file, **evidence berisi keluaran nyata**, dampak (ukuran payload), rollback; catat uji UI user menyusul.
- [ ] **Step 5: Commit**

```bash
git add WORKFLOW.md ARCHITECTURE.md docs/runbooks/monitoring.md README.md ROADMAP.md CHANGELOG.md
git commit -m "docs: bukti event system permanen — WORKFLOW, ARCHITECTURE, runbook, ROADMAP, CHANGELOG"
```
