# TV URL Filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/live/tv` membaca daftar kamera (dan kolom, auto-scroll) dari URL; tabel Konfigurasi Kamera menampilkan kolom ID; cookie login menjadi persisten.

**Architecture:** Parser URL berupa fungsi murni di `screenPrefs.ts`; `LiveTvPage` menggabungkan pengaturan tersimpan dengan override URL (tidak pernah menulis ke `localStorage`) dan mengunci kontrol yang diatur URL. Backend hanya menambah `max_age` pada helper tunggal `set_auth_cookie`. Tidak ada migrasi DB, endpoint, atau dependensi baru.

**Tech Stack:** FastAPI (Starlette `set_cookie`), React 19 + TypeScript, React Router 7 (`useSearchParams`), IBM Carbon, Vitest + Testing Library, pytest.

**Spec:** `docs/superpowers/specs/2026-10-14-tv-url-filter-design.md` (disetujui user 2026-10-14; baca bersama rencana ini).

## Global Constraints

- Tidak ada dependensi baru; tidak ada migrasi; vision/go2rtc/`LiveWall`/`useInView` tidak diubah.
- Tidak ada batas jumlah stream; auto-scroll tetap berjalan seperti sekarang.
- Nilai dari URL **tidak pernah** ditulis ke `localStorage`; URL tanpa parameter baru berperilaku persis seperti sekarang.
- Cookie: `Max-Age = settings.access_token_expire_min * 60` (bawaan 2880 menit → `172800`); `httponly`, `samesite="lax"`, `secure`, isi token, ambang perpanjangan separuh umur, dan `delete_cookie` pada logout tidak berubah.
- Semua teks tampil lewat `frontend/src/app/i18n.tsx` (id **dan** en); komponen Carbon; nol overflow horizontal pada 390 px.
- Commit: Conventional Commits, satu per perubahan fungsional, **tanpa atribusi AI**; tanpa `push` kecuali user mengizinkan eksplisit (tiap push).
- Jalankan suite berurutan (pytest, lalu vitest/build/lint); `env -u NODE_ENV` untuk backend/frontend/build/lint; dilarang `uv sync`/`uv lock`/membuat ulang venv.
- Deploy/restart server hanya setelah izin eksplisit user. Production (`gspe`, `10.8.0.182`) tidak bisa membangun image (`apt` ke CDN Debian terputus): image dibangun di dev lalu dikirim.

## Review Focus

Input atau kondisi yang tidak diurus tugas lain, dengan tes yang memaksanya (di tugas pemilik kode):

1. `cameras=` kosong atau berisi sampah → pesan `live.tv.urlEmpty`, bukan menampilkan semua kamera (Task 3).
2. Duplikat dan ID nonaktif/tak dikenal (`cameras=3,9,2,2`) → tiap tile maksimal sekali, urutan URL terjaga (Task 2 dan 3).
3. Nilai URL mengunci kontrol dan `localStorage` tetap kosong setelah render dan setelah mengklik kontrol terkunci (Task 3).
4. `scroll=ON`/`speed=FAST` (huruf besar) dan nilai asing (`scroll=yes`, `cols=5`) tidak merusak halaman; nilai asing diabaikan (Task 2).
5. Semua jalur yang menerbitkan cookie (login, ganti password, perpanjangan bergulir) ikut `Max-Age`; tidak ada `set_cookie` lain di backend (Task 1).

## File Structure

| Berkas | Perubahan |
|---|---|
| `backend/app/api/deps.py` | `set_auth_cookie` + `max_age` |
| `backend/tests/test_auth_api.py` | tes `Max-Age` |
| `frontend/src/features/live/screenPrefs.ts` | `TvUrlOverrides`, `parseTvUrl`, `selectByIds`, `withOverrides` |
| `frontend/src/features/live/LiveTvPage.tsx` | override URL, kunci kontrol, pesan kosong URL |
| `frontend/src/features/live/CameraPicker.tsx` | properti `disabled` |
| `frontend/src/features/config/CamerasPage.tsx` | kolom `id` paling kiri, `colSpan` 7 → 8 |
| `frontend/src/app/i18n.tsx` | `cameras.col.id`, `live.tv.lockedByUrl`, `live.tv.urlEmpty` (id + en) |
| `frontend/src/__tests__/live-prefs.test.ts`, `live-tv.test.tsx`, `cameras.test.tsx` | tes baru |
| `docs/runbooks/live-view-tv-pi.md`, `README.md`, `WORKFLOW.md`, `ARCHITECTURE.md`, `ROADMAP.md`, `CHANGELOG.md` | dokumentasi |

---

### Task 1: Cookie sesi persisten (backend)

**Files:**
- Modify: `backend/app/api/deps.py:17-19`
- Test: `backend/tests/test_auth_api.py` (tambah di akhir)

**Interfaces:**
- Produces: `set_auth_cookie(response: Response, token: str) -> None` kini menulis `Max-Age=<access_token_expire_min*60>`; dipakai login, ganti password, perpanjangan bergulir (sudah ada).

- [ ] **Step 1: Baseline.** Di cabang bersih catat keluaran `cd backend && env -u NODE_ENV pytest tests -q -m "not gpu and not llm"` dan, dari `frontend/`, `env -u NODE_ENV npx vitest run` serta `env -u NODE_ENV npm run lint` ke `temp/logs/tv-url-filter/baseline-*.txt` (gitignored). Angka ini dipakai Task 6.
- [ ] **Step 2: Tes gagal.** Tambah `test_login_cookie_max_age_equals_token_lifetime(client)` (login admin bootstrap seperti `test_bootstrap_and_login`; assert `f"Max-Age={settings.access_token_expire_min * 60}"` ada di header `set-cookie`) dan `test_renewed_cookie_has_max_age(client)` (alur `test_session_cookie_renewed_past_half_life`; assert `Max-Age=` pada cookie baru). `test_logout_clears_cookie` yang ada tidak diubah.
- [ ] **Step 3:** Jalankan `pytest tests/test_auth_api.py -q`; kedua tes baru GAGAL (tidak ada `Max-Age`).
- [ ] **Step 4: Implementasi.** Di `set_auth_cookie` tambah `max_age=settings.access_token_expire_min * 60`. Verifikasi dengan `grep -rn "set_cookie" backend/app` bahwa helper ini satu-satunya pemanggil `set_cookie`.
- [ ] **Step 5:** `pytest tests/test_auth_api.py tests/test_users_api.py -q` → semua lulus (termasuk `test_default_session_is_48_hours`, perpanjangan, bearer tidak diperpanjang).
- [ ] **Step 6: Commit** `feat(auth): cookie sesi persisten dengan Max-Age sama dengan umur token`.

### Task 2: Parser parameter URL (frontend, fungsi murni)

**Files:**
- Modify: `frontend/src/features/live/screenPrefs.ts`
- Test: `frontend/src/__tests__/live-prefs.test.ts`

**Interfaces:**
- Produces (diekspor dari `screenPrefs.ts`):
  - `type TvUrlOverrides = { cameras?: number[]; cols?: Cols; scroll?: boolean; speed?: ScrollSpeed }`; `cameras === undefined` = parameter tidak ada, `[]` = ada tetapi tanpa ID valid.
  - `parseTvUrl(params: URLSearchParams): TvUrlOverrides`
  - `selectByIds<T extends { id: number }>(cams: T[], ids: number[]): T[]` (urutan `ids`, ID yang tidak ada di `cams` dilewati)
  - `withOverrides(prefs: ScreenPrefs, o: TvUrlOverrides): ScreenPrefs` (menimpa `cols`, `scroll.on`, `scroll.speed` bila ada; `cameras` tidak disentuh; tidak menulis `localStorage`)

- [ ] **Step 1: Tes gagal** (nama dan asersi):
  - `parseTvUrl: cameras berurutan, spasi dipangkas, duplikat dan token sampah dibuang` — `cameras= 3, 1,1,x,0,-2,2.5,2` → `cameras: [3, 1, 2]`.
  - `parseTvUrl: cameras ada tetapi tanpa ID valid → [] (bukan undefined)` — `cameras=` dan `cameras=a,b` → `[]`; tanpa parameter → `undefined`.
  - `parseTvUrl: cols hanya 2/3/4` — `cols=4` → 4; `cols=5`, `cols=abc` → `undefined`.
  - `parseTvUrl: scroll dan speed tidak peka huruf besar-kecil, nilai asing diabaikan` — `scroll=ON` → true, `scroll=Off` → false, `scroll=yes` → `undefined`; `speed=FAST` → `'fast'`, `speed=turbo` → `undefined`.
  - `selectByIds: urutan mengikuti ids, ID tak dikenal dilewati` — cams `[{id:1},{id:2},{id:3}]`, ids `[3,9,1]` → `[{id:3},{id:1}]`.
  - `withOverrides: hanya field yang ada di URL yang menimpa, localStorage tetap kosong` — override `{cols: 2}` pada prefs bawaan → `cols` 2, `scroll` tetap; `localStorage.length` 0.
- [ ] **Step 2:** `npx vitest run src/__tests__/live-prefs.test.ts` → GAGAL (fungsi belum ada).
- [ ] **Step 3: Implementasi** tiga fungsi di `screenPrefs.ts`: ID valid = `/^\d+$/` dan > 0 (dedup dengan `Set` yang menjaga kemunculan pertama); `speed` dan `scroll` dibandingkan setelah `toLowerCase()`; `cols` lewat `isCols(Number(v))`.
- [ ] **Step 4:** vitest file yang sama → lulus. **Step 5: Commit** `feat(live): parser parameter URL mode TV (cameras, cols, scroll, speed)`.

### Task 3: Mode TV memakai override URL

**Files:**
- Modify: `frontend/src/features/live/LiveTvPage.tsx`, `frontend/src/features/live/CameraPicker.tsx`, `frontend/src/app/i18n.tsx`
- Test: `frontend/src/__tests__/live-tv.test.tsx`

**Interfaces:**
- Consumes: `parseTvUrl`, `selectByIds`, `withOverrides` (Task 2).
- Produces: `CameraPicker` menerima `disabled?: boolean` (tombol pembuka nonaktif); elemen `data-testid="live-tv-locked"` (keterangan `live.tv.lockedByUrl`, tampil bila ada field terkunci) dan `data-testid="live-tv-url-empty"` (pesan `live.tv.urlEmpty`). i18n: `live.tv.lockedByUrl` = "Diatur oleh URL" / "Set by URL"; `live.tv.urlEmpty` = "Tidak ada kamera aktif yang cocok dengan URL." / "No active camera matches the URL.".

- [ ] **Step 1: Tes gagal** di `live-tv.test.tsx`. Perluas `stubFetch` agar menerima daftar kamera (tambahkan `cam(3)` dengan `enabled: false`). Urutan DOM tile dibaca dari atribut `data-testid` (`cam-tile-<id>`):
  - `cameras=2,1 menampilkan tile 2 lalu 1` → `['cam-tile-2','cam-tile-1']`, meski `localStorage` layar A berisi `cameras: all`.
  - `ID tak dikenal, nonaktif, dan duplikat dilewati` — `cameras=3,9,2,2` → hanya `cam-tile-2`.
  - `cameras ada tapi tidak ada yang cocok → pesan URL, bukan semua kamera` — `cameras=9` dan `cameras=` → `live-tv-url-empty` ada, tidak ada `cam-tile-*`.
  - `URL mengunci toolbar dan tidak menulis localStorage` — `screen=A&cameras=1&cols=2&scroll=on&speed=fast`: `live-tv-cols-3`, `live-tv-scroll`, `live-tv-speed-slow`, `live-picker-open` nonaktif; `live-tv-locked` ada; grid `--lv-cols: 2`; `localStorage.length` 0 setelah render dan setelah klik chip terkunci; `live-tv-sound` dan `live-tv-exit` tetap aktif.
  - `field di luar URL tetap memakai pengaturan tersimpan` — `localStorage` layar A `cols: 4`, URL hanya `cameras=1` → grid `--lv-cols: 4`, chip kolom aktif, picker nonaktif.
  - `tanpa parameter baru: picker aktif dan tidak ada keterangan terkunci` (pemeriksaan perilaku lama).
- [ ] **Step 2:** `npx vitest run src/__tests__/live-tv.test.tsx` → tes baru GAGAL.
- [ ] **Step 3: Implementasi** di `LiveTvPage`: `overrides = useMemo(() => parseTvUrl(params), [params])`; `eff = withOverrides(prefs, overrides)` dipakai untuk kolom, chip, toggle, dan `useAutoScroll`; `shown = overrides.cameras !== undefined ? selectByIds(active, overrides.cameras) : selectCameras(active, prefs.cameras)`; `locked = { cameras, cols, scroll, speed }` dari `!== undefined`; kontrol terkunci `disabled`; cabang pesan `urlEmpty` didahulukan sebelum `live.picker.empty`. `update()` hanya dipanggil dari event toolbar dan tidak pernah menerima nilai `eff`.
- [ ] **Step 4:** vitest `live-tv`, `live-prefs`, `live-autoscroll`, `liveview` → lulus. **Step 5: Commit** `feat(live): mode TV membaca cameras/cols/scroll/speed dari URL, toolbar terkunci`.

### Task 4: Kolom ID di Konfigurasi Kamera

**Files:**
- Modify: `frontend/src/features/config/CamerasPage.tsx` (`headers` ±baris 240, sel baris ±baris 330, `colSpan` ±baris 377), `frontend/src/app/i18n.tsx` (`cameras.col.id` = "ID" di id dan en)
- Test: `frontend/src/__tests__/cameras.test.tsx`

**Interfaces:** Produces header `{ key: 'id', header: t('cameras.col.id') }` sebagai kolom pertama.

- [ ] **Step 1: Tes gagal.**
  - `tabel kamera: kolom ID paling kiri berisi ID, kamera nonaktif tetap tampil` — dengan `CAMS` yang ada: `getAllByRole('columnheader')[0]` berisi "ID"; sel pertama baris `CAM-01` = "1", baris `CAM-02` (nonaktif) = "2".
  - `baris kosong meliputi semua kolom` — daftar kosong: sel `Belum ada kamera terdaftar` memiliki `colspan` sama dengan jumlah `columnheader`.
- [ ] **Step 2:** `npx vitest run src/__tests__/cameras.test.tsx` → GAGAL. **Step 3: Implementasi:** sel ID berisi angka apa adanya, sempit tanpa pemotongan baris (`white-space: nowrap`); `colSpan` mengikuti jumlah header. **Step 4:** seluruh `cameras.test.tsx` dan `camera-sources.test.tsx` lulus. **Step 5: Commit** `feat(cameras): kolom ID di tabel Konfigurasi Kamera`.

### Task 5: Dokumentasi

**Files:** `docs/runbooks/live-view-tv-pi.md`, `README.md`, `WORKFLOW.md`, `ARCHITECTURE.md`, `ROADMAP.md`.

- [ ] **Step 1: Runbook TV.** Tambah: daftar parameter dan contoh URL per monitor (`scroll=on` ditulis eksplisit di script kiosk); cara mengambil ID dari Konfigurasi Kamera (kolom ID); templat tabel pemetaan (`Pi | Monitor | screen | cameras | URL`); catatan cookie persisten 48 jam bergulir + akun `viewer` khusus; setelah sesi berakhir login ulang mendarat di dashboard sehingga URL TV dibuka lagi (restart script kiosk); koreksi klaim "login sekali per profil".
- [ ] **Step 2:** `README.md` (bagian mode TV dan sesi bergulir), `WORKFLOW.md` (alur Live TV), `ARCHITECTURE.md` (cookie persisten) disesuaikan. `ROADMAP.md`: seksi baru "TV URL filter" dengan item `[ ]` per task dan tautan spec + plan (centang `[x]` hanya dengan bukti, Task 6/7).
- [ ] **Step 3: Verifikasi:** `grep -n "cameras=" docs/runbooks/live-view-tv-pi.md README.md` menemukan contoh URL. **Step 4: Commit** `docs(live): URL filter mode TV, ID kamera, cookie persisten`.

### Task 6: Verifikasi penuh dan CHANGELOG

- [ ] **Step 1:** Berurutan: `cd backend && env -u NODE_ENV pytest tests -q -m "not gpu and not llm"`; lalu `cd frontend && env -u NODE_ENV npx vitest run`, `env -u NODE_ENV npm run build`, `env -u NODE_ENV npm run lint`. Keluaran ke `temp/logs/tv-url-filter/`. Harapan: tidak ada kegagalan; jumlah tes naik sesuai tes baru; lint tidak lebih buruk dari baseline Task 1.
- [ ] **Step 2: Review.** Satu reviewer segar (model paling mampu) membaca seluruh diff cabang terhadap spec; temuan dikelompokkan menurut keparahan, diperbaiki dengan TDD.
- [ ] **Step 3: CHANGELOG.md** — entri 2026-10-14: konteks, berkas, bukti (keluaran suite), dampak, rollback; tanpa nama karyawan atau ID event. **Commit** `docs(changelog): URL filter mode TV, kolom ID, cookie persisten`.

### Task 7: Deploy ke server development dan uji

Server dev `gspe-ai3` (`temp/data/server-info.txt`); gunakan clone Docker `/home/gspe-ai3/project_cv/I-Sentinel-docker` (jalur `I-Sentinel` pada berkas itu adalah klon systemd lama).

- [ ] **Step 1: Izin push.** Minta izin eksplisit user, lalu `git push -u origin feat/tv-url-filter`.
- [ ] **Step 2: Deploy dev.** Dengan izin user: `ssh gspe-ai3`, `cd /home/gspe-ai3/project_cv/I-Sentinel-docker && git fetch && git checkout feat/tv-url-filter && git pull && ./docker/setup.sh`; `docker compose -f docker/compose.yml ps` semua healthy; `curl -s localhost:7701/api/v1/health` → `{"status":"ok"}`.
- [ ] **Step 3: Cookie.** Login admin dev (kredensial `temp/data/login.txt`, jangan ditempel) dan periksa `Set-Cookie` memuat `Max-Age=172800`.
- [ ] **Step 4: Bukti UI** (Playwright, ke `docs/evidence/`, lokal): tabel Konfigurasi Kamera pada 1280 dan 390 px (`document.documentElement.scrollWidth <= window.innerWidth`); `/live/tv?screen=T&cameras=<id2>,<id1>&cols=2&scroll=on` menampilkan urutan yang diminta dan toolbar terkunci.
- [ ] **Step 5: Gerbang.** Lapor hasil; user menguji di dev (browser/Pi dengan URL kiosk). Tanpa konfirmasi "OK", jangan lanjut. Catat hasil uji apa adanya di CHANGELOG/ROADMAP (`[~]` dan "BELUM diuji" bila dilewati).

### Task 8: Deploy ke production (setelah user menyatakan dev OK)

Server `gspe` (`10.8.0.182`, VPN; kredensial `temp/data/server-production.txt`), klon `/home/gspe/Monitoring_System/I-Sentinel`, data `../I-Sentinel-docker-data`. Catatan server: lihat memory `gspe-production-server-facts`.

- [ ] **Step 1: Merge.** Izin user eksplisit, lalu `git switch main && git merge --no-ff feat/tv-url-filter`, push `main`; dev kembali ke `main` (`git checkout main && git pull && ./docker/setup.sh`) sehingga image dev = kode `main`.
- [ ] **Step 2: Kirim image.** Hanya `isentinel-api:local` dan `isentinel-web:local` (vision tidak berubah). Di production beri tag cadangan dulu (`docker tag isentinel-api:local isentinel-api:prev-20261014`, idem web). Di dev `docker save <img> | gzip -5` ke Mac (cek ruang disk), kirim ke production dengan append yang bisa dilanjutkan (`tail -c +N | ssh 'cat >> file'`), verifikasi `sha256`, lalu `gunzip -c | docker load`. Jalur VPN `10.8.0.182` bawaan; jalur LAN `10.8.1.84` hanya bila user mengizinkan untuk transfer ini.
- [ ] **Step 3: Aktifkan.** `git pull` di klon production (selaras dengan `main`); jalankan `run-setup.sh` (melewati `compose build`) terlepas dari sesi (`setsid nohup`), pastikan prosesnya hidup, tunggu `EXIT=0`.
- [ ] **Step 4: Verifikasi.** Semua container `healthy`; `/api/v1/health` 200; `docker network inspect isentinel_default` tetap `172.16.200.0/24` dan `ip route | grep ^192.168` kosong; cookie login memuat `Max-Age=172800` (kata sandi admin dari user lewat stdin, tidak disimpan); kolom ID tampil di Konfigurasi Kamera; URL TV contoh menampilkan urutan yang benar.
- [ ] **Step 5: Kiosk.** User mengisi pemetaan monitor → ID dari tabel Konfigurasi Kamera, menulis URL ke script kiosk tiap Pi; login sekali dengan akun `viewer` khusus.
- [ ] **Step 6: Rollback bila gagal.** `docker tag isentinel-<img>:prev-20261014 isentinel-<img>:local` lalu `run-setup.sh`; revert merge di `main`.
- [ ] **Step 7:** Perbarui `ROADMAP.md` (`[x]` dengan bukti), `CHANGELOG.md` (hasil deploy dan uji), dan memory server production.

---

### Task 9 (amandemen spec §10): URL sebagai sumber kebenaran per jendela

Dikerjakan setelah Task 1–6 dan sebelum Task 7 diulang (deploy ulang ke dev) dan Task 8. Menggantikan perilaku kunci toolbar pada Task 3.

**Files:**
- Modify: `frontend/src/features/live/screenPrefs.ts`, `frontend/src/features/live/LiveTvPage.tsx`, `frontend/src/features/live/CameraPicker.tsx` (hapus `disabled`), `frontend/src/app/i18n.tsx` (hapus `live.tv.lockedByUrl` id+en), `frontend/src/app/theme.scss` (hapus `.lv-tv__locked`)
- Test: `frontend/src/__tests__/live-prefs.test.ts`, `frontend/src/__tests__/live-tv.test.tsx`
- Docs: runbook TV, README, WORKFLOW, ARCHITECTURE (bila menyebut kunci), CHANGELOG, ROADMAP

**Interfaces:**
- Produces (`screenPrefs.ts`): `type TvState = { cameras: number[]; cols: Cols; scroll: boolean; speed: ScrollSpeed }`;
  `orderCameraIds(current: number[], sel: CameraSel, active: { id: number }[]): number[]` (ID yang masih terpilih menjaga urutan `current`, yang baru di akhir menurut urutan `active`; `all` = semua `active`);
  `tvSearch(base: URLSearchParams, s: TvState): string` (query string tanpa `?`: parameter lain dari `base`, termasuk `screen`, dipertahankan berurutan, lalu `cameras` (koma ditulis apa adanya, bukan `%2C`), `cols`, `scroll`=`on|off`, `speed`; `base` tidak dimutasi; diberikan ke `setSearchParams(string, { replace: true })`).

- [ ] **Step 1: Tes gagal.** `live-prefs.test.ts`: `orderCameraIds` — current `[3,1]` + sel `some [1,3,2]` → `[3,1,2]`; sel `all` + active `[{id:1},{id:2},{id:3}]` → `[1,2,3]`; sel `some []` → `[]`. `tvSearch` — `screen=A` dipertahankan, `cameras=3,1`, `scroll=on`/`off`, `speed`, `cols`; `base` tidak dimutasi. `live-tv.test.tsx`: tambahkan komponen probe lokasi (`useLocation().search` dan `useNavigationType()` ke `data-testid`), hapus tes kunci toolbar yang lama, lalu: `toolbar tetap aktif saat URL berparameter`; `klik kolom menulis ulang URL dengan REPLACE, screen dipertahankan, localStorage layar ikut`; `scroll dan speed menulis scroll=on/off dan speed=…`; `pemilih: ID lama menjaga urutan, ID baru di akhir` (`?cameras=2` lalu centang kamera 1 → `cameras=2,1`); `membuka URL tidak mengubah URL dan localStorage kosong`; `tanpa parameter + satu edit menghasilkan URL lengkap` (`cameras` eksplisit, `cols`, `scroll`, `speed`).
- [ ] **Step 2:** `npx vitest run src/__tests__/live-prefs.test.ts src/__tests__/live-tv.test.tsx` → tes baru GAGAL karena alasan yang benar (fungsi belum ada; kontrol masih `disabled`; URL tidak berubah).
- [ ] **Step 3: Implementasi.** `screenPrefs.ts`: dua fungsi di atas. `LiveTvPage`: dapatkan `[params, setParams] = useSearchParams()`; satu fungsi `commit(patch)` memanggil `update(patch)` untuk `localStorage` lalu `setParams(tvSearch(params, state), { replace: true })` dengan `state` = nilai efektif + patch (ID kamera = `orderCameraIds(daftar ID tampil saat ini, pilihan baru, active)`); semua handler toolbar memakai `commit`; hapus `locked`, `anyLocked`, atribut `disabled` dari URL, keterangan terkunci, dan properti `disabled` di `CameraPicker`; tidak ada penulisan saat mount. Pesan `urlEmpty` tetap.
- [ ] **Step 4:** vitest `live-tv`, `live-prefs`, `liveview`, `live-autoscroll` lulus; lalu suite penuh berurutan (`--maxWorkers=2` bila mesin ber-load), build, lint (24 warning identik). **Step 5: Commit** `feat(live): toolbar mode TV menulis ulang URL (URL sebagai sumber kebenaran per jendela)`.
- [ ] **Step 6: Dokumentasi.** Runbook: cara membuat URL (buka `/live/tv`, atur kamera/kolom/scroll di toolbar, salin URL dari address bar ke script kiosk), hapus pernyataan "terkunci"; README/WORKFLOW/ARCHITECTURE/CHANGELOG/ROADMAP disesuaikan. **Commit** `docs(live): URL kiosk dibuat dari address bar mode TV`.

### Task 10 (spec §11): layout 1 kolom

**Files:** `screenPrefs.ts` (`Cols`, `COL_OPTIONS`, `isCols`), `LiveWall.tsx` (kelas `lv-grid--one`), `theme.scss`, `i18n.tsx` (`live.col1` id+en), `LiveViewPage.tsx` dan `LiveTvPage.tsx` (label chip), tes `live-prefs`, `live-tv`, `liveview`; dokumentasi (runbook, README, WORKFLOW), CHANGELOG, ROADMAP.

- [ ] Tes gagal: `cols=1` diterima parser (0, 5, -1, 1.5, abc, kosong ditolak); `COL_OPTIONS` = `[3, 2, 4, 1]`; `loadPrefs` menerima 1; chip `live-tv-cols-1` dan `live-cols-1` berlabel "1 kolom", menulis `cols=1` ke URL/`localStorage`, grid `--lv-cols: 1` dengan kelas `lv-grid--one` (kolom lain tanpa kelas itu).
- [ ] Implementasi dan pemeriksaan browser: 1 kolom tetap satu kolom pada 1280 px dan 900 px; 3 kolom pada 900 px tetap turun ke 2; tanpa overflow horizontal.
- [ ] Commit `feat(live): layout 1 kolom untuk Live dan mode TV`; dokumen dan CHANGELOG.
