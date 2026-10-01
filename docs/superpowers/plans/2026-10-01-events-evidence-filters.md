# Events: Filter Konsisten + Bukti Event System — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Filter halaman Events konsisten (server-side, opsi "Semua", reset) dan event `system` menampilkan panel Bukti (fakta + grafik tren) menggantikan Snapshot/Clip.

**Architecture:** Backend: `GET /events` mendapat `severity`; `GET /monitoring/history` mendapat mode jendela `from`/`to`/`node_id` (bucket 60 dtk). Frontend: filter Events memanggil API per perubahan (respons basi dibuang); fungsi murni `systemEvidence` menurunkan fakta/jendela/grafik dari payload; `SystemEvidence` merender dengan `LineChart` (+ prop `markers`).

**Tech Stack:** FastAPI + SQLAlchemy + pytest (SQLite uji); React 19 + TS + Carbon + SCSS + Vitest/Testing Library.

**Spec:** `docs/superpowers/specs/2026-10-01-events-evidence-filters-design.md` (keputusan D1 filter server-side, D2 opsi Tipe statis, D3 opsi "Semua" + reset).

## Global Constraints

- Branch `feat/system-event-evidence` dari `main` @ `b8c54db`. Jangan `push`, jangan merge, jangan deploy, jangan ssh ke server.
- Commit Conventional Commits berbahasa Indonesia, satu per tugas, `git add` path spesifik. **Tanpa** `Co-Authored-By` atau atribusi AI apa pun (AGENTS.md §9).
- Frontend: komponen Carbon + kelas SCSS di `frontend/src/app/theme.scss` dengan token `var(--cds-*, <fallback>)`; **tanpa** `style={{}}` dan hex di TSX (di `features/events/**` yang baru/diubah). REST hanya lewat `src/api/*`. Semua string lewat `src/app/i18n.tsx` (id **dan** en). Nol overflow horizontal di 390 px.
- Lint: jangan `setState` sinkron di badan `useEffect` (`react/set-state-in-effect`); `setState` hanya di callback async/event. Jangan `Date.now()` di badan render (`react/purity`): pakai `useState(() => Date.now())`.
- Backend: logika di `app/services/`, router tipis, tanpa SQL baru di router; semua endpoint tetap `get_current_user`. Parameter baru opsional (kompatibel mundur).
- Status tidak boleh hanya warna. Sumber/grafik gagal menampilkan pesan, **bukan** angka palsu; fakta tetap tampil.
- Uji tidak boleh mengunci detail implementasi: assert perilaku yang terlihat.

## Review Focus

1. Respons lama tiba setelah respons baru saat filter berubah cepat tidak boleh menimpa daftar → Task 2.
2. "Semua" harus memulihkan hasil untuk **tiap** dropdown (Tipe, Kamera, Severity) dan tombol reset juga mengembalikan Rentang dan pencarian → Task 2.
3. Batas jendela: `to - from` tepat 6 jam diterima, 6 jam + 1 detik ditolak (422); event berumur tepat di ambang 7 hari dan jendela dipotong ≤ 6 jam → Task 3 dan Task 4.
4. Varian payload: health `closed`, `resolved` tanpa `lasted_min`, node `online`, field hilang, rule tak dikenal, `node_id` null/node terhapus → Task 4 dan Task 5.
5. Event live yang tak cocok filter aktif tidak boleh muncul; duplikat tidak boleh muncul → Task 2.

---

### Task 1: Backend — filter `severity` di `GET /events`

**Files:**
- Modify: `backend/app/api/events.py:93-106` (`list_events`)
- Test: `backend/tests/test_events_api.py`

**Interfaces:**
- Produces: `GET /api/v1/events?severity=<s>&severity=<s2>` (berulang, `Event.severity IN (...)`), dapat digabung dengan `type`, `camera_id`, `since`, `limit`.

- [ ] **Step 1: Baseline** — dari `backend/`: `.venv/bin/python -m pytest tests -q -m "not gpu"` → catat jumlah lulus (baseline repo: **622**).
- [ ] **Step 2: Uji gagal** `test_list_events_filter_severity` (pakai `client`, `_payload`, `_admin_headers`, `_ingest_headers`): kirim `critical`, `warning`, `info` (tipe `intrusion`) dan satu `loitering` `info`; assert `?severity=critical` → hanya critical; `?severity=critical&severity=warning` → dua event; `?type=intrusion&severity=info` → tepat satu; `?severity=foo` → `[]`. Jalankan `-k filter_severity` → **FAIL** (semua event kembali).
- [ ] **Step 3: Implementasi** `severity: list[str] | None = Query(None)` pada `list_events`; `if severity: q = q.filter(Event.severity.in_(severity))` (pola sama dengan `type`).
- [ ] **Step 4: Jalankan** `pytest tests -q -m "not gpu"` → lulus (baseline + 1).
- [ ] **Step 5: Commit**

```bash
git add backend/app/api/events.py backend/tests/test_events_api.py
git commit -m "feat(events): filter severity di GET /events"
```

---

### Task 2: Frontend — filter Events konsisten

**Files:**
- Create: `frontend/src/features/events/eventTypes.ts`
- Modify: `frontend/src/api/events.ts`, `frontend/src/features/events/EventsPage.tsx`, `frontend/src/app/i18n.tsx`, `frontend/src/app/theme.scss` (hanya bila tombol reset butuh jarak di `.ev-toolbar`)
- Test: `frontend/src/__tests__/events.test.tsx` (tambah)

**Interfaces:**
- Produces (`api/events.ts`): `EventListParams.severities?: string[]` (dikirim sebagai `severity` berulang); `EventOut.node_id?: number | null` (opsional agar fixture uji dan frame WS lama tetap valid secara tipe; backend selalu mengirimnya).
- Produces (`eventTypes.ts`): `EVENT_TYPES: readonly string[]` = `intrusion, loitering, running, idle_zone, crowd, attendance, person_detect, system`; `eventTypeLabel(type: string, t: (k: TKey) => string): string` (lima behavior → `zones.behavior.<type>`, selainnya `events.type.<type>`, tak dikenal → `type`).
- Kunci i18n baru (id / en): `events.type.attendance` "Absensi" / "Attendance"; `events.type.system` "Sistem" / "System"; `events.type.person_detect` "Deteksi orang (debug)" / "Person detection (debug)"; `events.filterReset` "Atur ulang filter" / "Reset filters"; `events.limitHint` "Menampilkan {n} event terbaru — persempit filter untuk melihat lebih banyak" / "Showing the latest {n} events — narrow the filters to see more".

Keputusan perilaku `EventsPage`:
- Item dropdown Tipe/Kamera/Severity = `[SEMUA, ...opsi]` (label `events.filterAll`); `selectedItem = filter ?? SEMUA`; memilih SEMUA → filter `null`. Opsi Tipe = `EVENT_TYPES` berlabel `eventTypeLabel`; opsi Severity = `critical|warning|info`.
- `refresh` memanggil `listEvents({ limit: 200, since, types, camera_id, severities })` dan dependensinya mencakup Rentang + ketiga filter; setiap panggilan diberi nomor (`useRef`) dan hasil yang bukan panggilan terbaru dibuang (termasuk status `loading`/`loadFailed`).
- `matches(e)` (tipe/kamera/severity) dipakai pada `filtered` **dan** pada event live (`useLiveEvents`): event tak cocok tidak ditambahkan. Pencarian teks tetap klien.
- Hitungan `data-testid="event-count"` = `${filtered.length}${events.length >= 200 ? '+' : ''} event`; saat `events.length >= 200` tampil `data-testid="event-limit-hint"` dari `events.limitHint` (`{n}` = 200).
- Tombol `data-testid="filter-reset"` (Carbon `Button kind="ghost"`) tampil bila Tipe/Kamera/Severity terisi, Rentang ≠ `all`, atau pencarian tidak kosong; klik → semuanya default.

- [ ] **Step 1: Baseline** — dari `frontend/`: `npx vitest run` (baseline repo: **30 files / 296 passed**), `npm run build`, `npm run lint` → catat jumlah baris warning (**24**) per pasangan (rule, file).
- [ ] **Step 2: Uji gagal** (tambah ke `events.test.tsx`; pakai `stubFetch`/`renderPage`, ambil URL daftar dari `fetchMock.mock.calls` seperti uji rentang; buka dropdown dengan `userEvent.click(screen.getByRole('combobox', { name: ... }))` lalu klik `role="option"`):
  - `'type dropdown sends type to the API and Semua restores the full list'`: pilih "Sistem" → URL terakhir memuat `type=system`; pilih "Semua" → URL terakhir tanpa `type=`.
  - `'camera and severity dropdowns also restore with Semua'`: pilih kamera lalu "Semua" (tanpa `camera_id=`), pilih `critical` lalu "Semua" (tanpa `severity=`).
  - `'severity and camera filters are sent to the API'`: URL memuat `severity=critical` dan `camera_id=1`.
  - `'type options are static, localized and independent of loaded events'`: dengan `EVENTS` bertipe `intrusi`/`loitering`, opsi "Sistem", "Absensi", dan label `zones.behavior.intrusion` tetap ada.
  - `'reset button is hidden by default and clears every filter, range and search'`: tidak ada `filter-reset` awalnya; setelah memilih tipe + rentang `24h` + mengetik pencarian, tombol ada; klik → ketiganya default (URL tanpa `type=`/`since=`, kolom pencarian kosong).
  - `'full page shows N+ and the limit hint'`: stub 200 event → `event-count` berisi "200+", `event-limit-hint` ada; stub 3 event → tak ada petunjuk dan tanpa "+".
  - `'live event that does not match the active filter is not prepended'`: aktifkan `severity=critical`, kirim event live `warning` lewat jalur `useLiveEvents` (ikuti uji `poll (5s) appends new event row realtime`) → baris tidak muncul; event `critical` muncul sekali (tanpa duplikat).
  - `'a stale response does not overwrite a newer one'`: respons pertama (tanpa filter) ditahan lewat promise manual; ubah filter, selesaikan respons kedua, lalu selesaikan respons pertama → daftar tetap hasil kedua.
  Jalankan `npx vitest run src/__tests__/events.test.tsx` → **FAIL** (opsi/tombol belum ada).
- [ ] **Step 3: Implementasi** `eventTypes.ts`, perubahan `api/events.ts`, `EventsPage.tsx`, kunci i18n (id + en, paritas).
- [ ] **Step 4: Jalankan** `npx vitest run src/__tests__/events.test.tsx` → PASS (uji lama tetap hijau); `npm run lint` → tanpa pasangan (rule, file) baru.
- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/events/eventTypes.ts frontend/src/api/events.ts frontend/src/features/events/EventsPage.tsx frontend/src/app/i18n.tsx frontend/src/app/theme.scss frontend/src/__tests__/events.test.tsx
git commit -m "feat(events): filter server-side, opsi Semua, reset, penanda 200+"
```

---

### Task 3: Backend — jendela waktu di `GET /monitoring/history`

**Files:**
- Modify: `backend/app/services/monitoring_history.py` (pecah `query`, tambah `query_window`), `backend/app/api/monitoring.py` (`get_history`)
- Test: `backend/tests/test_monitoring_history.py`

**Interfaces:**
- Produces: `query_window(db: Session, start: datetime, end: datetime, node_id: int | None = None) -> dict` — bentuk sama dengan `query`, `range: "custom"`, `bucket_s: 60`, `from`/`to` = `start`/`end` (format `Z`), `offline` = `_offline(db, node, start, end)`; `nodes` hanya node `node_id` bila diberikan. `query(db, range_key, now)` tidak berubah perilaku.
- Produces (endpoint): `GET /api/v1/monitoring/history?from=<iso>&to=<iso>[&node_id=<int>]`. Aturan: `range` dan `from`/`to` bersamaan → 422; hanya salah satu dari `from`/`to` → 422; `to <= from` → 422; `to - from > 6 jam` → 422 (tepat 6 jam diterima); naif = UTC; tanpa parameter → perilaku lama (`range` default `6h`, uji lama tetap hijau).

- [ ] **Step 1: Uji gagal** di `test_monitoring_history.py` (pakai fixture/helper penulis sampel yang dipakai uji endpoint yang ada):
  - `test_history_window_returns_only_samples_inside_at_60s_buckets`: tiga sampel (di dalam, tepat di awal, di luar) → hanya yang di dalam, `bucket_s == 60`, `range == "custom"`.
  - `test_history_window_node_id_filters_nodes`.
  - `test_history_window_validation`: `range=1h&from=..&to=..` → 422; `from` saja → 422; `to <= from` → 422; span 6 jam → 200; span 6 jam + 1 dtk → 422.
  - `test_history_window_offline_bounded_by_end`: event `timeout` di dalam jendela tanpa `online` → periode `{from, to: null}`; dengan `online` sebelum `to` → `to` terisi.
  - `test_history_window_outside_retention_is_empty_not_error`: jendela 30 hari lalu → 200 dengan seri kosong.
  - `test_history_window_requires_auth` → 401.
  Jalankan `-k history_window` → **FAIL**.
- [ ] **Step 2: Implementasi**: ekstrak badan `query` menjadi fungsi dalam yang menerima `(start, end, bucket_s, node_filter)`; `query` memanggilnya dengan `RANGES`, `query_window` dengan bucket 60. Endpoint: `range_: Literal["1h","6h","24h","7d"] | None = Query(None, alias="range")`, `from_`/`to` (alias `from`), `node_id`; validasi → `HTTPException(422)`; tanpa parameter → `range_ = "6h"`.
- [ ] **Step 3: Jalankan** `pytest tests -q -m "not gpu"` → lulus (baseline + jumlah uji baru Task 1 dan Task 3).
- [ ] **Step 4: Commit**

```bash
git add backend/app/services/monitoring_history.py backend/app/api/monitoring.py backend/tests/test_monitoring_history.py
git commit -m "feat(monitoring): jendela waktu from/to/node_id di GET /monitoring/history"
```

---

### Task 4: Frontend — logika bukti event system (fungsi murni + API)

**Files:**
- Modify: `frontend/src/api/monitoring.ts` (`getMonitoringHistoryWindow`, `MonitoringHistory.range: string`), `frontend/src/app/i18n.tsx`
- Create: `frontend/src/features/events/systemEvidence.ts`
- Test: `frontend/src/__tests__/system-evidence.test.ts`

**Interfaces:**
- Consumes: `EventOut` (dengan `node_id`, Task 2), `NodeHistory`, `HistPoint`; `healthKey`/`fmt` dari `features/monitoring/health.ts`.
- Produces:
  ```ts
  export const EVIDENCE_RETENTION_MS = 7 * 24 * 3_600_000
  export const MAX_WINDOW_MS = 6 * 3_600_000
  export type ChartSpec = { key: string; titleKey: TKey; unit: string; yMin?: number
    series: { key: string; labelKey: TKey; pick: (n: NodeHistory) => { t: number; v: number }[] }[]
    refLine?: { v: number; labelKey: TKey } }
  export type Evidence = { kind: 'health' | 'node' | 'unknown'; expired: boolean; nodeId: number | null
    window: { from: number; to: number } | null; facts: { labelKey: TKey; value: string }[]; charts: ChartSpec[] }
  export function evidenceWindow(e: EventOut, now: number): { from: number; to: number }
  export function systemEvidence(e: EventOut, t: (k: TKey) => string, now: number): Evidence
  // api/monitoring.ts
  export function getMonitoringHistoryWindow(p: { from: Date; to: Date; nodeId?: number }): Promise<MonitoringHistory>
  ```
  `getMonitoringHistoryWindow` memanggil `/monitoring/history?from=<iso>&to=<iso>[&node_id=]` dan melempar `Error` bila `!res.ok`.
- Kunci i18n baru (id / en) `events.evidence.*`: judul panel, label fakta (`rule`, `target`, `value`, `threshold`, `durationRule`, `status`, `node`, `cause`), status (`firing` "Menyala", `resolved` "Pulih · selama {n} mnt" / `resolvedNoDuration` "Pulih", `closed` "Ditutup"), penyebab (`timeout` "Heartbeat berhenti", `lwt` "Koneksi MQTT node terputus", `online` "Node kembali online"), judul/seri grafik (CPU, RAM, latensi rata-rata/maks, backlog, suhu GPU, VRAM GPU, umur frame, FPS % target, FPS inferensi), `marker` "Event".

Keputusan: jendela dan pemetaan grafik persis spec §3.3. `window` null dan `expired` true bila `ts < now − EVIDENCE_RETENTION_MS`; `closed:true` diperlakukan seperti firing untuk jendela; panjang jendela dipotong ke `MAX_WINDOW_MS` dari sisi awal; `to` tidak melebihi `now`. `target` diurai: `gpu:<node>:<idx>` → idx, `cam:<id>` → id; `camera_low_fps` memetakan `fps.min / target_fps × 100` (target dari `cameras[].target_fps`; target kosong/0 → titik dibuang). Node offline/online: dua grafik (`cpu_pct`, `infer_fps`, avg). Rule tak dikenal → `kind: 'health'`, `charts: []`. Event system tanpa payload health/node yang valid → `kind: 'unknown'`, fakta kosong. Nilai tak ada → "—" (`fmt`).

- [ ] **Step 1: Uji gagal** (`system-evidence.test.ts`): `evidenceWindow` — firing `[ts−30m, min(now, ts+30m)]`; resolved dengan `lasted_min: 10` `[ts−25m, ts+15m]`; node `online` `[ts−30m, ts+15m]`; `closed` seperti firing; `lasted_min: 600` terpotong tepat 6 jam. `systemEvidence` — event berumur 7 hari + 1 menit → `expired`, `window null`, `charts []`, fakta tetap; tepat di ambang 7 hari → tidak expired; fakta health lengkap (Aturan, Target, Nilai+unit, Ambang+unit, Durasi aturan, Status firing/resolved/closed); fakta node (penyebab `timeout`/`lwt`/`online`); pemetaan grafik per rule (`node_cpu`, `node_ram`, `infer_latency` dua seri, `mqtt_backlog`, `gpu_temp`/`gpu_vram` idx dari target, `camera_no_frames`, `camera_low_fps` dalam persen dengan `target_fps`) dengan `pick` diuji terhadap fixture `NodeHistory` kecil; garis ambang = `payload.threshold`; rule tak dikenal → fakta saja; payload kosong → `unknown`; `node_id` null → `nodeId null`. `getMonitoringHistoryWindow`: URL memuat `from=`/`to=`/`node_id=` dan melempar saat 500. Jalankan → **FAIL** (modul belum ada).
- [ ] **Step 2: Implementasi** `systemEvidence.ts`, `getMonitoringHistoryWindow`, tipe `range: string`, kunci i18n (id + en, paritas).
- [ ] **Step 3: Jalankan** `npx vitest run src/__tests__/system-evidence.test.ts` → PASS; `npm run build` → exit 0; `npm run lint` tanpa pasangan baru.
- [ ] **Step 4: Commit**

```bash
git add frontend/src/api/monitoring.ts frontend/src/features/events/systemEvidence.ts frontend/src/app/i18n.tsx frontend/src/__tests__/system-evidence.test.ts
git commit -m "feat(events): logika bukti event system (jendela, fakta, pemetaan grafik)"
```

---

### Task 5: Frontend — `LineChart markers` dan panel `SystemEvidence`

**Files:**
- Modify: `frontend/src/components/LineChart.tsx` (prop `markers`), `frontend/src/app/theme.scss` (`.lc__marker`, `.ev-evidence*`), `frontend/src/app/i18n.tsx`
- Create: `frontend/src/features/events/SystemEvidence.tsx`
- Test: `frontend/src/__tests__/linechart.test.tsx` (tambah), `frontend/src/__tests__/system-evidence-panel.test.tsx`

**Interfaces:**
- Consumes: `systemEvidence`, `ChartSpec`, `Evidence` (Task 4); `getMonitoringHistoryWindow`; `LineChart`, `PALETTE`.
- Produces: `LineChart` prop `markers?: { t: number; label: string }[]` (garis vertikal `data-testid="lc-marker"`; `t` di luar `[from, to]` tidak digambar); `SystemEvidence({ event }: { event: EventOut })` (dipakai dengan `key={event.id}`).
- Kunci i18n baru (id / en): `events.evidence.title` "Bukti" / "Evidence"; `events.evidence.loading`; `events.evidence.chartFailed` "Gagal memuat grafik" / "Failed to load chart"; `events.evidence.noData` "Tidak ada data tren pada jendela ini" / "No trend data in this window"; `events.evidence.expired` "Data tren hanya disimpan 7 hari" / "Trend data is kept for 7 days only"; `events.evidence.unknown` "Tidak ada rincian tambahan untuk event ini" / "No further details for this event".

Keputusan `SystemEvidence`: `now` dari `useState(() => Date.now())`; `Evidence` dihitung dari `systemEvidence(event, t, now)`; fetch satu kali per event bila `window`, `nodeId`, dan `charts.length > 0` — status awal diturunkan (`'loading'` bila akan fetch, selain itu `'idle'`) sehingga tidak ada `setState` sinkron di efek; hasil di-`alive`-guard. Fakta ditampilkan sebagai daftar (`dl`) selalu; grafik memakai `LineChart` per `ChartSpec` (`from/to` = window, `bucketMs` 60 000, `markers=[{ t: ts, label: t('events.evidence.marker') }]`, `refLine` dari spec, `shaded` = `node.offline` untuk node `nodeId`, seri dari `pick`, warna `PALETTE`, `locale` dari `useT()`). Keadaan: `loading` → skeleton; `error` → `chartFailed`; semua seri kosong → `noData`; `expired` → `expired`; `kind === 'unknown'` → `unknown`.

- [ ] **Step 1: Uji gagal.** `linechart.test.tsx`: `'marker is drawn inside the range and skipped outside'` (satu di dalam → 1 `lc-marker`; satu di luar → tidak ada). `system-evidence-panel.test.tsx` (fetch palsu untuk `/monitoring/history?`): `'health event shows facts, a chart, the threshold line and the event marker'`; `'node offline event shows CPU and FPS charts with offline shading'`; `'camera_low_fps plots percent of target'` (nilai pada path grafik sesuai `fps/target×100`); `'event older than 7 days shows facts and the expired note, no history request'`; `'history failure keeps facts and shows the chart error'`; `'empty window shows the no-data note'`; `'unknown rule shows facts only without a history request'`; `'loading shows a skeleton before the chart'`. Jalankan → **FAIL**.
- [ ] **Step 2: Implementasi** `markers` + SCSS `.lc__marker` (garis putus-putus, token), `SystemEvidence.tsx`, SCSS panel (`.ev-evidence`), kunci i18n.
- [ ] **Step 3: Jalankan** kedua berkas uji → PASS; `npm run lint` tanpa pasangan baru.
- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/LineChart.tsx frontend/src/features/events/SystemEvidence.tsx frontend/src/app/theme.scss frontend/src/app/i18n.tsx frontend/src/__tests__/linechart.test.tsx frontend/src/__tests__/system-evidence-panel.test.tsx
git commit -m "feat(events): panel Bukti event system (grafik tren, ambang, marker waktu)"
```

---

### Task 6: Frontend — integrasi panel system ke `EventsPage`

**Files:**
- Modify: `frontend/src/features/events/EventsPage.tsx`, `frontend/src/app/theme.scss` (sel ikon baris daftar `.ev-thumb--icon`), `frontend/src/app/i18n.tsx` (bila perlu)
- Test: `frontend/src/__tests__/events.test.tsx` (tambah)

**Interfaces:**
- Consumes: `SystemEvidence` (Task 5); `eventTitle`, `eventWhere` dari `features/notifications/labels.ts`; `cams` yang sudah ada di halaman untuk `cameraName`.

Keputusan perilaku (untuk `type === 'system'`): tidak ada `ev-tabstrip` dan media; `<SystemEvidence key={selected.id} event={selected} />` mengganti blok media; judul detail `eventTitle · eventWhere`; sel meta Kamera dan Zona tidak dirender; `clipPending` selalu `false` (tidak ada polling 5 dtk dan tidak ada teks "sedang direkam"); baris daftar memakai `eventTitle` + `eventWhere` dan sel ikon `ev-thumb--icon` (Carbon `Activity`, `aria-hidden`) alih-alih `Thumb`; teks pencarian untuk event system memakai `eventWhere` (bukan `cam null`). Event non-system tidak berubah.

- [ ] **Step 1: Uji gagal** (tambah ke `events.test.tsx`; event system `type:'system'`, `camera_id:null`, `payload:{kind:'health', rule:'node_cpu', ...}` dan satu node `{node:'edge-1', reason:'timeout'}`): `'system event hides the snapshot, clip and crop tabs and shows the evidence'` (tak ada `event-tab-snapshot`/`event-tab-clip`; ada judul bukti); `'system event does not poll for a clip or show the recording text'` (event baru bertimestamp sekarang: `Clip sedang direkam` tidak ada dan tidak ada refetch ekstra dalam 6 detik dengan fake timers); `'system row shows a human title and location, not raw system'`; `'system detail hides Kamera and Zona meta'`; `'search finds a system event by node name'`; `'non-system events keep tabs and media'` (regresi). Jalankan → **FAIL**.
- [ ] **Step 2: Implementasi** perubahan `EventsPage.tsx`, SCSS ikon, i18n bila ada kunci baru.
- [ ] **Step 3: Verifikasi frontend penuh** (dari `frontend/`): `npx vitest run` → semua lulus; `npm run build` → exit 0; `npm run lint` → pasangan (rule, file) tidak bertambah dari baseline; `git grep -nE "style=\{\{|#[0-9a-fA-F]{6}" -- frontend/src/features/events` → tidak ada baris baru dari perubahan ini.
- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/events/EventsPage.tsx frontend/src/app/theme.scss frontend/src/app/i18n.tsx frontend/src/__tests__/events.test.tsx
git commit -m "feat(events): event system memakai panel Bukti, judul/lokasi lokal, tanpa polling klip"
```

---

### Task 7: Smoke test dan dokumen

**Files:**
- Modify: `WORKFLOW.md` (§8 Event Inbox), `ARCHITECTURE.md` (parameter `severity`, mode jendela history), `docs/runbooks/monitoring.md`, `README.md`, `ROADMAP.md`, `CHANGELOG.md`

- [ ] **Step 1: S1 suite penuh** di commit terakhir: backend `.venv/bin/python -m pytest tests -q -m "not gpu"`; frontend `npx vitest run`, `npm run build`, `npm run lint`. Cocokkan dengan baseline dan pertambahan uji; lint per pasangan (rule, file).
- [ ] **Step 2: S2 penjaga statis:** `rtk git diff --stat main...HEAD` hanya menyentuh berkas pada daftar Files semua task + dokumen Task 7 + spec/plan; paritas kunci i18n id=en untuk `events.*` yang baru.
- [ ] **Step 3: S3 smoke render (tanpa screenshot):** `cd frontend && npm run dev`, Playwright MCP dengan mock `/api/v1/**` (termasuk endpoint sesi agar lolos login, `/events?` dengan campuran event kamera/system, `/monitoring/history?from=…`). Di 1440 px dan 390 px: 0 error konsol; filter "Semua" memulihkan daftar; event system menampilkan panel Bukti (fakta + grafik + marker) tanpa tab media; `scrollWidth <= innerWidth` di 390 px. Bila tak tersedia: tulis "S3 tidak dijalankan" beserta alasannya.
- [ ] **Step 4: Dokumen.** `WORKFLOW.md §8`: filter server-side, opsi Semua, reset, penanda 200+, panel Bukti system (fakta, grafik, batas 7 hari). `ARCHITECTURE.md`: kontrak `GET /events` (`severity`) dan `GET /monitoring/history` (mode jendela, batas 6 jam, `range: "custom"`). `docs/runbooks/monitoring.md`: mode jendela. `README.md` dan `ROADMAP.md`: satu baris, **tanpa `[x]`** (menunggu uji lapangan). `CHANGELOG.md`: entri dengan konteks, file, **evidence berisi keluaran nyata**, dampak, rollback; catat bahwa uji UI visual oleh user menyusul.
- [ ] **Step 5: Commit**

```bash
git add WORKFLOW.md ARCHITECTURE.md docs/runbooks/monitoring.md README.md ROADMAP.md CHANGELOG.md
git commit -m "docs: filter Events dan bukti event system — WORKFLOW, ARCHITECTURE, runbook, README, ROADMAP, CHANGELOG"
```
