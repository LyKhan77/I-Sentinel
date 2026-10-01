# Spec — Bukti event system dan filter Events yang konsisten

Status: **Desain bagian 1–2 (bukti system, pendekatan B) DISETUJUI di chat (2026-10-01)**; bagian filter (A) diminta user dan
dirancang di sini; menunggu review spec tertulis. Keputusan D1–D3 (§2) butuh konfirmasi.
Branch: `feat/system-event-evidence` (dari `main` @ `b8c54db`).
Plan: `docs/superpowers/plans/2026-10-01-events-evidence-filters.md`.

---

## 1. Latar

Dua permintaan user atas halaman Events (`frontend/src/features/events/EventsPage.tsx`):
1. Event `system` (node offline/pulih, health alert) tidak punya bukti relevan; yang tampil hanya Snapshot dan Clip yang selalu kosong.
2. Filter belum konsisten dan tidak ada cara kembali ke "Semua".

### Kondisi kode (`main` @ `b8c54db`)

| # | Fakta | Lokasi |
|---|---|---|
| 1 | Panel detail `system` memakai layout event kamera: tab Snapshot/Clip kosong, meta "Kamera —" dan "Zona —", judul `system · cam null`; `payload` tidak pernah ditampilkan. Baris daftar menampilkan teks mentah `system` + thumbnail kosong. | `EventsPage.tsx:292-365, 353` |
| 2 | `clipPending` bernilai true 3 menit untuk event tanpa `clip_path` yang bukan attendance → event system memicu polling 5 dtk dan teks "Clip sedang direkam" yang tak pernah terpenuhi. | `EventsPage.tsx:172-187` |
| 3 | Payload node: `{node, reason}` (`reason` ∈ `timeout`, `lwt`, `online`). Payload health: `kind:"health"`, `rule`, `target` (`node:<id>` / `gpu:<node>:<idx>` / `cam:<id>`), `label`, `value`, `threshold`, `unit`, `duration_min`, `state` (`firing`/`resolved`), `lasted_min` atau `closed`. `Event.node_id` ada di API tetapi tipe frontend `EventOut` tidak memuatnya. | `node_health.py:32`, `health_alerts.py:133`, `api/events.ts` |
| 4 | `monitoring_sample` menyimpan bucket 1 menit per node selama 7 hari (CPU, RAM, GPU util/VRAM/suhu, ms/FPS inferensi, backlog MQTT, FPS dan umur frame per kamera). `GET /monitoring/history` hanya menerima rentang relatif terhadap sekarang: `1h`/`6h` = 60 dtk, `24h` = 300 dtk, `7d` = 1800 dtk. Alert 5 menit dari 3 hari lalu hanya satu bucket. | `monitoring_history.py:256, 262-340` |
| 5 | `_offline(db, node, start, now)` sudah memasangkan event offline → online menjadi periode (`to: null` bila belum pulih). | `monitoring_history.py:_offline` |
| 6 | Nilai alert `camera_low_fps` berupa **persen terhadap target FPS** (`fps / target_fps × 100`), bukan FPS mentah. | `health_alerts.py:_check` |
| 7 | Dropdown Tipe/Kamera/Severity berisi opsi tanpa "Semua"; Carbon `Dropdown` tak bisa membatalkan pilihan, jadi setelah memilih tak ada jalan kembali tanpa reload. Rentang waktu punya "Semua waktu". | `EventsPage.tsx:257-295` |
| 8 | Rentang waktu difilter di server (`since`, `limit: 200`) tetapi Tipe/Kamera/Severity difilter di klien atas 200 event terbaru. Event `attendance` (tiap lintasan face gate) memenuhi 200 teratas, sehingga event keamanan lama tak terjangkau filter; hitungan tidak memberi tahu bahwa daftar terpotong. | `EventsPage.tsx:94-105, 151-160` |
| 9 | Opsi Tipe diturunkan dari event yang sedang termuat: muncul/hilang saat data berubah, pilihan lama bisa tak ada di opsi; label mentah (`intrusion`). | `EventsPage.tsx:134` |
| 10 | API `GET /api/v1/events` mendukung `camera_id`, `type` berulang, `since`, `limit`; **belum** `severity`. | `backend/app/api/events.py:93-106` |
| 11 | `useLiveEvents` menambahkan event baru ke daftar tanpa memeriksa filter server-side yang aktif. | `EventsPage.tsx:118-132` |
| 12 | `eventTitle`, `eventWhere`, `sevClass` (judul/lokasi/severity event system sudah dilokalkan) ada di `features/notifications/labels.ts`; `LineChart` mendukung `shaded`, `refLine`, `from/to`. | `labels.ts`, `components/LineChart.tsx` |
| 13 | `GET /events/{id}` tidak ada: tautan `/events?event=<id>` ke event yang lebih tua dari 200 terbaru membuka event pertama. (Di luar scope, §3.5.) | `EventsPage.tsx:79-84` |

## 2. Keputusan

| # | Keputusan |
|---|---|
| K1 | Cakupan bukti = **B**: fakta + grafik tren (disetujui user). Bukti permanen di payload (C) ditunda. |
| K2 | Jendela grafik default ±30 menit (§3.3); dapat diubah. |
| **D1** | **Filter Events: Tipe, Kamera, Severity, Rentang semuanya server-side**; teks pencarian tetap klien. Menyelesaikan fakta #8. Butuh parameter `severity` di API (fakta #10). |
| **D2** | **Opsi Tipe statis** (daftar tipe yang diizinkan ingest, berlabel lokal) menggantikan opsi turunan data (fakta #9). |
| **D3** | Setiap dropdown punya opsi **"Semua"** sebagai item pertama; tombol **"Atur ulang filter"** muncul bila ada filter non-default. |

## 3. Desain

### 3.1 Bagian A — Filter Events

**Backend.** `GET /api/v1/events` mendapat `severity: list[str] | None = Query(None)` (berulang, `Event.severity IN (...)`), sama polanya dengan `type`.
Tanpa validasi nilai (nilai asing = hasil kosong). Kompatibel mundur.

**Frontend (`EventsPage.tsx`, `api/events.ts`, baru `features/events/eventTypes.ts`).**
- `EventListParams` mendapat `severities?: string[]`; `EventOut` mendapat `node_id?: number | null` (opsional di tipe; backend selalu mengirim).
- `EVENT_TYPES` = `intrusion, loitering, running, idle_zone, crowd, attendance, person_detect, system` (= `ALLOWED_TYPES` ingest);
  `eventTypeLabel(type, t)` memakai `zones.behavior.*` untuk lima behavior dan kunci baru `events.type.attendance|system|person_detect`;
  tipe tak dikenal → teks mentah.
- Item dropdown = `[SEMUA, ...opsi]`; `selectedItem = filter ?? SEMUA`; memilih SEMUA mengosongkan filter. Pola ini sama untuk Tipe, Kamera, Severity.
- `refresh` mengirim `types`, `camera_id`, `severities`, `since`, `limit: 200` dan dipanggil ulang saat salah satu filter berubah. Respons basi
  (permintaan lebih lama selesai belakangan) dibuang lewat penghitung permintaan.
- Predikat `matches(event)` (tipe/kamera/severity) tetap dipakai di daftar dan untuk event live yang masuk; pencarian teks tetap klien.
- Hitungan menjadi `N+ event` bila `events.length >= 200`, plus petunjuk "Menampilkan 200 event terbaru — persempit filter untuk melihat lebih banyak".
- Tombol "Atur ulang filter" (`data-testid="filter-reset"`) terlihat bila Tipe/Kamera/Severity terisi, Rentang ≠ "Semua waktu", atau pencarian tidak kosong;
  menekannya mengembalikan semuanya ke default.
- Kunci i18n baru (id / en): `events.type.attendance` "Absensi" / "Attendance"; `events.type.system` "Sistem" / "System";
  `events.type.person_detect` "Deteksi orang (debug)" / "Person detection (debug)"; `events.filterReset` "Atur ulang filter" / "Reset filters";
  `events.limitHint` "Menampilkan {n} event terbaru — persempit filter untuk melihat lebih banyak" / "Showing the latest {n} events — narrow the filters to see more".

### 3.2 Bagian B — Backend: jendela waktu di history

`GET /api/v1/monitoring/history` menerima mode jendela: `from`, `to` (ISO; naif = UTC), `node_id` opsional.
- `range` dan `from`/`to` saling eksklusif (keduanya → 422); `from` tanpa `to` atau sebaliknya → 422; `to <= from` → 422; `to - from > 6 jam` → 422.
- Tanpa satu pun parameter, perilaku lama tetap (`range` default `6h`).
- Bucket 60 dtk; respons berbentuk sama, `range: "custom"`, `from`/`to` = jendela; `offline` dihitung `_offline(db, node, from, to)` (periode terbuka di `to` → `to: null`).
- Jendela di luar retensi 7 hari menghasilkan seri kosong (bukan error). `node_id` membatasi `nodes` ke satu node.
- Implementasi: `query()` dipecah menjadi fungsi jendela yang dipakai kedua mode (`query_window(db, start, end, node_id=None)`); mode `range` tidak berubah perilaku.

### 3.3 Bagian B — Frontend: panel Bukti

- `api/monitoring.ts`: `getMonitoringHistoryWindow({ from: Date, to: Date, nodeId?: number })`; `MonitoringHistory.range` dilonggarkan menjadi `string`.
- `features/events/systemEvidence.ts` (fungsi murni): `systemEvidence(event, t, now)` → `{ kind: 'health'|'node'|'unknown', expired, nodeId, window, facts, charts }`.
  - **Fakta health:** Aturan (`health.rule.<rule>`), Target (`label`), Nilai (`value unit`), Ambang (`threshold unit`), Durasi aturan (`duration_min` mnt),
    Status ("Menyala"; "Pulih · selama N mnt" bila `lasted_min`; "Ditutup" bila `closed`).
  - **Fakta node:** Node, Penyebab (`timeout` "Heartbeat berhenti"; `lwt` "Koneksi MQTT node terputus"; `online` "Node kembali online"), Status.
  - **Jendela:** firing/offline: `[ts − 30 mnt, min(now, ts + 30 mnt)]`; resolved dengan `lasted_min`: `[ts − (lasted_min + 15) mnt, min(now, ts + 15 mnt)]`;
    node `online`: `[ts − 30 mnt, min(now, ts + 15 mnt)]`; panjang dibatasi 6 jam (potong dari sisi awal). Event lebih tua dari 7 hari → `expired`, tanpa jendela dan tanpa grafik.
  - **Grafik per rule** (bucket memakai agregat yang sama dengan pengecekan alert):

    | Rule | Seri (agregat) | Garis ambang |
    |---|---|---|
    | `node_cpu` / `node_ram` | `cpu_pct` / `ram_pct` (avg) | `threshold` % |
    | `infer_latency` | `ms_avg` (avg), `ms_max` (max) | `threshold` ms |
    | `mqtt_backlog` | `mqtt_backlog` (max) | `threshold` |
    | `gpu_temp` / `gpu_vram` | GPU `idx` dari `target gpu:<node>:<idx>`: `temp_c` / `vram_pct` (max) | `threshold` |
    | `camera_no_frames` | `frame_age_s` kamera `cam:<id>` (max) | `threshold` s |
    | `camera_low_fps` | `fps.min / target_fps × 100` kamera `cam:<id>` (fakta #6) | `threshold` % |
    | node offline/online | dua grafik: `cpu_pct` (avg), `infer_fps` (avg); arsir periode `offline` | — |

    Rule tak dikenal → fakta saja.
- `LineChart` mendapat prop `markers?: { t: number; label: string }[]` (garis vertikal bertanda waktu event; di luar `[from,to]` tidak digambar).
- `features/events/SystemEvidence.tsx` (`{ event }`, dipakai dengan `key={event.id}`): ringkasan + fakta + grafik; satu `getMonitoringHistoryWindow` per event terpilih bila
  ada jendela, `nodeId`, dan grafik. Status: memuat (skeleton), sukses, gagal ("Gagal memuat grafik", fakta tetap), kosong ("Tidak ada data tren pada jendela ini"),
  kedaluwarsa ("Data tren hanya disimpan 7 hari"), rule tak dikenal (fakta saja).
- `EventsPage.tsx` untuk `type === 'system'`: tanpa tablist/media, memakai `SystemEvidence`; judul dan lokasi memakai `eventTitle`/`eventWhere`; meta Kamera/Zona disembunyikan;
  baris daftar memakai judul + lokasi lokal dan ikon (bukan thumbnail kosong); `clipPending` selalu false; pencarian memakai `eventWhere` untuk event system.
- Kunci i18n baru (id / en) untuk fakta, status, penyebab, dan keadaan panel: `events.evidence.*`.

### 3.4 Pengujian

Backend (`test_events_api.py`, `test_monitoring_history.py`): filter `severity` (satu, berulang, gabungan dengan `type`); jendela history — hanya sampel di dalam jendela pada bucket 60 dtk,
`node_id`, semua kasus 422 (range+from, from tanpa to, `to <= from`, span 7 jam), default `range` tetap `6h`, periode offline terpotong di `to` dan terbuka → `null`, 401 tanpa login.

Frontend (`events.test.tsx`, `system-evidence.test.ts`, `system-evidence-panel.test.tsx`, `linechart.test.tsx`): dropdown "Semua" memulihkan hasil untuk Tipe/Kamera/Severity; filter dikirim ke API;
opsi Tipe statis dan berlabel; reset; `N+` dan petunjuk; event live yang tak cocok filter tidak ditambahkan; respons basi dibuang; jendela dan fakta per rule; setiap pemetaan grafik;
`camera_low_fps` dalam persen; kedaluwarsa tanpa permintaan; gagal/kosong; panel system tanpa tab media dan tanpa polling klip; judul dan meta lokal; `markers` di `LineChart`.

Verifikasi akhir: `pytest tests -q -m "not gpu"`, `npx vitest run`, `npm run build`, `npm run lint` (tanpa pasangan rule/file baru); smoke render dengan mock. Uji UI visual oleh user setelah deploy.

### 3.5 Di luar scope

Filter di URL; paginasi/"muat lebih banyak"; `GET /events/{id}` (fakta #13); bukti permanen di payload (K1 opsi C); bukti untuk event kamera; polling ulang grafik saat event masih berlangsung.

## 4. Dokumen yang ikut berubah

`WORKFLOW.md §8` (Inbox: filter dan bukti system), `ARCHITECTURE.md` (parameter `severity` dan mode jendela history), `docs/runbooks/monitoring.md` (mode jendela),
`README.md`, `ROADMAP.md`, `CHANGELOG.md`.

## 5. Risiko dan rollback

| Risiko | Mitigasi |
|---|---|
| Filter server-side memicu refetch tiap perubahan. | Hanya perubahan dropdown/rentang (bukan ketikan); respons basi dibuang. |
| `severity`/`from`/`to` baru di API. | Parameter opsional; perilaku lama tidak berubah; uji 422. |
| Grafik hanya untuk event ≤ 7 hari. | Pesan eksplisit; fakta tetap tampil. |
| Payload health lama tanpa field baru. | Semua field opsional → "—"; rule tak dikenal → fakta saja. |

Rollback: `git revert` per commit task; tanpa migrasi DB.
