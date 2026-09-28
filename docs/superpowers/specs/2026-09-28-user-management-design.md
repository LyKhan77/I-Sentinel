# Spec — User management (tab User, nonaktifkan akun, reset & ganti password, cabut sesi)

Status: **DISETUJUI di chat (2026-09-28)**, menunggu review spec tertulis.
Branch: `feat/user-management` (dari `main` @ `3154c7b`).
Checkpoint: `.cooper/context/next-features.md`.

---

## 1. Latar

Prioritas berikutnya setelah Live View TV. Mockup yang disetujui (`mockup-ui/06-configuration.html`, tab **User**):
tabel username/role/dibuat, tombol **+ Tambah user**, hapus, keterangan *"admin = semua konfigurasi + enrollment +
koreksi · viewer = read-only"*. Dari spec Live View TV (§3.6) tercatat kebutuhan pencabutan sesi karena sesi kini
bergulir 48 jam.

### Kondisi kode (`main` @ `3154c7b`)

| # | Fakta | Lokasi |
|---|---|---|
| 1 | Model `User`: `id, username, password_hash, role ('admin'/'viewer'), locale, created_at`. Tanpa status aktif / versi token. | `backend/app/models/user.py` |
| 2 | CRUD admin-only: `GET/POST /api/v1/users`, `PATCH /{id}` (body **`dict` mentah**: role/locale/password), `DELETE /{id}`; pengaman admin terakhir (demote/hapus). Password hanya "tidak kosong, ≤ 72 byte". | `backend/app/api/users.py`, `schemas/user.py` |
| 3 | JWT `{sub, role, exp}`; `get_current_user` membaca user dari DB tiap request, tanpa cek status; sesi bergulir (cookie diperbarui saat lewat separuh umur, default 48 jam). | `core/security.py`, `api/deps.py` |
| 4 | Login: rate limit per (username, ip), 401 `invalid credentials`; logout hapus cookie. | `api/auth.py` |
| 5 | Viewer = read-only: 59 endpoint tulis `require_admin`; halaman Absensi/Enrollment/Events/Kamera sudah menyembunyikan aksi admin. Menu Konfigurasi admin-only. | `AppShell.tsx`, fitur terkait |
| 6 | Frontend belum punya halaman user; kartu akun sidebar hanya nama, role, logout. | `AppShell.tsx` |
| 7 | Migrasi terakhir `0017`. | `backend/alembic/versions/` |

## 2. Keputusan user

| # | Keputusan |
|---|---|
| K1 | Tetap **2 role**: `admin` (akses penuh) dan `viewer` (read-only semua menu). Akun TV = `viewer`. |
| K2 | Fitur: **nonaktifkan/aktifkan akun**, **admin reset password**, **user ganti password sendiri**. |
| K3 | Tanpa tombol "keluarkan semua sesi" terpisah, tanpa role ketiga, tanpa audit log (di luar scope). |

## 3. Desain

### 3.1 Data (migrasi `0018_user_status`)

- `user.is_active` BOOLEAN NOT NULL default `true` (server_default untuk baris lama).
- `user.token_version` INTEGER NOT NULL default `0`.
- `user.last_login_at` TIMESTAMPTZ NULL.
- Downgrade menghapus ketiga kolom.

### 3.2 Token & sesi

- `create_access_token(user_id, role, token_version)` menambah klaim **`tv`**.
- `get_current_user` menolak (401) bila: token invalid/kedaluwarsa, user tidak ada, **`user.is_active` false**
  (`"account disabled"`), atau **`payload.get("tv", 0) != user.token_version`** (`"session revoked"`). Perpanjangan
  sesi bergulir memakai `user.token_version` saat ini → token yang sudah dicabut tidak bisa "diperpanjang".
- Token lama tanpa klaim `tv` dianggap `tv=0` → sesi yang ada saat deploy tetap berlaku sampai ada perubahan.
- `token_version` **naik** saat: admin reset password, user ganti password sendiri, akun dinonaktifkan.
  Perubahan role tidak menaikkan versi (role dibaca dari DB tiap request → berlaku langsung).

### 3.3 Login

- Urutan: rate limit → cek user + password (salah → 401 seperti sekarang, dihitung gagal) → **akun nonaktif →
  403 `"account disabled"`** (status hanya terungkap ke pemegang password benar) → set `last_login_at`, cookie.
- Frontend login menampilkan pesan khusus untuk 403: "Akun dinonaktifkan — hubungi admin".

### 3.4 API

- `GET /api/v1/users` → `UserOut` + `is_active`, `created_at`, `last_login_at` (tanpa hash/versi).
- `POST /api/v1/users` (`UserIn`): username 3–64 karakter `[A-Za-z0-9._-]`, role `admin|viewer`, password
  **≥ 8 karakter, ≤ 72 byte**; username terpakai → 409.
- `PATCH /api/v1/users/{id}` — body **`UserPatch`** (Pydantic, `extra="forbid"`): `role?`, `is_active?`,
  `password?`, `locale?`.
  - `password` → hash baru + `token_version += 1`.
  - `is_active: false` → `token_version += 1`.
- `DELETE /api/v1/users/{id}`.
- **Pengaman** (409, pesan jelas):
  - admin terakhir yang **aktif** tidak boleh diturunkan, dinonaktifkan, atau dihapus;
  - admin tidak boleh menurunkan role, menonaktifkan, atau menghapus **akunnya sendiri**.
- `POST /api/v1/auth/change-password` (semua role): `{current_password, new_password}`; password lama salah → 400
  `"current password is incorrect"` (dihitung ke rate limit login yang sama); aturan password sama; sukses →
  `token_version += 1` dan **cookie baru di response** (browser ini tetap login, perangkat lain keluar).
- 422 tidak menggemakan input (handler global yang sudah ada) — password tidak pernah muncul di response/log.

### 3.5 Frontend — tab **User** di Konfigurasi

- `TABS` + `users` (`/configuration?tab=users`), label "User"/"Users"; admin-only seperti Konfigurasi lain.
- Tabel Carbon: **Username** (+ "(Anda)" untuk akun sendiri), **Role** (Tag: admin merah, viewer abu),
  **Status** (Aktif/Nonaktif), **Dibuat**, **Login terakhir** ("—" bila belum), **aksi** (OverflowMenu):
  Ubah role (admin ↔ viewer), Reset password, Nonaktifkan/Aktifkan, Hapus. Untuk baris akun sendiri, Ubah role /
  Nonaktifkan / Hapus disabled.
- Tombol **+ Tambah user** → modal: username, role (Select: "viewer — read-only", "admin — akses penuh"), password
  awal + konfirmasi (PasswordInput); validasi klien sama dengan backend (≥ 8, konfirmasi cocok).
- Modal **Reset password**: password baru + konfirmasi, keterangan "Semua sesi user ini akan keluar".
- **Nonaktifkan** dan **Hapus** memakai modal konfirmasi (danger); Aktifkan langsung.
- Error API (409 pengaman, 409 username) ditampilkan sebagai notifikasi inline dengan pesan dari server.
- Keterangan di bawah tabel: "admin = semua konfigurasi + enrollment + koreksi · viewer = read-only".
- 390 px: tabel dalam kontainer scroll horizontal milik tabel (bukan halaman) → halaman tanpa overflow.

### 3.6 Frontend — ganti password sendiri

- Kartu akun sidebar mendapat tombol **"Ganti password"** (ikon kunci, semua role) → modal: password lama, baru,
  konfirmasi. Sukses → toast "Password diganti; perangkat lain telah dikeluarkan". 400 → pesan "Password lama
  salah". Sesi browser ini tetap hidup (cookie baru dari server).
- REST lewat `src/api/users.ts` (baru) dan `src/api/client.ts` (`changePassword`). String lewat `i18n.tsx`.

## 4. Penanganan error

| Kondisi | Perilaku |
|---|---|
| Login akun nonaktif (password benar) | 403 `account disabled` → pesan khusus |
| Login password salah (aktif/nonaktif) | 401 `invalid credentials`, dihitung rate limit |
| Request dengan sesi akun yang baru dinonaktifkan | 401 → frontend ke `/login?next=` (perilaku 401 yang ada) |
| Request dengan token versi lama (password diganti) | 401 → login ulang |
| Turunkan/nonaktifkan/hapus admin aktif terakhir | 409 |
| Turunkan/nonaktifkan/hapus diri sendiri | 409 |
| Password < 8 / > 72 byte / konfirmasi beda | 422 (server) / validasi klien |
| `PATCH` dengan field tidak dikenal | 422 |
| Ganti password: password lama salah | 400, dihitung rate limit |

## 5. Pengujian

- Backend (pytest, `test_auth_api.py` / `test_users_api.py`):
  - login nonaktif 403 hanya bila password benar; password salah tetap 401;
  - sesi aktif langsung 401 setelah akun dinonaktifkan; aktifkan lagi → login ulang berhasil;
  - reset password → token lama (cookie dan Bearer, termasuk yang lewat separuh umur) 401; token tanpa `tv` tetap
    valid selama versi 0;
  - ganti password sendiri: lama salah 400; sukses → cookie baru valid, token lama 401;
  - pengaman admin aktif terakhir & diri sendiri (demote/nonaktif/hapus);
  - validasi password & username, `PATCH` field liar 422, `last_login_at` terisi;
  - migrasi `0018` upgrade/downgrade (pola DB-level `test_migration_0017.py`).
- Frontend (Vitest): tab User (render tabel, tambah user + validasi, reset, nonaktifkan dengan konfirmasi, hapus,
  aksi akun sendiri disabled, error 409 tampil); modal ganti password (sukses, 400); login 403 pesan khusus.
- Visual: tab User 1440 px & 390 px (tanpa overflow halaman).
- Baseline `main` `3154c7b`: backend 435, vision 223 (3 deselected), frontend 161, build 0, lint set sama.

## 6. Verifikasi lapangan (butuh izin user)

Deploy (alembic upgrade `0018`, restart API; frontend Vite dev HMR). Uji: buat viewer `tv-uji` → login di browser
lain → nonaktifkan dari admin → browser viewer langsung keluar; aktifkan → login lagi; reset password → sesi lama
keluar; ganti password sendiri → tetap login di browser ini; pengaman admin terakhir.

## 7. Di luar scope

Role ketiga (operator), tombol keluarkan semua sesi tanpa ganti password, audit log aksi admin, kebijakan
kedaluwarsa/kompleksitas password lanjutan, lupa password via email, SSO/LDAP.

## 8. Rollback

`git revert` + `alembic downgrade 0017` + restart API. Downgrade menghapus status/versi/login terakhir (akun
nonaktif kembali bisa login — nonaktifkan dengan mengganti password bila perlu sebelum downgrade).
