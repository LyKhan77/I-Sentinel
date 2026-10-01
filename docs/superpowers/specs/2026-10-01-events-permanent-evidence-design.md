# Spec — Bukti event system permanen (disimpan di payload)

Status: **menunggu review spec tertulis** (keputusan P1–P5 §2 default; konfirmasi bila berbeda).
Branch: `feat/events-permanent-evidence` (dipotong dari `main` @ `afd95ff`; **dikerjakan setelah** bagian 1 `events-list-url-paging` di-merge — `git merge main` sebelum mulai).
Plan: `docs/superpowers/plans/2026-10-01-events-permanent-evidence.md`.
Seri: bagian 2 dari 2 backlog. Mewujudkan opsi **C** dari spec `2026-10-01-events-evidence-filters-design.md` (K1) yang waktu itu ditunda.

---

## 1. Latar

Panel Bukti event system (siklus lalu) mengambil grafik dari `monitoring_sample` saat event dibuka. Data itu hanya disimpan 7 hari, sehingga event yang lebih tua hanya menampilkan fakta teks.

### Kondisi kode (`main` @ `afd95ff`)

| # | Fakta | Lokasi |
|---|---|---|
| 1 | `monitoring_sample` dipangkas 7 hari (`RETENTION_DAYS`); panel menulis "Data tren hanya disimpan 7 hari" untuk event lebih tua. | `monitoring_history.py`, `systemEvidence.ts` |
| 2 | Panel meminta `GET /monitoring/history?from&to&node_id` per event dibuka (jendela ≤ 6 jam, node harus ada). | `EvidencePanel.tsx` |
| 3 | Payload health hanya memuat nilai **terakhir** (`value`), `threshold`, `duration_min`, `state`; bukan kurvanya. Payload node hanya `{node, reason}`; event `online` tidak mencatat lama offline (hanya Telegram yang menghitungnya). | `health_alerts.py:133`, `node_health.py:32,69` |
| 4 | Hanya dua emitter event `system`: `node_health._emit` dan `health_alerts._emit`. | backend |
| 5 | `health_alerts._check(rule, data, key, threshold)` sudah memberi nilai metrik per menit persis seperti yang dipakai alert (persen untuk `camera_low_fps`, detik untuk `camera_no_frames`, dll.). `evaluate` memuat sampel hanya sepanjang `max(duration_min) + RESOLVE_MIN` menit. | `health_alerts.py:37,112` |
| 6 | `mark_online(db, node, now, since)` sudah menerima `since` (awal offline) dari `events_consumer.py:123` dan `api/events.py:73`. | `node_health.py:61` |

## 2. Keputusan

| # | Keputusan |
|---|---|
| P1 | Skema `payload.evidence` versi 1 (§3.1), disimpan **saat event dibuat**; event lama tidak di-backfill. |
| P2 | Dibuat untuk: health `firing`, health `resolved` (bukan `closed`), node offline (`timeout`/`lwt`). Fakta tambahan: `last_seen` (node offline) dan `down_s` (node online). |
| P3 | Panel memakai bukti tersimpan bila valid: **tanpa fetch ke history dan tanpa batas 7 hari**; payload tanpa/ rusak → jalur lama (fetch + kedaluwarsa 7 hari). |
| P4 | Batas 360 titik per seri (6 jam × 1 menit); nilai dibulatkan 1 desimal; menit tanpa data = `null`. |
| P5 | Kegagalan membangun bukti tidak boleh menggagalkan event: dicatat (log) dan event dibuat tanpa `evidence`. |

## 3. Desain

### 3.1 Skema

```json
"evidence": {
  "v": 1,
  "from": "2026-10-01T07:20:00Z",
  "step_s": 60,
  "series": { "value": [91.2, 93.0, null, 95.1] }
}
```

- `from` = awal menit pertama (UTC, akhiran `Z`); titik ke-`i` berada pada `from + i·step_s`.
- Health: satu seri `value` = nilai `_check` per menit (cpu/ram avg %, ms avg, backlog max, suhu/VRAM GPU max, umur frame max s, persen terhadap target FPS).
- Node offline: dua seri `cpu_pct` (avg) dan `infer_fps` (avg).
- Setiap seri ≤ 360 elemen, elemen `number | null`.

### 3.2 Backend

- `monitoring_history.minute_samples(db, node_id, start, end) -> dict[datetime, dict]`: baris `monitoring_sample` dengan `start <= ts < end`, kunci = awal menit UTC aware, nilai = `_dict(data)`.
- `health_alerts._evidence(db, node_id, rule, key, threshold, start, end) -> dict`: memanggil `minute_samples` lalu `_check(...)[1]` untuk setiap menit di `[start, end)` (dibulatkan 1 desimal), menghasilkan skema §3.1. Dipakai pada `payload(..., extra={"evidence": …})`:
  - **firing:** `start = cur − (duration_min + 30) menit`, `end = cur`;
  - **resolved** (cabang yang menghitung `lasted`): `start = max(started_at − 15 menit, cur − 360 menit)`, `end = cur`;
  - **closed:** tanpa `evidence`.
  Seluruh pembangunan dibungkus `try/except` (P5).
- `node_health._emit(db, node, severity, reason, now, extra=None)` meneruskan `extra` ke payload. `mark_offline` menambah `last_seen` (ISO Z dari `node.last_seen` bila ada) dan `evidence` (30 menit sebelum `now`, seri `cpu_pct` dan `infer_fps`, dari `minute_samples`); `mark_online` menambah `down_s` (detik bulat, hanya bila `since` ada dan `now > since`). Kegagalan → tanpa `evidence` (P5).
- Tanpa migrasi; `Event.payload` JSON. Event lama tanpa `evidence` tetap valid.

### 3.3 Frontend

- `features/events/systemEvidence.ts`: `StoredEvidence = { fromMs: number; stepMs: number; series: Record<string, (number | null)[]> }`; `parseStored(payload): StoredEvidence | null` valid bila `v === 1`, `from` terurai, `step_s` > 0, `series` objek berisi hanya larik `number | null` dengan total ≤ 1000 elemen; selain itu `null`. `Evidence` mendapat `stored: StoredEvidence | null`.
- Bila `stored`: `expired = false` (berapa pun umur event), `window = [fromMs, fromMs + n·stepMs]`, dan grafik disusun dari bukti tersimpan: health → satu `ChartSpec` (judul per rule seperti sekarang, rule tak dikenal → judul generik, unit dari `payload.unit`, `refLine` = `threshold`, seri `value`); node → dua grafik (`cpu_pct`, `infer_fps`). `ChartSeriesSpec` mendapat `storedKey?: string` agar panel mengambil titik dari bukti tersimpan.
- Fakta tambahan: node offline → "Heartbeat terakhir" (`last_seen`, waktu lokal); node online → "Offline selama" (`down_s` → "N mnt" atau "H jam M mnt").
- `EvidencePanel.tsx`: bila `ev.stored` → grafik dirender langsung (titik `t = fromMs + i·stepMs`, `null` dilewati), **tanpa** fetch dan tanpa status loading; marker waktu event tetap; tanpa arsir offline. Tidak stored → jalur sekarang tanpa perubahan.
- Kunci i18n baru (id / en): `events.evidence.lastSeen` "Heartbeat terakhir" / "Last heartbeat"; `events.evidence.downFor` "Offline selama" / "Offline for"; `events.evidence.series.value` "Nilai" / "Value"; `events.evidence.chart.generic` "Metrik" / "Metric"; `events.evidence.hoursMinutes` "{h} jam {m} mnt" / "{h} h {m} min".

### 3.4 Pengujian

Backend: `minute_samples` hanya mengembalikan `start <= ts < end` dan kunci menit UTC aware; event health `firing` membawa `evidence` (`v`, `from` = `cur − (duration_min + 30)` menit, `step_s` 60, panjang `duration_min + 30`, `null` untuk menit tanpa sampel, nilai sesuai sampel); `camera_low_fps` memakai persen; `resolved` mulai sebelum `started_at` dan terpotong 360 titik untuk alert > 6 jam; `closed` tanpa `evidence`; kegagalan `_evidence` (monkeypatch) tidak menggagalkan event; node offline membawa `last_seen` dan seri `cpu_pct`/`infer_fps`; tanpa sampel → tanpa `evidence` tetapi tetap `last_seen`; event `online` membawa `down_s` bila `since` ada dan tidak bila tidak; kegagalan bukti node tidak menggagalkan event; uji lama health/node tetap hijau.

Frontend: `parseStored` (valid; `v` salah; `from` tak terurai; `step_s` ≤ 0; seri bukan larik; elemen bukan number/null; terlalu panjang); mode tersimpan menimpa kedaluwarsa dan jendela; grafik health/node dari bukti tersimpan (termasuk `refLine` dan celah `null`); fakta `last_seen`/`down_s`; jalur lama tidak berubah; panel: tanpa permintaan history, event > 7 hari tetap menggambar, `null` membuat celah, semua `null` → pesan tanpa data, bukti rusak → jatuh ke fetch.

Verifikasi akhir: `pytest tests -q -m "not gpu"`, `npx vitest run`, `npm run build`, `npm run lint` (tanpa pasangan rule/file baru), **berurutan**; smoke render dengan mock. Uji UI user setelah deploy.

### 3.5 Di luar scope

Backfill event lama; bukti untuk event `closed`; arsir periode offline pada bukti tersimpan; kompresi payload; bukti untuk event kamera.

## 4. Dokumen yang ikut berubah

`WORKFLOW.md §8` dan `§14`, `ARCHITECTURE.md` (skema `payload.evidence`), `docs/runbooks/monitoring.md`, `README.md`, `ROADMAP.md`, `CHANGELOG.md`.

## 5. Risiko dan rollback

| Risiko | Mitigasi |
|---|---|
| Payload membesar (≈ 1–3 KB per event; frame WS ikut membesar). | Batas 360 titik, 1 desimal; event system jarang. |
| Satu query tambahan per emisi di `evaluate`/`mark_offline`. | Hanya pada transisi (jarang); P5 mencegah kegagalan merambat. |
| Menit tanpa sampel di jendela. | `null` → celah di grafik. |
| Skema berubah di masa depan. | Versi `v`; panel hanya menerima `v === 1`, selain itu jalur lama. |

Rollback: `git revert` per commit task; tanpa migrasi; event yang sudah memuat `evidence` tetap valid (field tambahan diabaikan klien lama).
