# Spec — Tautan `/events?event=<id>` yang andal

Status: **menunggu review spec tertulis** (keputusan K1–K4 §2 default; konfirmasi bila berbeda).
Branch: `fix/events-deeplink` (dari `main` @ `9c8b220`).
Plan: `docs/superpowers/plans/2026-10-01-events-deeplink.md`.

---

## 1. Latar

Tautan `/events?event=<id>` dipakai di tiga tempat: caption Telegram (`telegram.py:224`), lonceng dan toast notifikasi (`NotificationBell.tsx:88`, `EventToasts.tsx:24`),
dan Dashboard (`RecentEvents.tsx:49`). Pemeriksaan kode menemukan dua cacat pada `EventsPage.tsx`.

### Kondisi kode (`main` @ `9c8b220`)

| # | Fakta | Lokasi |
|---|---|---|
| 1 | `selectedId` diinisialisasi dari `?event=` **hanya saat mount** (`useState(() => parse(searchParams.get('event')))`). Bila pengguna sudah berada di `/events` lalu mengeklik lonceng/toast, URL berubah tetapi pilihan tidak berpindah: klik terasa tidak berbuat apa-apa. | `EventsPage.tsx:~94` |
| 2 | Daftar hanya memuat 200 event terbaru (`limit` API ≤ 200). Tautan ke event yang lebih tua (tautan Telegram lama, event kemarin yang bukan 200 teratas) tidak ditemukan; `selected = filtered.find(...) ?? filtered[0]` diam-diam menampilkan **event pertama** — pengguna melihat event yang salah tanpa petunjuk. | `EventsPage.tsx:~225` |
| 3 | Tidak ada `GET /api/v1/events/{id}`; hanya daftar (`list_events`) dan `stats/today`. | `backend/app/api/events.py` |
| 4 | Klik baris daftar hanya mengubah state lokal; URL tidak mengikuti, sehingga tautan yang disalin dari bilah alamat tidak menunjuk event yang sedang dibuka. | `EventsPage.tsx` |

## 2. Keputusan

| # | Keputusan |
|---|---|
| K1 | **URL adalah sumber kebenaran pemilihan.** `selectedId` diturunkan dari `?event=`; klik baris menulis `?event=<id>` dengan `replace` (riwayat tidak menumpuk). Tanpa parameter → event pertama daftar, URL tidak ditulis. |
| K2 | Backend: `GET /api/v1/events/{event_id}` (int) → `EventOut`; 404 bila tidak ada; wajib login. Tanpa perubahan skema/migrasi. |
| K3 | Event yang diminta tetapi **tidak tampil di daftar saat ini** (di luar 200 terbaru, atau tersaring filter/pencarian) diambil sekali lewat id dan ditampilkan di panel detail ("disematkan") dengan catatan kecil. Tautan menang atas filter. |
| K4 | 404 → peringatan "Event #N tidak ditemukan — mungkin sudah dihapus oleh retensi" dan panel jatuh ke event pertama; kegagalan lain → "Gagal memuat event #N". Tidak pernah diam-diam menampilkan event lain tanpa pemberitahuan. |

## 3. Desain

### 3.1 Backend

`@router.get("/api/v1/events/{event_id}", response_model=EventOut)` di `app/api/events.py` (`event_id: int`, `get_current_user`, `db.get(Event, event_id)`, 404 `"event not found"`).
Tidak bentrok dengan `/api/v1/events/stats/today` (dua segmen). Logika sepele: tanpa service baru.

### 3.2 Frontend

- `api/events.ts`: `getEvent(id: number): Promise<EventOut | null>` — `null` pada 404, melempar `Error` pada status lain.
- `EventsPage.tsx`:
  - `eventParam` = bilangan bulat positif dari `searchParams.get('event')` (aturan parse yang sekarang), selain itu `null`. `selectedId = eventParam`.
  - Klik baris: `setSearchParams(prev => …set('event', id), { replace: true })`.
  - `pinned: { id: number; status: 'ok' | 'missing' | 'error'; event: EventOut | null } | null`. Efek mengambil `getEvent(eventParam)` sekali per `eventParam` ketika
    daftar selesai dimuat dan `eventParam` tidak ada di `filtered`; hasil dijaga `alive` dan dicocokkan dengan id (respons untuk id lama diabaikan).
  - `selected = filtered.find(id === eventParam) ?? (pinned.status === 'ok' && pinned.id === eventParam ? pinned.event : null) ?? filtered[0] ?? null`.
  - Panel detail dirender bila `selected` ada, walau `filtered` kosong (dulu pesan kosong menutup detail); pesan kosong hanya bila `filtered` kosong **dan** tidak ada `selected`.
  - Catatan "disematkan" (`data-testid="event-pinned-note"`) saat `selected` berasal dari `pinned`; peringatan `missing`/`error` memakai `InlineNotification` (kind `warning`/`error`).
  - Kunci i18n baru (id / en): `events.pinnedNote` "Event ini di luar daftar saat ini (filter atau 200 event terbaru)" / "This event is outside the current list (filters or latest 200)";
    `events.deeplinkMissing` "Event #{id} tidak ditemukan — mungkin sudah dihapus oleh retensi" / "Event #{id} not found — it may have been removed by retention";
    `events.deeplinkFailed` "Gagal memuat event #{id}" / "Failed to load event #{id}".
- Perilaku lama yang dipertahankan: parameter tak valid (`abc`, `0`, `-1`, `1.5`) → `null`; tab media kembali ke Snapshot saat event berganti; filter server-side dan live event tidak berubah.

### 3.3 Pengujian

Backend (`test_events_api.py`): `GET /events/{id}` → 200 isi `EventOut`; id tak ada → 404; tanpa login → 401; id bukan angka → 422; `stats/today` tetap berfungsi (regresi rute).

Frontend (`events.test.tsx`): `?event=<id>` di luar daftar diambil lewat id dan tampil dengan catatan disematkan (fetch by-id tepat sekali); event yang ada di daftar tidak memicu fetch by-id; 404 → peringatan dan panel jatuh ke event pertama; 500 → pesan gagal;
mengubah `?event=` saat halaman sudah terpasang (navigasi dari luar, seperti lonceng) memindahkan pilihan; klik baris menulis `?event=<id>` ke URL (lokasi) tanpa menambah entri riwayat; tanpa `?event` → event pertama dan URL tak berubah;
parameter tak valid diabaikan; event tersemat bertahan saat daftar di-refetch; daftar kosong + event tersemat tetap menampilkan detail.

Verifikasi akhir: `pytest tests -q -m "not gpu"`, `npx vitest run`, `npm run build`, `npm run lint` (tanpa pasangan rule/file baru); smoke render dengan mock. Uji UI oleh user setelah deploy.

### 3.4 Di luar scope

Filter di URL; paginasi; bukti permanen event system; perubahan lonceng/toast/Dashboard (mereka sudah menaut dengan benar); pencarian event berdasarkan UUID `event_id`.

## 4. Dokumen yang ikut berubah

`WORKFLOW.md §8` (perilaku tautan), `ARCHITECTURE.md` (kontrak `GET /events/{id}`), `README.md` bila menyebut tautan Telegram, `ROADMAP.md`, `CHANGELOG.md`.

## 5. Risiko dan rollback

| Risiko | Mitigasi |
|---|---|
| Menulis URL pada klik mengubah perilaku tombol Back. | `replace: true`; riwayat tidak menumpuk. |
| Event tersemat berumur lama: media sudah dihapus retensi. | Panel detail sudah menangani placeholder media tak tersedia. |
| Frontend baru dengan API lama (selisih deploy beberapa detik). | `getEvent` mendapat 404/405 → pesan "tidak ditemukan"; tidak crash. |

Rollback: `git revert` per commit task; tanpa migrasi DB.
