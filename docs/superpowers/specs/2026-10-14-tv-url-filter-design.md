# TV URL Filter — Design Spec

- Tanggal: 2026-10-14
- Branch: `feat/tv-url-filter`
- Status: disetujui user; diamandemen 2026-10-14 (lihat §10: URL sebagai sumber kebenaran)

## 1. Latar Belakang & Tujuan

Command center (CRC) menampilkan Live View di beberapa Raspberry Pi. Script kiosk di tiap Pi membuka
Chromium secara otomatis, satu jendela per monitor, ke `/live/tv?screen=A` atau `?screen=B`. Hari ini
pilihan kamera, jumlah kolom, dan auto-scroll disimpan di `localStorage` per profil Chromium dan diatur
lewat toolbar dengan klik. Itu tidak bisa diotomasi: setiap Pi dan setiap profil harus diatur manual, dan
pengaturan hilang bila profil dihapus. Pemetaan "kamera mana tampil di monitor mana" harus ditentukan
lebih dulu, lalu ditulis ke script kiosk.

Tujuan:

1. URL `/live/tv` membawa daftar kamera (beserta kolom dan auto-scroll), sehingga script kiosk menentukan isi
   tiap monitor dan hasilnya sama setelah setiap reboot.
2. Konfigurasi Kamera menampilkan ID kamera, sebagai sumber nomor untuk menyusun pemetaan.
3. Login kiosk bertahan melewati reboot Pi (cookie sesi menjadi persisten).

Non-goals (sengaja tidak dikerjakan):

- Batas jumlah stream aktif, tampilan berhalaman, atau pengurangan beban stream. Perangkat yang kuat boleh
  menampilkan semua kamera yang diberikan.
- Perubahan pemilih kamera (`CameraPicker`) selain dinonaktifkan saat `cameras` ada di URL; tidak ada ID di
  pemilih.
- Parameter URL untuk halaman `/live` biasa.
- Generator URL, token atau kunci di URL, perubahan pipeline go2rtc atau player.

Anti-goals (akan dianggap gagal walau secara teknis jalan):

- Parameter URL yang ikut tertulis ke `localStorage` dan mengubah pengaturan tersimpan tanpa disadari.
- Perubahan perilaku untuk URL tanpa parameter baru.
- ID yang salah ketik membuat layar menampilkan semua kamera (beban tak terduga) atau error layar penuh.
- Melonggarkan keamanan sesi selain umur cookie di browser.

## 2. Keputusan Desain

| Keputusan | Pilihan | Sumber |
|---|---|---|
| Identitas kamera di URL | ID angka | user |
| Sumber daftar ID | halaman Konfigurasi Kamera, diberi kolom ID | user |
| Auto-scroll | tetap ada dan tetap dipakai | user |
| Batas stream | tidak ada | user |
| Cookie login | persisten (`Max-Age` = umur token, 48 jam, bergulir) — opsi B | user |
| Akun TV | akun `viewer` khusus, bisa dicabut dari Konfigurasi → User | user (runbook yang ada) |
| Urutan tile | mengikuti urutan ID di URL | **call saya** |
| `scroll` tanpa parameter | sama seperti sekarang (pengaturan tersimpan; bawaan mati) | **call saya** |
| Field yang diatur URL | dikunci di toolbar, tampil "Diatur oleh URL" | **call saya** |
| `cameras` ada tetapi tidak ada ID valid | pesan kosong, bukan fallback ke semua kamera | **call saya** |

## 3. Kontrak URL `/live/tv`

Contoh satu monitor:
`http://10.8.0.182:7700/live/tv?screen=A&cameras=1,4,20&cols=3&scroll=on&speed=medium`

| Parameter | Nilai | Perilaku |
|---|---|---|
| `screen` | `[A-Za-z0-9_-]{1,32}` (sudah ada) | Kunci pengaturan tersimpan per layar; tanpa nilai valid → `default`. Tidak berubah. |
| `cameras` | ID dipisah koma, mis. `1,4,20` | Tile ditampilkan dengan urutan di URL. Spasi di sekitar token dipangkas. Token bukan bilangan bulat positif dibuang. Duplikat dibuang (kemunculan pertama dipakai). ID yang tidak ada atau kameranya nonaktif dilewati. |
| `cols` | `2`, `3`, atau `4` | Jumlah kolom. Nilai lain diabaikan (pakai pengaturan tersimpan). |
| `scroll` | `on` atau `off` | Auto-scroll. Nilai lain diabaikan. |
| `speed` | `slow`, `medium`, `fast` | Kecepatan auto-scroll. Nilai lain diabaikan. |

Aturan:

- Nilai `scroll` dan `speed` tidak peka huruf besar-kecil.
- **`cameras` ada** (meski kosong atau berisi sampah) berarti mode URL aktif untuk pilihan kamera. Bila tidak ada
  satu pun kamera aktif yang cocok, layar menampilkan pesan kosong khusus URL (`live.tv.urlEmpty`), tidak
  fallback ke "semua kamera".
- **`cameras` tidak ada** → pilihan kamera memakai pengaturan tersimpan seperti sekarang.
- Nilai dari URL **tidak pernah ditulis ke `localStorage`**. Menghapus parameter dari URL mengembalikan pengaturan
  tersimpan.
- Field yang ditentukan URL (kamera, kolom, scroll, speed) dikunci di toolbar: kontrolnya dinonaktifkan dan diberi
  keterangan "Diatur oleh URL" (`live.tv.lockedByUrl`). Kontrol lain (suara, keluar) tetap aktif.
- Field yang tidak ada di URL tetap memakai pengaturan tersimpan per `screen`. Contoh: `cols` tidak ada di URL →
  kolom dari pengaturan tersimpan.
- URL tanpa parameter baru berperilaku persis seperti sekarang.

## 4. Perubahan

### 4.1 Frontend — Live TV

- `frontend/src/features/live/screenPrefs.ts`: fungsi murni baru untuk mem-parse `URLSearchParams` menjadi
  override (`cameras` berurutan, `cols`, `scroll`, `speed`) dan fungsi memilih kamera menurut daftar ID dengan
  urutan URL dari kamera aktif. Fungsi ini tidak menyentuh `localStorage`.
- `frontend/src/features/live/LiveTvPage.tsx`: menggabungkan pengaturan tersimpan dengan override URL untuk
  nilai efektif; `shown` memakai pemilihan menurut URL saat `cameras` ada; kontrol terkunci dinonaktifkan;
  pesan kosong URL; pengaturan dari toolbar tidak berubah untuk field yang tidak dikunci.
- `frontend/src/features/live/CameraPicker.tsx`: properti `disabled`; label tombol memperlihatkan n/m seperti
  sekarang.
- `frontend/src/app/i18n.tsx` (id dan en): `cameras.col.id` ("ID"), `live.tv.lockedByUrl`
  ("Diatur oleh URL" / "Set by URL"), `live.tv.urlEmpty` ("Tidak ada kamera aktif yang cocok dengan URL." /
  "No active camera matches the URL.").
- Auto-scroll, `LiveWall`, `useInView`, player go2rtc: tidak diubah.

### 4.2 Frontend — Konfigurasi Kamera

- `frontend/src/features/config/CamerasPage.tsx`: kolom `id` paling kiri (header dari `cameras.col.id`), sel
  berisi angka ID apa adanya, sempit dan tanpa pemotongan baris. Urutan baris tetap menurut ID dari API. Kamera
  nonaktif tetap tampil dengan ID-nya. `colSpan` baris kosong disesuaikan dengan jumlah kolom baru.
- Aturan repo berlaku: nol overflow horizontal pada 390 px. Kolom tambahan tidak boleh membuat halaman bergulir
  ke samping; pembangun memeriksa perilaku tabel pada 390 px sebelum dan sesudah.

### 4.3 Backend — cookie sesi persisten

- `backend/app/api/deps.py` `set_auth_cookie`: tambahkan `max_age=settings.access_token_expire_min * 60`.
  Karena login, ganti password, dan perpanjangan sesi bergulir semuanya lewat helper ini, ketiganya ikut. Dengan
  nilai bawaan Max-Age = 172800 detik (48 jam).
- Tidak berubah: `httponly`, `samesite="lax"`, `secure`, isi token, umur 48 jam, ambang perpanjangan separuh umur,
  `delete_cookie` pada logout (tetap `Max-Age=0`), tidak ada pengaturan baru dan tidak ada migrasi DB.
- Catatan keamanan: cookie persisten berarti sesi bertahan di profil browser Pi selama maksimal 48 jam bergulir.
  Pencabutan tetap berlaku seketika lewat menonaktifkan akun atau reset password (`token_version`) dan rotasi
  `JWT_SECRET`. Karena itu TV harus memakai akun `viewer` khusus.
- Efek operasional: Pi yang mati lebih dari 48 jam tanpa request perlu login ulang. Setelah sesi berakhir,
  `RequireAuth` (`main.tsx`) mengarahkan ke `/login` tanpa parameter `next`, jadi login ulang mendarat di
  dashboard, bukan di URL TV. Perilaku ini sudah ada dan **tidak diubah** di siklus ini (call saya); runbook
  mencatat bahwa setelah login ulang URL TV dibuka lagi (mis. restart script kiosk).

## 5. Pengujian

Pengujian harus gagal pada bug yang masuk akal, bukan mengunci detail implementasi.

- Vitest, parser URL (`live-prefs.test.ts` atau berkas baru): daftar valid; spasi; duplikat; token sampah, nol,
  negatif, desimal; nilai kosong; `cols` di luar 2/3/4; `scroll`/`speed` dengan huruf besar dan nilai tak dikenal;
  urutan hasil sama dengan urutan URL; ID tak ada atau nonaktif dilewati.
- Vitest, `live-tv.test.tsx`: `?cameras=3,1` menampilkan tile 3 lalu 1; `cameras` hanya berisi ID tak valid →
  pesan `urlEmpty`, bukan semua kamera; tanpa `cameras` → perilaku lama dan picker aktif; nilai URL tidak
  menulis `localStorage`; kontrol terkunci dinonaktifkan; `cols`/`scroll`/`speed` dari URL menang atas
  pengaturan tersimpan; field di luar URL tetap memakai pengaturan tersimpan.
- Vitest, `cameras.test.tsx`: kolom ID ada di posisi pertama, berisi ID yang benar dalam urutan ID, termasuk
  kamera nonaktif; baris kosong tetap meliputi semua kolom.
- Pytest, `backend/tests/test_auth_api.py`: `Set-Cookie` login memuat `Max-Age=172800`; cookie hasil perpanjangan
  bergulir juga memuat `Max-Age`; logout tetap `Max-Age=0`; tes yang ada (`test_default_session_is_48_hours`,
  perpanjangan, bearer tidak diperpanjang) tetap lulus.
- Verifikasi sebelum klaim selesai (dengan keluaran ditempel): `pytest tests -q -m "not gpu and not llm"`,
  `npx vitest run`, `npm run build`, `npm run lint`.
- Bukti UI di `docs/evidence/` (lokal, gitignored): tabel kamera pada 1280 px dan 390 px (tanpa overflow
  horizontal), dan `/live/tv?cameras=...` dengan urutan yang diminta serta toolbar terkunci.

## 6. Rollout & Rollback

- Branch `feat/tv-url-filter` dari `main`. Satu commit per perubahan fungsional (Conventional Commits): kolom ID,
  URL filter TV, cookie persisten, dokumentasi. Setiap perubahan dicatat di `CHANGELOG.md` (konteks, berkas,
  bukti, dampak, rollback). Tanpa `push` kecuali diminta user.
- Dev (`gspe-ai3`): alur Docker biasa, `./docker/setup.sh` (image `web` dan `api` berubah).
- Production (`gspe`, VPN `10.8.0.182`): image tidak bisa dibangun di server itu (`apt` ke CDN Debian terputus).
  Bangun `api` dan `web` di dev, kirim dengan `docker save` / `docker load` disertai verifikasi sha256, lalu
  jalankan `run-setup.sh` di direktori data. Setiap deploy, restart, dan push butuh izin eksplisit user.
- Rollback: revert commit dan deploy ulang image sebelumnya. Cookie yang sudah terbit tetap sah (hanya atribut
  umur di browser yang berbeda). Tidak ada perubahan skema atau data.

## 7. Dokumentasi yang Ikut Diperbarui

- `docs/runbooks/live-view-tv-pi.md`: contoh URL per monitor, cara mengambil ID dari Konfigurasi Kamera, templat
  tabel pemetaan monitor → ID, catatan cookie persisten dan akun `viewer` khusus, koreksi klaim "login sekali per
  profil" agar sesuai perilaku baru.
- `README.md`, `WORKFLOW.md`, `ARCHITECTURE.md` (bagian mode TV dan sesi bergulir), `ROADMAP.md` (item siklus ini),
  `CHANGELOG.md`.

## 8. Diserahkan ke Pembangun

- Struktur internal komponen dan penamaan fungsi, selama fungsi parser murni dan teruji.
- Redaksi teks selain yang disebut, gaya tampilan keadaan terkunci, dan label n/m picker pada mode URL.
- Cara memeriksa dan menjaga nol overflow tabel kamera pada 390 px.

## 9. Pertanyaan Terbuka

Tidak ada. Empat call pada bagian 2 dan satu call pada bagian 4.3 (semuanya ditandai **call saya**) perlu dicek
user saat membaca spec. Pengecekan pembangun (reviewer independen) tidak menemukan pertanyaan penting yang
tersisa.

## 10. Amandemen 2026-10-14 — URL sebagai sumber kebenaran per jendela

Alasan: setelah uji di dev, user ingin menyusun script kiosk dengan memblok dan menyalin URL dari address bar, dan
satu Raspberry Pi menjalankan dua monitor dengan tampilan berbeda. Persistensi paling cocok berbasis tab/jendela,
yaitu URL itu sendiri (tahan restart karena script kiosk yang menyimpannya); `sessionStorage` tidak dipakai.

Keputusan user: (a) address bar `/live/tv` mengikuti toolbar; (b) toolbar tetap bisa diedit dan setiap perubahan
menulis ulang URL, tidak ada kontrol terkunci; (c) dikerjakan di branch yang sama, diuji di dev, baru ke production.

**Menggantikan** dari §2/§3/§4.1/§5: aturan "field yang diatur URL dikunci di toolbar" dan "nilai URL tidak pernah
ditulis ke `localStorage`". Tidak berubah: parser URL, `selectByIds`, pesan `live.tv.urlEmpty`, kolom ID, cookie persisten.

Aturan baru:

1. Nilai efektif saat dimuat: parameter URL yang valid > pengaturan tersimpan per `screen` > bawaan (sama seperti sebelumnya).
2. Membuka halaman tidak menulis apa pun (URL maupun `localStorage`), sehingga URL kiosk tidak berubah sendiri.
3. Aksi toolbar (kolom, auto-scroll, kecepatan, pemilih kamera): (a) memperbarui `localStorage` untuk `screen` itu seperti
   sebelumnya, dan (b) menulis ulang URL dengan `replace` (tanpa entri riwayat) berisi `cameras` (daftar ID eksplisit),
   `cols`, `scroll` (`on`/`off`), dan `speed`. Parameter lain, termasuk `screen`, dipertahankan persis; `screen` tidak
   ditambahkan bila tidak ada di URL.
4. Urutan `cameras` hasil edit: ID yang masih terpilih mempertahankan urutan sebelumnya, ID yang baru dicentang
   ditambahkan di akhir menurut urutan kamera (ID); "Semua" = semua kamera aktif dengan ID yang sudah ada tetap di urutan lama dan sisanya di akhir menurut urutan kamera (pemilih mengubah "semua dicentang" menjadi mode `all`, jadi aturannya sama); "Kosongkan" =
   `cameras=` kosong (layar menampilkan pesan `live.tv.urlEmpty`). **Call saya.**
5. Tidak ada kontrol toolbar yang `disabled` karena URL; `live.tv.lockedByUrl`, `data-testid="live-tv-locked"`, dan
   properti `disabled` pada `CameraPicker` dihapus.
6. Chromium kiosk tetap butuh `--user-data-dir` terpisah per jendela (kebutuhan Chromium); cookie login tetap per profil.

Pengujian tambahan: fungsi murni `orderCameraIds` dan `tvSearch` (screenPrefs); di `live-tv.test.tsx`: toolbar
aktif saat URL berparameter; tiap aksi (kolom, scroll, speed, pemilih) menulis ulang URL dengan navigasi `REPLACE` dan
mempertahankan `screen`; urutan ID hasil edit; membuka URL tidak mengubah URL maupun `localStorage`; URL tanpa
parameter + satu edit menghasilkan URL lengkap.

## 11. Tambahan 2026-10-14 — layout 1 kolom

Permintaan user setelah uji dev: tambah pilihan **1 kolom** (satu tile selebar layar). Berlaku untuk `/live` dan `/live/tv`.
`Cols` menjadi `1 | 2 | 3 | 4`; parameter URL `cols` menerima 1–4 (nilai lain diabaikan); `COL_OPTIONS` = `[3, 2, 4, 1]`
(posisi chip lama tidak berubah, 1 kolom di akhir, **call saya**); label "1 kolom" / "1 column" lewat `live.col1`.
Aturan CSS yang memaksa 2 kolom (≤1055 px) dan 1 kolom (≤671 px) tetap untuk 2–4 kolom; pilihan 1 kolom memakai kelas
`lv-grid--one` sehingga satu kolom dihormati di semua lebar. Tidak ada perubahan pemilihan stream: tile memakai
`cam_<id>` (SUB bila ada), jadi pada 1 kolom di monitor 1080p gambar SUB diperbesar; memakai stream MAIN pada 1 kolom
adalah perubahan terpisah bila diinginkan.
