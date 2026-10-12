# Spec — Tujuan event dan Mode uji untuk behavior absensi

Status: **Draft, arah disetujui user di chat 2026-10-12** ("konsistenkan semua type deteksi ... opsi 2 dengan mode uji, agar lebih simple"), menunggu review spec tertulis.
Branch: `feat/attendance-delivery` (dari `main` @ `87ed349`, yang sudah memuat radio tujuan event untuk behavior alert).
Konteks: `docs/superpowers/specs/2026-10-09-inbox-zone-ux-design.md` §6 (radio, Mode uji), `docs/runbooks/zone-test-mode.md`, `WORKFLOW.md` §12 (Absensi).

---

## 1. Latar

Spec 2026-10-09 membatasi radio tujuan event (*Inbox + Telegram* / *Hanya Inbox* / *Mode uji*) pada behavior alert dan membiarkan absensi dengan toggle sendiri (Telegram, Telegram wajah tidak dikenal, Catat absensi). Setelah UI dicoba, user meminta **semua tipe deteksi seragam**: absensi ikut radio yang sama, **termasuk Mode uji**.

## 2. Temuan kode

| # | Temuan | Lokasi | Dampak |
|---|---|---|---|
| 1 | `delivery` ditolak 422 untuk kind `attendance` (`ALERT_KINDS` tidak memuatnya) | `backend/app/services/zone_delivery.py`, `schemas/zone.py` | Daftar kind diperluas; tes validasi lama diubah |
| 2 | `_telegram_on(zone, kind, now)` sudah generik per kind lewat `effective_delivery` | `backend/app/services/alerting.py` | Absensi mengikuti `delivery` tanpa kode baru; `telegram_unknown` dan alasan `attendance_skipped` tetap |
| 3 | Event absensi dibuat `FaceGateWorker._emit` → `_finalize_event` (unggah media, `publish_event`); zona yang dibawa worker adalah dict config lengkap (`behaviors` ikut) | `vision/vision/face_worker.py` | Penekanan di `_emit` cukup; tanpa kunci config baru |
| 4 | `delivery_mode` (node) hidup di `node.py`, sedangkan `face_worker.py` hanya mengimpor `node` secara lazy (siklus impor) | `vision/vision/node.py` | Fungsi dipindah ke modul netral `delivery.py` |
| 5 | Blok absensi di UI: `Toggle zone-telegram-attendance` (+ `zone-telegram-unknown` bila Telegram aktif) dan `zone-record-attendance`; blok alert memakai radio `zone-delivery-<kind>` | `ZonesPage.tsx` | Radio dipakai bersama lewat komponen kecil; toggle Telegram absensi dihapus |
| 6 | Overlay Live View: label `test:<tipe>` hanya diterjemahkan untuk box `person`; box wajah (`face`) memakai kode gerbang atau nama | `LiveWall.tsx` (`boxLabel`) | Label uji diterjemahkan untuk semua kind box |

## 3. Keputusan user

| Topik | Keputusan |
|---|---|
| Cakupan | Absensi ikut radio tiga pilihan yang sama dengan behavior alert, termasuk Mode uji |
| Toggle Telegram absensi | Digantikan radio (`telegram = (delivery === "all")` tetap ditulis untuk kompatibilitas) |

Yang dipertahankan (bukan bagian keputusan, perancang): **Catat absensi** (`record`) dan **Telegram wajah tidak dikenal** (`telegram_unknown`, tampil hanya bila efektif *Inbox + Telegram*).

## 4. Tujuan, kriteria sukses, non-tujuan

**Kriteria sukses** (diuji):
1. API menerima `delivery`/`test_until`/`revert_to` pada behavior `attendance` dengan aturan stempel dan kedaluwarsa yang sama; kunci uji dibuang bila bukan `test`.
2. Telegram absensi: efektif `all` → perilaku lama (`matched`/`already_in`/`detected`, serta unknown sesuai `telegram_unknown`); `inbox` atau `test` → `telegram_off`; `test` kedaluwarsa mengikuti `revert_to`.
3. Node: zona absensi dengan `delivery` efektif `test` **tidak** membuat event (tanpa `publish_event`, tanpa unggah snapshot/crop, tanpa baris absensi), track ditandai selesai (tidak diulang), dan box wajah track itu berlabel `test:attendance` ±6 dtk; setelah `test_until` event terbit normal tanpa restart; zona tanpa `delivery` identik dengan sebelumnya.
4. UI: blok absensi memakai radio yang sama (`zone-delivery-attendance`), nilai lama `telegram: true/false` terbaca *Inbox + Telegram* / *Hanya Inbox*; konfirmasi pada zona `critical`; badge UJI mencakup behavior absensi; toggle `zone-telegram-attendance` hilang; `zone-telegram-unknown` tampil hanya saat efektif *Inbox + Telegram*; `zone-record-attendance` tetap.
5. Live View: box `face` dan `person` berlabel `test:<tipe>` tampil `UJI · <label tipe>`.

**Non-tujuan:** event uji tersimpan, menampilkan hasil pencocokan (nama) selama uji (pencocokan terjadi di API dan tidak ada event), mengubah `record`, pembatalan baris absensi lama, Mode uji untuk zona intrusion dengan `face_id` selain yang sudah ada.

## 5. Desain

- **Backend:** `DELIVERY_KINDS` (lima kind alert + `attendance`) menggantikan `ALERT_KINDS` di `zone_delivery.py` dan `schemas/zone.py`; tidak ada perubahan di `stamp_test_mode`, `effective_delivery`, atau `_telegram_on`.
- **Vision:** modul baru `vision/vision/delivery.py` memuat `wall_of`, `delivery_mode`, dan `delivery_cfg_for(behavior: dict, zone_telegram: bool) -> dict` (isi yang kini dibuat `VisionNode._with_delivery`); `node.py` mengimpornya dan tetap mengekspor `delivery_mode`. `FaceGateWorker._emit` memeriksa `delivery_mode(delivery_cfg_for(attendance behavior zona), time.time())` di awal: bila `test`, set `st.done = True`, catat `self._flash[tid] = ("test:attendance", ts + 6.0)` dan keluar tanpa antrean media/`publish_event`; label box wajah memakai flash (di bawah label identitas) dan entri basi dibuang tiap frame. Zona legacy tanpa `behaviors` → tanpa konfigurasi uji.
- **Frontend:** komponen `DeliveryRadio.tsx` (radio + teks bantu) dipakai blok behavior alert dan blok absensi; `zoneTestLabel` mencakup `attendance`; `LiveWall.boxLabel` menerjemahkan `test:<tipe>` untuk semua kind. Teks bantu *Inbox + Telegram* untuk absensi menyebut "wajah dikenali; wajah tidak dikenal mengikuti toggle di bawah".

## 6. Tes

Mengikuti berkas yang ada. Backend: `test_zones_api.py` (tes validasi lama `test_zone_delivery_validation` diubah: `delivery` pada `attendance` kini sah dan terstempel), `test_alerting.py` (kasus absensi per mode, tambahan). Vision: `test_face_worker.py` (tambahan: uji menekan event dan media, label, kedaluwarsa, zona tanpa `delivery`), `test_node.py` (impor `delivery_mode` tetap berfungsi; `delivery_cfg_for`). Frontend: `zones.test.tsx` (dua tes lama diubah karena toggle Telegram absensi diganti radio; tambahan: radio, konfirmasi, badge, Unknown bersyarat), `liveview.test.tsx` (label `test:attendance` pada box `face`).

## 7. Dokumen

`WORKFLOW.md` §6 dan §12, `docs/runbooks/zone-test-mode.md` (semantik absensi: tanpa event dan tanpa rekap; beda dengan Catat absensi yang masih menampilkan event "terdeteksi"), `ARCHITECTURE.md`, `README.md`, `ROADMAP.md`, `CHANGELOG.md`.

## 8. Risiko dan rollback

| Risiko | Mitigasi |
|---|---|
| Zona absensi terlupa di Mode uji → karyawan tidak tercatat diam-diam | pengaman yang sama: badge UJI, konfirmasi `critical`, kedaluwarsa 24 jam (kembali ke `revert_to`) |
| Node lama menerbitkan event absensi selama uji | API menolak Telegram; baris absensi tetap tercatat (didokumentasikan; `api`, `vision`, `web` di-deploy bersamaan) |
| Mode uji tidak menampilkan nama (pencocokan di API) | batas diterima; untuk melihat hasil pencocokan tanpa rekap gunakan Catat absensi mati |

**Rollback:** `git revert`; tanpa migrasi (kunci JSON tak dikenal diabaikan kode lama).
