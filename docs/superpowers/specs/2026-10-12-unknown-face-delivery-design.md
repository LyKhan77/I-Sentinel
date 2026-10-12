# Spec — Tujuan wajah tidak dikenal (Inbox / Telegram) per zona absensi

Status: **Draft, desain disetujui user di chat 2026-10-12** ("Desain benar, lanjut buat branch dan tulis spec+plan langsung"); user melewati review spec tertulis dan meminta plan langsung.
Branch: `feat/unknown-face-delivery` (dari `main` @ `73bc4cf`).
Konteks: `docs/superpowers/specs/2026-10-12-attendance-delivery-design.md` (radio tujuan event absensi, toggle `telegram_unknown` yang dipertahankan), `WORKFLOW.md` §12 (Absensi), `docs/runbooks/attendance.md`.

---

## 1. Latar

Di Zona Deteksi, blok **Absensi** punya toggle **Kirim wajah tidak dikenal** (`telegram_unknown`). Toggle itu hanya mengatur Telegram dan hanya tampil bila tujuan event efektif *Inbox + Telegram*. Event wajah tidak dikenal selalu masuk Inbox, tanpa pilihan. User ingin satu opsi per zona yang menentukan ke mana wajah tidak dikenal berlaku: **Inbox** dan/atau **Telegram**. Bentuk yang dipilih user: radio tiga pilihan (*Inbox + Telegram* / *Hanya Inbox* / *Tidak dikirim*), karena alert Telegram bertaut ke baris event sehingga Telegram tanpa Inbox tidak mungkin.

## 2. Temuan kode

| # | Temuan | Lokasi | Dampak |
|---|---|---|---|
| 1 | Toggle `zone-telegram-unknown` tampil hanya saat efektif `all` dan menulis `telegram_unknown` | `frontend/src/features/config/ZonesPage.tsx` (blok `selected.type === 'attendance'`) | Diganti radio baru yang selalu tampil (kecuali Mode uji) |
| 2 | Gerbang Telegram untuk `no_match` membaca `zone.behavior_flag("attendance", "telegram_unknown")` | `backend/app/services/alerting.py` `should_alert` | Dibaca lewat fungsi `unknown_delivery` |
| 3 | Pencocokan wajah terjadi di API setelah event di-ingest dan di-commit (`handle_face_event`; embedding dikirim node, mode unified pun dicocokkan di API) | `backend/app/services/attendance.py`, `events_consumer.py` | Node tidak tahu hasil; "Tidak dikirim" harus dilakukan di API, tidak bisa di node seperti Mode uji |
| 4 | Urutan consumer: `ingest_event` → `handle_face_event` → `alerting.handle` → caption AI → `intrusion_face` → `hub.broadcast`; pesan media (`MEDIA_TOPIC`) menyusul dan mencatat warning bila baris event tidak ada | `events_consumer.py` | Titik buang: sesudah `handle_face_event`, sebelum alert/AI/broadcast; pesan media susulan harus ditangani tanpa warning |
| 5 | File media sudah ada di storage sebelum event: `crop_path` di payload, `snapshot_path`/`clip_path` di baris event atau menyusul lewat topik media; retensi punya sapuan orphan berdasarkan mtime | `services/retention.py` (`_safe_join`, sapuan lapis 2) | Event yang dibuang ikut menghapus file yang dikenal; sisanya ditangani sapuan orphan |
| 6 | Inbox menampilkan `no_match`, `low_quality`, dan `ambiguous` sebagai "Tidak dikenal"; Telegram hanya untuk `no_match` | `EventsPage.tsx` (`faceMatch`), `alerting.should_alert` | "Tidak dikirim" membuang ketiganya; aturan Telegram tidak berubah |
| 7 | `config_push.build_node_config` meneruskan `behaviors` mentah ke node; node mengabaikan kunci tak dikenal | `services/config_push.py` | Tanpa perubahan vision. Menyimpan perubahan ini ikut mendorong config zona, sama dengan toggle lama |
| 8 | Lima tes `zones.test.tsx` mengunci toggle lama (`zone-telegram-unknown`) | `frontend/src/__tests__/zones.test.tsx` | Lima tes itu diubah; semua tes backend lama lulus tanpa perubahan |

## 3. Keputusan user

| Topik | Keputusan |
|---|---|
| Bentuk opsi | Tiga pilihan radio: *Inbox + Telegram* / *Hanya Inbox* / *Tidak dikirim* |
| Arti "Tidak dikirim" | Event wajah tidak dikenal dibuang di API setelah pencocokan: tanpa baris event, tanpa Telegram |
| Cakupan buang | `no_match`, `ambiguous`, `low_quality` (asumsi yang disetujui) |
| Branch, lokasi spec dan plan | `feat/unknown-face-delivery`; `docs/superpowers/specs|plans/2026-10-12-unknown-face-delivery*` |

Diputuskan perancang (bukan keputusan user): zona lama tidak berubah perilaku; opsi tampil selalu kecuali Mode uji; pilihan *Inbox + Telegram* nonaktif bila tujuan utama bukan *Inbox + Telegram*.

## 4. Tujuan, kriteria sukses, non-tujuan

**Kriteria sukses** (diuji):
1. API menerima `unknown_delivery` ∈ `all` | `inbox` | `none` pada behavior `attendance`; nilai lain atau kunci itu pada kind lain ditolak 422.
2. Fungsi `unknown_delivery(behaviors)` mengembalikan kunci bila sah; bila tidak ada: `telegram_unknown == false` → `inbox`, selain itu `all`. Zona tanpa `behaviors` → `all`. Zona lama berperilaku persis seperti sebelumnya.
3. Telegram untuk `no_match`: terkirim hanya bila tujuan utama efektif `all` **dan** `unknown_delivery == "all"`; `inbox` dan `none` → `attendance_skipped`. Aturan `matched`/`already_in`/`detected` tidak berubah.
4. Consumer: event `attendance` dengan `employee_id` kosong dan `match_reason` ∈ {`no_match`, `ambiguous`, `low_quality`} pada zona `none` dihapus; tidak ada baris `alert`, caption AI, atau siaran WS untuknya. Pada zona `inbox`/`all`/tanpa kunci event tetap utuh. Event dikenali dan event anomali (arah tidak valid, tanpa embedding dan crop) tidak pernah dibuang.
5. Pesan media untuk event yang dibuang: file yang dirujuk dihapus, tanpa warning. Untuk `event_id` lain yang tak dikenal tetap warning seperti sekarang.
6. UI: radio **Wajah tidak dikenal** (`zone-unknown-<all|inbox|none>`) tampil di blok absensi kecuali efektif Mode uji; pilihan `all` nonaktif dengan bantuan bila tujuan utama bukan *Inbox + Telegram*, dan pilihan yang tampil jatuh ke *Hanya Inbox* tanpa mengubah nilai tersimpan; memilih menulis `unknown_delivery` dan `telegram_unknown = (nilai === "all")`; nilai lama `telegram_unknown: false` terbaca *Hanya Inbox*.

**Non-tujuan:** event wajah tidak dikenal yang disimpan tetapi disembunyikan, Telegram tanpa Inbox, penghitung event yang dibuang, konfirmasi dialog untuk "Tidak dikirim", perubahan vision, perubahan aturan Telegram `ambiguous`/`low_quality`, pembuangan event lama yang sudah tersimpan.

## 5. Desain

- **Kontrak (tanpa migrasi):** kunci `unknown_delivery` di JSON behavior `attendance`. `zone_delivery.py` mendapat `UNKNOWN_DELIVERIES = ("all", "inbox", "none")` dan `unknown_delivery(behaviors: list | None) -> str` (murni, tanpa DB). `schemas/zone.py` memvalidasi enum dan membatasi kunci ke kind `attendance`.
- **Telegram:** `alerting.should_alert` mengganti `behavior_flag("attendance", "telegram_unknown")` dengan `unknown_delivery(zone.behaviors) != "all"`. `Zone.behavior_flag` tidak berubah (tes bawaannya tetap).
- **Inbox:** `attendance.drop_unknown_event(db, event) -> bool` (kondisi pada kriteria 4): ambil path media (`payload.crop_path`, `snapshot_path`, `clip_path`), `db.delete(event)` + commit, catat `event_id` di `deque(maxlen=512)` modul, hapus file lewat `retention._safe_join` + `os.remove` (kegagalan dicatat, tidak melempar), log info tanpa identitas. `events_consumer.handle_message` memanggilnya tepat setelah `handle_face_event` (dibungkus try/except seperti hook lain); bila `True`, fungsi `return` sebelum alert, caption AI, `intrusion_face`, dan siaran WS.
- **Media susulan:** di cabang `MEDIA_TOPIC`, bila baris tidak ada dan `event_id` ada di daftar buangan, hapus `snapshot_path`/`clip_path` pesan itu lalu `return` tanpa warning (`attendance.discard_dropped_media(data) -> bool`). Daftar di memori hilang saat API restart: pesan susulan lalu hanya memicu satu warning dan file diurus sapuan orphan retensi (batas diterima).
- **Frontend:** `api/zones.ts` `Behavior.unknown_delivery?: 'all' | 'inbox' | 'none'`. `zoneDelivery.ts` mendapat `effectiveUnknownDelivery(b, mainDelivery)`. Komponen baru `UnknownFaceRadio.tsx` (pola `DeliveryRadio`). `ZonesPage.tsx` mengekstrak `patchAttendanceBehavior(patch)` dari `applyAttendanceDelivery` (membuat item `attendance` bila belum ada) dan memakainya untuk radio ini; toggle lama dihapus. Teks id/en di `i18n.tsx`; `zones.telegramUnknown` dihapus; teks bantu `zones.delivery.allHintAttendance` menunjuk radio baru.

## 6. Tes

Backend: `test_zone_delivery.py` (`unknown_delivery` murni: kunci, turunan `telegram_unknown`, `None`, nilai tak sah), `test_zones_api.py` (enum sah/tidak sah, kind lain ditolak), `test_alerting.py` (matriks tujuan utama × `unknown_delivery`; dua tes `telegram_unknown` lama tetap lulus), `test_events_consumer.py` (buang vs simpan per nilai dan per `match_reason`, event dikenali dan anomali tidak dibuang, tanpa alert/AI/WS, media susulan menghapus file dan tanpa warning). Frontend: `zones.test.tsx` (lima tes toggle lama diubah; tambahan: radio tampil/sembunyi, nonaktif, payload simpan, pemetaan data lama, behavior dibuat bila belum ada).

## 7. Dokumen

`WORKFLOW.md` (§6, §12), `ARCHITECTURE.md` (kontrak behavior absensi dan urutan consumer), `README.md`, `docs/runbooks/attendance.md` (efek "Tidak dikirim" pada pantauan `face_top_score`), `ROADMAP.md`, `CHANGELOG.md`.

## 8. Risiko dan rollback

| Risiko | Mitigasi |
|---|---|
| Event yang dibuang tidak bisa dipulihkan, dan skor `face_top_score` zona itu hilang dari pantauan noise | Dipilih eksplisit per zona; bantuan UI menyebutnya; default zona lama tidak berubah |
| Event duplikat dari node (QoS1) dengan `event_id` sama | Baris dibuat ulang, dicocokkan ulang, dibuang ulang; media ditangani daftar buangan |
| API restart menghapus daftar buangan | Satu warning media; file diurus sapuan orphan retensi |
| Zona diubah ke `none` saat event sedang diproses | Nilai dibaca saat keputusan dibuat; tidak ada kondisi balapan yang merusak data |
| Menyimpan zona mendorong config ke node | Sama dengan toggle lama; perilaku apply per kamera tidak berubah |

**Rollback:** `git revert`, tanpa migrasi. Kode lama mengabaikan `unknown_delivery` dan membaca `telegram_unknown` (UI baru menulis `false` untuk `inbox` dan `none`), sehingga zona `none` kembali menyimpan event wajah tidak dikenal di Inbox tanpa Telegram.
