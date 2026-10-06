# Spec — Caption AI di alert Telegram

Status: **DISETUJUI di chat (opsi A, 2026-10-06)**, menunggu review spec tertulis.
Branch: `feat/telegram-ai-caption` (dari `main` @ `ca6d16b`).
Spec induk: `docs/superpowers/specs/2026-10-02-ai-event-caption-ask-design.md` §6.6 (Telegram = fase 2).

---

## 1. Latar

Permintaan user: integrasi AI ke bot Telegram. Dari tiga opsi (A caption masuk ke alert, B tombol Tanya AI
preset, C tombol URL) user memilih **A**. Alasan: Tanya AI jarang dipakai, sedangkan A memberi nilai utamanya
(caption AI terlihat di Telegram) tanpa infrastruktur baru. Tombol Tanya AI dan poller `getUpdates` **tidak** dikerjakan.

Fakta (server `gspe-ai3`, 2026-10-06): bot sudah terkonfigurasi dan dipakai (17 alert `sent`, 2 `rate_limited`,
grup "I-Sentinel Alert"), tetapi hanya outbound. Alert terkirim ±1 detik setelah event; caption AI siap ±3 detik setelah event.

## 2. Temuan kode

| # | Temuan | Lokasi | Dampak |
|---|---|---|---|
| 1 | `AlertDispatcher.process` membentuk caption (`telegram.format_caption`), mengirim lewat `telegram.deliver`, lalu menulis `status`; `message_id` tidak disimpan | `alert_dispatcher.py` | Perlu kolom `message_id` agar pesan bisa di-edit |
| 2 | `deliver` mengembalikan tuple `("sent", None)`; tes memalsukannya dengan tuple polos | `telegram.py`, `test_alert_dispatcher.py` | Nilai kembali harus tetap bisa di-unpack dua nilai dan sama dengan tuple (kompatibel) |
| 3 | `format_caption` menjamin < 1024 karakter lewat batas 120 karakter per nilai | `telegram.py` | Baris AI butuh anggaran sisa, bukan batas tetap |
| 4 | Baris `alert` hanya ada bila zona/behavior menyalakan Telegram; status `queued\|sent\|failed\|rate_limited\|not_configured` | `alerting.py` | Hanya alert `sent` yang dapat di-edit |
| 5 | `AiWorker.process` menyelesaikan caption (`ok`) lalu commit dan broadcast WS | `ai_worker.py` | Titik pemicu edit |
| 6 | Urutan dapat terbalik: alert baru terkirim setelah caption selesai (retry kirim sampai ±48 detik), atau caption selesai di antara pembentukan caption alert dan commit status | dispatcher + worker | Dua jalur harus memakai satu fungsi idempoten |
| 7 | Setting `app_url` di server masih `http://192.168.2.133:5173` (port dev); web di `7700` | DB `setting` | Operasional, di luar kode: tautan "Lihat klip" rusak sampai diganti di Konfigurasi → Notifikasi |

## 3. Keputusan user

| Topik | Keputusan |
|---|---|
| Lingkup | Opsi **A**: caption AI ditambahkan ke caption alert yang sudah terkirim (edit pesan) |
| Ditunda | Tombol Tanya AI, long-polling `getUpdates`, balasan terpisah |

## 4. Tujuan, kriteria sukses, non-tujuan

**Kriteria sukses** (diuji):
1. Alert tetap dikirim segera tanpa menunggu LLM; tidak ada pesan atau notifikasi tambahan (edit tidak memicu notifikasi baru).
2. Caption `ok` ditambahkan ke caption alert yang sudah terkirim; bila caption selesai **sebelum** alert terkirim, ia sudah termasuk di pesan awal (tanpa edit).
3. Idempoten dan bebas race: tepat satu penambahan per alert, apa pun urutan penyelesaian caption dan pengiriman.
4. Kegagalan edit tidak mengubah status alert, caption web, atau antrean AI; token tidak muncul di log atau galat.
5. Caption akhir ≤ 1024 karakter, HTML valid (teks AI di-escape), alert tanpa caption AI identik dengan perilaku sekarang.
6. Alert tanpa foto (teks saja), `rate_limited`, `failed`, `not_configured`, atau tanpa `message_id` tidak pernah di-edit.
7. Tes yang ada tidak diubah (kecuali penegasan yang memang bergantung pada nilai kembali baru).

**Non-tujuan:** tombol Tanya AI, poller, kirim Q&A, edit alert lama (tanpa `message_id`), retry berkala edit yang gagal.

## 5. Desain

### 5.1 Data (migrasi `0022`, aditif)
`alert.message_id` Integer null; `alert.message_photo` Boolean null; `alert.ai_synced` Boolean not null default false.

### 5.2 `app/services/telegram.py`
- `class Delivery(tuple)`: isi `(status, error)` (kompatibel dengan unpack dan `==` tuple) plus atribut `message_id: int | None` dan `photo: bool`. `deliver` mengembalikan `Delivery`; `message_id` dari `result["message_id"]` balasan `sendPhoto`/`sendMessage`.
- `edit_caption(token, chat_id, message_id, caption, *, retries=2, sleep=time.sleep) -> tuple[str, str | None]`: `editMessageCaption` dengan `parse_mode=HTML`; balasan "message is not modified" dianggap sukses; tidak pernah raise; galat bebas token (pola `deliver`).
- `format_caption(..., ai_text: str | None = None)`: baris `🤖 <b>AI</b>: <teks>` setelah baris data dan sebelum tautan. Teks AI: spasi/newline dilipat jadi satu spasi, dipotong dengan "…" sehingga panjang akhir ≤ `CAPTION_MAX`; teks mentah dipotong **sebelum** di-escape dan dikurangi sampai hasil escape muat; sisa anggaran < 40 karakter → baris AI dihilangkan.

### 5.3 `app/services/alert_ai.py` (baru)
- `ai_text(db, event_id) -> str | None`: teks caption `ok` terbaru (`kind=caption`) atau `None`.
- `build_caption(db, alert, ai: str | None) -> str`: nama kamera/zona, `app_url`, dan `ai` → `telegram.format_caption` (pembentukan yang sekarang ada di dispatcher dipindah ke sini).
- `sync_ai_caption(db, event_id: int) -> bool`: guard `alert.status == "sent"`, `message_id`, `message_photo`, `not ai_synced`, token dan chat aktif, caption `ok` ada; panggil `telegram.edit_caption` dengan caption penuh dari `build_caption`; sukses → `ai_synced = True` dan commit; gagal → log peringatan (tanpa nilai) dan `ai_synced` tetap false. Tidak pernah raise.

### 5.4 Dispatcher dan worker
- `AlertDispatcher.process`: memakai `alert_ai.build_caption` dengan `ai_text` yang sudah ada; menyimpan `message_id` dan `message_photo` dari `Delivery` (`getattr(..., None)` agar tuple polos dari tes tetap jalan); `ai_synced = True` bila teks AI sudah termasuk di pesan awal; **setelah** commit status memanggil `sync_ai_caption` (menutup race "caption selesai di antara pembentukan caption dan commit").
- `AiWorker.process`: setelah caption `ok` dan commit/broadcast, panggil `alert_ai.sync_ai_caption(db, row.event_id)` dalam `try/except` (kegagalan Telegram tidak memengaruhi baris caption). `# ponytail:` dipanggil di thread worker (jaringan ≤ ~15 detik + retry) sehingga bisa menunda caption berikutnya; pindah ke antrean terpisah bila terbukti masalah.

### 5.5 Contoh pesan
```
🚨 LOITERING

Kamera: Lorong Server
Zona: Server
Waktu: 06 Okt 2026 13:44:24 WIB
Level: WARNING
🤖 AI: Seorang pria berdiri di lorong memegang ponsel, lalu keluar dari bingkai.

🎥 Lihat klip: http://…/events?event=4770
```

## 6. Galat dan keamanan
Edit gagal → peringatan log, `ai_synced` tetap false, tanpa retry berkala. Teks AI melewati `html.escape`; token hanya lewat `_call` (sudah bebas token pada galat). Alert lama tanpa `message_id` tidak disentuh. Event `attendance`/`system` tidak punya caption AI sehingga tidak berubah.

## 7. Pengujian
- `test_telegram.py`: `Delivery` (unpack dan `==` tuple; `message_id`/`photo` dari balasan), `edit_caption` (sukses, "message is not modified" sukses, galat bebas token, retry), `format_caption` dengan `ai_text` (baris dan urutan, anggaran ≤ 1024 pada nilai terpanjang, `<`/`&` ter-escape dan HTML valid, sisa anggaran kecil → tanpa baris AI, tanpa `ai_text` identik dengan sebelumnya).
- `test_migration_0022.py`: aditif, default `ai_synced=false`, downgrade.
- `test_alert_ai.py`: `sync_ai_caption` (guard satu per satu: bukan `sent`, tanpa `message_id`, teks saja, sudah `ai_synced`, tanpa caption `ok`; sukses menandai `ai_synced`; gagal tidak menandai dan tidak raise; idempoten pada panggilan kedua).
- `test_alert_dispatcher.py`: caption `ok` sudah ada saat kirim → termasuk di pesan awal dan tanpa edit; caption selesai di antara format dan commit → tepat satu edit; `deliver` tuple polos tetap bekerja.
- `test_ai_worker.py`: caption `ok` memicu `sync_ai_caption`; Telegram yang raise tidak mengubah baris caption.
- Verifikasi: `pytest backend -m "not gpu"`, tes Docker/vision tak berubah.

## 8. Rollout dan rollback
Migrasi aditif; deploy `git pull` + `./docker/setup.sh` (rebuild `api`). Prasyarat operasional: `app_url` dikoreksi ke `http://192.168.2.133:7700`. Rollback: `git revert` (kolom baru tidak berbahaya) atau `alembic downgrade 0021`.

## 9. Risiko terbuka
| Risiko | Mitigasi |
|---|---|
| Edit tidak memicu notifikasi baru (caption muncul tanpa bunyi) | Diterima: alert tetap instan; caption terlihat saat chat dibuka |
| Telegram membatasi laju edit | Retry kecil; kegagalan hanya dicatat |
| Thread worker terblokir Telegram | Batas jaringan 15 detik, ditandai `ponytail:` |
| Alert diedit setelah pesan dihapus pengguna | Galat diperlakukan sebagai gagal biasa (log), tanpa efek lain |

## 10. Dokumen yang diperbarui
`README.md` (Alert Telegram), `ARCHITECTURE.md`, `WORKFLOW.md` (§Telegram dan §8.1), `docs/RUNBOOK.md` (`app_url`), `CHANGELOG.md`, `ROADMAP.md`.
