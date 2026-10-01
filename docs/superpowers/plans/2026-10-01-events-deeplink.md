# Events Deep Link Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/events?event=<id>` selalu membuka event yang dituju: berpindah saat halaman sudah terbuka, menjangkau event di luar 200 terbaru, dan memberi tahu bila event tidak ada.

**Architecture:** Backend: `GET /api/v1/events/{event_id}`. Frontend: `?event=` menjadi sumber kebenaran pemilihan di `EventsPage`; event yang tak tampil di daftar diambil lewat id dan disematkan di panel detail.

**Tech Stack:** FastAPI + SQLAlchemy + pytest (SQLite uji); React 19 + TS + Carbon + Vitest/Testing Library.

**Spec:** `docs/superpowers/specs/2026-10-01-events-deeplink-design.md` (K1 URL = sumber kebenaran, K2 endpoint by-id, K3 sematan, K4 pesan 404/gagal).

## Global Constraints

- Branch `fix/events-deeplink` dari `main` @ `9c8b220`. Jangan `push`, jangan merge, jangan deploy, jangan ssh ke server.
- Commit Conventional Commits berbahasa Indonesia, satu per tugas, `git add` path spesifik. **Tanpa** `Co-Authored-By` atau atribusi AI apa pun (AGENTS.md §9).
- Frontend: komponen Carbon + kelas SCSS di `theme.scss` bila perlu gaya baru, **tanpa** `style={{}}` dan hex di TSX. REST hanya lewat `src/api/*`. String lewat `src/app/i18n.tsx` (id **dan** en).
- Lint: jangan `setState` sinkron di badan `useEffect` (`react/set-state-in-effect`); jangan baca/tulis `ref` di badan render. Dependensi efek berupa nilai primitif.
- Backend: parameter/endpoint baru tidak mengubah perilaku lama; `get_current_user` wajib.
- Uji tidak boleh mengunci detail implementasi: assert perilaku yang terlihat.

## Review Focus

1. `?event=` berubah saat `EventsPage` sudah terpasang (navigasi dari lonceng/toast) harus memindahkan pilihan → Task 2.
2. Event yang sudah ada di daftar tidak boleh memicu fetch by-id; event di luar daftar memicu tepat satu fetch → Task 2.
3. Parameter tak valid (`abc`, `0`, `-1`, `1.5`, kosong) diabaikan tanpa fetch → Task 2.
4. 404 dan 500 menghasilkan pesan berbeda dan panel tetap berfungsi (jatuh ke event pertama) → Task 2.
5. Respons by-id untuk `eventParam` lama tidak boleh menimpa pilihan baru (ganti `?event=` cepat) → Task 2.

---

### Task 1: Backend — `GET /api/v1/events/{event_id}`

**Files:**
- Modify: `backend/app/api/events.py` (setelah `list_events`)
- Test: `backend/tests/test_events_api.py`

**Interfaces:**
- Produces: `GET /api/v1/events/{event_id}` (`event_id: int`) → `EventOut`; 404 `{"detail": "event not found"}`; 401 tanpa login; 422 bila bukan angka. Rute `GET /api/v1/events/stats/today` tidak berubah.

- [ ] **Step 1: Baseline** — dari `backend/`: `.venv/bin/python -m pytest tests -q -m "not gpu"` → catat jumlah (baseline repo: **631 passed**).
- [ ] **Step 2: Uji gagal** di `test_events_api.py` (pakai `client`, `_payload`, `_admin_headers`, `_ingest_headers`): `test_get_event_by_id` (ingest satu event, ambil `id` dari respons ingest, `GET /api/v1/events/<id>` → 200, `event_id`/`type`/`severity` cocok); `test_get_event_by_id_not_found` (→ 404); `test_get_event_by_id_requires_auth` (→ 401); `test_get_event_by_id_rejects_non_integer` (`/events/abc` → 422); `test_stats_today_route_not_shadowed` (`/events/stats/today` tetap 200 berisi `total`). Jalankan `-k "event_by_id or not_shadowed"` → **FAIL** (404/405 untuk by-id).
- [ ] **Step 3: Implementasi** `get_event(event_id: int, user=Depends(get_current_user), db=Depends(get_db)) -> EventOut` dengan `response_model=EventOut`; `ev = db.get(Event, event_id)`; `HTTPException(404, "event not found")` bila `None`.
- [ ] **Step 4: Jalankan** `pytest tests -q -m "not gpu"` → semua lulus (baseline + 5).
- [ ] **Step 5: Commit**

```bash
git add backend/app/api/events.py backend/tests/test_events_api.py
git commit -m "feat(events): GET /events/{id}"
```

---

### Task 2: Frontend — `?event=` sebagai sumber kebenaran + sematan event

**Files:**
- Modify: `frontend/src/api/events.ts` (`getEvent`), `frontend/src/features/events/EventsPage.tsx`, `frontend/src/app/i18n.tsx`, `frontend/src/app/theme.scss` (hanya bila catatan sematan butuh gaya)
- Test: `frontend/src/__tests__/events.test.tsx` (tambah)

**Interfaces:**
- Produces: `getEvent(id: number): Promise<EventOut | null>` (`null` pada 404; `Error` pada status lain; URL `/events/<id>` lewat `apiFetch`).
- Kunci i18n baru (id / en): `events.pinnedNote`, `events.deeplinkMissing`, `events.deeplinkFailed` — teks persis spec §3.2 (`{id}` diganti lewat `.replace`).

Keputusan perilaku `EventsPage` (spec §3.2): `eventParam` = bilangan bulat positif dari `searchParams.get('event')` atau `null`; `selectedId = eventParam` (state `selectedId` dan `setSelectedId` dihapus); klik baris → `setSearchParams` bentuk fungsi yang menulis `event=<id>` dengan `{ replace: true }`; `pinned` + efek fetch tunggal per `eventParam` bila daftar selesai dimuat dan `eventParam` tidak ada di `filtered`; `selected` = `filtered.find(...)` ?? event tersemat bila `status === 'ok'` dan id cocok ?? `filtered[0]` ?? `null`; panel detail dirender bila `selected` ada walau `filtered` kosong, pesan kosong (`events.empty`/`events.emptyFiltered`) hanya bila tidak ada `selected`; catatan `data-testid="event-pinned-note"` saat `selected` berasal dari sematan; `missing` → `InlineNotification` warning `events.deeplinkMissing`, `error` → kind error `events.deeplinkFailed`.

- [ ] **Step 1: Baseline** — dari `frontend/`: `npx vitest run` (baseline repo: **32 files / 353 passed**), `npm run build`, `npm run lint` → 24 baris, catat per pasangan (rule, file).
- [ ] **Step 2: Uji gagal** (tambah ke `events.test.tsx`; ikuti `stubFetch`/`renderPage` yang ada, tambahkan stub `/events/<id>` yang menghitung panggilan; gunakan komponen penanda lokasi + tombol `useNavigate` seperti uji `event-alerts.test.tsx` untuk navigasi dari luar):
  - `'?event beyond the loaded list is fetched by id and pinned'`: daftar tanpa id 777; stub by-id mengembalikan event → detail menampilkan event itu, `event-pinned-note` ada, panggilan by-id tepat 1.
  - `'?event already in the list does not trigger a by-id fetch'`: 0 panggilan by-id.
  - `'?event with an invalid value is ignored without a fetch'`: loop `abc`, `0`, `-1`, `1.5` → event pertama terpilih, 0 panggilan by-id.
  - `'missing event shows a warning and falls back to the first event'` (404): peringatan memuat "tidak ditemukan", detail = event pertama.
  - `'by-id failure shows the failed message'` (500): pesan "Gagal memuat event" dan detail tetap berfungsi.
  - `'changing ?event while mounted selects that event'`: pasang di `/events`, navigasi ke `/events?event=2` → detail berpindah ke event 2.
  - `'clicking a row writes ?event= to the URL without adding history'`: klik baris → lokasi memuat `?event=<id>`; `history` tidak bertambah (navigate(-1) keluar dari halaman, atau cek `window.history.length`/`useNavigationType` = `REPLACE`).
  - `'no ?event keeps the first event selected and the URL untouched'`.
  - `'a stale by-id response does not override a newer selection'`: tahan respons by-id id=777 dengan promise manual, navigasi ke `?event=2`, selesaikan 777 → detail tetap event 2.
  - `'pinned event survives a list refetch'`: ubah filter (refetch) saat event tersemat → detail tetap event tersemat.
  - `'empty list with a pinned event still shows the detail'`.
  Jalankan `npx vitest run src/__tests__/events.test.tsx` → **FAIL** (perilaku baru belum ada; uji lama tetap hijau).
- [ ] **Step 3: Implementasi** `getEvent`, perubahan `EventsPage.tsx`, kunci i18n (id + en, paritas).
- [ ] **Step 4: Jalankan** `npx vitest run src/__tests__/events.test.tsx` → PASS (termasuk uji lama `?event=<id> opens that event in the detail panel`); `npx vitest run` penuh → lulus; `npm run build` → exit 0; `npm run lint` → pasangan (rule, file) tidak bertambah dari baseline.
- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/events.ts frontend/src/features/events/EventsPage.tsx frontend/src/app/i18n.tsx frontend/src/app/theme.scss frontend/src/__tests__/events.test.tsx
git commit -m "fix(events): tautan ?event=<id> berpindah saat terbuka, menjangkau event lama, memberi tahu bila hilang"
```

---

### Task 3: Smoke test dan dokumen

**Files:**
- Modify: `WORKFLOW.md` (§8 Event Inbox), `ARCHITECTURE.md` (kontrak `GET /events/{id}`), `README.md` (hanya bila menyebut tautan Telegram/Inbox), `ROADMAP.md`, `CHANGELOG.md`

- [ ] **Step 1: S1 suite penuh** di commit terakhir: backend `.venv/bin/python -m pytest tests -q -m "not gpu"`; frontend `npx vitest run`, `npm run build`, `npm run lint` (pasangan rule/file tidak bertambah).
- [ ] **Step 2: S2 penjaga statis:** `rtk git diff --stat main...HEAD` hanya menyentuh berkas pada daftar **Files** tiap task + dokumen Task 3 + spec/plan; paritas kunci i18n id = en untuk `events.*` yang baru.
- [ ] **Step 3: S3 smoke render (tanpa screenshot):** `cd frontend && npm run dev`, Playwright MCP dengan mock `/api/v1/**` (endpoint sesi, `/events?` berisi beberapa event, `/events/<id>` untuk event di luar daftar dan satu id yang 404). Di 1440 px dan 390 px: 0 error konsol; membuka `/events?event=<id luar daftar>` menampilkan event itu dengan catatan sematan; `/events?event=<id 404>` menampilkan peringatan; dari `/events` mengubah URL ke `?event=<id lain>` melalui `history.pushState` + popstate (atau klik tautan) memindahkan pilihan; klik baris memperbarui `?event=`; `scrollWidth <= innerWidth` di 390 px. Bila tak tersedia: tulis "S3 tidak dijalankan" beserta alasannya.
- [ ] **Step 4: Dokumen.** `WORKFLOW.md §8`: tautan `?event=` selalu membuka event yang dituju (berpindah saat terbuka, menjangkau event di luar 200 terbaru, pesan bila tidak ditemukan, klik baris memperbarui URL). `ARCHITECTURE.md`: kontrak `GET /api/v1/events/{id}`. `ROADMAP.md`: satu baris **tanpa `[x]`** (menunggu uji lapangan). `CHANGELOG.md`: entri dengan konteks, file, **evidence berisi keluaran nyata**, dampak, rollback; catat bahwa uji UI user menyusul.
- [ ] **Step 5: Commit**

```bash
git add WORKFLOW.md ARCHITECTURE.md README.md ROADMAP.md CHANGELOG.md
git commit -m "docs: tautan event by id — WORKFLOW, ARCHITECTURE, ROADMAP, CHANGELOG"
```
