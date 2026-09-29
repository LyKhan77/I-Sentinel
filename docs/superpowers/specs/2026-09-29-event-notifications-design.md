# Spec — Notifikasi event di web UI + outline tile Live View

Status: **DISETUJUI di chat (2026-09-29)**, menunggu review spec tertulis.
Branch: `feat/event-notifications` (dari `main` @ `8476792`).
Checkpoint: `.cooper/context/next-features.md`.

---

## 1. Latar

Usulan user: *"fitur notifikasi untuk web UI. notifikasi ini berdasarkan events saja. namun ada modifikasinya
yaitu pada halaman live views jika terjadi suatu events berikan suatu peringatan seperti tanda outline pada tile
camera ketika terjadi event pada camera tersebut."* Pemakaian utama: operator command center (Live View mode TV,
kiosk Pi tanpa mouse) dan user di PC.

### Kondisi kode (`main` @ `8476792`)

| # | Fakta | Lokasi |
|---|---|---|
| 1 | Event baru (status `created`) di-broadcast WS sebagai `EventOut` JSON (`id`, `type`, `camera_id`, `zone_id`, `severity`, `ts_event`, `payload`, ...). | `backend/app/services/events_consumer.py:69`, `backend/app/api/events.py:39` |
| 2 | WS juga membawa pesan non-event: `{"type":"detections",...}` (bbox realtime) dan `{"kind":"alert",...}` (status Telegram). | `events_consumer.py:38`, `services/alerting.py:119` |
| 3 | Event `system` dibuat saat LWT node vision (node mati / putus MQTT): `node_id`, `camera_id=null`, severity `warning`, `payload={"node", "reason":"lwt"}`. **Tidak di-broadcast WS** — hanya terlihat lewat polling. | `events_consumer.py:101-115` |
| 4 | `useLiveEvents(onEvent)`: polling `listEvents` tiap 5 s (poll pertama `limit=50` = event terakhir, lalu `since`) + WS sebagai enhancement. Event bisa datang dua kali (WS dan polling). | `frontend/src/api/useWs.ts` |
| 5 | `CameraTile` sudah punya `useInView` (IntersectionObserver); dipakai `LiveViewPage` dan `LiveTvPage` lewat `LiveWall`. | `frontend/src/features/live/LiveWall.tsx:22-26` |
| 6 | `/live/tv` berada di luar `AppShell` (tanpa header), di dalam `RequireAuth`; toolbar overlay auto-hide (`useIdle`). | `frontend/src/main.tsx:54-75`, `features/live/LiveTvPage.tsx` |
| 7 | Deep link detail event: `/events?event=<id>`. | `features/events/EventsPage.tsx:80` |
| 8 | Severity: `critical` / `warning` / `info` (kelas warna `ev-dot--*` sudah ada). | `EventsPage.tsx:13` |
| 9 | Payload behavior memuat `zone_name` (intrusion, idle_zone, crowd, dst.). | `vision/vision/analyzers/*.py` |
| 10 | Kiosk Pi sudah memakai `--autoplay-policy=no-user-gesture-required`. | `docs/runbooks/live-view-tv-pi.md:16` |

## 2. Keputusan user

| # | Keputusan |
|---|---|
| K1 | Pemicu: event behavior (`intrusion`, `loitering`, `running`, `idle_zone`, `crowd`) + `system`. `attendance` (dan `person_detect`) **tidak** memicu. |
| K2 | Outline tile hilang sendiri **30 s** sejak event terakhir di kamera itu (event baru memperpanjang). |
| K3 | Tile kena event tapi tidak terlihat (auto-scroll TV / scroll manual) → **chip indikator** di pojok; auto-scroll tidak diubah. |
| K4 | Status dibaca **per browser** (localStorage), tanpa backend. |
| K5 | **Bunyi** beep untuk event baru, bisa di-mute (per browser). |
| K6 | Backend tidak diubah. Notifikasi OS (Web Notification API) di luar scope: butuh secure context, app diakses via `http://` LAN. |

## 3. Desain

Satu sumber state global (**pendekatan A**): `EventAlertsProvider` dipasang di `RequireAuth` (membungkus `<Outlet />`),
sehingga berlaku untuk halaman `AppShell` dan `/live/tv`. Provider berlangganan `useLiveEvents` **satu kali** dan
membagikan state lewat context ke lonceng, toast, tile, chip, dan bunyi. Komponen lain tidak berlangganan sendiri
untuk keperluan notifikasi (menghindari bunyi ganda / state beda).

Modul baru: `frontend/src/features/notifications/`.

### 3.1 Provider — `EventAlertsProvider` + `useEventAlerts()`

- **Penyaring**: pesan dianggap event bila objek dengan `id: number`, `event_id: string`, `type: string`;
  hanya `type ∈ NOTIFY_TYPES = {intrusion, loitering, running, idle_zone, crowd, system}`. Pesan `detections`,
  `kind:"alert"`, `attendance`, `person_detect` diabaikan.
- **Anti duplikat**: `Set` id yang sudah dilihat (dibatasi ~500 id terakhir); event dengan id yang sudah ada dibuang.
- **Riwayat vs baru**: saat mount provider memanggil `listEvents({limit: 50})` sendiri → hasilnya = **riwayat**
  (masuk daftar + set id terlihat), **tanpa** toast / bunyi / outline. Pesan dari `useLiveEvents` yang tiba
  **sebelum** riwayat selesai dimuat ditampung dulu; setelah riwayat masuk, tampungan diproses: id yang ada di
  riwayat dibuang, sisanya = **baru**. Setelah itu setiap pesan dengan id belum terlihat = **baru**. (Poll pertama
  `useLiveEvents` juga `limit=50`, jadi isinya jatuh ke anti duplikat.) `listEvents` riwayat gagal → riwayat
  kosong dan pesan berikutnya dari aliran yang sudah ≥ 60 s lebih tua dari waktu browser dianggap riwayat.
- **State yang dibagikan**:
  - `recent: EventOut[]` — 20 event terakhir (urut `id` turun).
  - `unread: number` — jumlah di `recent` dengan `id > seenId`.
  - `markAllRead()` — `seenId = max id` di `recent`, simpan ke localStorage `isentinel_notif_seen`.
    Kunjungan pertama (key belum ada) → setelah riwayat dimuat `seenId = max id riwayat` (tanpa badge "20+" palsu).
  - `active: Record<cameraId, {type, severity, zoneName, until}>` — alert aktif per kamera; `until = now + 30 s`,
    event baru di kamera sama mengganti isi dan memperpanjang `until`. Kedaluwarsa dibersihkan timer 1 s.
  - `systemActive: {node, until}[]` — event `system` baru, aktif 30 s (untuk chip, karena tanpa kamera).
  - `toasts` + `dismissToast(id)` — maks 3 (yang terlama dibuang), auto-dismiss 8 s.
  - `muted: boolean`, `setMuted(v)` — localStorage `isentinel_notif_mute`.
- **Bunyi**: event baru dan tidak `muted` → beep pendek Web Audio API (oscillator ~880 Hz, ~150 ms), tanpa file
  audio; **throttle** maks 1 bunyi / 5 s. `AudioContext` tidak tersedia / di-suspend → diam tanpa error.
- **Nama kamera**: provider memanggil `listCameras()` sekali saat mount (gagal → tampilkan `#<camera_id>`).
- Semua akses localStorage dibungkus try/catch (private mode / diblokir → default: `seenId=0`, `muted=false`).

### 3.2 Lonceng di header (`NotificationBell`, di `AppShell` `HeaderGlobalBar`)

- Ikon lonceng (Carbon `Notification`) + badge jumlah `unread` (tampil `20+` bila ≥ 20; tanpa badge bila 0).
- Klik → panel dropdown: judul, toggle **Mute**, daftar `recent` (titik severity, label jenis, kamera / node,
  zona bila ada, waktu relatif/lokal). Kosong → teks "Belum ada event".
- Item diklik → navigasi `/events?event=<id>`, panel tertutup.
- Membuka panel → `markAllRead()`.
- Tombol "Lihat semua" → `/events`.
- 390 px: panel selebar layar (tanpa overflow horizontal); tutup dengan Escape / klik di luar.

### 3.3 Toast (`EventToasts`, di `AppShell` saja)

- Carbon `ToastNotification` low-contrast, kanan atas di bawah header; judul = jenis event, subjudul = kamera
  (+ zona) atau "Node <nama> offline" untuk `system`; `kind` dari severity (`critical`→error, `warning`→warning,
  `info`→info). Klik isi → detail event. Tidak ditampilkan di `/live/tv`.

### 3.4 Live View — outline tile + chip

- `CameraTile` membaca `active[cam.id]` dari context. Aktif → kelas `lv-tile--alert lv-tile--alert-<severity>`:
  outline 4 px warna severity, sama dengan titik severity halaman Events (`ev-dot`: critical `#fa4d56`, warning `#f1c21b`, info `#4589ff`), animasi kedip
  ~3 s lalu menyala tetap sampai `until`; label kecil di pojok tile: jenis event (+ zona). Berlaku di Live View
  normal, mode TV, dan modal tile besar.
- `prefers-reduced-motion` → tanpa kedip (outline tetap).
- **Chip** (`AlertChips`, dirender `LiveWall`): daftar alert aktif yang tile-nya **tidak terlihat** + semua
  `systemActive`. Teks: "⚠ <kamera> — <jenis>" / "⚠ Node <nama> offline". Tile melaporkan visibilitas ke
  `LiveWall` lewat callback `onVisibleChange(camId, inView)` dari `useInView` yang sudah ada.
  - Mode normal: klik chip kamera → `scrollIntoView` tile tsb.
  - Mode TV: chip hanya indikator; auto-scroll tetap berjalan.
  - Posisi **pojok kanan bawah** (fixed) di kedua mode: tidak bertabrakan dengan toast (kanan atas) maupun toolbar TV (atas).
  - Kamera yang tidak ada di layar ini (tidak dipilih di screen TV) **tidak** masuk chip (chip hanya untuk tile
    yang ada di wall); `system` selalu masuk.
- **Mute di TV**: toggle mute ditambahkan ke toolbar overlay `LiveTvPage` (memakai `setMuted` yang sama).

### 3.5 i18n

Semua string baru lewat `i18n.tsx` (id + en): judul panel, kosong, lihat semua, mute/unmute, label badge
aria ("N notifikasi belum dibaca"), "Node {node} offline". Label jenis memakai kunci yang sudah ada
(`zones.behavior.<kind>`, `storage.cleanup.type.system`).

## 4. Penanganan error

| Kondisi | Perilaku |
|---|---|
| WS gagal / ditolak | Polling 5 s tetap jalan (perilaku `useLiveEvents`); notifikasi telat ≤ 5 s |
| Event sama dari WS dan polling | Dibuang lewat anti duplikat id |
| Halaman dibuka dengan 50 event lama | Masuk riwayat lonceng saja; tanpa toast, bunyi, outline |
| Muat riwayat gagal | Riwayat kosong; event aliran dengan `ts_event` ≥ 60 s lebih tua dari jam browser = riwayat (tanpa toast/bunyi/outline) |
| `listCameras` gagal | Nama kamera jadi `#<id>` |
| localStorage tidak tersedia | Default (`seenId=0`, tidak mute); tanpa crash |
| Autoplay diblokir browser | Bunyi diam; visual tetap |
| Event untuk kamera yang tidak ada di wall | Tidak ada outline/chip; tetap di lonceng/toast |
| Event `system` (tanpa kamera) | Lonceng + toast + bunyi + chip 30 s; tanpa outline |

## 5. Pengujian (vitest, `frontend/src/__tests__/event-alerts.test.tsx`; `notifications.test.tsx` sudah dipakai tes Telegram)

- Provider: riwayat awal tidak memicu toast/bunyi/outline; event baru memicu ketiganya; duplikat (WS + polling)
  hanya dihitung sekali; `attendance`/`detections`/`kind:"alert"` diabaikan; outline hilang setelah 30 s dan
  diperpanjang event baru di kamera sama (fake timers); `system` masuk `systemActive` tanpa `active`.
- Bunyi: dipanggil untuk event baru; tidak saat `muted`; throttle 5 s.
- Lonceng: badge sesuai unread; buka panel → badge hilang dan tetap hilang setelah remount (localStorage);
  item → `/events?event=<id>`.
- Live View: tile kamera kena event punya kelas `lv-tile--alert-<severity>`; tile lain tidak; chip muncul untuk
  tile tidak terlihat (mock IntersectionObserver) dan untuk `system`; toggle mute di TV.
- 390 px tanpa overflow horizontal (panel lonceng).
- Baseline `main` `8476792`: backend 490, vision 223 (3 deselected), frontend 182, build 0.

## 6. Verifikasi lapangan (butuh izin user)

Deploy frontend (build/HMR; backend tanpa perubahan). Uji: buka Live View + mode TV di browser lain → picu intrusion
di satu kamera → toast + bunyi + badge di halaman biasa, outline 30 s di tile, chip saat tile di luar layar; reload
→ tanpa toast untuk event lama; buka lonceng → badge hilang; mute → tanpa bunyi; matikan node vision sebentar
(dengan izin) → chip "Node offline" + toast.

## 7. Di luar scope

Notifikasi OS / push (butuh HTTPS), status dibaca per user di server, notifikasi absensi, acknowledge per event,
broadcast WS untuk event `system`, event "node online kembali", Telegram untuk node offline, chip "node offline"
yang bertahan selama node masih offline (butuh status node realtime).

## 8. Rollback

`git revert` merge + build frontend. Tanpa migrasi / perubahan backend. Key localStorage
`isentinel_notif_seen` / `isentinel_notif_mute` diabaikan kode lama.
