# Spec — Pendaftaran kamera sederhana (IP + path main/sub + kredensial terpilih)

Status: **DISETUJUI di chat (2026-09-24)**, menunggu review spec tertulis.
Branch: `feat/camera-registration-simple` (dari `main` @ `cb695f5`).
Checkpoint: `.cooper/context/next-features.md`.

---

## 1. Latar

Permintaan user: *"Camera Management, untuk simplified pendaftaran camera nya apakah bisa langsung native saja?
cek perbandingannya dengan project ActivityTracking-AI lebih mudah mana? karena admin supervisor ini tidak boleh
kebingungan inputnya. yang mereka pahami hanya ip camera, stream path mainstream dan substream."* Ditambah:
beberapa kamera memakai username/password yang **berbeda** dari default.

### Perbandingan

| | ActivityTracking-AI (`templates/settings.html:255`) | I-Sentinel sekarang (`CameraWizard.tsx`) |
|---|---|---|
| Input | Nama, Area, **1 URL** `rtsp://user:pass@ip/path` + Probe; substream opsional + "Suggest substream" | Nama, Lokasi, IP/Host, Port, **Node**, "Deteksi otomatis" (scan channel NVR) *atau* "Isi path manual" MAIN/SUB + Probe |
| Kredensial | di dalam URL, tersimpan polos | tidak ada di form; default `.env` (`CAM_USERNAME/CAM_PASSWORD`) atau "Profil kredensial" `env:NAMA` yang harus ditulis manual ke `.env` server |
| Tambahan | — | panel "Sumber & kredensial (lanjutan)", Import CCTV (CSV) |

### Data server (gspe-ai3, 2026-09-24, baca-saja lewat API)

- 13 kamera, semuanya `host` + `main_path` + `sub_path` (mis. `192.168.2.184`, `/Streaming/Channels/1401` /
  `1402`; ZKteco `192.168.2.179:8554` `/stream`, sub kosong).
- **0** stream source, **0** profil kredensial, **0** override; node selalu 1.
- cam 361/362: `sub_path == main_path` (AI memproses 1080p) — contoh salah isi yang tidak terlihat di form.

Kesimpulan: model data sudah cocok dengan mental model supervisor; yang membingungkan adalah UI. Meniru URL tunggal
ActivityTracking justru lebih rawan salah dan melanggar aturan zero-secret (`AGENTS.md` §6).

### Kode yang dipakai ulang

- `CredentialProfile(name, username, secret_ref, enabled)` + `Camera.credential_override_id` (sudah ada, belum
  dipakai). `secret_ref` saat ini hanya `env:NAMA` (`schemas/credential_profile.py:6`,
  `services/stream_endpoint.py:_secret`).
- `POST /api/v1/cameras/probe` sudah menerima `credential_override_id` (`api/probe.py`).
- `PATCH /api/v1/credential-profiles/{id}` sudah memicu sinkron go2rtc + config push bila `username`/
  `secret_ref`/`enabled` berubah.
- `backend` belum mendeklarasikan `cryptography` (tidak ada cipher simetris di stdlib).

## 2. Keputusan user

| # | Keputusan |
|---|---|
| K1 | Ada kamera dengan kredensial berbeda → form punya pilihan kredensial (default + profil bernama + "Kredensial baru…"). |
| K2 | Password disimpan dengan **pendekatan A**: file rahasia di server (0600), DB hanya referensi `store:cred_<id>`. Tanpa dependensi baru. |
| K3 | Fitur yang tidak dipakai (Node, scan NVR, panel Sumber, Import CSV) **disembunyikan di "Lanjutan"**, tidak dihapus. |
| K4 | go2rtc hardening di-skip (kredensial terbaca di LAN diterima; tidak boleh publik). |

## 3. Desain

### 3.1 Form tambah/ubah kamera (`CameraWizard.tsx`)

```
Nama kamera      [Lorong Manager                ]
Lokasi           [LT 2                        ▼]   ComboBox: lokasi yang ada atau ketik baru
IP kamera        [192.168.2.184                 ]   port opsional: 192.168.2.179:8554
Path mainstream  [/Streaming/Channels/1401      ]   wajib
Path substream   [/Streaming/Channels/1402      ]   kosong = pakai mainstream
Kredensial       [Default (NVR)               ▼]   + Kredensial baru…
                 [Tes koneksi]
                 MAIN 1920×1080 · 25 fps · h264 ✔   SUB 640×480 · 25 fps ✔
                 [thumbnail substream]
▸ Lanjutan: Node (hanya bila node > 1) · Cari channel NVR otomatis
                                               [Batal] [Simpan]
```

- **IP kamera** disimpan ke `host` apa adanya (sama dengan data sekarang). Port 554 default.
- **Path** dinormalisasi oleh `path_only` yang sudah ada (tempel URL penuh → path saja; tanpa `/` → ditambah).
- **Kredensial**: `Default (NVR)` = `credential_override_id: null`; lalu profil `enabled` urut nama;
  "+ Kredensial baru…" membuka dialog (Nama, Username, Password) → `POST /credential-profiles` → profil baru
  terpilih.
- **Tes koneksi** = probe yang ada + `snapshot: true` → tampilkan res/fps/codec MAIN & SUB + thumbnail SUB.
  Peringatan kuning bila `sub_path == main_path` ("substream sama dengan mainstream — AI akan memproses
  resolusi penuh").
- **Simpan** boleh tanpa tes; bila belum dites tampil konfirmasi "Simpan tanpa tes koneksi?".
- **Edit kamera** memakai form yang sama, terisi nilai kamera.
- **Lanjutan** (tertutup default): Node (select; disembunyikan bila hanya 1 node, dan node itu dipakai
  otomatis), tombol "Cari channel NVR otomatis" (alur scan lama; memilih channel mengisi path main/sub).

### 3.2 Halaman Kamera (`CamerasPage.tsx`)

- Panel `CameraSourcesPanel` **tidak dirender** lagi.
- Tombol header: `+ Tambah kamera` (utama) dan menu **Lanjutan** berisi: "Import CSV" (alur lama) dan
  "Kelola kredensial" (modal daftar profil: nama, username, status; aksi ganti password, ganti username,
  nonaktifkan — nonaktifkan ditolak 409 bila dipakai kamera aktif, pesan jelas).
- Tabel kamera: kolom baru kecil **Kredensial** ("Default" atau nama profil).

### 3.3 Penyimpanan password (`backend/app/services/secret_store.py`, baru)

- Setting `camera_secrets_file: str = "~/.isentinel/camera-secrets.json"` (`CAMERA_SECRETS_FILE`).
  **Harus di luar `storage_root`** — `/api/v1/media/{path}` menyajikan isi `storage_root`. Bila path berada di
  dalam `storage_root`, API tetap berjalan tetapi `secret_store` menolak `put`/`get` (error ter-log sekali,
  profil `store:` tidak bisa dibuat/di-resolve).
- Isi: JSON `{"cred_3": "<password>"}`. Tulis atomik (`tmp` di direktori yang sama → `os.chmod 0600` →
  `os.replace`), direktori dibuat `0700`. Satu `threading.Lock` per proses (API = satu proses uvicorn).
- API: `put(key, value)`, `get(key) -> str | None`, `delete(key)`.
- `stream_endpoint._secret`: `store:cred_<id>` → `secret_store.get`; `None` → `StreamEndpointError(
  "credential reference is unavailable")` (perilaku sama seperti `env:` yang hilang).

### 3.4 API profil kredensial

- `CredentialProfileIn`: `secret_ref` jadi opsional; field baru `password: str | None` (write-only, 1–256).
  Tepat satu dari `secret_ref` (`env:`) atau `password` wajib ada.
- `POST` dengan `password`: buat baris dulu (dapat `id`), `secret_store.put(f"cred_{id}", password)`,
  `secret_ref = f"store:cred_{id}"`, commit. Gagal tulis store → rollback + 500 "gagal menyimpan kredensial".
- `PATCH` dengan `password`: timpa nilai di store (key dari `secret_ref` bila `store:`, atau buat `cred_<id>`
  bila sebelumnya `env:`), `secret_ref` ikut diperbarui → memicu sinkron go2rtc + config push yang sudah ada.
- `CredentialProfileOut`: `secret_ref` **diganti** `has_password: bool` + `source: "env" | "store"`; password
  tidak pernah dikirim. (`frontend/src/api/credentialProfiles.ts` disesuaikan.)
- Validasi `secret_ref` menerima `env:NAMA` (input) — `store:` hanya dibuat server.

### 3.5 Probe snapshot

- `ProbeIn.snapshot: bool = False`. Bila true dan SUB (atau MAIN bila SUB kosong) terbaca: `ffmpeg
  -rtsp_transport tcp -i <url> -frames:v 1 -vf scale=480:-1 -f image2 -` (timeout 6 s) → `snapshot_jpeg_b64`.
  Tidak ditulis ke disk. Gagal → field `null`, probe tetap sukses.

### 3.6 Yang tidak berubah

Skema DB (tanpa migrasi), sinkron go2rtc, config push, vision node, Import CSV (alurnya), endpoint
stream-sources (backend tetap, hanya panel UI disembunyikan).

## 4. Penanganan error

| Kondisi | Perilaku |
|---|---|
| File rahasia tidak bisa ditulis | profil tidak dibuat; 500 + pesan UI "Gagal menyimpan kredensial" |
| `camera_secrets_file` di dalam `storage_root` | tulis ditolak + log error saat startup |
| Key `store:` hilang dari file | probe/go2rtc: "kredensial tidak tersedia" (sama dengan `env:` hilang) |
| Nama profil duplikat | 409 (sudah ada) → pesan inline di dialog |
| Probe gagal / timeout | baris MAIN/SUB "gagal · timeout", thumbnail kosong, Simpan tetap boleh |

## 5. Pengujian

- Backend `test_secret_store.py`: put/get/delete, izin file 0600, tulis atomik, penolakan path di dalam
  `storage_root`.
- Backend `test_credential_profiles_api.py`: POST dengan password → `secret_ref` `store:` di DB, response tanpa
  password (`has_password`), file berisi nilai; PATCH password memperbarui store; `env:` tetap diterima; keduanya
  kosong → 422; `_secret("store:…")` mengembalikan nilai.
- Backend probe: `snapshot: true` memanggil ffmpeg (subprocess di-mock) dan mengembalikan base64; gagal → null.
- Frontend `cameras.test.tsx` / wizard: form hanya menampilkan field utama; Lanjutan tertutup; Node tersembunyi
  bila 1 node; "+ Kredensial baru…" membuat profil lalu terpilih; peringatan `sub == main`; kolom Kredensial di
  tabel; panel Sumber tidak dirender.
- UI 390 px tanpa overflow horizontal (form + modal).
- Baseline: backend 342, vision 200 (3 deselected), frontend 121, build 0, lint set sama.

## 6. Verifikasi lapangan (butuh izin user)

Deploy ke gspe-ai3 (API restart; frontend Vite otomatis). Supervisor/user menambah satu kamera memakai form baru
(uji: kamera ZKteco atau kamera dengan kredensial berbeda), Tes koneksi menampilkan thumbnail, kamera muncul di
Live View. File rahasia di server `ls -l` → `-rw-------`, dan `grep` password di DB dump/API → tidak ada.

## 7. Di luar scope

Enkripsi file rahasia; hapus profil (cukup nonaktifkan); perubahan alur Import CSV; migrasi profil `env:` lama
(tidak ada datanya); Zona UX (antrean berikutnya); go2rtc hardening (di-skip, K4).

## 8. Rollback

`git revert`; profil `store:` yang terlanjur dibuat akan gagal di-resolve (kamera terkait perlu dikembalikan ke
Default atau `env:`) — sebutkan di runbook. Tanpa migrasi DB.
