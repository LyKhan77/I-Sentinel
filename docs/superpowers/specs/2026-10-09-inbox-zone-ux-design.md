# Spec — UX Inbox (pencarian, filter tipe) dan tujuan event per behavior zona (Mode uji)

Status: **Draft, keputusan arah disetujui di chat 2026-10-09**, menunggu review spec tertulis.
Branch: `feat/events-ux` (bertumpuk di atas `feat/face-attendance-unified` @ `f399998`+, karena server menjalankan branch itu; keduanya di-merge ke `main` bersamaan).
Konteks: `WORKFLOW.md` §6 (Zona), §9–10 (Events, Telegram), `docs/detection-behavior-inventory.md`.

Dua subsistem yang berdiri sendiri, masing-masing dengan plan sendiri: **A** halaman Events, **B** tujuan event per behavior zona.

---

## 1. Latar

Permintaan user (2026-10-09):
1. Zona deteksi: elemen radio untuk tujuan event: *All / Telegram only / Inbox only / Debugger only*; minta penilaian dan usulan yang lebih baik.
2. Halaman Events: pencarian dapat mencari nama karyawan; filter Tipe dirapikan berdasarkan semua tipe yang tersedia dan pengelompokannya; opsi "deteksi orang (debug)" dihapus; tambah "Semua kecuali system".

## 2. Temuan kode

| # | Temuan | Lokasi | Dampak |
|---|---|---|---|
| 1 | Pencarian Events berjalan di klien atas event yang sudah termuat; haystack = tipe, ID, severity, nama kamera, dan `JSON.stringify(payload)` (system: judul dan lokasi terjemahan) | `frontend/src/features/events/EventsPage.tsx` (±baris 282–289) | Nama (`payload.employee_name` absensi, `payload.face.name` intrusion) sudah cocok bila event ada di halaman termuat; event di halaman lebih lama tidak dicari |
| 2 | `GET /events` tidak punya parameter pencarian; `type` boleh berulang | `backend/app/api/events.py` (`list_events`) | Perlu parameter `q` baru |
| 3 | `SECURITY` = semua tipe kecuali `attendance` (termasuk `system` dan `person_detect`); `EVENT_TYPES` memuat 8 tipe termasuk `person_detect` | `eventFilters.ts` (`typesFor`), `eventTypes.ts` | Kelompok "Keamanan" tidak murni keamanan; perlu dirapikan |
| 4 | `person_detect` hanya muncul bila flag node `VISION_EMIT_PERSON_DETECT=true` (server: false) | `vision/vision/config.py`, `node.py` | Opsi filter-nya tidak berguna; tipe tetap valid di backend |
| 5 | Toggle Telegram per behavior (`zone-telegram-<kind>`) menulis `behaviors[].telegram`; alert memakai `_telegram_on` (item tanpa key → flag zona; zona pra-R5 → flag zona) | `ZonesPage.tsx` (±545), `backend/app/services/alerting.py:32`, `schemas/zone.py:24` | Tempat radio tujuan event menggantikan toggle |
| 6 | Event selalu tersimpan (Inbox); pesan Telegram berisi tautan `/events?event=<id>` dan media event itu | `alerting.py`, `WORKFLOW.md` §10 | "Telegram only" berarti event tersimpan tetapi disembunyikan: ditolak (lihat §3) |
| 7 | `CameraWorker.run` mem-publish overlay orang dengan `label: None` dan membuat event dari `az.on_frame(...)`; media per behavior dipasang lewat `_with_media` | `vision/vision/node.py` (±baris 168–214, 330–360) | Titik pemasangan Mode uji: tekan publish/enqueue event, tampilkan label overlay |
| 8 | Overlay `DetBox.label` untuk `kind: person` ditampilkan apa adanya (hanya kind `face` yang diterjemahkan) | `frontend/src/features/live/LiveWall.tsx` (±247–256) | Label uji dikirim sebagai kode `test:<kind>` dan diterjemahkan di UI |

## 3. Keputusan user

| Topik | Keputusan |
|---|---|
| Tujuan event | Radio **tiga pilihan** per behavior alert: *Inbox + Telegram*, *Hanya Inbox*, *Mode uji*. **Tanpa** "Telegram only" (event harus tetap tersimpan untuk tautan dan bukti; menyembunyikannya mengurangi jejak audit) |
| Mode uji | Zona dievaluasi, **tanpa event dan tanpa Telegram**; overlay Live View menampilkan label saat zona akan memicu |
| Pengaman Mode uji | Badge **UJI** di daftar zona, konfirmasi bila severity zona `critical`, dan **kedaluwarsa otomatis 24 jam** |
| Cakupan | Behavior alert (`intrusion`, `loitering`, `running`, `idle_zone`, `crowd`); **absensi tidak diubah** (punya `record`, `telegram_unknown`) |
| Filter Tipe | Dirapikan menurut semua tipe dan kelompoknya; default tidak ditentukan user ("rapihkan saja") → **default tetap Semua** |
| Pencarian | **Di server** atas semua halaman |

Penyempurnaan oleh perancang (perlu dikonfirmasi saat review): setelah kedaluwarsa, behavior **kembali ke nilai sebelum uji** (disimpan di `revert_to`, bawaan *Inbox + Telegram*), bukan selalu *Inbox + Telegram*; supaya zona yang sengaja "Hanya Inbox" tidak tiba-tiba mengirim Telegram.

## 4. Tujuan, kriteria sukses, non-tujuan

**Kriteria sukses** (diuji):
1. `GET /events?q=budi` mengembalikan event yang tipe, ID, nama kamera, atau teks payload (termasuk `employee_name` dan `face.name`) memuat "budi" (tidak peka huruf besar), di semua halaman, bersama filter lain (`type`, `camera_id`, `severity`, `since`) dan `before`/`limit`; `%` dan `_` diperlakukan literal; `q` kosong diabaikan; `q` > 100 karakter → 422.
2. UI Events: mengetik di pencarian memicu satu permintaan server setelah jeda 300 ms; daftar dan "muat lebih" memakai `q`; event live (WS) hanya masuk bila lolos filter dan `q`.
3. Dropdown Tipe: kelompok dan urutan seperti §5.2; opsi `person_detect` tidak ada; tautan lama `?type=person_detect` jatuh ke Semua; `?type=security` tetap valid (arti dirapikan).
4. Zona: setiap behavior alert punya radio tiga pilihan; nilai lama (`telegram` true/false atau tanpa key) terbaca sebagai *Inbox + Telegram* / *Hanya Inbox*; menyimpan menulis `delivery` dan menjaga `telegram` konsisten (`telegram = (delivery == "all")`) untuk node/API lama.
5. Mode uji: node tidak mem-publish event dari behavior itu (tidak ada Telegram, tidak ada Inbox, tidak ada klip), overlay orang yang memicu menampilkan `UJI · <tipe>` ±6 dtk; setelah `test_until` node dan API memperlakukannya sebagai `revert_to`, tanpa restart.
6. Badge UJI tampil di daftar zona selama uji berlaku; memilih Mode uji pada zona `critical` meminta konfirmasi.

**Non-tujuan:** "Telegram only", mode uji untuk absensi, penyimpanan event uji (dry-run dengan bukti) atau filter "Uji", pencarian dengan indeks teks penuh/trigram, pencarian diakritik, lonceng notifikasi per tipe.

## 5. Desain A — halaman Events

### 5.1 Pencarian di server
- **Backend (`api/events.py`):** parameter `q: str | None = Query(None, max_length=100)`. Setelah `strip`, bila tidak kosong: `Event.type`, `Event.event_id`, `Event.severity`, nama kamera (join `Camera`), dan `CAST(Event.payload AS TEXT)` dibandingkan `ILIKE %q%` dengan `%` `_` `\` di-escape (`escape="\\"`), digabung `OR`. Kecocokan teks payload mencakup `employee_name`, `face.name`, dan teks system. Berlaku bersama filter lain dan keyset/pagination yang ada. Catatan batas: pemindaian penuh pada rentang yang difilter; indeks trigram bila tabel > 100 ribu baris (komentar `ponytail:` di kode).
- **Klien (`api/events.ts`, `EventsPage.tsx`):** `EventListParams.q`; `q` ditulis ke URL tanpa jeda seperti sekarang (penyempitan instan atas event yang sudah termuat tetap berjalan), sedangkan **permintaan ke server memakai salinan ber-debounce 300 ms** (`refresh` dan `loadMore` mengirim `q`); `hasFilter`/`resetFilters` tetap. **Penyaringan klien dipertahankan sebagai lapis kedua** dan haystack-nya diperluas agar selalu ⊇ haystack server: event `system` ikut mencocokkan `type` dan teks payload (selain judul/lokasi terjemahan), sehingga hasil server tidak pernah hilang oleh saringan klien; event live memakai haystack yang sama.
- Batas yang diterima: judul system terjemahan (mis. "Node offline") hanya cocok bila ada di teks payload; event system lama dicari lewat tipe/ID/payload.

### 5.2 Filter Tipe
Dropdown dengan kepala kelompok (item `disabled` bergaya judul) dan urutan:

| Kelompok | Opsi (nilai URL) | Isi tipe |
|---|---|---|
| — | Semua (`null`) | tanpa filter |
| — | Semua kecuali sistem (`nosystem`) | semua tipe kecuali `system` |
| Kelompok | Keamanan (`security`) | `intrusion`, `loitering`, `running`, `idle_zone`, `crowd` (dirapikan: tanpa `system`/`person_detect`) |
| Kelompok | Absensi (`attendance`) | `attendance` |
| Kelompok | Sistem (`system`) | `system` |
| Per perilaku | Intrusion, Loitering, Running, Idle zone, Crowd | masing-masing satu tipe |

`person_detect` dihapus dari dropdown (tetap di `ALLOWED_TYPES` backend dan label; muncul di "Semua" bila ada). `parseFilters` menerima `nosystem` dan menolak `person_detect`; `typesFor`/`matchesFilters` diperbarui; i18n id/en untuk judul kelompok dan opsi baru.

## 6. Desain B — tujuan event per behavior zona

### 6.1 Data (tanpa migrasi; JSON `behaviors`)
Kunci baru per behavior alert: `delivery` ∈ {`all`, `inbox`, `test`}; `test_until` (ISO-8601 UTC, hanya bila `test`); `revert_to` ∈ {`all`, `inbox`} (hanya bila `test`). Tanpa `delivery`: diturunkan dari `telegram` (item) atau flag zona: true → `all`, false → `inbox`.
- **Validasi (`schemas/zone.py`):** nilai tidak sah → 422; `test_until`/`revert_to` dibuang bila `delivery != "test"`; `delivery` hanya untuk kind alert (bukan `attendance`).
- **Stempel server:** saat menyimpan zona, untuk behavior `test`: bila behavior itu sebelumnya bukan `test` atau `test_until` hilang/lampau/tak terbaca → `test_until = now + 24 jam` dan `revert_to` = delivery sebelumnya (`all` bila tidak ada); selain itu nilai tersimpan dipertahankan (menyimpan perubahan lain tidak memperpanjang uji).
- **Efektif:** fungsi murni `effective_delivery(behavior, zone_flag, now) -> "all" | "inbox" | "test"`: `test` yang `now >= test_until` → `revert_to`.

### 6.2 API (`services/alerting.py`)
`_telegram_on` memakai `effective_delivery(...) == "all"` (perilaku lama untuk item tanpa `delivery`). Event dari behavior `test` tidak pernah tiba (node menekannya); untuk node lama yang tetap mengirim, tidak ada Telegram.

### 6.3 Node (`vision/vision/node.py`, `analyzers`)
- `_make_analyzers` memasang `delivery`, `test_until`, `revert_to` pada tiap analyzer (seperti `_with_media`).
- `CameraWorker.run`: untuk tiap `partial` dari analyzer, bila efektif `test` (waktu dinding `time.time() < test_until`): **tidak** memanggil `_merge_event`/`transport.publish_event`/`recorder.enqueue`/`registry.bind`; sebagai gantinya catat `flash[track_id] = (f"test:{type}", frame.ts + 6.0)`. Overlay person yang dipublish memakai label flash untuk track itu selama berlaku. Setelah `test_until`, jalur normal.
- Perubahan behavior menyalakan/mematikan uji memicu restart kamera itu lewat diff config yang sudah ada; kedaluwarsa tidak memerlukan restart.

### 6.4 UI
- **`ZonesPage.tsx`:** untuk behavior alert, `RadioButtonGroup` tiga pilihan menggantikan `Toggle zone-telegram-<kind>`; teks bantu satu baris per pilihan; memilih *Mode uji* pada zona `severity === "critical"` membuka konfirmasi ("alert keamanan zona ini berhenti selama uji, kembali otomatis dalam 24 jam"); menyimpan menulis `delivery` dan `telegram = (delivery === "all")`. Absensi tidak berubah.
- Daftar zona menampilkan badge **UJI** (dengan "sampai HH:MM") selama `test_until` belum lewat.
- **`LiveWall.tsx`:** label `test:<tipe>` pada box `person` diterjemahkan menjadi `UJI · <label tipe>` (`live.testFired`); label lain tidak berubah.
- i18n `id`/`en` untuk radio, bantuan, badge, konfirmasi, dan label overlay.

## 7. Tes

Mengikuti berkas yang ada; tiap tes harus gagal pada bug yang masuk akal. Rincian di plan masing-masing.
- **A:** `backend/tests/test_events_api.py` (`q`: nama absensi, nama intrusion, kamera, ID, kasus huruf, escape `%`/`_`, `q` kosong, 422 panjang, kombinasi filter dan paging); `frontend/src/__tests__/events.test.tsx` (debounce: mengetik cepat memicu satu permintaan ber-`q`, `q` ikut `loadMore`, event live disaring, kelompok dan item dropdown, `nosystem`, `person_detect` tidak ada, URL lama). Tiga tes lama yang menyandikan perilaku lama diubah dengan alasan tercatat: pencarian tanpa permintaan baru, jumlah tipe grup `security`, dan opsi `Deteksi orang (debug)`.
- **B:** `backend/tests/test_zones_api.py` (validasi `delivery`, stempel `test_until` dan `revert_to`, menyimpan ulang tidak memperpanjang, absensi menolak `delivery`), `test_alerting.py` (`effective_delivery` murni termasuk kedaluwarsa, `_telegram_on` per mode dan kompatibilitas lama); `vision/tests/test_node.py` (behavior `test` tidak mem-publish/enqueue/bind, label flash pada overlay, kedaluwarsa memulihkan emisi tanpa restart, `all`/`inbox` tidak berubah); `frontend/src/__tests__/zones.test.tsx` (radio menulis `delivery` dan `telegram`, konfirmasi critical, badge UJI, nilai lama terbaca), `liveview.test.tsx` (label `test:intrusion` → `UJI · …`).

## 8. Dokumen

`WORKFLOW.md` §6 dan §9–10 (tujuan event, Mode uji, pencarian), `ARCHITECTURE.md` (kunci behavior baru, `q` di `GET /events`, alur flash overlay), `README.md`, `docs/runbooks/` (cara memakai Mode uji dan batasnya), `ROADMAP.md`, `CHANGELOG.md` per commit.

## 9. Risiko dan rollback

| Risiko | Mitigasi |
|---|---|
| Zona keamanan terlupa di Mode uji → alert mati diam-diam | kedaluwarsa 24 jam, badge UJI, konfirmasi `critical`; zona kembali ke `revert_to` |
| Jam node dan API berbeda (kedaluwarsa bergeser) | keduanya di server yang sama sekarang; Jetson memakai NTP; selisih detik tak berarti untuk 24 jam |
| Node lama mengabaikan `delivery` | event tetap tiba tanpa Telegram (API); dicatat di runbook |
| Pencarian `CAST(payload AS TEXT)` lambat pada tabel besar | rentang waktu/filter menyempit; indeks trigram bila > 100 ribu baris |
| Judul system terjemahan tak cocok di server | batas diterima (§5.1); tipe/ID/payload tetap dicari |

**Rollback:** A — `git revert`; B — set radio ke *Inbox + Telegram* atau `git revert` (tanpa migrasi; kunci JSON tak dikenal diabaikan kode lama).
