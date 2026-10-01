# Spec — Events: filter di URL, "Muat lebih banyak", tab Konfigurasi untuk viewer

Status: **menunggu review spec tertulis** (keputusan D1–D6 §2 default; konfirmasi bila berbeda).
Branch: `feat/events-list-url-paging` (dari `main` @ `afd95ff`).
Plan: `docs/superpowers/plans/2026-10-01-events-list-url-paging.md`.
Seri: bagian 1 dari 2 backlog; bagian 2 = `2026-10-01-events-permanent-evidence-*` (dikerjakan setelah ini di-merge).

---

## 1. Latar

Backlog dari penutupan siklus deep link: filter Events di URL (sekaligus deep link dari Dashboard), paginasi, dan tab Konfigurasi untuk viewer.

### Kondisi kode (`main` @ `afd95ff`)

| # | Fakta | Lokasi |
|---|---|---|
| 1 | Filter Tipe/Kamera/Severity/Rentang/pencarian adalah `useState` lokal: hilang saat reload, tak bisa dibagikan, Back/Forward tidak memulihkannya. Hanya `?event=` yang hidup di URL. | `EventsPage.tsx` |
| 2 | Tile Dashboard "Event hari ini" menaut ke `/events` polos. Angkanya = sejak tengah malam **tanpa** `attendance` (D1 siklus Dashboard), tetapi Events hanya punya rentang 24 jam/7 hari/30 hari dan tipe tunggal → tidak ada padanan, angka pasti berbeda. | `KpiTiles.tsx:31`, `event_stats.py` |
| 3 | Daftar dibatasi 200 (`LIMIT`); `refresh` **mengganti** seluruh daftar; event live memakai `slice(0, LIMIT)`; interval 5 dtk untuk klip tertunda memanggil `refresh`. Tidak ada cara memuat yang lebih lama. | `EventsPage.tsx` |
| 4 | `GET /api/v1/events` tanpa `offset`; urutan `ts_event DESC` tanpa pemutus seri → halaman berikut tidak deterministik bila `ts_event` sama. | `backend/app/api/events.py` |
| 5 | Menu Konfigurasi hanya untuk admin, tetapi route `/configuration` terbuka dan menampilkan ketujuh tab; hanya Storage yang dirancang read-only untuk non-admin (`isAdmin`). Endpoint admin ditegakkan backend. | `ConfigurationPage.tsx`, `StoragePage.tsx` |

## 2. Keputusan

| # | Keputusan |
|---|---|
| D1 | **URL = sumber kebenaran filter** (pola sama dengan `?event=` siklus lalu): `type`, `camera`, `severity`, `range`, `q`. Nilai default tidak ditulis; nilai tak valid = default. Perubahan memakai `replace` (riwayat tidak menumpuk). |
| D2 | Rentang baru `today` (sejak 00:00 lokal) di samping `all`/`24h`/`7d`/`30d`. |
| D3 | Opsi tipe baru **"Keamanan (tanpa absensi)"** (`type=security`) = semua tipe kecuali `attendance`; dikirim ke server sebagai daftar `types`. Menyamakan semantik dengan tile Dashboard. |
| D4 | Paginasi `offset` + dedupe klien (bukan keyset): halaman berikut dapat mengulang baris saat event baru masuk, tidak melewatkan; duplikat dibuang berdasarkan `id`. Ditambah pemutus seri `id DESC`. |
| D5 | Tombol **"Muat lebih banyak"**; daftar maksimal `MAX_EVENTS = 1000` baris di klien. |
| D6 | Viewer melihat **hanya tab Storage** di Konfigurasi (read-only); tab lain disembunyikan. Admin tidak berubah. |

## 3. Desain

### 3.1 Backend

`GET /api/v1/events` mendapat `offset: int = Query(0, ge=0, le=10_000)` dan urutan `ORDER BY ts_event DESC, id DESC`. Perilaku lama (tanpa `offset`) identik. Tanpa migrasi.

### 3.2 Filter di URL

Berkas baru `features/events/eventFilters.ts` (fungsi murni):

| Param | Nilai valid | Default (tidak ditulis) |
|---|---|---|
| `type` | `security` atau salah satu `EVENT_TYPES` | tidak ada |
| `camera` | bilangan bulat positif | tidak ada |
| `severity` | `critical` \| `warning` \| `info` | tidak ada |
| `range` | `all` \| `today` \| `24h` \| `7d` \| `30d` | `all` |
| `q` | teks, dipotong 100 karakter | kosong |
| `event` | (tetap seperti siklus deep link) | tidak ada |

- `parseFilters(params)` → `{ type, camera, severity, range, q }` dengan koersi nilai tak valid ke default; `writeFilters(prev, patch)` → `URLSearchParams` baru (menjaga param lain termasuk `event`; menghapus param bernilai default); `typesFor(type)` → daftar tipe untuk server (`security` → semua kecuali `attendance`; tipe tunggal → `[type]`; `null` → `undefined`); `sinceFor(range, now)`; `matchesFilters(event, filters)` (tipe/kamera/severity, dipakai daftar dan event live).
- `EventsPage` menurunkan nilai filter dari `useSearchParams` (state lokal `typeFilter/camFilter/sevFilter/range/query` dihapus); setiap dropdown/rentang/pencarian menulis lewat `setSearchParams(prev => writeFilters(prev, …), { replace: true })`.
- "Atur ulang filter" menghapus kelima param filter dan menjaga `event`. `hasFilter` diturunkan dari URL.
- Dropdown Tipe: `[Semua, Keamanan (tanpa absensi), ...EVENT_TYPES]`. Kunci i18n baru (id / en): `events.range.today` "Hari ini" / "Today"; `events.type.security` "Keamanan (tanpa absensi)" / "Security (excluding attendance)".
- Kamera di URL yang tidak ada lagi: dropdown menampilkan "Semua" tetapi filter tetap berlaku dan tombol reset terlihat (kasus langka, dapat dipulihkan).
- Tile Dashboard "Event hari ini" menaut ke `/events?type=security&range=today`.

### 3.3 Muat lebih banyak

- Konstanta `LIMIT = 200` (ukuran halaman), `MAX_EVENTS = 1000`. State baru: `hasMore` (halaman terakhir yang diambil penuh `LIMIT`), `loadingMore`.
- Fungsi murni (di `eventFilters.ts` atau `eventPaging.ts`): `appendPage(prev, rows, cap)` (tambah di akhir, buang `id` yang sudah ada, potong `cap`) dan `mergeFirstPage(prev, rows, cap)` (`rows` di depan sesuai urutan server + baris `prev` yang tidak ada di `rows` dengan urutan lama, potong `cap`).
- `refresh` karena **filter berubah** mengganti seluruh daftar dan mengatur ulang `hasMore`; `refresh` dari **interval klip tertunda** memakai `mergeFirstPage` (halaman yang sudah dimuat tidak hilang).
- Klik "Muat lebih banyak" (`data-testid="events-load-more"`, tampil bila `hasMore` dan `events.length < MAX_EVENTS`): `listEvents({ …filter, limit: LIMIT, offset: events.length })`, hasil digabung `appendPage`, `hasMore` = ukuran halaman penuh. Respons yang tiba setelah filter berubah dibuang (token yang sama dengan `refresh`).
- Event live: prepend dengan dedupe tanpa `slice(0, LIMIT)`, dibatasi `MAX_EVENTS`.
- Hitungan: `N+ event` bila `hasMore`. Petunjuk `events.limitHint` diubah menjadi "Menampilkan {n} event terbaru — muat lebih banyak atau persempit filter" / "Showing the latest {n} events — load more or narrow the filters" (`{n}` = jumlah termuat); pada batas `MAX_EVENTS`, kunci baru `events.capHint` "Batas {n} event tercapai — persempit filter" / "Limit of {n} events reached — narrow the filters" menggantikan tombol.

### 3.4 Konfigurasi untuk viewer

`ConfigurationPage`: `restricted = me != null && me.role !== 'admin'`; tab terlihat = `restricted ? ['storage'] : semua`; `?tab=` di luar tab terlihat → tab pertama yang terlihat; `selectedIndex` dihitung atas tab terlihat. `me` null/undefined (memuat, atau uji tanpa shell) → semua tab (perilaku sekarang).

### 3.5 Pengujian

Backend (`test_events_api.py`): `offset` menggeser hasil dan halaman tidak tumpang tindih; urutan deterministik untuk `ts_event` sama (id turun); `offset` negatif/di atas 10 000 → 422; tanpa `offset` identik dengan sebelumnya.

Frontend: `eventFilters` (parse default + nilai tak valid, write menjaga `event` dan menghapus default, `typesFor`, `sinceFor`, `matchesFilters`, `appendPage`, `mergeFirstPage`); `events.test.tsx` (filter hidup dari URL awal; mengubah filter menulis URL dengan `replace`; reset menjaga `event`; Back/Forward memulihkan; rentang `today` mengirim `since` tengah malam; `type=security` mengirim daftar tipe tanpa `attendance`; muat lebih banyak menambah dan tidak menduplikasi; tombol hilang bila halaman tak penuh dan di `MAX_EVENTS`; `refresh` interval tidak membuang halaman termuat; ganti filter saat muat-lebih-banyak berjalan → respons dibuang); `dashboard-blocks.test.tsx` (tile Event menaut ke `/events?type=security&range=today`); `configuration.test.tsx` (viewer hanya Storage dan `?tab=users` jatuh ke Storage; admin tujuh tab; `me` kosong tujuh tab).

Verifikasi akhir: `pytest tests -q -m "not gpu"`, `npx vitest run`, `npm run build`, `npm run lint` (tanpa pasangan rule/file baru), dijalankan **berurutan**; smoke render dengan mock. Uji UI oleh user setelah deploy.

### 3.6 Di luar scope

Gulir tak hingga; pencarian teks di server; menyimpan filter di `localStorage`; paginasi keyset; bukti permanen event system (spec terpisah); route guard `/configuration`.

## 4. Dokumen yang ikut berubah

`WORKFLOW.md §8` dan `§15`, `ARCHITECTURE.md` (parameter `offset`), `README.md`, `ROADMAP.md`, `CHANGELOG.md`.

## 5. Risiko dan rollback

| Risiko | Mitigasi |
|---|---|
| Menulis URL per ketikan pencarian. | `replace`; `q` tidak memicu fetch (klien); dipotong 100 karakter. |
| `refresh` interval menimpa halaman yang sudah dimuat. | `mergeFirstPage`; uji khusus. |
| `offset` tidak stabil saat event baru masuk. | Dedupe `id`; hanya dapat mengulang, tidak melewatkan. |
| Viewer kehilangan akses tab lain lewat URL. | Disengaja (D6); backend tetap menegakkan role. |

Rollback: `git revert` per commit task; tanpa migrasi DB.
