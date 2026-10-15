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
| `cols` | `1`, `2`, `3`, `4` | Jumlah kolom; nilai lain diabaikan. `1` = satu tile selebar layar (dihormati di semua lebar layar; 2–4 kolom tetap turun otomatis di layar sempit). |
| `scroll` | `on` / `off` | Auto-scroll (tidak peka huruf besar-kecil); nilai lain diabaikan. |
| `speed` | `slow` / `medium` / `fast` | Kecepatan auto-scroll; nilai lain diabaikan. |

**URL adalah sumber kebenaran per jendela.** Membuka URL tidak menulis apa pun; hanya aksi toolbar
(kolom, gulir, kecepatan, pemilih kamera) yang menulis ulang URL (replace, tanpa entri riwayat) dan
`localStorage` layar itu. Nilai efektif saat dimuat: parameter URL yang valid > pengaturan tersimpan per
`screen` > bawaan. Tanpa parameter baru, perilaku persis seperti sebelumnya.

**Membuat URL kiosk (disarankan):** buka `/live/tv` di browser biasa, atur kamera (pemilih), kolom, gulir,
dan kecepatan lewat toolbar; address bar langsung mengikuti, mis.
`…/live/tv?screen=A&cameras=3,1,7&cols=3&scroll=on&speed=medium`. Blok URL itu, salin, lalu tempel ke script
kiosk. Urutan tile = urutan `cameras`; kamera yang baru dicentang ditambahkan di akhir; "Kosongkan" menghasilkan
`cameras=` (pesan "Tidak ada kamera aktif yang cocok dengan URL").

Tiap jendela/tab punya URL sendiri, sehingga dua monitor di satu Pi (profil Chromium terpisah A dan B)
menampilkan kamera berbeda: isi tiap monitor ditentukan oleh URL di script, bukan oleh penyimpanan browser.

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

> **Wajib beri kutip pada URL.** Tanda `&` tanpa kutip di bash berarti "jalankan di background": URL terpotong di `&` pertama
> (Chromium hanya menerima `…/live/tv?screen=default`), parameter `cameras`, `cols`, `scroll`, `speed` hilang, dan layar
> menampilkan **semua kamera** dari pengaturan tersimpan. Gejala: jendela menampilkan 19/19 kamera padahal URL di script
> berisi daftar `cameras`. Periksa dengan `ps -eo args | grep chromium | grep -v -- --type=` (URL harus lengkap).
> Dengan URL dikutip, tambahkan ` &` di akhir tiap perintah `chromium` (supaya jendela kedua tetap dibuka) dan `wait` di
> akhir script, contoh `start-kiosk.sh` untuk dua jendela:
> ```bash
> #!/bin/bash
> sleep 5
> chromium --kiosk --user-data-dir=$HOME/.config/chromium-profile-1 --window-position=0,0 --new-window \
>   'http://<server>:7700/live/tv?screen=default&cameras=1,2,3&cols=1&scroll=on&speed=medium' &
> sleep 3
> chromium --kiosk --user-data-dir=$HOME/.config/chromium-profile-2 --window-position=1080,0 --new-window \
>   'http://<server>:7700/live/tv?screen=default&cameras=4,5,6&cols=1&scroll=on&speed=medium' &
> wait
> ```

## Autostart
Tambahkan kedua perintah (diakhiri `&`) ke `~/.config/labwc/autostart` (Wayland/labwc) atau
`~/.config/lxsession/LXDE-pi/autostart` (X11, awali tiap baris dengan `@`).

## Operasional
- Gerakkan mouse → toolbar muncul: kolom, **Kamera (n/m)**, gulir otomatis + kecepatan, Keluar.
  Perubahan di toolbar menulis ulang URL jendela itu; setelah kiosk di-restart isi monitor ditentukan lagi oleh URL di script.
- **Cookie persisten 48 jam bergulir**: cookie login kini menyimpan `Max-Age` = umur token
  (default 172800 detik) dan diperpanjang otomatis selama halaman terbuka me-refresh, sehingga
  Pi yang reboot tetap login selama kunjungan terakhir < 48 jam (teramati 2026-10-15 pada tiga Pi: setelah reboot/restart
  Chromium kiosk langsung memuat stream tanpa halaman login).
- Pi yang mati > 48 jam tanpa request → sesi berakhir dan `RequireAuth` mengarahkan ke `/login`
  (dashboard, tanpa kembali ke URL TV otomatis). Login ulang sekali, lalu buka URL TV lagi —
  praktiknya: restart script kiosk (kill Chromium, jalankan ulang perintah autostart).
- Akun TV sebaiknya `viewer` khusus; perangkat hilang → nonaktifkan akun / reset password dari
  Konfigurasi → User (sesi langsung ditolak).
- Tile yang putus kembali streaming sendiri ≤ 60 s. Beban: pantau `top` di Pi; kurangi jumlah
  kamera di URL bila CPU > 85 %.

## Rollback
Hapus baris autostart; `rm -rf ~/.config/isentinel-tv-A ~/.config/isentinel-tv-B` untuk mengosongkan profil.
