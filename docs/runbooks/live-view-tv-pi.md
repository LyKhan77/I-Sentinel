# Runbook — Live View mode TV di Raspberry Pi (2 monitor)

Tujuan: satu Raspberry Pi 5 menampilkan `/live/tv` di dua monitor command center, pulih sendiri setelah boot.

## Prasyarat
- Raspberry Pi OS (Bookworm, desktop), Chromium terpasang, kedua monitor terdeteksi (Screen Configuration).
- Resolusi monitor 1080p (disarankan untuk beban decode; Pi 5 tanpa decoder H.264 hardware).
- URL aplikasi: `http://<server>:5173` (LAN).

## Satu kali per layar
1. Jalankan Chromium dengan profil layar A (perintah di bawah tanpa `--kiosk`), login, lalu tutup.
2. Ulangi untuk layar B. Setiap profil menyimpan cookie login dan pengaturan layarnya sendiri.

## Perintah per layar
```bash
chromium-browser --kiosk --noerrdialogs --disable-infobars --autoplay-policy=no-user-gesture-required \
  --user-data-dir="$HOME/.config/isentinel-tv-A" --window-position=0,0 \
  "http://<server>:5173/live/tv?screen=A"

chromium-browser --kiosk --noerrdialogs --disable-infobars --autoplay-policy=no-user-gesture-required \
  --user-data-dir="$HOME/.config/isentinel-tv-B" --window-position=1920,0 \
  "http://<server>:5173/live/tv?screen=B"
```
`--window-position` = posisi kiri-atas monitor kedua di layout desktop (lebar monitor pertama).

## Autostart
Tambahkan kedua perintah (diakhiri `&`) ke `~/.config/labwc/autostart` (Wayland/labwc) atau
`~/.config/lxsession/LXDE-pi/autostart` (X11, awali tiap baris dengan `@`).

## Operasional
- Gerakkan mouse → toolbar muncul: kolom, **Kamera (n/m)**, gulir otomatis + kecepatan, Keluar.
- Sesi login diperpanjang otomatis selama halaman terbuka (48 jam tanpa aktivitas → login ulang).
- Tile yang putus kembali streaming sendiri ≤ 60 s. Beban: pantau `top` di Pi; turunkan kolom bila CPU > 85 %.

## Rollback
Hapus baris autostart; `rm -rf ~/.config/isentinel-tv-A ~/.config/isentinel-tv-B` untuk mengosongkan profil.
