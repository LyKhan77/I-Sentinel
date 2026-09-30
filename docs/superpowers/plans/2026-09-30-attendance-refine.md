# Attendance Refinement — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tabel Attendance menampilkan tanggal dan status yang benar (Di dalam / Tanpa exit / Tanpa entry / Tidak hadir), hari ditutup otomatis setelah jam shift + toleransi, dan baris yang perlu koreksi mudah ditindaklanjuti.

**Architecture:** Backend: `compute_status` mengenali `no_entry`; `effective_status` mengoreksi `waiting` yang lewat batas saat dibaca; `close_due` + thread `AttendanceCloser` (15 menit, catch-up 7 hari saat start) membuat `absent` dan menutup `waiting` tanpa menyentuh baris yang dikoreksi. Frontend: kolom Tanggal, jam `HH:MM`, durasi live, label/warna status baru, tombol Koreksi, penanda dikoreksi, tile & chip filter status.

**Tech Stack:** FastAPI, SQLAlchemy 2, pytest; React 19 + TypeScript + Carbon + Vitest.

**Spec:** `docs/superpowers/specs/2026-09-30-attendance-refine-design.md`

## Global Constraints

- Tanpa migrasi, tanpa dependensi baru. `status` baru: `no_entry` (string di kolom yang ada).
- `batas(d) = d + shift.end_time + settings.no_exit_grace_min` (tz lokal server, `LOCAL_TZ`).
- Baris dengan `override_note` (non-kosong) **tidak pernah** diubah oleh `effective_status`, `close_due`, `close_days`.
- Karyawan tanpa shift: tidak pernah `absent` / `no_exit` otomatis.
- `AttendanceCloser`: interval 900 s, run pertama saat start; conftest menonaktifkan (interval panjang, tanpa run awal).
- List API urut `date DESC`, lalu nama karyawan.
- Frontend: string lewat `i18n.tsx` (id + en), REST lewat `src/api/*`, 390 px tanpa overflow halaman.
- Commit Conventional Commits **tanpa** atribusi AI (AGENTS.md §9); prefix `rtk`; jangan `uv sync`/`uv lock`.
- Baseline `main` `c22eac5`: backend 606, vision 233 (3 deselected), frontend 237, build 0.

## Review Focus

1. **Job membuat `absent` untuk hari ini sebelum shift selesai** (karyawan belum datang ≠ tidak hadir) — tes Task 2.
2. **Koreksi manual tertimpa** oleh job / status efektif / `close_days` — tes Task 1 & 2.
3. **Catch-up saat start** tidak menduplikasi baris dan idempoten bila dijalankan dua kali — tes Task 2.
4. **Durasi "berjalan" untuk hari lampau** (tanpa shift / waiting lama) tidak boleh terus bertambah — tes Task 3.
5. **Thread closer menyentuh DB nyata di tes** — fixture conftest (Task 2).

---

### Task 1: Status `no_entry`, status efektif, urutan list, CSV

**Files:**
- Modify: `backend/app/services/attendance.py` (`compute_status`, tambah `deadline`, `effective_status`)
- Modify: `backend/app/api/attendance.py` (`VALID_STATUSES`, `_row_dict`, `_query_days` order, export CSV)
- Test: `backend/tests/test_attendance_logic.py`, `backend/tests/test_attendance_api.py`

**Interfaces:**
- Produces: `attendance.deadline(shift, day) -> datetime` (batas lokal); `attendance.effective_status(row: AttendanceDay,
  shift, now: datetime | None = None) -> str`.

- [ ] **Step 1: Tes (gagal)** — tambahkan di `test_attendance_logic.py` (pakai helper `_at`, `_shift`, `_emp`, `_camera`,
  `_att_event`, konstanta `MON` yang ada):

```python
def test_exit_without_entry_is_no_entry(db):
    sh = _shift(db)
    e = _emp(db, sh)
    _camera(db)
    _att_event(db, e.id, "exit", _at(*MON, 16, 5))
    row = attendance.recompute_day(db, e.id, _at(*MON, 16, 5).date(), now=_at(*MON, 18, 0))
    assert row.status == "no_entry" and row.duration_min is None and row.late_minutes is None


def test_effective_status_waiting_past_deadline_is_no_exit(db):
    sh = _shift(db)  # 07:00-16:00, grace default 60 → batas 17:00
    e = _emp(db, sh)
    _camera(db)
    _att_event(db, e.id, "entry", _at(*MON, 7, 5))
    row = attendance.recompute_day(db, e.id, _at(*MON, 7, 5).date(), now=_at(*MON, 9, 0))
    assert row.status == "waiting"
    assert attendance.effective_status(row, sh, now=_at(*MON, 16, 59)) == "waiting"
    assert attendance.effective_status(row, sh, now=_at(*MON, 17, 0)) == "no_exit"
    row.override_note = "dikoreksi HR"
    assert attendance.effective_status(row, sh, now=_at(*MON, 18, 0)) == "waiting"  # koreksi manual tidak diubah
    assert attendance.effective_status(row, None, now=_at(*MON, 23, 0)) == "waiting"  # tanpa shift
```

Di `test_attendance_api.py` (pakai fixture/klien yang ada di file itu):
- list `?from=&to=` mengembalikan baris urut `date` turun lalu nama;
- baris `waiting` kemarin (shift berakhir) tampil `status: "no_exit"` di list dan di CSV;
- PATCH `status: "no_entry"` + catatan → 200; status tak dikenal tetap 422;
- import CSV dengan `first_entry` kosong + `last_exit` terisi → status `no_entry`.

Run: `rtk bash -c "cd backend && .venv/bin/python -m pytest tests/test_attendance_logic.py tests/test_attendance_api.py -q"` → FAIL.

- [ ] **Step 2: Implementasi**

`attendance.py`:

```python
def deadline(shift, day) -> datetime:
    """Batas penutupan hari: jam shift selesai + toleransi no_exit (tz lokal)."""
    return _shift_dt(shift, day, shift.end_time) + timedelta(minutes=settings.no_exit_grace_min)
```

`compute_status`: tepat setelah `now = ...`, sebelum cabang `first_entry is None`:

```python
    if first_entry is None:
        # hanya exit terdeteksi: orangnya hadir tapi entry terlewat → perlu koreksi, bukan absent
        return ("no_entry" if last_exit is not None else "absent"), None, None
```

dan ganti perhitungan `end_grace` memakai `deadline(shift, first_entry.date())`.

```python
def effective_status(row, shift, now: datetime | None = None) -> str:
    """Status untuk ditampilkan: `waiting` yang sudah lewat batas → `no_exit` walau job belum jalan.
    Baris yang dikoreksi manual (override_note) dan karyawan tanpa shift tidak diubah."""
    if row.status != "waiting" or (row.override_note or "").strip() or shift is None:
        return row.status
    now = _local(now) or datetime.now(LOCAL_TZ)
    return "no_exit" if now >= deadline(shift, row.date) else "waiting"
```

`api/attendance.py`:
- `VALID_STATUSES` tambah `"no_entry"`.
- `_row_dict(day, emp, now=None)`: `"status": attendance.effective_status(day, emp.shift if emp else None, now)`.
- `_query_days`: `order_by(AttendanceDay.date.desc(), Employee.name, Employee.employee_code)`.
- export CSV: kolom status memakai `attendance.effective_status(day, emp.shift, None)`; urutan export boleh tetap
  menaik (ubah `_query_days` menerima parameter `desc: bool = True` dan export memanggil `desc=False` agar CSV tetap
  kronologis — catat pilihan ini).

Run tes Step 1 → PASS; suite backend → PASS (sesuaikan tes lama yang mengecek urutan list bila ada, catat).

- [ ] **Step 3: Commit**

```bash
rtk git add backend/
rtk git commit -m "feat(attendance): status tanpa entry, status efektif saat dibaca, urutan tanggal terbaru"
```

---

### Task 2: Penutupan hari otomatis (`close_due` + `AttendanceCloser`)

**Files:**
- Modify: `backend/app/services/attendance.py` (`close_due`, `close_days` lewati override, `AttendanceCloser`, `closer`)
- Modify: `backend/app/main.py` (lifespan start/stop), `backend/tests/conftest.py` (nonaktifkan)
- Test: `backend/tests/test_attendance_logic.py`

**Interfaces:**
- Produces: `CLOSE_INTERVAL_S = 900`, `CLOSE_DAYS_BACK = 7`; `close_due(db, now=None, days_back=CLOSE_DAYS_BACK) -> dict`
  (`{"created": n, "updated": n}`); `AttendanceCloser(interval_s=CLOSE_INTERVAL_S, session_factory=SessionLocal,
  run_on_start=True)` dengan `run_once(now=None)`, `start()`, `stop()`; instance `closer`.

- [ ] **Step 1: Tes (gagal)**

```python
from datetime import timedelta


def test_close_due_absent_only_after_deadline_and_workdays(db):
    sh = _shift(db)            # Senin-Jumat 07:00-16:00, batas 17:00
    e = _emp(db, sh, code="E1")
    _emp(db, None, code="E2")  # tanpa shift → tidak pernah absent
    off = _emp(db, sh, code="E3")
    off.active = False
    db.commit()
    day = _at(*MON, 9, 0).date()
    assert attendance.close_due(db, now=_at(*MON, 16, 59), days_back=0) == {"created": 0, "updated": 0}
    assert db.query(AttendanceDay).count() == 0  # hari ini sebelum batas: belum "tidak hadir"
    r = attendance.close_due(db, now=_at(*MON, 17, 0), days_back=0)
    assert r == {"created": 1, "updated": 0}
    row = db.query(AttendanceDay).one()
    assert row.employee_id == e.id and row.date == day and row.status == "absent"


def test_close_due_turns_waiting_into_no_exit_and_skips_override(db):
    sh = _shift(db)
    a = _emp(db, sh, code="A")
    b = _emp(db, sh, code="B")
    _camera(db)
    for emp in (a, b):
        _att_event(db, emp.id, "entry", _at(*MON, 7, 5))
        attendance.recompute_day(db, emp.id, _at(*MON, 7, 5).date(), now=_at(*MON, 8, 0))
    rb = db.query(AttendanceDay).filter_by(employee_id=b.id).one()
    rb.override_note = "koreksi HR"
    db.commit()
    r = attendance.close_due(db, now=_at(*MON, 18, 0), days_back=0)
    assert r["updated"] == 1
    assert db.query(AttendanceDay).filter_by(employee_id=a.id).one().status == "no_exit"
    assert db.query(AttendanceDay).filter_by(employee_id=b.id).one().status == "waiting"  # tidak disentuh


def test_close_due_catch_up_and_idempotent(db):
    sh = _shift(db)
    _emp(db, sh)
    now = _at(*MON, 10, 0) + timedelta(days=8)  # Selasa minggu berikutnya 10:00, hari ini belum lewat batas
    first = attendance.close_due(db, now=now)            # 7 hari ke belakang
    again = attendance.close_due(db, now=now)
    workdays = sum(1 for i in range(1, 8) if (now - timedelta(days=i)).isoweekday() <= 5)
    assert first["created"] == workdays and again == {"created": 0, "updated": 0}
    assert db.query(AttendanceDay).count() == workdays


def test_close_days_skips_override(db):
    sh = _shift(db)
    e = _emp(db, sh)
    day = _at(*MON, 9, 0).date()
    db.add(AttendanceDay(employee_id=e.id, date=day, status="ontime", override_note="manual"))
    db.commit()
    attendance.close_days(db, day, now=_at(*MON, 23, 0))
    assert db.query(AttendanceDay).one().status == "ontime"


def test_closer_runs_on_start_survives_error_and_stops(monkeypatch):
    calls = []

    def boom():
        calls.append(1)
        raise RuntimeError("db down")

    c = attendance.AttendanceCloser(interval_s=0.01, session_factory=boom, run_on_start=True)
    c.start()
    import time
    deadline = time.monotonic() + 2
    while len(calls) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    c.stop()
    assert len(calls) >= 2 and not c._thread.is_alive()
```

(Sesuaikan konstanta `MON` / pemanggilan `_at` dengan helper yang ada; `MON` di file ini adalah tanggal Senin.)

Run → FAIL (`close_due` tidak ada).

- [ ] **Step 2: Implementasi**

```python
import threading

from app.core.db import SessionLocal

CLOSE_INTERVAL_S = 900
CLOSE_DAYS_BACK = 7


def _has_override(row) -> bool:
    return bool((row.override_note or "").strip())


def close_due(db, now: datetime | None = None, days_back: int = CLOSE_DAYS_BACK) -> dict:
    """Tutup hari yang sudah lewat batas untuk karyawan aktif ber-shift di hari kerjanya:
    buat baris (absent / dari event) bila belum ada; hitung ulang `waiting`. Baris dikoreksi dilewati."""
    now = _local(now) or datetime.now(LOCAL_TZ)
    created = updated = 0
    emps = [e for e in db.query(Employee).filter(Employee.active.is_(True)).all() if e.shift is not None]
    for back in range(days_back, -1, -1):
        day = (now - timedelta(days=back)).date()
        for emp in emps:
            if day.isoweekday() not in (emp.shift.workdays or []) or now < deadline(emp.shift, day):
                continue
            row = db.query(AttendanceDay).filter_by(employee_id=emp.id, date=day).first()
            if row is None:
                recompute_day(db, emp.id, day, now=now)
                created += 1
            elif row.status == "waiting" and not _has_override(row):
                recompute_day(db, emp.id, day, now=now)
                updated += 1
    return {"created": created, "updated": updated}
```

`close_days(db, day, now=None)`: sebelum `recompute_day`, lewati bila baris hari itu ada dan `_has_override(row)`.

```python
class AttendanceCloser:
    """Thread latar: close_due tiap interval_s; run pertama saat start (catch-up setelah API restart)."""

    def __init__(self, interval_s: float = CLOSE_INTERVAL_S, session_factory=SessionLocal, run_on_start: bool = True):
        self.interval_s = interval_s
        self.run_on_start = run_on_start
        self._session_factory = session_factory
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def run_once(self, now: datetime | None = None) -> dict:
        db = self._session_factory()
        try:
            return close_due(db, now=now)
        finally:
            db.close()

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="attendance-closer")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def _loop(self) -> None:
        first = self.run_on_start
        while first or not self._stop.wait(self.interval_s):
            first = False
            if self._stop.is_set():
                break
            try:
                self.run_once()
            except Exception:
                logger.warning("attendance close failed", exc_info=True)


closer = AttendanceCloser()
```

Catatan: `SessionLocal` diimpor di level modul `attendance.py` — pastikan tidak menimbulkan import melingkar
(pola sama dengan `node_health.py`; bila bermasalah, impor lokal di `__init__` default). `recompute_day` sudah
`commit` per baris.

`main.py` lifespan: setelah `history_sampler.start()`:
`from app.services.attendance import closer as attendance_closer` + `attendance_closer.start()`; di `finally`
`attendance_closer.stop()` pertama.

`conftest.py` fixture autouse (seperti `_quiet_node_monitor`):

```python
@pytest.fixture(autouse=True)
def _quiet_attendance_closer(monkeypatch):
    """Penutup hari latar tidak boleh menyentuh DB nyata selama tes."""
    from app.services import attendance
    monkeypatch.setattr(attendance.closer, "interval_s", 3600)
    monkeypatch.setattr(attendance.closer, "run_on_start", False)
```

Run: suite backend → PASS; durasi tidak naik berarti.

- [ ] **Step 3: Commit**

```bash
rtk git add backend/
rtk git commit -m "feat(attendance): penutupan hari otomatis (tidak hadir, tanpa exit) tanpa menimpa koreksi manual"
```

---

### Task 3: Tabel — tanggal, jam, durasi, status baru

**Files:**
- Modify: `frontend/src/features/attendance/AttendancePage.tsx`, `frontend/src/api/attendance.ts`,
  `frontend/src/app/i18n.tsx`
- Test: `frontend/src/__tests__/attendance.test.tsx`

**Interfaces:**
- Produces: `AttendanceStatus` + `'no_entry'`; helper di file halaman: `fmtDay(iso, locale)`, `hhmm(raw)`,
  `durationText(row, now, t)`; test id `at-col-date`, `at-date-<id>`, `status-<status>`.

- [ ] **Step 1: Tes (gagal)** — di `attendance.test.tsx` (pakai stub fetch & data baris yang ada; tambah baris
  `no_entry`, `no_exit`, `waiting` hari ini, `waiting` kemarin tanpa shift):
  - tab Harian: tidak ada kolom Tanggal (`queryByTestId('at-col-date')` null);
  - tab Rentang: kolom Tanggal tampil, sel baris 2026-09-29 berisi teks hari+tanggal lokal (`Sen` / `29` / `Sep`);
  - Entry/Exit tampil `07:58` (tanpa detik) dan judul kolom memuat `WIB`;
  - durasi: `duration_min: 492` → `8j 12m`; `waiting` hari ini dengan `first_entry` 2 jam lalu → teks memuat
    `berjalan` dan bertambah setelah `vi.advanceTimersByTime(60_000)`; `waiting` kemarin → `—`; `no_exit` → `—`;
  - label status: `no_exit` → "Tanpa exit — perlu koreksi", `no_entry` → "Tanpa entry — perlu koreksi",
    `waiting` → "Di dalam";
  - modal override: opsi status memuat `no_entry`.

- [ ] **Step 2: Implementasi**
  - `api/attendance.ts`: `AttendanceStatus = 'ontime' | 'late' | 'waiting' | 'no_exit' | 'no_entry' | 'absent'`.
  - `STATUSES` + `STATUS_COLOR`: `waiting: '#4589ff'`, `no_exit` & `no_entry`: `'#ff832b'`.
  - Helper:

```tsx
function fmtDay(iso: string, locale: string) {
  const d = new Date(`${iso}T00:00:00`)
  const opts: Intl.DateTimeFormatOptions = { weekday: 'short', day: 'numeric', month: 'short' }
  if (d.getFullYear() !== new Date().getFullYear()) opts.year = 'numeric'
  return d.toLocaleDateString(locale, opts)
}
const hhmm = (raw: string | null) => (raw ? raw.slice(0, 5) : '—')
```

  - Durasi: state `now` diperbarui `setInterval(60_000)`; `waiting` + `r.date === todayIso()` + `first_entry` →
    menit = `now − (tanggal+first_entry)`, teks `t('at.duration.running').replace('{h}',…).replace('{m}',…)`
    ("{h}j {m}m · berjalan"); `waiting` lain / `no_exit` / `no_entry` / `absent` → `—`.
  - Kolom: `headers` = (`at.col.date` bila tab ≠ daily) + employee, shift, entry, exit, duration, status. Sel tanggal
    `data-testid={`at-date-${r.id}`}`; `<TableHeader data-testid="at-col-date">`.
  - i18n baru/ubah (id / en): `at.col.date` Tanggal/Date, `at.col.entry` "ENTRY (WIB)", `at.col.exit` "EXIT (WIB)",
    `at.status.waiting` "DI DALAM"/"INSIDE", `at.status.no_exit` "TANPA EXIT — PERLU KOREKSI"/"NO EXIT — NEEDS
    CORRECTION", `at.status.no_entry` "TANPA ENTRY — PERLU KOREKSI"/"NO ENTRY — NEEDS CORRECTION",
    `at.duration.running` "{h}j {m}m · berjalan"/"{h}h {m}m · ongoing" (ganti nilai lama "berjalan…").

- [ ] **Step 3: Commit**

```bash
rtk git add frontend/src
rtk git commit -m "feat(attendance): kolom tanggal, jam HH:MM, durasi berjalan, label status baru"
```

---

### Task 4: Tindak lanjut — tombol Koreksi, penanda dikoreksi, filter status

**Files:**
- Modify: `frontend/src/features/attendance/AttendancePage.tsx`, `frontend/src/app/i18n.tsx`
- Test: `frontend/src/__tests__/attendance.test.tsx`

**Interfaces:**
- Produces: test id `fix-<id>` (tombol Koreksi), `corrected-<id>` (ikon), `tile-fix` (tile Perlu koreksi),
  `status-filter-<key>` (chip); state `statusFilter: 'all' | 'present' | 'inside' | 'fix' | 'absent'`.

- [ ] **Step 1: Tes (gagal)**
  - admin: baris `no_exit` / `no_entry` punya tombol `fix-<id>` yang membuka modal override; baris `ontime` tidak;
    viewer tidak punya tombol;
  - baris dengan `override_note` menampilkan `corrected-<id>` dengan `title` berisi catatan;
  - tab Harian: tile `tile-fix` = jumlah `no_exit` + `no_entry`; klik tile Perlu koreksi → hanya baris itu yang tampil;
    klik lagi → semua;
  - tab Rentang: chip `status-filter-absent` menyaring baris `absent`.

- [ ] **Step 2: Implementasi**
  - Filter: `present` = ontime|late, `inside` = waiting, `fix` = no_exit|no_entry, `absent` = absent; `rows` yang
    ditampilkan = hasil filter; tile ringkasan tetap menghitung dari semua baris.
  - Tile Harian: Hadir, Di dalam, **Perlu koreksi** (baru, oranye), Tidak hadir, Telat terlama — tile (kecuali Telat
    terlama) menjadi `<button>` dengan `aria-pressed`; grid `repeat(auto-fit, minmax(160px, 1fr))` agar 390 px aman.
  - Chip filter (`lv-chip`, `aria-pressed`) di tab Rentang & Per karyawan: Semua, Hadir, Di dalam, Perlu koreksi,
    Tidak hadir.
  - Sel status: badge + (admin & `no_exit|no_entry`) `Button kind="ghost" size="sm"` "Koreksi" (`fix-<id>`,
    `onClick={(e) => { e.stopPropagation(); openOverride(r) }}`).
  - Sel karyawan: bila `override_note`, ikon Carbon `Edit` 16 (`corrected-<id>`, `title={r.override_note}`,
    `aria-label={t('at.corrected')}`).
  - i18n: `at.summary.fix` "Perlu koreksi"/"Needs correction", `at.summary.fixSub` "Tanpa exit / tanpa entry"/"No exit /
    no entry", `at.fix` "Koreksi"/"Correct", `at.corrected` "Dikoreksi manual"/"Manually corrected",
    `at.filter.all|present|inside|fix|absent`.

- [ ] **Step 3: Commit**

```bash
rtk git add frontend/src
rtk git commit -m "feat(attendance): tombol koreksi, penanda dikoreksi, filter status dari tile dan chip"
```

---

### Task 5: Verifikasi, dokumentasi, push

- [ ] **Step 1: Suite penuh**

```bash
rtk bash -c "cd backend && .venv/bin/python -m pytest tests -q -m 'not gpu' > /tmp/be.log 2>&1; grep -oE '[0-9]+ (passed|failed)[^|]*' /tmp/be.log | tail -1"
rtk backend/.venv/bin/python -m pytest vision/tests -q -m "not gpu"
rtk bash -c "cd frontend && npx vitest run && npm run build && npm run lint"
```

Expected: backend > 606, vision 233, frontend > 237, build 0, lint tanpa error baru; `rtk git diff --stat main -- vision`
kosong.

- [ ] **Step 2: Cek visual** — `/attendance` tab Harian & Rentang 1440 px dan 390 px (stub data berisi semua status),
  screenshot `docs/evidence/2026-09-30-attendance-*.png`. Matikan server dev.

- [ ] **Step 3: Dokumentasi**
  - `README.md` bagian Attendance: arti status (Di dalam, Tanpa exit/entry — perlu koreksi, Tidak hadir otomatis
    setelah jam shift + 60 menit), koreksi manual tidak ditimpa job.
  - Runbook (buat `docs/runbooks/attendance.md` bila belum ada): penutupan otomatis tiap 15 menit + catch-up 7 hari,
    endpoint manual `close-days`, cara koreksi.
  - `ROADMAP.md`: baris **AR** (`[ ] menunggu deploy + verifikasi user`, restart API, tanpa migrasi).
  - `CHANGELOG.md`: entri teratas `### Refining halaman Attendance (2026-09-30)` (konteks + temuan bug penutupan hari
    tidak terjadwal, perubahan, file, bukti suite nyata, dampak: baris `absent` dibuat otomatis untuk 7 hari ke
    belakang saat pertama deploy, rollback).

- [ ] **Step 4: Commit + push (berhenti di sini)**

```bash
rtk git add README.md ROADMAP.md CHANGELOG.md docs/runbooks docs/evidence
rtk git commit -m "docs(attendance): README, runbook, ROADMAP, CHANGELOG refining Attendance"
rtk git push -u origin feat/attendance-refine
```

Deploy (restart API), uji lapangan, dan merge dilakukan sesi perencana — **jangan** deploy atau merge.
