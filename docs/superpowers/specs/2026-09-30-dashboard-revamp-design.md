# Spec — Revamp halaman Dashboard (status-first)

Status: **Bagian 1–2 DISETUJUI di chat (2026-09-30)**, menunggu review spec tertulis. Satu keputusan baru (D1, §2) butuh konfirmasi.
Branch: `feat/dashboard-revamp` (dari `main` @ `8e57d09`).
Plan: `docs/superpowers/plans/2026-09-30-dashboard-revamp.md`.

---

## 1. Latar

Dashboard (`frontend/src/features/dashboard/DashboardPage.tsx`, 270 baris) belum mengikuti fitur yang sudah ada:
Monitoring (health rule + alert), Attendance, Storage, notifikasi realtime. Permintaan user: analisis dan rancang ulang
UI/UX-nya.

### Kondisi kode (`main` @ `8e57d09`)

| # | Fakta | Lokasi |
|---|---|---|
| 1 | Hanya 3 tile (Kamera, Event hari ini, Node). Tidak ada Attendance, health sistem, atau disk (disk hanya banner saat ≥ ambang). | `DashboardPage.tsx:176-214` |
| 2 | "Kamera online" = `camera.status === 'online'`; kamera tanpa frame / FPS rendah tetap hijau. Monitoring sudah punya `summary.cameras {ok,warning,critical}`. | `DashboardPage.tsx:142`, `api/monitoring.ts` |
| 3 | Tidak ada satu pun `<Link>`; `WORKFLOW.md §15` menulis "titik masuk ke Inbox, Live View, Monitoring". | `DashboardPage.tsx` (import), `WORKFLOW.md:220` |
| 4 | Event terbaru: 3 baris, `cam {id}` (bukan nama), tanpa snapshot, severity hanya warna dot, waktu tanpa tanggal. Polling 15 dtk padahal satu langganan realtime app-wide sudah ada. | `DashboardPage.tsx:228-267`, `EventAlertsProvider.tsx` |
| 5 | `GET /events/stats/today` hanya `{total, by_type}` dan **menghitung semua tipe, termasuk `attendance`** (tiap lintasan face gate) → angka "Event hari ini" membengkak di pabrik dengan banyak karyawan. | `backend/app/api/events.py:108` |
| 6 | Fetch gagal → kamera tampil `0/0` + "belum ada kamera"; notifikasi error di bawah halaman; storage gagal diam-diam. | `DashboardPage.tsx:123-158, 229-237` |
| 7 | Hex hard-coded (`#262626`, `#42be65`, …) + inline style di hampir semua elemen; AGENTS.md §6 meminta token `theme.scss` + Carbon. | `DashboardPage.tsx` |
| 8 | `useEventAlerts()` sudah menyediakan `recent` (event pemicu sejak 00:00 kemarin, terbaru dulu, diperbarui realtime) dan `cameraName(id)`. `NOTIFY_TYPES` = intrusion, loitering, running, idle_zone, crowd, system (tanpa attendance). | `EventAlertsProvider.tsx:10-17, 82-88` |
| 9 | `getHealthAlerts()` (`/monitoring/alerts`) = sumber yang sama dengan lonceng dan Telegram; `health.rule.*` i18n sudah ada. | `api/monitoring.ts`, `app/i18n.tsx:717` |
| 10 | `/events?event=<id>` (id numerik) membuka detail event; dibaca saat init. | `EventsPage.tsx:79-84` |
| 11 | `LineChart` SVG bersama (`components/LineChart.tsx`) menerima `series`, `from`, `to`, `bucketMs`, `locale`; celah bila titik > 1,5 bucket. Nilai tooltip selalu `toFixed(1)`. | `components/LineChart.tsx` |
| 12 | Baris `attendance_day` baru dibuat saat ada event wajah atau setelah batas shift (`close_due`) → "belum masuk" tidak bisa dihitung jujur sebagai penyebut. | `services/attendance.py` |

## 2. Keputusan

| # | Keputusan |
|---|---|
| K1 | Prioritas layout: **keamanan & kesehatan dulu** (disetujui user). |
| K2 | **Pendekatan B**: frontend + perluasan `stats/today` (chart event per jam). Disetujui user. |
| K3 | Tile kehadiran **tanpa penyebut**: hadir, telat, perlu koreksi. Disetujui user. |
| K4 | Chart memakai `LineChart` yang ada (bukan komponen bar baru). Disetujui user. |
| K5 | Kartu GPU lama dipangkas jadi baris node ringkas; detail di Monitoring. Disetujui user. |
| **D1** | **Butuh konfirmasi.** Endpoint `stats/today` **mengecualikan tipe `attendance`** dari `total`, `by_type`, `by_severity`, `by_hour` (fakta #5). Default saya: dikecualikan — tile "Event hari ini" adalah angka keamanan, dan ia sejalan dengan `NOTIFY_TYPES` di lonceng. Satu-satunya konsumen `stats/today` adalah Dashboard. Jika tidak setuju, hapus satu filter di backend; frontend tidak berubah. |

## 3. Desain

### 3.1 Backend — `GET /api/v1/events/stats/today`

Skema respons (baru `EventStatsOut` di `app/schemas/event.py`, dipasang sebagai `response_model`):

```json
{
  "total": 47,
  "by_type": {"intrusion": 12, "loitering": 8},
  "by_severity": {"critical": 3, "warning": 20, "info": 24},
  "by_hour": [0, 0, 1, "... 24 angka, indeks = jam lokal 0-23"],
  "critical_by_hour": [0, 0, 0, "... 24 angka"]
}
```

- `total` dan `by_type` tetap; tambah `by_severity` (selalu tiga kunci, 0 bila kosong), `by_hour`, `critical_by_hour`.
- Invarian: `sum(by_severity) == sum(by_hour) == total`; `sum(critical_by_hour) == by_severity.critical`.
- Filter: `ts_event >= midnight` (definisi hari yang sama dengan sekarang: `datetime.combine(date.today(), time.min).astimezone()`) dan
  `type != 'attendance'` (D1).
- Implementasi: logika pindah ke `backend/app/services/event_stats.py` (`today(db) -> dict`; konvensi: tanpa SQL di router, router tinggal memanggilnya). Satu query kolom `(type, severity, ts_event)`, dibucket di Python. Jam = `ts.astimezone().hour` (tz sistem, sama dengan
  definisi tengah malam); `ts` naif (SQLite uji) diperlakukan UTC. Portable Postgres/SQLite, satu jalur kode.
  `# ponytail: fetch O(event hari ini); pindah ke GROUP BY date_trunc bila volume > puluhan ribu/hari`.
- Kompatibel mundur: klien lama hanya membaca `total`/`by_type`.

### 3.2 Frontend — data

`useDashboardData()` (`features/dashboard/useDashboardData.ts`), polling 15 dtk (interval sekarang), satu `grab` per sumber agar
kegagalan terisolasi:

| Sumber | API | Dipakai untuk |
|---|---|---|
| `monitoring` | `getMonitoring()` | StatusStrip, tile Kamera, baris node |
| `alerts` | `getHealthAlerts()` (`.active`) | StatusStrip, ActiveIssues |
| `stats` | `eventStats()` (diperluas) | tile Event, EventsPerHour |
| `attendance` | `attendanceList()` (default hari ini) | tile Kehadiran |
| `storage` | `getStorageStats()` | tile Disk, `DiskAlertBanner` |

- Menggantikan `listCameras` + `listNodes` + `listEvents` (nama kamera dari `useEventAlerts().cameraName`; node dari `monitoring.nodes`).
- Hook mengembalikan `{ monitoring, alerts, stats, attendance, storage, updatedAt, failed }`. Tiap sumber menyimpan **nilai sukses terakhir**
  dan flag `failed[sumber]`; gagal tidak mengosongkan nilai lama.
- Event terbaru **tidak** dari hook ini: halaman membaca `useEventAlerts().recent` (tanpa langganan kedua). `stats` di-refetch saat
  `recent[0]?.id` berubah, sehingga tile dan chart ikut realtime tanpa menunggu 15 dtk.

### 3.3 Frontend — blok (`features/dashboard/`)

| Komponen | Isi |
|---|---|
| `StatusStrip` | Satu baris: titik + **teks** status dan `diperbarui HH:MM`, link `Monitoring →`. Keadaan: `monitoring.summary.health=ok` dan 0 alert → "Semua sistem normal"; ada alert aktif → "N peringatan aktif"; health ≠ ok tanpa alert → label `mon.health.*`; `monitoring` gagal → "Status sistem tidak tersedia". Sumber basi → "Gagal memperbarui — data terakhir HH:MM". |
| `KpiTiles` | 4 tile sebagai `<Link>` (satu elemen interaktif per tile): **Kamera** `ok/(ok+warning+critical)` dengan sub "N bermasalah"/"semua sehat" → `/monitoring`; **Event hari ini** `total` dengan sub "N critical" → `/events`; **Kehadiran** hadir (= baris dengan status ≠ `absent`) dengan sub "N telat · M perlu koreksi" (`late`; `no_exit`+`no_entry`) → `/attendance`; **Disk** `disk.percent` % dengan sub "X GB kosong" (`formatBytes`) → `/configuration?tab=storage`. Tanpa data → "—" (bukan 0). |
| `EventsPerHour` | `LineChart` 24 jam hari ini: seri `total` dan `critical`, titik per jam `t = awalHari + h·3600000`, **hanya jam ≤ jam sekarang** (tanpa garis nol palsu ke masa depan), `bucketMs=3600000`, `yMin=0`, `locale` dari `useT()`. `LineChart` mendapat prop `digits?: number` (default `1`) agar tooltip hitungan tampil "3", bukan "3.0". |
| `RecentEvents` | 8 baris dari `useEventAlerts().recent`: thumbnail `/api/v1/media/<snapshot_path>` (kelas `ev-thumb`, fallback `ev-thumb--empty` saat tak ada/`onError`), judul `eventTitle`, lokasi `eventWhere`, `Tag` severity **dengan teks**, waktu (jam; tanggal bila bukan hari ini). Baris = `<Link to={`/events?event=${id}`}>`. Kosong → "belum ada event". |
| `ActiveIssues` | `alerts.active` urut critical dulu, maks 5: `Tag` severity, judul `health.rule.<rule>`, `label`, nilai/ambang/unit. Kosong → "Tidak ada masalah aktif". Link "Semua →" ke `/monitoring`. |
| `NodeCompact` | Satu baris per `monitoring.nodes`: titik + teks Online/Offline, nama, `Tag` health, GPU pertama util %/VRAM % (atau "—"). Link "Detail di Monitoring →". |

Urutan halaman: `DiskAlertBanner` → `StatusStrip` → `KpiTiles` → `EventsPerHour` → grid dua kolom (`RecentEvents` | `ActiveIssues` + `NodeCompact`).
Badge detektor PIN/AUTO dan daftar proses GPU dihapus dari Dashboard (ada di Monitoring: `inference.detector.device`).

### 3.4 Loading, error, kosong

- Muat pertama: `SkeletonText` per blok (bukan satu skeleton global).
- Sumber gagal dan belum pernah sukses: blok menampilkan "Gagal memuat" inline + nilai "—"; **tidak pernah** angka 0 palsu (fakta #6).
- Sumber gagal tetapi punya nilai lama: tampilkan nilai lama; `StatusStrip` memberi tahu basi.
- `InlineNotification` error di bawah halaman dihapus (digantikan status per blok).

### 3.5 Gaya dan i18n

- Semua `style={{...}}` dan hex diganti kelas `.dash-*` di `frontend/src/app/theme.scss` dengan token Carbon
  (`--cds-layer-01`, `--cds-border-subtle`, `--cds-text-helper`, `--cds-support-success|warning|error`). Status tidak hanya warna: selalu ada teks.
- Responsif: KPI `repeat(auto-fit, minmax(160px, 1fr))` (2×2 di 390 px); grid dua kolom `minmax(0,3fr) minmax(0,2fr)` menjadi satu kolom di
  `max-width: 899px` (breakpoint yang sudah ada). Nol overflow horizontal di 390 px.
- Kunci i18n baru (id + en) di `app/i18n.tsx`: status strip, tile, chart, issues, node ringkas, "Gagal memuat". Kunci `dash.*` yang tak terpakai
  (`nodeHw`, `noGpuInfo`, `detector`, `pinned`, `auto`, `notPinned`, `vram`, `processes`, `latestAlerts`, `nodes`) dihapus;
  `cameras`, `eventsToday`, `noEvents`, `noCameras`, `noNodes`, `online`, `offline`, `sub` dipertahankan (masih dipakai).

### 3.6 Di luar scope

Widget yang bisa dikustomisasi; penyebut kehadiran ("112/130"); chart per kamera; endpoint agregat `/dashboard/summary`; perubahan Monitoring;
mode TV Dashboard.

## 4. Pengujian

Backend (`backend/tests/test_events_api.py`): `stats/today` — `attendance` tidak dihitung (D1); `sum(by_severity)==sum(by_hour)==total`;
event pada jam lokal tertentu masuk bucket jam itu; `critical_by_hour` benar; kunci severity selalu tiga; `total`/`by_type` tetap.

Frontend (`__tests__/dashboard.test.tsx` diganti; `linechart.test.tsx` ditambah `digits`):
- StatusStrip: ok / N alert / monitoring gagal / basi.
- Tile: nilai dari `monitoring.summary`, `stats`, `attendance`, `storage`; `—` saat sumber gagal; semua tile berupa link dengan `href` benar.
- RecentEvents: nama kamera (bukan ID), teks severity, link `/events?event=<id>`, tanggal untuk event bukan hari ini.
- ActiveIssues: urutan critical dulu; kosong.
- Refetch stats saat event realtime baru masuk.
- EventsPerHour: hanya titik jam ≤ sekarang.
- `LineChart digits=0`.

Verifikasi akhir (AGENTS §7.5): `pytest tests -q -m "not gpu"`, `npx vitest run`, `npm run build`, `npm run lint`; screenshot 1440 px dan 390 px
ke `docs/evidence/` (lokal, gitignored); `scrollWidth <= innerWidth` di 390 px.

## 5. Dokumen yang ikut berubah

`WORKFLOW.md §15`, `README.md` (ringkasan Dashboard + kontrak `stats/today` bila disebut), `ARCHITECTURE.md` (baris frontend `dashboard`, kontrak
`stats/today`), `CHANGELOG.md` (konteks, file, evidence, dampak, rollback), `ROADMAP.md` (siklus fitur).

## 6. Risiko dan rollback

| Risiko | Mitigasi |
|---|---|
| Angka "Event hari ini" turun (attendance dikecualikan). | D1 eksplisit; disebut di CHANGELOG; satu filter untuk dibalik. |
| "Kamera online" berganti makna menjadi "sehat" (health ok). | Label "sehat"; link ke Monitoring untuk rinci. |
| `recent` hanya `NOTIFY_TYPES` dan bergantung pada `EventAlertsProvider`. | Sumber sama dengan lonceng (konsisten); tes membungkus halaman dengan provider. |
| Fetch 5 sumber per 15 dtk. | Semua ringan dan read-only; `grab` terisolasi; tanpa langganan realtime kedua. |

Rollback: `git revert` commit per tugas; `stats/today` kompatibel mundur (tidak ada migrasi DB).
