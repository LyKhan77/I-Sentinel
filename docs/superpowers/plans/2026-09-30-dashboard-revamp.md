# Dashboard Revamp Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ganti halaman Dashboard dengan layout status-first (strip status, 4 tile link, chart event per jam, event terbaru live, masalah aktif, node ringkas) dan perluas `GET /api/v1/events/stats/today`.

**Architecture:** Backend: logika statistik pindah ke `services/event_stats.py` dan mendapat `by_severity`, `by_hour`, `critical_by_hour`, tanpa tipe `attendance`. Frontend: `useDashboardData` (polling 15 dtk, kegagalan per sumber) memberi `DashboardData` ke blok presentasional; event terbaru dari `useEventAlerts()` (tanpa langganan realtime kedua).

**Tech Stack:** FastAPI + SQLAlchemy + pytest (SQLite uji); React 19 + TS + Carbon + SCSS + Vitest/Testing Library.

**Spec:** `docs/superpowers/specs/2026-09-30-dashboard-revamp-design.md` (keputusan D1 = `attendance` dikecualikan dari `stats/today`).

## Global Constraints

- Branch `feat/dashboard-revamp` dari `main` @ `8e57d09`. Jangan `push`, jangan deploy.
- Commit Conventional Commits berbahasa Indonesia, satu per tugas. **Tanpa** `Co-Authored-By` atau atribusi AI apa pun (AGENTS.md §9 menimpa trailer default).
- Frontend: komponen Carbon + kelas `.dash-*` di `frontend/src/app/theme.scss` dengan token `var(--cds-*, <fallback>)`; **tanpa** `style={{}}` dan hex di TSX. REST hanya lewat `src/api/*`. Semua string lewat `src/app/i18n.tsx` (id **dan** en). Nol overflow horizontal di 390 px.
- Status tidak boleh hanya warna: selalu ada teks. Sumber gagal menampilkan "—"/"Gagal memuat", **bukan** angka 0.
- Backend: logika di `app/services/`, router tipis, kontrak Pydantic di `app/schemas/`. Semua endpoint tetap `get_current_user`.
- Uji tidak boleh mengunci detail implementasi (AGENTS.md §6): assert perilaku yang terlihat.

## Review Focus

1. Event tepat di batas hari (00:00:30 dan 23:59:30 lokal) harus masuk jam 0 dan jam 23 → Task 1.
2. Semua sumber sukses tetapi kosong (0 event, 0 hadir) harus tampil `0`, bukan `—` → Task 3.
3. `severity` tak dikenal dari API tidak boleh merusak baris/Tag → Task 4.
4. Event system tanpa `camera_id` (node offline) tetap tampil dengan teks node, bukan `#?` → Task 4.
5. Satu sumber gagal tidak boleh mengosongkan blok lain, dan nilai lama bertahan saat poll berikutnya gagal → Task 2 dan Task 3.

---

### Task 1: Backend — `stats/today` diperluas

**Files:**
- Create: `backend/app/services/event_stats.py`
- Modify: `backend/app/schemas/event.py` (tambah `EventStatsOut`), `backend/app/api/events.py:108-117`
- Test: `backend/tests/test_events_api.py`

**Interfaces:**
- Produces: `event_stats.today(db: Session) -> dict` dan `EventStatsOut(total: int, by_type: dict[str,int], by_severity: dict[str,int], by_hour: list[int], critical_by_hour: list[int])`; respons JSON identik dengan spec §3.1.

- [ ] **Step 1: Baseline** — dari `backend/`: `pytest tests -q -m "not gpu"`. Catat jumlah lulus (dipakai di Task 7).
- [ ] **Step 2: Tulis uji gagal** di `test_events_api.py` (pakai `client`, `_payload`, `_admin_headers`, `_ingest_headers` yang ada; waktu lokal hari ini = `datetime.combine(date.today(), time(h, m, s)).astimezone().isoformat()` dikirim sebagai `ts_event`):
  - `test_stats_today_excludes_attendance`: kirim 1 `intrusion` + 2 `attendance` → `total == 1`, `"attendance" not in by_type`.
  - `test_stats_today_by_severity_three_keys_sum_to_total`: kirim critical, warning, warning, info → `by_severity == {"critical":1,"warning":2,"info":1}`; pada hari tanpa event lain severity kosong tetap memiliki tiga kunci bernilai 0 (assert `set(keys)=={"critical","warning","info"}`); `sum(by_severity.values()) == sum(by_hour) == total`.
  - `test_stats_today_buckets_by_local_hour`: kirim critical pukul 00:00:30 dan warning pukul 23:59:30 lokal → `by_hour[0]==1`, `by_hour[23]==1`, `critical_by_hour[0]==1`, `critical_by_hour[23]==0`, `len(by_hour)==24`.
  Jalankan: `pytest tests/test_events_api.py -k stats_today -v` → **FAIL** (KeyError `by_severity`, dll.). Uji `test_stats_today` lama harus tetap lulus.
- [ ] **Step 3: Implementasi** `today(db)` di `services/event_stats.py`: `midnight = datetime.combine(date.today(), time.min).astimezone()`; satu query `(Event.type, Event.severity, Event.ts_event)` dengan `ts_event >= midnight` dan `type != "attendance"`; bucket di Python. Jam = `ts.astimezone().hour`; `ts` naif (SQLite) diperlakukan UTC (`replace(tzinfo=timezone.utc)`). Kunci `by_severity` selalu `critical|warning|info`; severity di luar itu dihitung ke `total`/`by_hour` tetapi tidak ditambahkan sebagai kunci (`ALLOWED_SEVERITY` sudah membatasi di ingest). Beri komentar `# ponytail: fetch O(event hari ini); pindah ke GROUP BY date_trunc bila volume > puluhan ribu/hari`.
- [ ] **Step 4: Schema + router.** Tambah `EventStatsOut` (Pydantic) di `schemas/event.py`; `stats_today` memakai `response_model=EventStatsOut` dan `return event_stats.today(db)`; hapus import `func`/`time` di `events.py` bila tak terpakai lagi.
- [ ] **Step 5: Jalankan** `pytest tests -q -m "not gpu"` → semua lulus (jumlah = baseline + 3).
- [ ] **Step 6: Commit**

```bash
git add backend/app/services/event_stats.py backend/app/schemas/event.py backend/app/api/events.py backend/tests/test_events_api.py
git commit -m "feat(events): stats/today tambah by_severity, by_hour, critical_by_hour; kecualikan attendance"
```

---

### Task 2: Frontend — data hook dan ringkasan

**Files:**
- Modify: `frontend/src/api/events.ts:16` (tipe `EventStats`)
- Create: `frontend/src/features/dashboard/summary.ts`, `frontend/src/features/dashboard/useDashboardData.ts`, `frontend/src/__tests__/dashboardFixtures.ts`
- Test: `frontend/src/__tests__/dashboard-data.test.tsx`

**Interfaces:**
- Produces (`api/events.ts`): `EventStats = { total: number; by_type: Record<string, number>; by_severity: Record<string, number>; by_hour: number[]; critical_by_hour: number[] }`.
- Produces (`summary.ts`): `summarizeCameras(m: Monitoring): { healthy: number; total: number; problems: number }` (`healthy=ok`, `total=ok+warning+critical`, `problems=warning+critical`; `disabled` opsional/undefined aman); `summarizeAttendance(rows: AttendanceRow[]): { present: number; late: number; needsFix: number }` (`present` = status ≠ `absent`; `late` = `late`; `needsFix` = `no_exit` + `no_entry`).
- Produces (`useDashboardData.ts`):
  ```ts
  export const DASH_POLL_MS = 15_000
  export type Source = 'monitoring' | 'alerts' | 'stats' | 'attendance' | 'storage'
  export type DashboardData = { monitoring: Monitoring | null; alerts: HealthAlert[] | null; stats: EventStats | null
    attendance: AttendanceRow[] | null; storage: StorageStats | null; loading: boolean; updatedAt: Date | null
    failed: Record<Source, boolean> }
  export function useDashboardData(statsKey?: number | null): DashboardData
  ```
  `alerts` = `getHealthAlerts().active`. `loading` true sampai siklus pertama selesai. `updatedAt` = waktu siklus terakhir yang punya minimal satu sumber sukses.
- Produces (`dashboardFixtures.ts`): builder `mon(over?)` (Monitoring dengan `summary.cameras {ok:1,warning:1,critical:1}`, 1 node `server` online dengan 1 GPU 5000/24000 MB util 55), `alert(over?)`, `ev(id, over?)` (EventOut: intrusion, critical, `camera_id:1`, `snapshot_path:'snapshots/x.jpg'`, `ts_event` = sekarang), `stats(over?)`, `att(status, over?)`, `storage(over?)`, `ok(body)`/`fail()` (respons fetch palsu), dan `emptyData(over?)`: `DashboardData` dengan semua sumber `null`, `loading:false`, semua `failed:false`.

- [ ] **Step 1: Baseline** — dari `frontend/`: `npx vitest run` dan `npm run lint`; catat jumlah lulus dan set warning lint.
- [ ] **Step 2: Uji gagal `summary`** (`dashboard-data.test.tsx`): `summarizeCameras` → `{healthy:1,total:3,problems:2}` untuk fixture dan `total:0` tanpa kamera; `summarizeAttendance([ontime, late, no_exit, no_entry, absent, waiting])` → `{present:5,late:1,needsFix:2}`; daftar kosong → semua 0.
- [ ] **Step 3: Uji gagal hook** (`renderHook`, fetch palsu per akhiran URL: `/monitoring`, `/monitoring/alerts`, `/events/stats/today`, `/attendance`, `/storage/stats`):
  - `loads all five sources and ends loading`: setelah `waitFor`, `loading === false`, kelima nilai terisi, `failed` semua `false`, `updatedAt` bukan null.
  - `a failed source leaves only its own value null`: `/events/stats/today` → 500 → `stats === null`, `failed.stats === true`, `monitoring` tetap terisi, `failed.monitoring === false`.
  - `keeps the last good value when a later poll fails`: `vi.useFakeTimers({ shouldAdvanceTime: true })`; siklus 1 sukses; ganti `/events/stats/today` jadi 500; `await act(() => vi.advanceTimersByTime(DASH_POLL_MS))` → `stats` masih nilai lama, `failed.stats === true`.
  - `refetches stats only when statsKey changes, not on mount`: hitung panggilan ke URL stats = 1 setelah mount; `rerender({ key: 2 })` → 2; panggilan `/monitoring` tidak bertambah.
  Jalankan `npx vitest run src/__tests__/dashboard-data.test.tsx` → **FAIL** (modul belum ada).
- [ ] **Step 4: Implementasi** `EventStats`, `summary.ts`, dan hook. Hook: satu `grab(promise, source)` per sumber (catat `failed`, pertahankan nilai lama lewat fungsi-updater state); `Promise.all` untuk kelima sumber (`getMonitoring`, `getHealthAlerts`, `eventStats`, `attendanceList`, `getStorageStats`); `setInterval(DASH_POLL_MS)` dengan pembersihan dan penjaga `alive`; efek `statsKey` hanya me-refetch `eventStats` dan **melewati eksekusi pertama** (ref).
- [ ] **Step 5: Jalankan** `npx vitest run src/__tests__/dashboard-data.test.tsx` → PASS; `npm run build` → sukses (tipe `EventStats` baru tidak merusak `DashboardPage` lama).
- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/events.ts frontend/src/features/dashboard/summary.ts frontend/src/features/dashboard/useDashboardData.ts frontend/src/__tests__/dashboardFixtures.ts frontend/src/__tests__/dashboard-data.test.tsx
git commit -m "feat(dashboard): useDashboardData (polling per sumber) dan ringkasan kamera/kehadiran"
```

---

### Task 3: Frontend — StatusStrip dan KpiTiles

**Files:**
- Create: `frontend/src/features/dashboard/StatusStrip.tsx`, `frontend/src/features/dashboard/KpiTiles.tsx`
- Modify: `frontend/src/app/theme.scss` (kelas `.dash-strip`, `.dash-dot` + `--ok|--warning|--critical|--neutral`, `.dash-kpis`, `.dash-tile` + `__label|__value|__sub`; grid `repeat(auto-fit, minmax(160px, 1fr))`), `frontend/src/app/i18n.tsx` (kunci di bawah)
- Test: `frontend/src/__tests__/dashboard-blocks.test.tsx`

**Interfaces:**
- Consumes: `DashboardData`, `summarizeCameras`, `summarizeAttendance`, `emptyData` (Task 2); `formatBytes(n, locale)` dari `features/config/bytes.ts`; `healthKey` dari `features/monitoring/health.ts`.
- Produces: `StatusStrip({ data }: { data: DashboardData })`, `KpiTiles({ data }: { data: DashboardData })`.
- Kunci i18n baru (id / en): `dash.status.ok` "Semua sistem normal" / "All systems normal"; `dash.status.alerts` "{n} peringatan aktif" / "{n} active alerts"; `dash.status.unavailable` "Status sistem tidak tersedia" / "System status unavailable"; `dash.status.stale` "Gagal memperbarui — data terakhir {time}" / "Update failed — last data {time}"; `dash.status.updated` "Diperbarui {time}" / "Updated {time}"; `dash.cam.problems` "{n} bermasalah" / "{n} with issues"; `dash.cam.allHealthy` "semua sehat" / "all healthy"; `dash.ev.critical` "{n} critical" / "{n} critical"; `dash.att.title` "Kehadiran hari ini" / "Today's attendance"; `dash.att.sub` "{late} telat · {fix} perlu koreksi" / "{late} late · {fix} need correction"; `dash.disk.title` "Disk" / "Disk"; `dash.disk.free` "{size} kosong" / "{size} free"; `dash.unavailable` "Gagal memuat" / "Failed to load".

Keputusan status `StatusStrip` (urutan evaluasi):

| Kondisi | Teks | Titik |
|---|---|---|
| `loading` | skeleton | — |
| `monitoring === null` | `dash.status.unavailable` | neutral |
| `alerts?.length > 0` | `dash.status.alerts` | critical bila ada alert `critical`, selain itu warning |
| `summary.health !== 'ok'` | `mon.health.<health>` | sesuai health |
| lainnya | `dash.status.ok` | ok |

Bila ada sumber `failed` tetapi data ada: tambahkan `dash.status.stale` (waktu `updatedAt` HH:MM); selain itu `dash.status.updated`. Link "Monitoring →" ke `/monitoring`.

Tile (semua `<Link>`): Kamera `healthy/total` + sub `dash.cam.problems`/`dash.cam.allHealthy` → `/monitoring` (total 0 → `dash.noCameras`); Event `stats.total` + sub `dash.ev.critical` (`by_severity.critical`) → `/events`; Kehadiran `present` + sub `dash.att.sub` → `/attendance`; Disk `Math.round(disk.percent)%` + sub `dash.disk.free` → `/configuration?tab=storage`. Sumber `null` dan `failed` → nilai "—" + sub `dash.unavailable`; `null` saat `loading` → `SkeletonText`.

- [ ] **Step 1: Uji gagal** (`MemoryRouter` + `I18nProvider`, `emptyData({...})`):
  - StatusStrip: `'shows normal when healthy and no alerts'` → teks "Semua sistem normal"; `'shows alert count'` dengan 2 alert → "2 peringatan aktif"; `'shows unavailable when monitoring failed'`; `'shows stale note when a source failed but data exists'` → cocok `/Gagal memperbarui — data terakhir/`; link bernama Monitoring ber-`href="/monitoring"`.
  - KpiTiles: `'camera tile shows healthy/total and problem count'` → "1/3", "2 bermasalah", href `/monitoring`; `'event tile'` (total 47, critical 3) → "47", "3 critical", href `/events`; `'attendance tile'` → angka hadir dan "1 telat · 2 perlu koreksi", href `/attendance`; `'disk tile'` (percent 62) → "62%", href `/configuration?tab=storage`; `'zero from a successful source renders 0, not a dash'` (stats total 0, attendance `[]`) → teks "0" ada dan tidak ada "—" pada kedua tile itu; `'failed source renders dash and Gagal memuat, never 0'`; `'one failed source does not blank the other tiles'` (attendance gagal, lainnya terisi); `'loading renders skeletons'` (`.cds--skeleton__text`).
  Jalankan `npx vitest run src/__tests__/dashboard-blocks.test.tsx` → **FAIL**.
- [ ] **Step 2: Implementasi** kedua komponen, kelas SCSS, dan kunci i18n (id + en). Waktu `HH:MM` dari `updatedAt.toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit' })`; substitusi `{n}`/`{time}`/`{size}` dengan `.replace` seperti pola `DiskAlertBanner`.
- [ ] **Step 3: Jalankan** `npx vitest run src/__tests__/dashboard-blocks.test.tsx` → PASS; `npm run lint` → tidak ada warning baru.
- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/dashboard/StatusStrip.tsx frontend/src/features/dashboard/KpiTiles.tsx frontend/src/app/theme.scss frontend/src/app/i18n.tsx frontend/src/__tests__/dashboard-blocks.test.tsx
git commit -m "feat(dashboard): StatusStrip dan 4 tile KPI berupa link"
```

---

### Task 4: Frontend — EventsPerHour dan RecentEvents

**Files:**
- Modify: `frontend/src/components/LineChart.tsx` (prop `digits?: number`, default `1`, dipakai `fmtV`), `frontend/src/app/theme.scss` (`.dash-section`, `.dash-card`, `.dash-event`), `frontend/src/app/i18n.tsx`
- Create: `frontend/src/features/dashboard/EventsPerHour.tsx`, `frontend/src/features/dashboard/RecentEvents.tsx`
- Test: `frontend/src/__tests__/linechart.test.tsx` (tambah), `frontend/src/__tests__/dashboard-blocks.test.tsx` (tambah)

**Interfaces:**
- Consumes: `DashboardData` (Task 2); `dayStart(0, now)`, `eventTitle`, `eventWhere`, `sevClass` dari `features/notifications/labels.ts`; `PALETTE` dari `LineChart`; `EventOut`.
- Produces: `EventsPerHour({ data, now }: { data: DashboardData; now?: Date })`; `RecentEvents({ events, cameraName, now }: { events: EventOut[]; cameraName: (id: number | null) => string; now?: Date })` (maks 8 baris, urutan input dipertahankan).
- Kunci i18n baru (id / en): `dash.hourly.title` "Event per jam (hari ini)" / "Events per hour (today)"; `dash.hourly.total` "Semua" / "All"; `dash.hourly.critical` "Critical" / "Critical"; `dash.recent.title` "Event terbaru" / "Latest events"; `dash.recent.all` "Semua event →" / "All events →"; `dash.sev.critical|warning|info` "Critical" / "Warning" / "Info" (kedua bahasa).

Keputusan: `EventsPerHour` menggambar seri `total` (`by_hour`) dan `critical` (`critical_by_hour`) dengan titik `t = awalHari + h·3600000` **hanya untuk `h ≤ now.getHours()`**, `from = awalHari`, `to = from + 24 jam`, `bucketMs = 3600000`, `yMin = 0`, `digits = 0`, `locale` dari `useT()`, `testId="dash-hourly"`; `stats === null` → teks `dash.unavailable` (atau skeleton saat `loading`), tanpa chart. `RecentEvents`: tiap baris `<Link to={`/events?event=${e.id}`}>`; thumbnail `<img className="ev-thumb" src={`/api/v1/media/${snapshot_path}`}>`, tanpa snapshot atau `onError` → `<span className="ev-thumb ev-thumb--empty">`; `Tag` severity dari `sevClass` dengan teks `dash.sev.*` (critical → `red`, selain itu `warm-gray`); waktu `HH:MM`, event bukan hari ini diberi tanggal `DD/MM`; kosong → `dash.noEvents`.

- [ ] **Step 1: Uji gagal.**
  - `linechart.test.tsx`: `'digits=0 formats values without decimals'` → `aria-label` dari `role="img"` memuat "3 %" bila `digits={0}` dan "3.0 %" tanpa prop.
  - `EventsPerHour`: `'draws only hours up to now'` — `now` = 10:30 lokal, `by_hour` 24 angka → `lc-line-total` bernilai `d.match(/[ML]/g)` panjang 11 (tanpa celah); `lc-line-critical` ada; `'all-zero stats still render both lines without crashing'`; `'null stats renders Gagal memuat and no chart'` (`failed.stats=true`).
  - `RecentEvents`: `'shows camera name, severity text and link to the event'` (`cameraName` → "Gate-A", event id 7) → teks "Gate-A", "Critical", link `href="/events?event=7"`; `'renders at most 8 rows'` (10 event); `'unknown severity falls back to a visible tag'` (`severity:'foo'`) → tidak melempar dan Tag teks "Warning"; `'system event without camera shows node text, not #?'` (`type:'system'`, `camera_id:null`, `payload:{node:'edge-1'}`) → teks memuat "edge-1" dan tidak memuat "#?"; `'older-day event shows a date'`; `'thumbnail falls back when the image errors'` (`fireEvent.error` pada `img` → `.ev-thumb--empty` muncul, `img` hilang); `'empty list shows belum ada event'`.
  Jalankan `npx vitest run src/__tests__/linechart.test.tsx src/__tests__/dashboard-blocks.test.tsx` → **FAIL**.
- [ ] **Step 2: Implementasi** `digits` di `LineChart`, dua komponen, SCSS, dan kunci i18n.
- [ ] **Step 3: Jalankan** kedua berkas uji → PASS; `npm run lint` → tanpa warning baru.
- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/LineChart.tsx frontend/src/features/dashboard/EventsPerHour.tsx frontend/src/features/dashboard/RecentEvents.tsx frontend/src/app/theme.scss frontend/src/app/i18n.tsx frontend/src/__tests__/linechart.test.tsx frontend/src/__tests__/dashboard-blocks.test.tsx
git commit -m "feat(dashboard): chart event per jam dan daftar event terbaru dengan thumbnail"
```

---

### Task 5: Frontend — ActiveIssues dan NodeCompact

**Files:**
- Create: `frontend/src/features/dashboard/ActiveIssues.tsx`, `frontend/src/features/dashboard/NodeCompact.tsx`
- Modify: `frontend/src/app/theme.scss` (`.dash-row`), `frontend/src/app/i18n.tsx`
- Test: `frontend/src/__tests__/dashboard-blocks.test.tsx` (tambah)

**Interfaces:**
- Consumes: `DashboardData`, `emptyData`, `mon`, `alert` (Task 2); `healthKey`, `fmt` dari `features/monitoring/health.ts`; `MonNode` dari `api/monitoring.ts`.
- Produces: `ActiveIssues({ data })`, `NodeCompact({ data })` (keduanya `{ data: DashboardData }`).
- Kunci i18n baru (id / en): `dash.issues.title` "Masalah aktif" / "Active issues"; `dash.issues.none` "Tidak ada masalah aktif" / "No active issues"; `dash.issues.all` "Semua →" / "All →"; `dash.nodes.title` "Node" / "Nodes"; `dash.nodes.detail` "Detail di Monitoring →" / "Details in Monitoring →".

Keputusan: `ActiveIssues` mengurutkan `critical` dulu lalu `started_at` terbaru, maks 5; baris = `Tag` severity (teks `dash.sev.*`) + judul `t(`health.rule.${rule}` as TKey)` + `label` + `value/threshold unit`; tautan "Semua →" ke `/monitoring`. `NodeCompact`: per `monitoring.nodes` — titik + teks `dash.online`/`dash.offline` (dari `status === 'online'`), nama, `Tag` health (`healthKey`), dan untuk GPU pertama `GPU{idx} {util}% · VRAM {used/total %}` (tanpa GPU → "—"); tautan `dash.nodes.detail` ke `/monitoring`; `monitoring === null` → `dash.unavailable`; `monitoring.nodes` kosong → `dash.noNodes` (uji: `'no nodes shows belum ada node'`).

- [ ] **Step 1: Uji gagal.** `ActiveIssues`: `'lists critical first and caps at 5'` (7 alert campuran → 5 baris, baris pertama critical); `'shows rule title and label'` → "Kamera tanpa frame"; `'empty shows Tidak ada masalah aktif'`; `'failed and null shows Gagal memuat'`; link ke `/monitoring`. `NodeCompact`: `'online node shows name, online text and GPU summary'` → "server", "online", "GPU0 55% · VRAM 21%"; `'offline node shows offline text'`; `'node without GPU shows a dash'`; link `Detail di Monitoring →` ber-`href="/monitoring"`. Jalankan berkas uji → **FAIL**.
- [ ] **Step 2: Implementasi** kedua komponen, SCSS, i18n.
- [ ] **Step 3: Jalankan** `npx vitest run src/__tests__/dashboard-blocks.test.tsx` → PASS; `npm run lint` tanpa warning baru.
- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/dashboard/ActiveIssues.tsx frontend/src/features/dashboard/NodeCompact.tsx frontend/src/app/theme.scss frontend/src/app/i18n.tsx frontend/src/__tests__/dashboard-blocks.test.tsx
git commit -m "feat(dashboard): masalah aktif dan node ringkas"
```

---

### Task 6: Frontend — rakit `DashboardPage`, bersihkan kode lama

**Files:**
- Modify (tulis ulang): `frontend/src/features/dashboard/DashboardPage.tsx`; `frontend/src/app/theme.scss` (`.dash-grid` dua kolom `minmax(0,3fr) minmax(0,2fr)` → satu kolom di `@media (max-width: 899px)`, `.dash-side`); `frontend/src/app/i18n.tsx` (hapus kunci `dash.nodeHw|noGpuInfo|detector|pinned|auto|notPinned|vram|processes|latestAlerts|nodes` di id dan en)
- Test: `frontend/src/__tests__/dashboard.test.tsx` (ganti isinya)

**Interfaces:**
- Consumes: semua blok Task 3–5; `useDashboardData`; `useEventAlerts()` (`recent`, `cameraName`); `DiskAlertBanner`.
- Produces: `DashboardPage` (default export, tanpa props).

Keputusan susunan: kepala halaman (`nav.dashboard`, `dash.sub`) → `DiskAlertBanner stats={data.storage}` → `StatusStrip` → `KpiTiles` → `EventsPerHour` → `.dash-grid` berisi `RecentEvents events={recent}` (kiri) dan `.dash-side` = `ActiveIssues` + `NodeCompact` (kanan). `useDashboardData(recent[0]?.id ?? null)`.

- [ ] **Step 1: Uji gagal** — ganti `dashboard.test.tsx`; render `<I18nProvider><MemoryRouter><EventAlertsProvider><DashboardPage/>` dengan fetch palsu untuk `/monitoring`, `/monitoring/alerts`, `/events/stats/today`, `/attendance`, `/storage/stats`, `/events?` (riwayat provider), `/cameras` (nama kamera provider):
  - `'renders every block from API data'`: "Semua sistem normal"/jumlah alert, nilai tile, event terbaru dengan nama kamera "CAM-01" dan link `/events?event=<id>`, baris masalah aktif, baris node "server".
  - `'shows the disk alert banner when usage is over the threshold'` (pertahankan dari uji lama: `findByTestId('disk-alert')` memuat "Disk hampir penuh (91%)").
  - `'never shows fake zeros when every request fails'`: semua fetch 500 → "Status sistem tidak tersedia", minimal satu "Gagal memuat", dan tidak ada teks "0/0".
  - `'a new live event refetches today stats'`: setelah event baru masuk lewat provider (mock `useLiveEvents` atau polling provider), panggilan `/events/stats/today` bertambah.
  Jalankan `npx vitest run src/__tests__/dashboard.test.tsx` → **FAIL** (halaman lama).
- [ ] **Step 2: Implementasi** `DashboardPage` baru (hapus `NodeCard`, `TileStat`, `DetectorBadge`, `SEV_COLOR`, semua inline style) dan kunci i18n yang dihapus.
- [ ] **Step 3: Verifikasi penuh frontend** (dari `frontend/`): `npx vitest run` → semua lulus (≥ baseline + uji baru, tanpa uji dashboard lama); `npm run build` → exit 0; `npm run lint` → set warning sama dengan baseline Task 2.
- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/dashboard/DashboardPage.tsx frontend/src/app/theme.scss frontend/src/app/i18n.tsx frontend/src/__tests__/dashboard.test.tsx
git commit -m "feat(dashboard): rakit layout status-first, hapus kartu GPU dan style inline lama"
```

---

### Task 7: Verifikasi di aplikasi, dokumen, CHANGELOG

**Files:**
- Modify: `WORKFLOW.md` (§15), `README.md` (ringkasan Dashboard dan kontrak `stats/today` bila disebut; baris ±286), `ARCHITECTURE.md` (baris frontend `dashboard` ±142; kontrak `stats/today`), `ROADMAP.md` (catatan siklus fitur), `CHANGELOG.md` (entri baru di atas)
- Evidence lokal (gitignored, tidak di-commit): `docs/evidence/2026-09-30-dashboard-revamp-{1440,390}.png`

- [ ] **Step 1: Jalankan app** (skill `run`; backend lokal + `npm run dev`, atau ikuti `docs/DEVELOPMENT.md`). Login, buka `/dashboard`.
- [ ] **Step 2: Screenshot 1440 px dan 390 px** ke `docs/evidence/` (Playwright MCP). Di 390 px jalankan `browser_evaluate`: `document.documentElement.scrollWidth <= window.innerWidth` → harus `true`. Periksa juga: status strip tidak hanya warna; tile dapat di-Tab dan terfokus; `getComputedStyle` warna titik `--cds-support-*` tidak kosong (jika kosong, fallback hex SCSS dipakai — catat).
- [ ] **Step 3: Perbarui dokumen.** `WORKFLOW.md §15`: tulis ulang alur (strip status, 4 tile link, chart per jam, event terbaru live, masalah aktif, node ringkas; titik masuk ke Events/Attendance/Monitoring/Storage; `attendance` tidak dihitung di "Event hari ini"). `ARCHITECTURE.md`: kontrak `stats/today` memuat `by_severity`, `by_hour`, `critical_by_hour` dan pengecualian `attendance`; `dashboard` memakai `/monitoring`, `/monitoring/alerts`, `attendance`, `storage`, `useEventAlerts`. `README.md` dan `ROADMAP.md`: satu baris sesuai bagian yang menyebut Dashboard.
- [ ] **Step 4: CHANGELOG** — entri "Revamp Dashboard status-first (2026-09-30)" dengan konteks, file berubah, **evidence berisi keluaran** `pytest` (jumlah lulus), `npx vitest run` (jumlah lulus), `npm run build` (exit 0), `npm run lint` (set sama), hasil `scrollWidth`; dampak (angka "Event hari ini" tidak lagi menghitung `attendance`; "kamera online" menjadi "sehat"; badge detektor PIN/AUTO pindah ke Monitoring); rollback (`git revert` commit per tugas; tanpa migrasi DB).
- [ ] **Step 5: Verifikasi akhir** — `pytest tests -q -m "not gpu"` (dari `backend/`), `npx vitest run`, `npm run build`, `npm run lint` (dari `frontend/`); tempel keluarannya ke CHANGELOG. `git status` bersih kecuali berkas yang sengaja di-commit; `docs/evidence/` tidak ter-stage.
- [ ] **Step 6: Commit**

```bash
git add WORKFLOW.md README.md ARCHITECTURE.md ROADMAP.md CHANGELOG.md
git commit -m "docs: Dashboard status-first — WORKFLOW, ARCHITECTURE, README, ROADMAP, CHANGELOG"
```
