# DEVELOPMENT — I-Sentinel

Cara kerja pengembangan dari ide sampai fitur ter-merge di `main`. Aturan agent lengkap ada di
`AGENTS.md`; arsitektur di `ARCHITECTURE.md`; alur per fitur di `WORKFLOW.md`; status fase di `ROADMAP.md`.

## 1. Siklus fitur

```
Brainstorm ─► Spec ─► Plan ─► Eksekusi ─► Review ─► Deploy ─► Uji user ─► Docs verifikasi ─► Merge
 (chat)      (docs/   (docs/   (branch    (log     (izin     (lapangan)  (CHANGELOG,        (--no-ff
             super-   super-   feat/*)    eksekutor) user)               ROADMAP)          ke main)
             powers/  powers/
             specs)   plans)
```

1. **Brainstorm** — diskusi di chat: tujuan, keputusan user, opsi + rekomendasi. Klasifikasi:
   - **Bounded** (perubahan kecil pada alur yang sudah ada): desain singkat di chat → persetujuan
     user → langsung dikerjakan, tanpa file spec/plan.
   - **Arsitektural** (subsistem baru, kontrak berubah): lanjut ke spec + plan.
2. **Spec** — `docs/superpowers/specs/YYYY-MM-DD-<topik>-design.md`: kondisi kode, keputusan user,
   desain, penanganan error, pengujian, verifikasi lapangan, di luar scope, rollback. User me-review.
3. **Plan** — `docs/superpowers/plans/YYYY-MM-DD-<topik>.md`: task kecil TDD (tes gagal → implementasi →
   tes lulus → commit) dengan path file, antarmuka, dan perintah verifikasi. User me-review.
   Spec dan plan adalah **catatan permanen**; tidak diduplikasi dan tidak diperbarui setelah selesai.
4. **Eksekusi** — di branch `feat/<slug>` dari `main`, salah satu cara:
   - **Native handoff**: prompt eksekutor di `temp/prompt-<topik>-exec.txt` untuk sesi baru;
     eksekutor mengerjakan plan, menjalankan review independen, menulis ringkasan ke
     `temp/log.txt`, lalu **berhenti setelah `git push`**.
   - **Subagent**: sesi perencana membagi task ke subagent + reviewer per task.
5. **Review** — sesi perencana membaca `temp/log.txt`, memeriksa diff dan hasil tes, memperbaiki
   temuan sebelum deploy.
6. **Deploy** — hanya dengan izin eksplisit user (§4).
7. **Uji user** — user menguji di lapangan; feedback diperbaiki di branch yang sama lalu deploy ulang.
8. **Docs verifikasi** — catat hasil deploy + uji user di `CHANGELOG.md`, tandai baris `ROADMAP.md`.
9. **Merge** — setelah user menyatakan "sudah sesuai": `git merge --no-ff` ke `main`, push, dan
   checkout server kembali ke `main`.

Checkpoint sesi (untuk melanjutkan setelah konteks habis): `.cooper/context/` (gitignored).

## 2. Branch & commit

- Branch: `feat/<slug>`, `fix/<slug>`, `chore/<slug>`, `docs/<slug>` dari `main`.
- Satu commit per perubahan fungsional, format Conventional Commits berbahasa Indonesia
  (`feat(attendance): …`, `fix(monitoring): …`, `docs: …`).
- **Tanpa atribusi AI** di commit, PR, kode, maupun dokumen (tidak ada `Co-Authored-By` AI).
- Setiap perubahan dicatat di `CHANGELOG.md`: konteks, file, bukti, dampak, rollback.
- File baru yang tidak boleh masuk git (rahasia, hasil generate, scratch) → `.gitignore`.

## 3. Verifikasi sebelum push

```bash
cd backend  && pytest tests -q -m "not gpu"      # server: pytest tests -q
cd vision   && pytest tests -q -m "not gpu"
cd frontend && npx vitest run && npm run lint && npm run build
```

- Tes harus gagal pada bug yang masuk akal, bukan mengunci detail implementasi.
- UI diperiksa di app yang berjalan (desktop 1440 px dan mobile 390 px tanpa overflow horizontal).
  Screenshot disimpan di `docs/evidence/` — **lokal saja, gitignored**.
- Migrasi dicek idempoten (upgrade → downgrade → upgrade).
- `[x]` di ROADMAP hanya dengan angka/keluaran nyata.

### Verifikasi deployment Docker

**Belum aktif di `gspe-ai3` sampai cutover.** Siklus Docker memakai handoff
khusus `temp/prompt/docker-deploy.md`: executor hanya Task 1–7 + smoke lokal,
tanpa review/push/merge/server. Summary dibawa ke sesi perencanaan untuk review
dan Part B. Ini pengecualian dari alur native generik §1.

Artefak ada di `docker/`; kode aplikasi backend/frontend/vision tidak diubah,
selain extra CPU `face` di backend/pyproject.toml. Dev lokal venv/Vite tetap
seperti sebelumnya. Tes shell berjalan dengan Bash 3.2 maupun Bash 5:

```bash
backend/.venv/bin/python -m pytest docker/tests -q
docker compose -f docker/compose.yml --env-file docker/.env.example config -q
docker compose -f docker/compose.yml --env-file docker/.env.example --profile vision config -q
```

Ukur baseline dan suite akhir **berurutan** (docker, backend, frontend, build,
lint); gunakan `env -u NODE_ENV` untuk backend/frontend/build/lint. Tidak perlu
`uv sync`, `uv lock`, atau venv baru. Docker Compose config tidak membutuhkan
daemon; build/run hanya bila `docker info` berhasil. Jangan menyalakan Docker
Desktop otomatis; image vision hanya dibangun di server amd64/GPU.

`./docker/setup.sh --env-only` bisa diuji tanpa Docker memakai ENV_FILE dan
DATA_DIR sementara. Tes migrasi hanya `--dry-run` dengan env/data palsu,
bukan `.env` server. `.env.example` berisi placeholder; `.env`, YAML go2rtc
runtime (kredensial kamera), dan secrets tetap di luar git. Skrip menggunakan
Python 3 stdlib di host untuk parsing/rendering/edit dotenv lintas platform.

Verifikasi server (Part B) meliputi instalasi bersih, idempotensi, tag image,
healthcheck, live LAN, auth MQTT, enrollment CPU, dump/restore, heartbeat/event
vision, engine 4090/5080, shm, reboot, serta cutover/rollback. ROADMAP DK tetap
`[~]` sampai bukti server tersedia; petunjuk operasi ada di bagian Docker RUNBOOK.


## 4. Deploy ke `gspe-ai3`

Akses baca ke server bebas; **tulis, deploy, restart, dan push butuh izin eksplisit user.**

> **Catatan port:** peta port baru blok `7700–7705` (lihat README/ARCHITECTURE/RUNBOOK) baru
> berlaku setelah cutover Docker (`docs/superpowers/specs/2026-10-01-docker-deploy-design.md`).
> Sampai saat itu server masih memakai port lama; semua perintah di bagian ini tidak berubah.

```bash
ssh gspe-ai3
cd /home/gspe-ai3/project_cv/I-Sentinel
git fetch && git checkout feat/<slug> && git pull

# migrasi (bila ada) — env dimuat tanpa dicetak
cd backend && set -a && . ../.env && set +a && /home/gspe-ai3/isentinel-venv/bin/alembic upgrade head && cd ..

# restart tanpa sudo: kill proses cgroup, unit Restart=always
kill $(cat /sys/fs/cgroup/system.slice/vision-node.service/cgroup.procs)     # bila vision berubah
kill $(cat /sys/fs/cgroup/system.slice/isentinel-api.service/cgroup.procs)   # bila backend berubah
curl -s localhost:8000/api/v1/health                                          # {"status":"ok"}
journalctl -u isentinel-api -n 50 --no-pager
```

- Frontend: Vite dev server (`isentinel-web`) memuat perubahan lewat HMR setelah `git pull`.
- Bila vision dan API sama-sama berubah, restart **vision dulu**, lalu API.
- Dependensi Python dipasang dengan `pip install -e` di venv yang tepat (`isentinel-venv` untuk API,
  `vision-venv` untuk vision); jangan `uv sync` / `uv lock`.
- Verifikasi hasil di server lewat query/endpoint read-only; jangan mencetak isi `.env` atau rahasia.
- Setelah merge: `git checkout main && git pull` di server (tanpa restart bila kodenya identik).

## 5. Rollback

- Kode: `git revert` commit/merge terkait, lalu restart unit yang terdampak.
- Migrasi: `alembic downgrade <revisi>` sesuai bagian rollback di spec/runbook; backup DB dulu bila
  migrasi menghapus data.
- Data turunan yang dibuat job (mis. baris absensi otomatis) dijelaskan di bagian rollback spec.

## 6. Dokumen yang ikut diperbarui

| Perubahan | Dokumen |
|---|---|
| Fitur/alur aplikasi | `README.md`, `WORKFLOW.md`, runbook terkait di `docs/runbooks/` |
| Komponen, kontrak, thread, tabel | `ARCHITECTURE.md` |
| Cara kerja tim | `docs/DEVELOPMENT.md`, `AGENTS.md` |
| Setiap commit fungsional | `CHANGELOG.md` |
| Fase/fitur selesai | `ROADMAP.md` |
| Operasional server | `docs/RUNBOOK.md` |

## 7. Aturan keamanan

- Jangan commit/cetak password, token, atau isi `.env`; kredensial hanya di `.env` server dan
  `CAMERA_SECRETS_FILE`. Token Telegram diisi user lewat UI, tidak pernah lewat chat.
- `temp/` gitignored: scratch, prompt handoff, `temp/log.txt`, dan `temp/data/` (catatan server
  lokal — tidak disalin ke dokumen).
- Paparan LAN diterima; tidak ada komponen yang dibuka ke publik.
