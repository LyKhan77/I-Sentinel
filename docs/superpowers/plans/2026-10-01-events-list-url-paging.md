# Events: Filter di URL, Muat Lebih Banyak, Tab Konfigurasi Viewer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Filter Events hidup di URL (dapat dibagikan, tahan reload/Back), daftar dapat dimuat lebih dari 200 baris, tile Dashboard "Event hari ini" menaut ke tampilan yang setara, dan viewer hanya melihat tab Storage di Konfigurasi.

**Architecture:** Backend: `offset` + pemutus seri `id DESC` di `GET /events`. Frontend: `eventFilters.ts` (fungsi murni parse/write/typesFor/sinceFor/matches + paging) menjadi dasar `EventsPage` yang menurunkan filter dari `useSearchParams`; `ConfigurationPage` menyaring tab untuk non-admin.

**Tech Stack:** FastAPI + SQLAlchemy + pytest (SQLite uji); React 19 + TS + Carbon + Vitest/Testing Library.

**Spec:** `docs/superpowers/specs/2026-10-01-events-list-url-paging-design.md` (D1 URL sumber kebenaran, D2 rentang `today`, D3 grup `security`, D4 offset+dedupe, D5 `MAX_EVENTS`, D6 viewer = Storage saja).

## Global Constraints

- Branch `feat/events-list-url-paging` dari `main` @ `afd95ff`. Jangan `push`, jangan merge, jangan deploy, jangan ssh ke server.
- Commit Conventional Commits berbahasa Indonesia, satu per tugas, `git add` path spesifik. **Tanpa** `Co-Authored-By` atau atribusi AI apa pun (AGENTS.md §9).
- Frontend: komponen Carbon + kelas SCSS di `theme.scss` bila perlu, **tanpa** `style={{}}` dan hex di TSX. REST hanya lewat `src/api/*`. String lewat `src/app/i18n.tsx` (id **dan** en, paritas).
- Lint: jangan `setState` sinkron di badan `useEffect` (`react/set-state-in-effect`); jangan baca/tulis `ref` di badan render; jangan `Date.now()` di badan render. Dependensi efek berupa nilai primitif.
- Backend: parameter baru opsional; perilaku lama tidak berubah; `get_current_user` wajib.
- Jalankan pytest dan vitest **berurutan, tidak bersamaan**.
- Uji tidak boleh mengunci detail implementasi: assert perilaku yang terlihat.

## Review Focus

1. Nilai URL tak valid (`type=foo`, `camera=abc`, `range=99d`, `severity=x`) jatuh ke default tanpa error; reload dan Back/Forward mempertahankan filter → Task 2.
2. `refresh` karena interval klip tertunda **tidak** membuang halaman yang sudah dimuat; `refresh` karena filter berubah **mereset** → Task 3.
3. "Muat lebih banyak" tidak menduplikasi baris saat event live masuk di antara halaman dan membuang respons yang tiba setelah filter berubah → Task 3.
4. Batas `MAX_EVENTS`: tombol hilang dan petunjuk batas tampil; halaman tak penuh → tombol hilang → Task 3.
5. Viewer tidak melihat tab admin dan `?tab=users` jatuh ke Storage; admin dan `me` kosong tetap tujuh tab → Task 5.

---

### Task 1: Backend — `offset` dan urutan deterministik

**Files:**
- Modify: `backend/app/api/events.py` (`list_events`)
- Test: `backend/tests/test_events_api.py`

**Interfaces:**
- Produces: `GET /api/v1/events?offset=<n>` (`0 ≤ n ≤ 10000`, default 0; di luar rentang → 422); urutan `ts_event DESC, id DESC`.

- [ ] **Step 1: Baseline** — dari `backend/`: `.venv/bin/python -m pytest tests -q -m "not gpu"` → catat jumlah (baseline repo: **637 passed**).
- [ ] **Step 2: Uji gagal** (`test_events_api.py`; pakai `client`, `_payload`, `_admin_headers`, `_ingest_headers`; kirim `ts_event` eksplisit): `test_list_events_offset_pages_do_not_overlap` (5 event berbeda waktu; `limit=2&offset=0`, `offset=2`, `offset=4` → id berurutan menurun tanpa tumpang tindih, total 5); `test_list_events_order_is_deterministic_for_equal_ts` (3 event `ts_event` sama → hasil terurut `id` menurun, dan `limit=1&offset=1` = elemen kedua); `test_list_events_offset_validation` (`offset=-1` dan `offset=10001` → 422; `offset=0` → 200). Jalankan `-k "offset or deterministic"` → **FAIL**.
- [ ] **Step 3: Implementasi**: `offset: int = Query(0, ge=0, le=10_000)`; `q.order_by(Event.ts_event.desc(), Event.id.desc()).offset(offset).limit(limit)`.
- [ ] **Step 4: Jalankan** `pytest tests -q -m "not gpu"` → lulus (baseline + 3).
- [ ] **Step 5: Commit**

```bash
git add backend/app/api/events.py backend/tests/test_events_api.py
git commit -m "feat(events): offset dan urutan deterministik di GET /events"
```

---

### Task 2: Frontend — filter Events di URL

**Files:**
- Create: `frontend/src/features/events/eventFilters.ts`
- Modify: `frontend/src/api/events.ts` (`offset` di `EventListParams`), `frontend/src/features/events/EventsPage.tsx`, `frontend/src/app/i18n.tsx`
- Test: `frontend/src/__tests__/event-filters.test.ts` (baru), `frontend/src/__tests__/events.test.tsx` (tambah)

**Interfaces:**
- Produces (`api/events.ts`): `EventListParams.offset?: number` (dikirim sebagai `offset` bila > 0).
- Produces (`eventFilters.ts`):
  ```ts
  export const RANGE_IDS = ['all', 'today', '24h', '7d', '30d'] as const
  export type RangeId = (typeof RANGE_IDS)[number]
  export const SECURITY = 'security'
  export type Filters = { type: string | null; camera: number | null; severity: string | null; range: RangeId; q: string }
  export function parseFilters(params: URLSearchParams): Filters
  export function writeFilters(prev: URLSearchParams, patch: Partial<Filters>): URLSearchParams
  export function typesFor(type: string | null): string[] | undefined   // 'security' → EVENT_TYPES minus 'attendance'; tipe tunggal → [type]; null → undefined
  export function sinceFor(range: RangeId, now: Date): string | undefined // 'today' → 00:00 lokal; 24h/7d/30d → now − N; 'all' → undefined (ISO UTC)
  export function matchesFilters(e: EventOut, f: Filters): boolean       // type (termasuk grup), camera, severity — bukan range/q
  ```
  `parseFilters`: `type` valid bila `security` atau anggota `EVENT_TYPES`; `camera` bilangan bulat positif; `severity` ∈ `critical|warning|info`; `range` ∈ `RANGE_IDS` selain itu `all`; `q` dipotong 100 karakter; nilai tak valid → default. `writeFilters`: menyalin `prev`, menetapkan nilai dari `patch`, **menghapus** param bernilai default (`null`, `all`, `''`), menjaga param lain (terutama `event`).
- Kunci i18n baru (id / en): `events.range.today` "Hari ini" / "Today"; `events.type.security` "Keamanan (tanpa absensi)" / "Security (excluding attendance)".

Keputusan perilaku `EventsPage`: state `typeFilter/camFilter/sevFilter/range/query` dihapus; `filters = parseFilters(searchParams)` dibaca tiap render (dependensi `refresh` memakai nilai primitifnya: `type`, `camera`, `severity`, `range`); setiap dropdown, `Select` rentang, dan kolom pencarian memanggil `setSearchParams(prev => writeFilters(prev, patch), { replace: true })`; "Atur ulang filter" menulis `{ type: null, camera: null, severity: null, range: 'all', q: '' }` (param `event` terjaga); `hasFilter` diturunkan dari `filters`; dropdown Tipe = `[Semua, Keamanan (tanpa absensi), ...EVENT_TYPES]`; `listEvents` menerima `types: typesFor(type)`, `camera_id`, `severities`, `since: sinceFor(range, new Date())`; pemfilteran live dan `filtered` memakai `matchesFilters` + pencarian klien `q`. Perilaku Task sebelumnya (`?event=`, sematan, stale guard, panel Bukti) tidak berubah.

- [ ] **Step 1: Baseline** — dari `frontend/`: `npx vitest run` (baseline repo: **32 files / 365 passed**), `npm run build`, `npm run lint` → 24 baris, catat per pasangan (rule, file).
- [ ] **Step 2: Uji gagal.** `event-filters.test.ts`: `parseFilters` default untuk param kosong; nilai valid terbaca (`type=system&camera=2&severity=critical&range=today&q=gate`); nilai tak valid → default (`type=foo`, `camera=abc`, `camera=0`, `severity=x`, `range=99d`); `q` dipotong 100; `writeFilters` menghapus nilai default, menjaga `event`, dan tidak mengubah `prev`; `typesFor('security')` tidak memuat `attendance` dan memuat tujuh tipe lain; `typesFor('system')` = `['system']`; `typesFor(null)` = `undefined`; `sinceFor('today', new Date('2026-10-01T15:30:00'))` = ISO dari 00:00 lokal tanggal itu; `sinceFor('24h', now)` = now − 24 jam; `sinceFor('all', now)` = `undefined`; `matchesFilters` untuk grup `security` menolak `attendance` dan menerima `system`. `events.test.tsx`: `'filters come alive from the initial URL'` (`/events?type=system&severity=critical` → request daftar memuat `type=system` dan `severity=critical`, dropdown menampilkan "Sistem"/"critical", tombol reset ada); `'changing a filter writes the URL with replace'` (lokasi memuat param baru, `useNavigationType` = `REPLACE`); `'reset clears filters but keeps ?event='`; `'Back restores the previous filter'` (push navigasi eksternal ke `?type=system` lalu `navigate(-1)` → filter kembali); `'range today sends since at local midnight'`; `'type security sends every type except attendance'` (URL request memuat `type=intrusion` … dan **tidak** `type=attendance`); `'invalid URL values fall back to defaults without a crash'`; `'search box writes q to the URL and filters client-side without a new request'`. Jalankan → **FAIL**.
- [ ] **Step 3: Implementasi** `eventFilters.ts`, `api/events.ts`, perubahan `EventsPage.tsx`, kunci i18n.
- [ ] **Step 4: Jalankan** `npx vitest run src/__tests__/event-filters.test.ts src/__tests__/events.test.tsx` → PASS (uji lama tetap hijau, termasuk filter server-side dan deep link); `npm run lint` → pasangan tidak bertambah.
- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/events/eventFilters.ts frontend/src/api/events.ts frontend/src/features/events/EventsPage.tsx frontend/src/app/i18n.tsx frontend/src/__tests__/event-filters.test.ts frontend/src/__tests__/events.test.tsx
git commit -m "feat(events): filter di URL, rentang Hari ini, grup Keamanan (tanpa absensi)"
```

---

### Task 3: Frontend — "Muat lebih banyak"

**Files:**
- Modify: `frontend/src/features/events/eventFilters.ts` (atau berkas baru `eventPaging.ts`; pilih satu dan konsisten), `frontend/src/features/events/EventsPage.tsx`, `frontend/src/app/i18n.tsx`
- Test: `frontend/src/__tests__/event-filters.test.ts` (atau `event-paging.test.ts`), `frontend/src/__tests__/events.test.tsx`

**Interfaces:**
- Produces: `LIMIT = 200`, `MAX_EVENTS = 1000`; `appendPage(prev: EventOut[], rows: EventOut[], cap: number): EventOut[]` (tambah di akhir, buang `id` yang sudah ada, potong `cap`); `mergeFirstPage(prev: EventOut[], rows: EventOut[], cap: number): EventOut[]` (`rows` di depan sesuai urutan server, lalu baris `prev` yang tidak ada di `rows` sesuai urutan lama, potong `cap`).
- Kunci i18n: `events.loadMore` "Muat lebih banyak" / "Load more"; `events.capHint` "Batas {n} event tercapai — persempit filter" / "Limit of {n} events reached — narrow the filters"; **ubah teks** `events.limitHint` menjadi "Menampilkan {n} event terbaru — muat lebih banyak atau persempit filter" / "Showing the latest {n} events — load more or narrow the filters" (`{n}` = jumlah termuat).

Keputusan perilaku: state `hasMore` (halaman terakhir yang diambil berisi tepat `LIMIT`) dan `loadingMore`; `refresh` karena filter berubah mengganti daftar (`setEvents(rows)`) dan menyetel `hasMore`; `refresh` yang dipicu interval klip tertunda memakai `mergeFirstPage(prev, rows, MAX_EVENTS)` dan **tidak** mengubah `hasMore`; tombol `data-testid="events-load-more"` tampil bila `hasMore && events.length < MAX_EVENTS && !loadingMore`; klik memanggil `listEvents({ …filter, limit: LIMIT, offset: events.length })`, hasil digabung `appendPage(prev, rows, MAX_EVENTS)`, `hasMore` diperbarui dari ukuran halaman; respons yang tiba setelah filter berubah dibuang (token permintaan yang sama dengan `refresh`); event live di-prepend dengan dedupe tanpa `slice(0, LIMIT)` (dibatasi `MAX_EVENTS`); hitungan `N+ event` bila `hasMore`; `event-limit-hint` tampil bila `hasMore` (teks `limitHint`, `{n}` = `events.length`); pada `events.length >= MAX_EVENTS` tombol hilang dan `data-testid="event-cap-hint"` menampilkan `capHint`.

- [ ] **Step 1: Uji gagal.** Fungsi murni: `appendPage` menambah di akhir dan membuang duplikat `id`, memotong `cap`; `mergeFirstPage` menaruh baris baru di depan, mempertahankan baris lama yang tak ada di `rows` berurutan, memotong `cap`, dan memperbarui isi baris dengan `id` sama. `events.test.tsx` (stub daftar yang menghormati `offset`): `'load more appends the next page and requests offset = loaded count'` (halaman pertama 200 → tombol ada → klik → request `offset=200` dan baris bertambah); `'load more does not duplicate rows that a live event shifted'` (satu id ada di kedua halaman → tampil sekali); `'load more button disappears when the last page is not full'`; `'load more stops at the cap and shows the cap hint'` (mock `MAX_EVENTS` melalui data: halaman berulang sampai 1000 → tombol hilang, `event-cap-hint` ada); `'interval refresh keeps already loaded pages'` (event segar tanpa klip memicu interval 5 dtk; setelah muat-lebih-banyak, baris halaman kedua tetap ada setelah interval); `'changing the filter while a load-more is in flight discards that response'` (tahan respons offset=200; ganti filter; selesaikan → daftar tidak berisi baris lama); `'filter change resets the list and hasMore'`. Jalankan → **FAIL**.
- [ ] **Step 2: Implementasi** fungsi murni, perubahan `EventsPage.tsx`, kunci i18n (id + en).
- [ ] **Step 3: Jalankan** berkas uji terkait → PASS; `npx vitest run` penuh → lulus; `npm run lint` → pasangan tidak bertambah.
- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/events frontend/src/app/i18n.tsx frontend/src/__tests__/event-filters.test.ts frontend/src/__tests__/events.test.tsx
git commit -m "feat(events): muat lebih banyak dengan offset, dedupe, dan batas 1000"
```

(Bila memakai `eventPaging.ts`/`event-paging.test.ts`, sesuaikan path `git add`.)

---

### Task 4: Frontend — tile Dashboard menaut ke tampilan setara

**Files:**
- Modify: `frontend/src/features/dashboard/KpiTiles.tsx` (`to` tile Event)
- Test: `frontend/src/__tests__/dashboard-blocks.test.tsx`

**Interfaces:**
- Produces: tile "Event hari ini" menaut ke `/events?type=security&range=today`; tile lain tidak berubah.

- [ ] **Step 1: Uji gagal:** ubah ekspektasi `'event tile shows total and critical count'` menjadi `href="/events?type=security&range=today"`; **tambah** `'event tile deep link yields the same filters the Events page reads'` yang memanggil `parseFilters` (Task 2) dengan query tile → `{ type: 'security', range: 'today' }`. Jalankan → **FAIL**.
- [ ] **Step 2: Implementasi** `to` tile Event; dependensi pada `eventFilters` hanya di uji.
- [ ] **Step 3: Jalankan** `npx vitest run src/__tests__/dashboard-blocks.test.tsx src/__tests__/dashboard.test.tsx` → PASS.
- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/dashboard/KpiTiles.tsx frontend/src/__tests__/dashboard-blocks.test.tsx
git commit -m "feat(dashboard): tile Event hari ini menaut ke Events (Keamanan, Hari ini)"
```

---

### Task 5: Frontend — tab Konfigurasi untuk viewer

**Files:**
- Modify: `frontend/src/features/config/ConfigurationPage.tsx`
- Test: `frontend/src/__tests__/configuration.test.tsx`

**Interfaces:**
- Consumes: `useOutletContext<Me | null | undefined>()` yang sudah dipakai halaman.
- Produces: tab terlihat = `restricted ? ['storage'] : TABS` dengan `restricted = me != null && me.role !== 'admin'`; `?tab=` di luar tab terlihat → tab terlihat pertama; `Tabs.selectedIndex` dihitung atas daftar terlihat; `onChange` memetakan indeks ke daftar terlihat.

- [ ] **Step 1: Uji gagal** (`configuration.test.tsx`; pasang halaman di dalam rute dengan `Outlet context`/`createMemoryRouter` atau komponen pembungkus yang memberi context; ikuti pola yang sudah ada di berkas): `'viewer sees only the Storage tab'` (satu `role="tab"` "Storage"; tab Kamera/Pengguna tidak ada); `'viewer with ?tab=users falls back to Storage'` (panel Storage tampil, tidak ada panggilan `/users`); `'admin sees all seven tabs'`; `'without a session context all seven tabs are shown'` (perilaku sekarang untuk uji/ memuat). Jalankan → **FAIL**.
- [ ] **Step 2: Implementasi** penyaringan tab di `ConfigurationPage.tsx`.
- [ ] **Step 3: Jalankan** `npx vitest run src/__tests__/configuration.test.tsx src/__tests__/shell.test.tsx` → PASS.
- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/config/ConfigurationPage.tsx frontend/src/__tests__/configuration.test.tsx
git commit -m "feat(config): viewer hanya melihat tab Storage di Konfigurasi"
```

---

### Task 6: Smoke test dan dokumen

**Files:**
- Modify: `WORKFLOW.md` (§8 Event Inbox, §15 Dashboard), `ARCHITECTURE.md` (parameter `offset` dan urutan), `README.md` (bila menyebut filter/Inbox), `ROADMAP.md`, `CHANGELOG.md`

- [ ] **Step 1: S1 suite penuh** di commit terakhir, **berurutan**: backend `.venv/bin/python -m pytest tests -q -m "not gpu"`; frontend `npx vitest run`, `npm run build`, `npm run lint` (pasangan rule/file tidak bertambah).
- [ ] **Step 2: S2 penjaga statis:** `rtk git diff --stat main...HEAD` hanya menyentuh berkas pada daftar **Files** tiap task + dokumen Task 6 + spec/plan; `git grep -nE "style=\{\{|#[0-9a-fA-F]{6}" -- frontend/src/features/events frontend/src/features/config` tidak menambah baris dibanding `main`; paritas kunci i18n id = en untuk kunci baru/berubah.
- [ ] **Step 3: S3 smoke render (tanpa screenshot):** `cd frontend && npm run dev`, Playwright MCP dengan mock `/api/v1/**` (sesi admin dan sesi viewer, `/events?` yang menghormati `offset` dengan ≥ 450 event). Di 1440 px dan 390 px: 0 error konsol; membuka `/events?type=system&severity=critical&range=today` memulihkan filter; ubah dropdown → URL berubah dan Back mengembalikan; "Muat lebih banyak" menambah baris; tile Dashboard "Event hari ini" membawa ke `/events?type=security&range=today`; sesi viewer di `/configuration` hanya menampilkan Storage; `scrollWidth <= innerWidth` di 390 px. Bila tak tersedia: tulis "S3 tidak dijalankan" beserta alasannya.
- [ ] **Step 4: Dokumen.** `WORKFLOW.md §8`: filter hidup di URL (param, nilai tak valid → default, reset menjaga `?event=`), rentang Hari ini, grup Keamanan, "Muat lebih banyak" (batas 1000). `§15`: tile Event menaut ke Events (Keamanan, Hari ini). `ARCHITECTURE.md`: `offset` dan urutan `ts_event DESC, id DESC`. `ROADMAP.md`: satu baris **tanpa `[x]`**. `CHANGELOG.md`: entri dengan konteks, file, **evidence berisi keluaran nyata**, dampak, rollback; catat bahwa uji UI user menyusul.
- [ ] **Step 5: Commit**

```bash
git add WORKFLOW.md ARCHITECTURE.md README.md ROADMAP.md CHANGELOG.md
git commit -m "docs: filter di URL, muat lebih banyak, tab Konfigurasi viewer — WORKFLOW, ARCHITECTURE, ROADMAP, CHANGELOG"
```
