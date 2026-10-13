# Audit Log — Design Spec

- Tanggal: 2026-10-13
- Branch: `feat/audit-log`
- Status: disetujui untuk ditulis rencana implementasi (setelah review spec ini)

## 1. Latar Belakang & Tujuan

I-Sentinel belum punya jejak audit umum. Aksi sensitif — login, perubahan kamera/zona,
pengaturan AI/Telegram/storage, data karyawan & absensi — hanya ada di log aplikasi
(level info/debug), bukan di data yang bisa difilter dan diverifikasi. Satu-satunya
jejak audit yang ada adalah `event_ai.actor` (siapa bertanya ke AI).

Tujuan fase 1: tabel audit log terpusat yang merekam aksi user pada tiga kategori —
auth, konfigurasi, dan data sensitif attendance — dengan bukti integritas rantai hash,
retensi 90 hari, UI admin, dan overhead yang tidak terasa di jalur request.

## 2. Keputusan Desain (diputuskan via diskusi)

| Keputusan | Pilihan | Catatan |
|---|---|---|
| Scope fase 1 | Auth events, perubahan konfigurasi, data sensitif attendance | Manajemen user & role **tidak** masuk fase 1; skema mendukung penambahan nanti |
| Detail perubahan | Nama field berubah + **nilai baru** saja (JSON), tanpa nilai lama | Disertai denylist rahasia |
| Akses baca | Admin only (`require_admin`) | |
| Anti-tamper | Hash chain per baris (SHA-256) | Verifikasi di dalam window retensi |
| Jalur tulis | Helper eksplisit `audit.record(...)` dipanggil di router/service (pendekatan A) | Bukan listener ORM, bukan middleware |
| Performa | Tulis sinkron dalam transaksi aksi; tanpa queue/worker | Insert 1 baris kecil + advisory lock |
| Retensi | 90 hari (`AUDIT_RETENTION_DAYS`), sweeper harian | Menghapus batch 5000 |
| UI | **Halaman sidebar baru** `/audit-log` (bukan tab Configuration) | Nav item `adminOnly` |

## 3. Katalog Aksi Fase 1

Naming: `{kategori}.{entitas}.{verba}`. Kategori = prefix pertama.

| Kategori | Aksi | Titik integrasi |
|---|---|---|
| `auth` | `auth.login` (ok), `auth.login_failed` (failed), `auth.lockout` (failed) | Router auth (login, rate-limit lockout) |
| `config` | `camera.create/update/delete` | Router cameras |
| `config` | `stream_source.create/update/delete` | Router stream_sources |
| `config` | `credential_profile.create/update/delete` | Router credential_profiles |
| `config` | `location_group.create/update/delete` | Router location_groups |
| `config` | `node.create/update/delete` | Router nodes |
| `config` | `zone.create/update/delete` | Router zones |
| `config` | `detector_setting.update` | Router detector_settings |
| `config` | `ai_settings.update` | Router ai_settings |
| `config` | `storage_settings.update` | Router storage |
| `config` | `telegram.update` | Router telegram |
| `attendance` | `employee.create/update/delete` | Router employees |
| `attendance` | `enrollment.create` (3-photo enroll) | Router/service enrollment |
| `attendance` | `shift.create/update/delete` | Router shifts |
| `attendance` | `attendance.correct` (koreksi manual) | Router/service attendance |
| `attendance` | `attendance.import` / `attendance.export` (CSV) | Router attendance |

**Tidak diaudit:** endpoint vision internal (`/internal/nodes/*`, pakai node API key —
sudah tercakup sistem event), aksi baca (GET), login rate-limit internal selain lockout,
bootstrap admin saat startup.

## 4. Skema Data

Satu tabel baru `audit_log` (migrasi `0026_audit_log.py`):

```python
class AuditLog(Base):
    __tablename__ = "audit_log"

    id: int            # BIGSERIAL PK
    ts: datetime       # TIMESTAMPTZ, waktu aksi; default now(utc)
    category: str(16)  # auth | config | attendance (di-derive dari prefix action)
    action: str(48)    # camera.update, auth.login_failed, ...
    actor_id: int | None      # TANPA FK — user bisa dihapus, jejak audit harus tetap ada
    actor_label: str(64)      # username resolved; login gagal = username yang dicoba; "system" bila sistem
    target_type: str(32) | None  # camera, zone, employee, ...
    target_id: str(64) | None    # id sebagai string (fleksibel untuk key komposit)
    target_label: str(128) | None  # nama kamera/zona/karyawan — UI readable tanpa join
    changes: JSON | None      # {field: nilai_baru} untuk field berubah; NULL untuk delete & aksi tanpa payload
    ip: str(45) | None
    user_agent: str(255) | None
    status: str(16)    # ok | failed
    prev_hash: str(64)
    hash: str(64)      # sha256(prev_hash + fields kanonik)
```

Index (4): `(ts)`, `(category, ts)`, `(actor_label)`, `(target_type, target_id)`.

Estimasi volume skala LAN: puluhan ribu baris per 90 hari — tabel tetap kecil dan semua
query filter di atas ter-indeks.

### Aturan `changes`

- Hanya field yang berubah beserta **nilai baru**; tidak menyimpan nilai lama.
- Sanitasi denylist berbasis nama key: key mengandung `password`, `token`, `secret`,
  `credential`, atau `api_key` (case-insensitive) → nilai diganti `"***"`.
  (Profil kredensial memang hanya menyimpan referensi `env:...`, tapi aturan ini
  pagar ganda bila ada field sensitif lain di masa depan.)
- Khusus: `attendance.import` menyimpan `{"rows": <jumlah baris>}`.

## 5. Jalur Tulis — `app/services/audit.py`

```python
def record(
    db, *, action: str, actor: User | None = None, actor_label: str | None = None,
    target: tuple[str, str, str] | None = None,   # (type, id, label)
    changes: dict | None = None, status: str = "ok",
    ip: str | None = None, user_agent: str | None = None,
) -> AuditLog
```

Perilaku:

1. `category` di-derive dari prefix `action`.
2. `actor_label` default = `actor.username` bila actor ada; else dari argumen.
3. Sanitasi `changes` via denylist.
4. Hash chain dalam transaksi yang sama:
   - Kunci serialize: `SELECT pg_advisory_xact_lock(<konstanta>)` (Postgres) agar
     insert konkuren tidak memecah rantai. Di SQLite (test) lock dilewati.
   - `prev_hash` = hash baris terakhir (`ORDER BY id DESC LIMIT 1`); baris pertama
     sepanjang sejarah memakai `"0" * 64` sebagai genesis absolut.
   - `hash = sha256("|".join([prev_hash, ts.isoformat(), category, action,
     actor_label or "", target_type or "", target_id or "", changes_json, status]))`
     dengan `changes_json` = JSON key tersortir kanonik, hex digest.
5. Row ditambahkan ke sesi yang sama dengan transaksi aksi — komit/rollback atomik.
   Tidak ada queue, worker, atau tulis async.

Helper turunan `record_from_request(db, request, user, **kw)` mengisi `ip` dan
`user_agent` dari request.

## 6. Retensi

- Setting baru di `app/core/config.py`: `audit_retention_days: int = 90`.
- `app/services/audit_sweeper.py` — pola sama dengan monitor existing
  (`disk_alert`, `attendance_closer`): thread ringan di lifespan API, jalan tiap
  24 jam, menghapus `ts < now - audit_retention_days` dalam batch 5000 baris.
- **Konsekuensi chain:** setelah sapuan, verifikasi rantai dilakukan di dalam window
  retensi. Baris tertua di window dianggap **genesis window** (prev_hash-nya tidak
  diverifikasi). Ini batas yang diterima: bukti integritas berlaku untuk window 90 hari.

## 7. API Baca (semua `require_admin`)

| Endpoint | Fungsi |
|---|---|
| `GET /api/v1/audit-logs` | Filter: `from`, `to`, `category`, `action`, `actor`, `target_type`, `target_id`, `status`, `q` (cari ke `target_label`/`action`, ILIKE), `limit` (default 50, maks 200), `offset`. Response `{total, items}` dengan item = skema `AuditLogOut` (semua kolom kecuali hash internal; `changes` sebagai objek). |
| `GET /api/v1/audit-logs/actors` | Daftar distinct `actor_label` untuk dropdown filter. |
| `POST /api/v1/audit-logs/verify` | Hitung ulang rantai dari baris tertua di window retensi sampai terbaru. Response `{ok, checked, first_break_id?}`. |

Tanpa WebSocket/realtime — log bersifat historis.

## 8. Frontend

- **Route baru**: `/audit-log` di `frontend/src/main.tsx` (child AppShell, sejajar
  `/monitoring`).
- **Nav sidebar**: item baru di `AppShell.tsx` dengan `adminOnly: true`, icon
  `Document` (@carbon/icons-react), key i18n `nav.auditLog`.
- **Struktur** (konsisten konvensi fitur):
  - `frontend/src/api/auditLogs.ts` — client REST (list, actors, verify).
  - `frontend/src/features/audit/AuditLogPage.tsx` — halaman.
- **UI (Carbon)**:
  - Baris filter: DatePicker rentang tanggal, Dropdown kategori, Dropdown aksi,
    Dropdown actor (dari `/actors`), Dropdown status, Search target.
  - DataTable kolom: waktu, actor, aksi, target, status, ip; baris expandable
    menampilkan `changes` (JSON) dan user agent.
  - Paginasi prev/next + total.
  - Tombol "Verifikasi integritas" → memanggil POST verify, hasil inline
    (success/warning notification).
- Semua string melalui `src/app/i18n.tsx` (id + en).
- Mobile 390px tanpa overflow horizontal.

## 9. Migrasi, Konfigurasi, Dokumentasi

- `backend/alembic/versions/0026_audit_log.py` — create table + 4 index, pola sama
  dengan migrasi existing; idempotent.
- `Settings.audit_retention_days = 90`.
- Update docs saat implementasi: `README.md` (fitur), `DESIGN.md`, `CHANGELOG.md`
  (evidence per konvensi repo), `ARCHITECTURE.md` bila perlu.

## 10. Testing

Backend (`backend/tests/test_audit_api.py`, marker default non-gpu):

- Unit: hash chain (genesis, dua insert beruntun, verifikasi ok; verifikasi gagal
  bila 1 baris diubah), sanitasi denylist changes.
- API: login sukses/gagal/lockout tercatat dengan benar (actor None + label + status);
  perubahan kamera tercatat dengan `changes` yang benar; viewer dapat 403; filter +
  paginasi; POST verify; sweeper menghapus sesuai retensi.

Frontend (`frontend/src/__tests__/auditLog.test.tsx`): halaman render (mock API),
filter memanggil client dengan param benar, verifikasi menampilkan hasil.

## 11. Verifikasi Wajib (evidence sebelum klaim selesai)

- `pytest tests -q -m "not gpu"` (backend)
- `npx vitest run` + `npm run build` (frontend)
- UI dicek terhadap app berjalan; screenshot ke `docs/evidence/` (gitignored).

## 12. Out of Scope (Fase Berikutnya)

- Audit manajemen user & role (titik panggil tinggal ditambahkan).
- Export CSV audit log.
- Tombol "riwayat perubahan" per target (mis. dari halaman kamera).
- Notifikasi realtime.
