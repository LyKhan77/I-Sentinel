# Spec — Live View mode TV (kiosk, auto-scroll, filter kamera, layout responsif)

Status: **DISETUJUI di chat (2026-09-28)**, menunggu review spec tertulis.
Branch: `feat/live-view-tv` (dari `main` @ `de32abc`).
Checkpoint: `.cooper/context/next-features.md`.

---

## 1. Latar

Usulan user: Live View untuk **TV monitoring command center** — mode fokus/kompak, toggle auto-scroll, filter
checkbox per kamera, responsif untuk TV horizontal & vertikal FHD/2K/4K.

Konteks pemakaian (jawaban user):
- Dipakai **setiap hari oleh operator** di ruang command center.
- Smart TV 2K, tampilan web lewat **satu Raspberry Pi 5 yang menggerakkan 2 monitor** (resolusi bisa di-set 1080p
  agar ringan). Bila aplikasi jalan di browser Smart TV, Pi ingin dicopot.

### Kondisi kode (`main` @ `de32abc`)

| # | Fakta | Lokasi |
|---|---|---|
| 1 | Live View: grid kolom 2/3/4 (`localStorage` `isentinel_live_cols`), filter lokasi (Dropdown), klik tile → modal debugger (zona + deteksi realtime). | `frontend/src/features/live/LiveViewPage.tsx` |
| 2 | Tiap tile memutar `<video-stream>` go2rtc (webrtc → mse) **semua sekaligus**; gagal dalam 10 s → snapshot proxy tiap 2 s. | `CameraTile` |
| 3 | **Bug 24/7**: `streamFailed` tidak pernah di-reset → tile yang sekali gagal tetap di snapshot selamanya (refresh `/live` 30 s tidak me-remount tile). | `CameraTile` |
| 4 | Semua halaman ber-auth di bawah `AppShell` (header + side nav). | `frontend/src/main.tsx` |
| 5 | JWT HS256 di cookie httpOnly, `exp` = `access_token_expire_min` (**480 = 8 jam**), tanpa perpanjangan → TV terlempar ke login tiap 8 jam. `get_current_user` membaca ulang user dari DB tiap request. | `backend/app/core/config.py:8`, `core/security.py`, `api/deps.py`, `api/auth.py:_login` |
| 6 | Pi 5 tidak punya decoder H.264 hardware → decode CPU; perkiraan kasar ≈ 9 substream 640×480 per layar (18 untuk 2 layar) masih layak di 1080p, 16 per layar tidak. | pengetahuan umum, divalidasi lapangan |

## 2. Keputusan user

| # | Keputusan |
|---|---|
| K1 | Pemakaian: operator aktif di command center, Pi 5 → 2 monitor 2K (bisa 1080p). |
| K2 | Kamera per layar mengikuti UX terbaik → **default 3 kolom horizontal (9 terlihat di 1080p)**, 2 kolom vertikal; 4 kolom tetap opsi. |
| K3 | Auto-scroll = **gulir halus vertikal terus-menerus** di satu halaman (bukan ganti halaman). |
| K4 | Mode fokus = **layar penuh ala kiosk** (tanpa header/menu; toolbar muncul saat mouse bergerak). |
| K5 | Pengaturan per layar: **`?screen=<nama>` + penyimpanan browser** (tanpa backend). |
| K6 | Sesi: **sesi bergulir** + masa berlaku **> 24 jam** (48 jam). Penyesuaian User management dicatat (§3.6). |

## 3. Desain

### 3.1 Mode TV (kiosk)

- Route baru **`/live/tv`** di bawah `RequireAuth` tetapi **di luar `AppShell`** → tanpa header/side nav, grid
  memenuhi viewport (`100vw × 100vh`, latar hitam).
- Nama layar dari query `?screen=` (huruf/angka/`-`/`_`, maks 32; kosong/tidak valid → `default`).
- Live View biasa mendapat tombol **"Mode TV"**: navigasi ke `/live/tv?screen=<layar aktif>` lalu
  `document.documentElement.requestFullscreen()` (diabaikan bila ditolak/tidak didukung).
- **Toolbar** (overlay atas) muncul saat mouse bergerak / sentuh / tombol ditekan, hilang sendiri setelah **4 s**
  tanpa aktivitas; kursor ikut disembunyikan saat toolbar hilang. Isi: nama layar, kolom 2/3/4, pemilih kamera,
  auto-scroll on/off + kecepatan, tombol keluar (kembali ke `/live`, keluar fullscreen).
- Klik tile → modal debugger yang sama dengan Live View biasa.
- Runbook Pi: Chromium `--kiosk --app=…/live/tv?screen=A` dan `?screen=B` pada `--window-position` monitor
  masing-masing (dua profil/jendela), autostart saat boot.

### 3.2 Layout responsif

- Tile tetap **16:9**, lebar = lebar viewport / kolom (grid CSS yang ada).
- Kolom default saat layar belum punya pengaturan: `matchMedia('(orientation: portrait)')` → **2**, selain itu **3**.
  Pilihan operator disimpan per layar.
- Di mode TV, teks overlay tile (nama kamera, badge LIVE/OFFLINE) memakai `clamp()` berbasis `vw` supaya terbaca di
  2K/4K dari jarak kursi; celah antar tile 2 px.
- Live View biasa tetap: < 672 px 1 kolom, < 1056 px 2 kolom (390 px tanpa overflow).

### 3.3 Filter kamera (checkbox)

- Dropdown lokasi diganti **pemilih kamera** (panel/popover): kamera aktif dikelompokkan per lokasi (tanpa lokasi →
  "Lainnya"); checkbox per kamera; checkbox judul grup (termasuk status indeterminate); tombol **Semua** dan
  **Kosongkan**; penghitung "n dari m kamera".
- Berlaku di Live View biasa (layar `default`) dan mode TV (layar dari `?screen=`), komponen yang sama.
- Penyimpanan: `{"mode": "all"}` atau `{"mode": "some", "ids": [..]}`. `all` → kamera baru otomatis tampil. ID
  kamera yang sudah dihapus/nonaktif diabaikan saat render. Pilihan kosong → pesan "Belum ada kamera dipilih" +
  tombol buka pemilih.

### 3.4 Auto-scroll halus vertikal

- Toggle per layar (default **off**), kecepatan **lambat / sedang / cepat** = 20 / 40 / 80 px per detik
  (dikalibrasi di lapangan; nilai jadi konstanta).
- Loop: gulir ke bawah → sampai dasar, **jeda 5 s** → kembali ke atas (lompat halus) → **jeda 5 s** → ulang.
- **Jeda otomatis**: saat mouse bergerak/klik di grid, toolbar/pemilih terbuka, atau modal debugger terbuka; lanjut
  **10 s** setelah aktivitas terakhir. Konten muat satu layar → tidak menggulir.
- Implementasi `requestAnimationFrame` pada kontainer grid (bukan `window`), posisi pecahan diakumulasi agar
  kecepatan rendah tetap halus.

### 3.5 Hemat beban + pulih sendiri (24/7)

- **Stream hanya untuk tile terlihat**: `IntersectionObserver` pada tiap tile dengan `rootMargin` satu baris
  (≈ tinggi tile) di bawah viewport. Di luar area → `<video-stream>` di-unmount, tile menampilkan snapshot terakhir
  (tanpa refresh berkala). Masuk area → snapshot tetap tampil sampai video `playing` (tanpa kotak hitam).
  Berlaku di Live View biasa dan mode TV.
- **Coba ulang stream**: tile di mode snapshot karena gagal stream mencoba streaming lagi tiap **60 s**
  (perbaikan bug #3). Tidak ada perubahan pada go2rtc/backend.

### 3.6 Sesi bergulir

- `access_token_expire_min` default **480 → 2880** (48 jam); tetap bisa diatur lewat `ACCESS_TOKEN_EXPIRE_MIN`
  (`.env.example` diperbarui).
- `get_current_user`: bila sisa umur token < **separuh** masa berlaku, terbitkan token baru dan set cookie di
  response (atribut sama dengan `_login`). Hanya untuk token dari cookie (Bearer tidak diubah).
- Live View me-refresh `/live` tiap 30 s → TV tidak pernah logout selama halaman terbuka; tab tertutup > 48 jam
  tetap kedaluwarsa.
- **Catatan untuk User management** (di luar siklus ini): tambah `is_active` (cek di `get_current_user`, sesi
  langsung ditolak) dan `token_version` (naik saat ganti password/role → token lama tak berlaku, termasuk yang
  bergulir); akun TV memakai role `viewer` (Live View + Events saja).

### 3.7 Penyimpanan per layar (frontend)

- Satu kunci `localStorage` per layar: `isentinel_live_screen:<nama>` →
  `{"cols": 2|3|4, "cameras": {...§3.3}, "scroll": {"on": bool, "speed": "slow"|"medium"|"fast"}}`.
- Nilai rusak/tidak ada → default; akses dibungkus try/catch (mode privat / storage penuh tidak mematahkan halaman).
- Kunci lama `isentinel_live_cols` dibaca sekali sebagai default `cols` layar `default`.

### 3.8 Smart TV tanpa Pi

- Tidak ada aplikasi native (Tizen/webOS) di siklus ini. Player sudah berurutan webrtc → mse → snapshot; setelah
  fitur ini, **spike lapangan**: buka `/live/tv?screen=A` di browser Smart TV → catat transport yang jalan, beban,
  fullscreen, stabilitas 1 jam → putuskan Pi dicopot atau tidak.

## 4. Penanganan error

| Kondisi | Perilaku |
|---|---|
| `?screen=` tidak valid | pakai `default` |
| Storage rusak / tidak tersedia | default, tanpa crash |
| Stream gagal / putus | snapshot, coba ulang tiap 60 s |
| `/live` API gagal | notifikasi error seperti sekarang, grid tetap |
| Fullscreen ditolak browser | tetap mode TV (tanpa fullscreen) |
| Semua kamera tidak dipilih | pesan + tombol buka pemilih |
| Token hampir habis | cookie diperbarui otomatis |

## 5. Pengujian

- Frontend (Vitest):
  - penyimpanan per layar (dua layar tidak saling menimpa, nilai rusak → default, migrasi `isentinel_live_cols`);
  - pemilih kamera (grup lokasi, Semua/Kosongkan, `all` ikut kamera baru, ID hilang diabaikan);
  - route `/live/tv` tanpa header/side nav, toolbar auto-hide (fake timers);
  - auto-scroll (fake timers + rAF: maju, jeda di dasar, kembali ke atas, jeda saat aktivitas, tidak menggulir bila
    muat);
  - tile di luar viewport tidak me-mount `<video-stream>` (mock `IntersectionObserver`), coba ulang 60 s.
- Backend (pytest): cookie diperbarui saat sisa < separuh, tidak saat masih baru, Bearer tidak diubah, default 2880.
- Visual (browser): 1920×1080, 2560×1440, 3840×2160, 1080×1920, 390 px → tanpa overflow horizontal, teks terbaca.
- Baseline `main` `de32abc`: backend 432, vision 223 (3 deselected), frontend 142, build 0, lint set sama.

## 6. Verifikasi lapangan (butuh izin user)

Deploy (restart API; frontend Vite dev HMR). Pi 5 dua monitor: `?screen=A` 3 kolom semua kamera + auto-scroll
sedang, `?screen=B` pilihan kamera lain → kedua layar tidak saling menimpa, gulir halus, beban CPU Pi (`top`)
tercatat, tile kembali streaming setelah go2rtc di-restart, sesi tetap login > 8 jam. Spike Smart TV (§3.8).

## 7. Di luar scope

Layout tersimpan di server, akun/role `viewer` dan `is_active`/`token_version` (User management), audio, tour satu
kamera, penanda event/alert di tile, aplikasi native Smart TV.

## 8. Rollback

`git revert` + restart API. Tanpa migrasi DB. Kunci `localStorage` baru tidak mengganggu kode lama.
