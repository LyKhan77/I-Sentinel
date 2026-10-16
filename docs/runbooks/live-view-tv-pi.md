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
> akhir script. Untuk kiosk 24/7 pakai varian ber-supervisor di bawah.

## Script kiosk 24/7 (respawn + restart harian 03:30)
Terpasang di tiga Pi production sejak 2026-10-15 (`~/start-kiosk.sh`; cadangan versi lama `~/start-kiosk.sh.bak-20261015-fix2`).
Tiap jendela Chromium berjalan di loop: bila Chromium mati/crash, dijalankan ulang 5 detik kemudian (30 detik bila
mati < 10 detik setelah mulai, agar tidak berputar cepat). Satu loop `daily_restart` mematikan semua Chromium pada
03:30 WIB; loop jendela lalu menjalankannya lagi, jadi memori Chromium (naik ±35 MB/jam teramati) kembali bersih tiap hari.

```bash
#!/bin/bash
SERVER='http://<server>:7700'
RESTART_HHMM=${RESTART_HHMM:-0330}   # Asia/Jakarta, dibandingkan dengan jam SERVER
run_window() {   # $1=profil $2=posisi $3=URL
  local started
  while true; do
    started=$(date +%s)
    chromium --kiosk --noerrdialogs --disable-session-crashed-bubble \
      --user-data-dir="$1" --window-position="$2" --new-window "$3"
    if [ $(( $(date +%s) - started )) -lt 10 ]; then sleep 30; else sleep 5; fi
  done
}
daily_restart() {
  local last="" d t day hm
  while true; do
    sleep 30
    d=$(curl -sI --max-time 5 "$SERVER/" | sed -n 's/^[Dd]ate: *//p' | tr -d '\r')
    [ -n "$d" ] || continue
    t=$(TZ=Asia/Jakarta date -d "$d" +'%Y%m%d %H%M' 2>/dev/null) || continue
    day=${t% *}; hm=${t#* }
    if [ "$hm" = "$RESTART_HHMM" ] && [ "$day" != "$last" ]; then
      last=$day
      pkill -u "$(id -u)" -f '/usr/lib/chromium/chromium'
    fi
  done
}
sleep 5
run_window "$HOME/.config/chromium-profile-1" '0,0' 'http://<server>:7700/live/tv?screen=default&cameras=1,2,3&cols=1&scroll=on&speed=medium' &
sleep 3
run_window "$HOME/.config/chromium-profile-2" '1080,0' 'http://<server>:7700/live/tv?screen=default&cameras=4,5,6&cols=1&scroll=on&speed=medium' &
daily_restart &
wait
```
- **Jam diambil dari header `Date` server, bukan jam Pi**: jam ketiga Pi tidak tersinkron (`NTPSynchronized=no`,
  selisih 26–29 jam terukur 2026-10-15). Perbaikan NTP di Pi = pekerjaan terpisah (butuh sudo + akses NTP).
- Uji 2026-10-15 (Pi `.222`): restart terjadwal terdeteksi tepat pada menit yang dituju (Chromium pid 3633 → 3896);
  `kill -9` Chromium → hidup lagi ±6 detik (3896 → 4095). Uji ulang: jalankan script dengan `RESTART_HHMM=<HHMM server + 2>`.
- **Bubble "Translate" (Indonesian | English) di atas tile paling atas**: muncul bila bahasa Chromium bukan Indonesia
  (Pi `.162`/`.222` memakai `en-GB`; Pi `.235` memakai `id-ID` sehingga tidak muncul). Flag `--disable-features=Translate`
  **tidak** menghilangkannya di Chromium 142. Yang berhasil (2026-10-16): matikan Chromium, lalu di tiap
  `~/.config/chromium-profile-*/Default/Preferences` set `translate.enabled=false` dan tambahkan `"id"` ke
  `translate_blocked_languages`, lalu jalankan ulang kiosk. Edit Preferences hanya saat Chromium mati (Chromium menulis ulang file itu saat keluar).
- **Setelah menjalankan ulang dari SSH, pastikan tidak ada proses ganda**: `pgrep -fc 'bash .*start-kiosk.sh'` harus 3 (satu jendela)
  atau 4 (dua jendela). Bila `pkill` gagal dan script dijalankan lagi, dua supervisor berebut profil yang sama
  (load 12, RAM 3,1 GB, swap terpakai, layar kosong). Bersihkan dengan `pkill -u $(id -u) -f start-kiosk.sh` lalu
  `pkill -u $(id -u) -f /usr/lib/chromium/chromium`, pastikan `pgrep` kosong, baru jalankan sekali.
- Mematikan kiosk secara sengaja: `pkill -f start-kiosk.sh` **lalu** `pkill -f /usr/lib/chromium/chromium`
  (membunuh Chromium saja membuatnya hidup lagi). Menjalankan ulang dari SSH:
  `DISPLAY=:0 setsid nohup bash ~/start-kiosk.sh > /tmp/start-kiosk.log 2>&1 < /dev/null &`.

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
  praktiknya: restart script kiosk (matikan `start-kiosk.sh` dan Chromium, jalankan ulang perintah autostart).
- Akun TV sebaiknya `viewer` khusus; perangkat hilang → nonaktifkan akun / reset password dari
  Konfigurasi → User (sesi langsung ditolak).
- Beban server: tiap jendela hanya meminta info `/live` untuk kamera di URL-nya (tiap 30 s) dan satu poller `/events` (5 s). Beri jeda mulai berbeda antar Pi (mis. `sleep` 5, 35, 65 detik di `start-kiosk.sh`) agar tidak memuat bersamaan.
- Tile yang putus kembali streaming sendiri ≤ 60 s. Beban: pantau `top` di Pi; kurangi jumlah
  kamera di URL bila CPU > 85 %.

## Rollback
Hapus baris autostart; `rm -rf ~/.config/isentinel-tv-A ~/.config/isentinel-tv-B` untuk mengosongkan profil.
