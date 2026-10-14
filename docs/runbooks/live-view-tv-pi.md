# Runbook — Live View mode TV di Raspberry Pi (2 monitor)

Tujuan: satu Raspberry Pi 5 menampilkan `/live/tv` di dua monitor command center, pulih sendiri setelah boot.

## Prasyarat
- Raspberry Pi OS (Bookworm, desktop), Chromium terpasang, kedua monitor terdeteksi (Screen Configuration).
- Resolusi monitor 1080p (disarankan untuk beban decode; Pi 5 tanpa decoder H.264 hardware).
- URL aplikasi: `http://<server>:5173` (LAN).
- Akun TV khusus role `viewer` (buat di Konfigurasi → User); perangkat hilang → nonaktifkan akun
  atau reset password (sesi langsung ditolak).

## Menyusun URL per monitor

`/live/tv` membaca parameter URL sehingga isi tiap monitor ditentukan oleh script kiosk,
bukan oleh klik di toolbar. Daftar ID kamera diambil dari kolom **ID** paling kiri di
**Konfigurasi → Kamera** (kamera nonaktif tetap punya ID dan ikut tercetak).

| Parameter | Nilai | Perilaku |
|---|---|---|
| `screen` | `A`/`B`/nama bebas (huruf/angka/-/_ ≤ 32) | Kunci pengaturan tersimpan per layar; opsional. |
| `cameras` | ID dipisah koma, mis. `1,4,20` | Tile mengikuti urutan ID di URL. Token bukan bilangan bulat positif dibuang; duplikat dibuang. ID nonaktif/tak ada dilewati. Ada parameter tapi tidak ada yang cocok → layar menampilkan pesan kosong (bukan semua kamera). |
| `cols` | `2`, `3`, `4` | Jumlah kolom; nilai lain diabaikan. |
| `scroll` | `on` / `off` | Auto-scroll (tidak peka huruf besar-kecil); nilai lain diabaikan. |
| `speed` | `slow` / `medium` / `fast` | Kecepatan auto-scroll; nilai lain diabaikan. |

Field yang diatur URL **dikunci di toolbar** (dinonaktifkan, berlabel "Diatur oleh URL") dan
nilai URL **tidak pernah ditulis ke `localStorage`** — menghapus parameter dari URL mengembalikan
pengaturan tersimpan. Tanpa parameter baru, perilaku persis seperti sebelumnya.

Contoh satu monitor:
```
http://<server>:5173/live/tv?screen=A&cameras=1,4,20&cols=3&scroll=on&speed=medium
```

Templat pemetaan (isi setelah kolom ID tersedia):

| Pi | Monitor | screen | cameras | URL |
|---|---|---|---|---|
| pi-tv-1 | kiri | A | 1,4,20 | `http://<server>:5173/live/tv?screen=A&cameras=1,4,20&cols=3&scroll=on&speed=medium` |
| pi-tv-1 | kanan | B | 2,3 | `http://<server>:5173/live/tv?screen=B&cameras=2,3&cols=2&scroll=on&speed=medium` |

Tidak ada batas jumlah stream: semua kamera yang dicantumkan ditampilkan. Pantau `top` di Pi;
turunkan jumlah kamera di URL bila CPU > 85 %.

## Satu kali per layar
1. Jalankan Chromium dengan profil layar A (perintah di bawah tanpa `--kiosk`), login dengan akun
   `viewer`, lalu tutup. Ulangi untuk layar B. Setiap profil menyimpan cookie dan pengaturan layarnya sendiri.

## Perintah per layar
```bash
chromium-browser --kiosk --noerrdialogs --disable-infobars --autoplay-policy=no-user-gesture-required \
  --user-data-dir="$HOME/.config/isentinel-tv-A" --window-position=0,0 \
  "http://<server>:5173/live/tv?screen=A&cameras=<id1>,<id2>&cols=3&scroll=on"

chromium-browser --kiosk --noerrdialogs --disable-infobars --autoplay-policy=no-user-gesture-required \
  --user-data-dir="$HOME/.config/isentinel-tv-B" --window-position=1920,0 \
  "http://<server>:5173/live/tv?screen=B&cameras=<id3>,<id4>&cols=3&scroll=on"
```
`--window-position` = posisi kiri-atas monitor kedua di layout desktop (lebar monitor pertama).
Tulis parameter `scroll=on` eksplisit di script kiosk bila auto-scroll diinginkan.

## Autostart
Tambahkan kedua perintah (diakhiri `&`) ke `~/.config/labwc/autostart` (Wayland/labwc) atau
`~/.config/lxsession/LXDE-pi/autostart` (X11, awali tiap baris dengan `@`).

## Operasional
- Gerakkan mouse → toolbar muncul: kolom, **Kamera (n/m)**, gulir otomatis + kecepatan, Keluar.
  Kontrol yang diatur URL terkunci dan diberi label "Diatur oleh URL".
- **Cookie persisten 48 jam bergulir**: cookie login kini menyimpan `Max-Age` = umur token
  (default 172800 detik) dan diperpanjang otomatis selama halaman terbuka me-refresh, sehingga
  Pi yang reboot diharapkan tetap login selama kunjungan terakhir < 48 jam (belum diuji di Pi: setelah
  uji pertama, reboot Pi lalu pastikan `/live/tv` terbuka tanpa halaman login dan catat hasilnya di sini).
- Pi yang mati > 48 jam tanpa request → sesi berakhir dan `RequireAuth` mengarahkan ke `/login`
  (dashboard, tanpa kembali ke URL TV otomatis). Login ulang sekali, lalu buka URL TV lagi —
  praktiknya: restart script kiosk (kill Chromium, jalankan ulang perintah autostart).
- Akun TV sebaiknya `viewer` khusus; perangkat hilang → nonaktifkan akun / reset password dari
  Konfigurasi → User (sesi langsung ditolak).
- Tile yang putus kembali streaming sendiri ≤ 60 s. Beban: pantau `top` di Pi; kurangi jumlah
  kamera di URL bila CPU > 85 %.

## Rollback
Hapus baris autostart; `rm -rf ~/.config/isentinel-tv-A ~/.config/isentinel-tv-B` untuk mengosongkan profil.
