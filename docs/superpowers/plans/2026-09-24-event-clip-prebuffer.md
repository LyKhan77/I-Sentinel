# Event Clip Pre-buffer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clip event berisi momen kejadian: 10 s sebelum event sampai 15 s setelah track terakhir terlihat, dari mainstream 1080p, satu clip per insiden per kamera.

**Architecture:** Modul baru `vision/vision/clipring.py` menjalankan ffmpeg `-c copy` per kamera yang menulis segmen MPEG-TS 2 s ke tmpfs. `Recorder` menjadi pengelola insiden per kamera: snapshot dikirim segera per event; saat insiden ditutup, segmen yang menutupi jendela digabung (concat `-c copy`) menjadi satu `.mp4`, diunggah sekali, lalu `publish_media` dikirim untuk setiap event insiden. Backend tidak berubah.

**Tech Stack:** Python 3.11 stdlib (`subprocess`, `shutil`, `threading`), ffmpeg binary sistem, pydantic-settings, pytest; React 19 + Vitest untuk placeholder clip.

**Spec:** `docs/superpowers/specs/2026-09-24-event-clip-prebuffer-design.md`

## Global Constraints

- Branch `feat/event-clip-prebuffer` (sudah dibuat dari `main` @ `bab61a9`).
- **Tanpa AI attribution** di commit/kode/docs (AGENTS.md §9 — menimpa trailer default apa pun).
- Vision node: tanpa dependensi Python baru; tidak import FastAPI/SQLAlchemy; semua tes jalan tanpa GPU/RTSP/ffmpeg (subprocess di-mock).
- Attendance / `FaceGateWorker` / `face_worker.py` tidak diubah. `Recorder.upload_bytes` tetap sama (dipakai face gate).
- Nilai: pre **10 s**, post **15 s**, max **120 s**, ring `/dev/shm/isentinel`, segmen **2 s**.
- Env vision memakai prefix `VISION_` (`NodeSettings`, `env_prefix="VISION_"`): `VISION_CLIP_PRE_S`, `VISION_CLIP_POST_S`, `VISION_CLIP_MAX_S`, `VISION_CLIP_RING_DIR`.
- Clip ring hanya untuk `CameraWorker` dengan analyzer `media["clip"]` true (atau `emit_person_detect`).
- Setiap task: commit Conventional Commits + satu bullet di `CHANGELOG.md` bagian `### Event clip pre-buffer (2026-09-24 – …)` (buat bagian ini di atas bagian "Enrollment & Shift refining" pada task pertama).
- Baseline hijau: backend **339 passed**; vision **177 passed, 3 deselected**; frontend **118 passed**, build exit 0, lint = 22 warning lama (bandingkan SET rule+file, bukan jumlah).
- Server `gspe-ai3`: baca bebas; **deploy/restart/hapus file butuh izin eksplisit user** (Task 6).

## Deviasi dari spec (disengaja, dicatat di sini)

1. **Jam recorder, bukan `wall(ts)`**: `enqueue`/`touch` memakai `clock()` recorder (default `time.time`) saat dipanggil. Worker memanggilnya di frame yang sama (selisih < 1 frame), sehingga helper konversi monotonic→wall tidak diperlukan dan `node._iso` tidak disentuh.
2. **Fallback live hanya saat ring tidak sehat di waktu event** (ffmpeg tidak ada/mati/stall): event diproses seperti perilaku lama (tarik live `stream.mp4` dari `cam_<id>_main`, durasi = post). Bila ring sehat tetapi segmen ternyata tidak menutupi event saat insiden ditutup, **tidak ada clip + log warning** — menarik live pada saat itu akan merekam momen yang salah.
3. **Perbaikan kebocoran outbox**: file lokal di `<data_dir>/outbox` sekarang dihapus setelah upload. Terukur di server: `I-Sentinel-data/vision/outbox` = **582 MB, 2.464 file** yang tidak pernah dihapus.
4. **Inbox auto-refresh**: poll `useLiveEvents` hanya menambah event baru (cursor `since`), sehingga `clip_path` yang datang belakangan tidak pernah tampil tanpa reload. Selama clip event terpilih masih "sedang direkam", halaman memanggil `refresh()` tiap 5 s.
5. **Perintah ffmpeg segmen tanpa `-reset_timestamps 1`** (spec §3.1 menyebutkannya): dengan `-c copy` + concat protocol, PTS yang berlanjut antar segmen membuat timeline MP4 tetap monotonik; menambahkan flag itu justru berisiko pada jalur concat mentah.
6. **`cut()` memakai concat protocol** (`-i concat:a.ts|b.ts`) alih-alih concat demuxer (`-f concat -safe 0 -i list.txt`) seperti di spec §3.1. Hasil setara untuk segmen MPEG-TS hasil `-c copy`; kalau suatu saat klip hasil gabungan bermasalah (durasi/pemutaran di batas segmen), ganti ke concat demuxer.
7. **`cut()` hanya mengembalikan path atau `None`** — tidak ada `covered_s` seperti spec §3.1/§5. Cakupan sebagian karena itu hanya terlihat dari log total-miss (`ring missed incident ... no clip`). Bila verifikasi lapangan butuh angka cakupan, tambahkan log jendela yang tercakup.
8. **`SETTLE_S = SEGMENT_S + 1 = 3 s`** (spec §3.2 menulis "end + 1 s") dan **`prune` menyimpan segmen yang menutupi `keep_from`** (spec §3.1 menulis "hapus segmen `start < keep_from − 4 s`"): keduanya setara/konservatif untuk pre-post yang disetujui; konsekuensi `SETTLE_S` ada di langkah verifikasi lapangan di bawah.

## Review Focus

1. **ffmpeg mati/stall di tengah insiden** → ring di-restart dengan backoff, clip insiden itu dibuat dari segmen yang ada bila menutupi event, bila tidak: tanpa clip + warning (tidak crash thread recorder). Tes: `test_check_restarts_dead_process_with_backoff`, `test_check_restarts_stalled_ffmpeg`, `test_ring_miss_publishes_no_clip`.
2. **Celah waktu antar segmen setelah restart** tidak boleh dianggap menutupi event (segmen sebelum celah tidak "memanjang" sampai segmen berikutnya). Tes: `test_select_gap_not_covered`.
3. **Config push / node stop saat insiden terbuka** → clip difinalisasi dengan segmen yang ada (termasuk segmen terakhir setelah ffmpeg di-stop), upload dibatasi (timeout 10 s, 1 percobaan) agar config push tidak tertahan lama. Tes: `test_close_finalizes_open_incident`.
4. **Track lain (bukan pemicu) yang lalu-lalang** tidak memperpanjang insiden; hanya track milik event insiden. Tes: `test_touch_extends_incident` (bagian track 99).
5. **Satu orang diam lama di zona** → insiden dibatasi `clip_max_s`, ring tidak tumbuh tanpa batas (prune mengikuti awal insiden terbuka). Tes: `test_incident_capped_at_max`, `test_tick_prunes_to_open_incident_start`.

---

### Task 1: `ClipRing` — ring segmen mainstream

**Files:**
- Create: `vision/vision/clipring.py`
- Test: `vision/tests/test_clipring.py`
- Modify: `CHANGELOG.md` (buat bagian baru + bullet)

**Interfaces:**
- Consumes: —
- Produces (dipakai Task 2 dan 3):
  - `SEGMENT_S: int = 2`
  - `select(segments: list[tuple[int, str]], t0: float, t1: float) -> list[str]`
  - `class ClipRing(camera_id: int, src_url: str, ring_dir: str, *, clock=time.time)` dengan atribut `available: bool`, `dir: str` dan method `command() -> list[str]`, `start() -> None`, `segments() -> list[tuple[int, str]]`, `healthy() -> bool`, `check() -> None`, `prune(keep_from: float) -> None`, `cut(t0: float, t1: float, out_path: str, *, must_cover: float, include_open: bool = False) -> str | None`, `stop() -> None`, `close() -> None`.
  - Titik monkeypatch tes: `vision.clipring._popen`, `vision.clipring._run`, `vision.clipring._which`.

- [ ] **Step 1: Tulis tes yang gagal**

Buat `vision/tests/test_clipring.py`:

```python
import os

import pytest

import vision.clipring as cr
from vision.clipring import ClipRing, select


class FakeProc:
    def __init__(self, cmd, **kw):
        self.cmd = cmd
        self.rc = None
        self.terminated = False

    def poll(self):
        return self.rc

    def terminate(self):
        self.terminated = True
        self.rc = -15

    def wait(self, timeout=None):
        return self.rc

    def kill(self):
        self.rc = -9


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def procs(monkeypatch):
    made = []

    def popen(cmd, **kw):
        p = FakeProc(cmd, **kw)
        made.append(p)
        return p

    monkeypatch.setattr(cr, "_popen", popen)
    monkeypatch.setattr(cr, "_which", lambda name: "/usr/bin/ffmpeg")
    return made


def touch_segments(ring, starts):
    os.makedirs(ring.dir, exist_ok=True)
    for s in starts:
        with open(os.path.join(ring.dir, f"{s}.ts"), "wb") as f:
            f.write(b"ts")


SEGS = [(100, "a"), (102, "b"), (104, "c"), (106, "d")]


def test_select_covers_window():
    assert select(SEGS, 101, 105) == ["a", "b", "c"]
    assert select(SEGS, 100, 104) == ["a", "b"]  # t1 on a segment start excludes it
    assert select(SEGS, 106.5, 107) == ["d"]


def test_select_gap_not_covered():
    segs = [(100, "a"), (102, "b"), (130, "c")]
    assert select(segs, 115, 116) == []  # b ends at min(130, 102 + 6)


def test_segments_parses_and_sorts(tmp_path, procs):
    ring = ClipRing(1, "rtsp://h:8554/cam_1_main", str(tmp_path))
    touch_segments(ring, [104, 100])
    open(os.path.join(ring.dir, "junk.txt"), "w").close()
    open(os.path.join(ring.dir, "x.ts"), "w").close()
    assert [s for s, _ in ring.segments()] == [100, 104]


def test_command_copies_mainstream_into_segments(tmp_path, procs):
    ring = ClipRing(1, "rtsp://h:8554/cam_1_main", str(tmp_path))
    cmd = ring.command()
    assert cmd[0] == "ffmpeg"
    assert cmd[cmd.index("-i") + 1] == "rtsp://h:8554/cam_1_main"
    assert cmd[cmd.index("-c") + 1] == "copy"
    assert cmd[cmd.index("-f") + 1] == "segment"
    assert cmd[cmd.index("-segment_time") + 1] == "2"
    assert cmd[-1] == os.path.join(str(tmp_path), "cam1", "%s.ts")


def test_cut_concats_selected_segments(tmp_path, procs, monkeypatch):
    ring = ClipRing(1, "src", str(tmp_path))
    touch_segments(ring, [100, 102, 104, 106, 108])
    runs = []

    def run(cmd, **kw):
        runs.append(cmd)
        open(cmd[-1], "wb").close()
        return type("R", (), {"returncode": 0, "stderr": b""})()

    monkeypatch.setattr(cr, "_run", run)
    out = str(tmp_path / "o.mp4")
    assert ring.cut(101, 105, out, must_cover=103) == out
    src = runs[0][runs[0].index("-i") + 1]
    assert src == "concat:" + "|".join(os.path.join(ring.dir, f"{s}.ts") for s in (100, 102, 104))
    assert runs[0][runs[0].index("-c") + 1] == "copy"
    # the newest file is still being written: dropped unless include_open
    ring.cut(105, 111, out, must_cover=107)
    assert runs[1][runs[1].index("-i") + 1].endswith("104.ts|" + os.path.join(ring.dir, "106.ts"))
    ring.cut(105, 111, out, must_cover=107, include_open=True)
    assert runs[2][runs[2].index("-i") + 1].endswith("108.ts")


def test_cut_returns_none_when_event_not_covered(tmp_path, procs, monkeypatch):
    ring = ClipRing(1, "src", str(tmp_path))
    touch_segments(ring, [100, 102])
    runs = []
    monkeypatch.setattr(cr, "_run", lambda cmd, **kw: runs.append(cmd))
    assert ring.cut(120, 130, str(tmp_path / "o.mp4"), must_cover=125) is None
    assert runs == []


def test_cut_returns_none_on_ffmpeg_error(tmp_path, procs, monkeypatch):
    ring = ClipRing(1, "src", str(tmp_path))
    touch_segments(ring, [100, 102, 104])
    monkeypatch.setattr(cr, "_run", lambda cmd, **kw: type("R", (), {"returncode": 1, "stderr": b"boom"})())
    assert ring.cut(100, 103, str(tmp_path / "o.mp4"), must_cover=101) is None


def test_prune_keeps_segment_covering_keep_from(tmp_path, procs):
    ring = ClipRing(1, "src", str(tmp_path))
    touch_segments(ring, [100, 102, 104, 106, 108, 110])
    ring.prune(105)
    assert [s for s, _ in ring.segments()] == [104, 106, 108, 110]


def test_check_restarts_dead_process_with_backoff(tmp_path, procs):
    clock = Clock(1000.0)
    ring = ClipRing(1, "src", str(tmp_path), clock=clock)
    ring.start()
    assert len(procs) == 1
    procs[-1].rc = 1              # ffmpeg died
    ring.check()
    assert len(procs) == 2 and procs[0].terminated is False  # dead proc is not re-terminated
    procs[-1].rc = 1
    clock.t = 1000.5
    ring.check()
    assert len(procs) == 2        # backoff 1 s not elapsed
    clock.t = 1001.0
    ring.check()
    assert len(procs) == 3        # next backoff is 2 s
    procs[-1].rc = 1
    clock.t = 1002.9
    ring.check()
    assert len(procs) == 3
    clock.t = 1003.0
    ring.check()
    assert len(procs) == 4


def test_check_restarts_stalled_ffmpeg(tmp_path, procs):
    clock = Clock(1000.0)
    ring = ClipRing(1, "src", str(tmp_path), clock=clock)
    ring.start()
    clock.t = 1009.0
    ring.check()
    assert len(procs) == 1 and ring.healthy()
    clock.t = 1011.0              # no segment for > 10 s
    assert not ring.healthy()
    ring.check()
    assert len(procs) == 2 and procs[0].terminated


def test_unavailable_without_ffmpeg(tmp_path, monkeypatch):
    made = []
    monkeypatch.setattr(cr, "_which", lambda name: None)
    monkeypatch.setattr(cr, "_popen", lambda cmd, **kw: made.append(cmd))
    ring = ClipRing(1, "src", str(tmp_path))
    ring.start()
    ring.check()
    assert ring.available is False and not ring.healthy() and made == []


def test_close_stops_process_and_removes_dir(tmp_path, procs):
    ring = ClipRing(1, "src", str(tmp_path))
    ring.start()
    touch_segments(ring, [100])
    ring.close()
    assert procs[0].terminated and not os.path.exists(ring.dir)
```

- [ ] **Step 2: Jalankan, pastikan gagal**

Run: `backend/.venv/bin/python -m pytest vision/tests/test_clipring.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'vision.clipring'`.

- [ ] **Step 3: Implementasi minimal**

Buat `vision/vision/clipring.py`:

```python
"""Per-camera mainstream clip ring: ffmpeg copies the go2rtc RTSP stream into short
MPEG-TS segments on tmpfs; an incident clip is the concat of the segments covering it.

Stdlib only. Segment file name = wall-clock epoch when ffmpeg opened it (strftime %s);
segments always start on a keyframe.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time

log = logging.getLogger(__name__)

SEGMENT_S = 2
MAX_SEG_S = 6.0      # longest believable segment (GOP <= 6 s); beyond that = gap
STALL_S = 10.0       # no new segment for this long = ffmpeg stalled
BACKOFF_MAX_S = 30.0

# module-level for test monkeypatching
_popen = subprocess.Popen
_run = subprocess.run
_which = shutil.which


def select(segments: list[tuple[int, str]], t0: float, t1: float) -> list[str]:
    """Paths of sorted (start, path) segments overlapping [t0, t1).

    Segment i spans [start_i, min(start_{i+1}, start_i + MAX_SEG_S)), so a restart gap
    is never counted as covered.
    """
    out = []
    for i, (start, path) in enumerate(segments):
        nxt = segments[i + 1][0] if i + 1 < len(segments) else start + MAX_SEG_S
        end = min(nxt, start + MAX_SEG_S)
        if start < t1 and end > t0:
            out.append(path)
    return out


class ClipRing:
    """ffmpeg segment ring for one camera's mainstream, with a restart watchdog."""

    def __init__(self, camera_id: int, src_url: str, ring_dir: str, *, clock=time.time):
        self.camera_id = camera_id
        self.src_url = src_url
        self.dir = os.path.join(os.path.expanduser(ring_dir), f"cam{camera_id}")
        self._clock = clock
        self._proc = None
        self._started_at = 0.0
        self._backoff = 1.0
        self._next_restart = 0.0
        shutil.rmtree(self.dir, ignore_errors=True)  # leftovers from a crashed run
        self.available = _which("ffmpeg") is not None
        if not self.available:
            log.error("clip ring cam%s: ffmpeg not found, clips fall back to live pull",
                      camera_id)

    def command(self) -> list[str]:
        return ["ffmpeg", "-nostdin", "-loglevel", "error", "-rtsp_transport", "tcp",
                "-i", self.src_url, "-map", "0:v:0", "-c", "copy", "-an",
                "-f", "segment", "-segment_time", str(SEGMENT_S),
                "-segment_format", "mpegts", "-strftime", "1",
                os.path.join(self.dir, "%s.ts")]

    def start(self) -> None:
        if not self.available:
            return
        os.makedirs(self.dir, exist_ok=True)
        self._proc = _popen(self.command(), stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self._started_at = self._clock()

    def segments(self) -> list[tuple[int, str]]:
        try:
            names = os.listdir(self.dir)
        except OSError:
            return []
        out = []
        for name in names:
            stem, ext = os.path.splitext(name)
            if ext == ".ts" and stem.isdigit():
                out.append((int(stem), os.path.join(self.dir, name)))
        return sorted(out)

    def healthy(self) -> bool:
        if self._proc is None or self._proc.poll() is not None:
            return False
        segs = self.segments()
        progress = max(segs[-1][0] if segs else 0, self._started_at)
        return self._clock() - progress <= STALL_S

    def check(self) -> None:
        """Watchdog step: restart a dead or stalled ffmpeg with exponential backoff."""
        if not self.available:
            return
        if self.healthy():
            segs = self.segments()
            if segs and segs[-1][0] >= int(self._started_at):
                self._backoff = 1.0  # produced output since the last (re)start
            return
        now = self._clock()
        if now < self._next_restart:
            return
        log.warning("clip ring cam%s: ffmpeg dead or stalled, restarting (backoff %.0fs)",
                    self.camera_id, self._backoff)
        self.stop()
        self.start()
        self._next_restart = now + self._backoff
        self._backoff = min(self._backoff * 2, BACKOFF_MAX_S)

    def prune(self, keep_from: float) -> None:
        """Delete segments older than the one covering keep_from."""
        segs = self.segments()
        keep_idx = max((i for i, (s, _) in enumerate(segs) if s <= keep_from), default=0)
        for _, path in segs[:keep_idx]:
            try:
                os.remove(path)
            except OSError:
                pass

    def cut(self, t0: float, t1: float, out_path: str, *, must_cover: float,
            include_open: bool = False) -> str | None:
        """Concat segments covering [t0, t1] into out_path (mp4, faststart).

        None when no segment covers must_cover (the event moment) or ffmpeg fails.
        The newest segment is still being written unless include_open (ffmpeg stopped).
        """
        segs = self.segments()
        paths = select(segs, t0, t1)
        if not include_open and segs and paths and paths[-1] == segs[-1][1]:
            paths.pop()
        hit = select(segs, must_cover, must_cover + 0.001)
        if not paths or not hit or hit[0] not in paths:
            log.warning("clip ring cam%s: no segment covers %.1f", self.camera_id, must_cover)
            return None
        cmd = ["ffmpeg", "-nostdin", "-loglevel", "error", "-y",
               "-i", "concat:" + "|".join(paths),
               "-c", "copy", "-movflags", "+faststart", out_path]
        try:
            r = _run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=60)
        except (OSError, subprocess.TimeoutExpired) as e:
            log.warning("clip ring cam%s: concat failed: %s", self.camera_id, e)
            return None
        if r.returncode != 0 or not os.path.exists(out_path):
            log.warning("clip ring cam%s: concat rc=%s %s", self.camera_id, r.returncode,
                        (r.stderr or b"")[-300:])
            return None
        return out_path

    def stop(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None or proc.poll() is not None:
            return
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=3)

    def close(self) -> None:
        self.stop()
        shutil.rmtree(self.dir, ignore_errors=True)
```

- [ ] **Step 4: Jalankan, pastikan lulus**

Run: `backend/.venv/bin/python -m pytest vision/tests/test_clipring.py -q`
Expected: `12 passed`.

- [ ] **Step 5: CHANGELOG + commit**

Tambahkan di atas `### Enrollment & Shift refining (2026-09-23 – 2026-09-24)`:

```markdown
### Event clip pre-buffer (2026-09-24 – …)

- **`ClipRing`** (`vision/vision/clipring.py`): ffmpeg `-c copy` per kamera menulis segmen MPEG-TS 2 s
  ke tmpfs; `cut` menggabung segmen yang menutupi jendela insiden (concat `-c copy`, `+faststart`);
  watchdog restart ffmpeg mati/stall dengan backoff ≤ 30 s; celah restart tidak dianggap tertutup.
  Belum dipakai recorder. Vision **<angka> passed**.
```

Isi `<angka>` dari output `backend/.venv/bin/python -m pytest vision/tests -q -m "not gpu"` (harus 189 passed = 177 + 12).

```bash
git add vision/vision/clipring.py vision/tests/test_clipring.py CHANGELOG.md
git commit -m "feat(vision): ClipRing — ring segmen mainstream ffmpeg untuk clip pre-buffer"
```

---

### Task 2: `Recorder` sebagai pengelola insiden + config clip

**Files:**
- Modify: `vision/vision/config.py:36` (ganti `record_clip_s`)
- Modify: `vision/vision/recorder.py` (kelas `Recorder` kecuali `push_jpeg`, `push_frame`, `_outbox_dir`, `_save_snapshot`, `_TRACK_COLORS`, `_draw_track_box`, `upload_bytes`, `_upload_one`)
- Test: `vision/tests/test_recorder.py` (tulis ulang tes lama berbasis `capture`/`upload`)
- Modify: `deploy/vision.env.example`, `CHANGELOG.md`

**Interfaces:**
- Consumes: `SEGMENT_S` dan kontrak `ClipRing` dari Task 1 (`healthy()`, `cut(...)`, `check()`, `prune(keep_from)`, `stop()`, `close()`).
- Produces (dipakai Task 3):
  - `Recorder(camera_id, cfg, transport=None, clip_ring=None, *, clock=time.time, autostart=True)`
  - `Recorder.enqueue(event: dict) -> None` (argumen kedua `track_bbox_norm` dihapus; tidak ada pemanggil yang memakainya)
  - `Recorder.touch(track_ids: Iterable[int]) -> None`
  - `Recorder.tick(force: bool = False) -> None`, `Recorder.close() -> None`
  - `NodeSettings.clip_pre_s: float = 10.0`, `clip_post_s: float = 15.0`, `clip_max_s: float = 120.0`, `clip_ring_dir: str = "/dev/shm/isentinel"`
  - Payload media sekarang parsial: `{"event_id", "snapshot_path"}` atau `{"event_id", "clip_path"}` (backend sudah menerimanya, `events_consumer.py:75`).
  - Dihapus: `Recorder.capture`, `Recorder.upload`, `NodeSettings.record_clip_s`.

- [ ] **Step 1: Ganti config**

`vision/vision/config.py` — ganti baris `record_clip_s: int = 30` dengan:

```python
    clip_pre_s: float = 10.0     # clip starts this long before the first incident event
    clip_post_s: float = 15.0    # ...and ends this long after its tracks were last seen
    clip_max_s: float = 120.0    # hard cap on one incident clip (pre included)
    clip_ring_dir: str = "/dev/shm/isentinel"  # tmpfs for mainstream segments
```

- [ ] **Step 2: Tulis tes yang gagal**

Di `vision/tests/test_recorder.py`:
- **Hapus** tes: `test_capture_go2rtc_fail_snapshot_still_saved`, `test_capture_and_upload_success`, `test_upload_no_blobs_returns_none`, `test_recorder_queue_drop_oldest`, `test_event_flags_skip_snapshot_or_clip`, `test_capture_defaults_true_without_flags`, serta helper `_recorder` dan `_fake_urlopen`.
- **Ubah** `test_upload_retries_three_times_then_none`: ganti bagian `result = rec.upload({...})` dengan `result = rec._upload_one(str(tmp_path / "x.jpg"), "snapshot", "image/jpeg")`; sisanya tetap.
- **Ubah** `test_snapshot_draws_bbox_and_track_id`: ganti `cfg = type("C", (), {...})()` dengan `cfg = make_cfg(tmp_path)`.
- **Ganti** seluruh `test_worker_recorder_media_publish` dengan versi di bawah. Recorder tanpa ring → clip lewat fallback live yang gagal (go2rtc down) → hanya snapshot yang dipublikasi. `_wait` harus berjalan di dalam `try` agar thread recorder masih memakai `urlopen` palsu:

```python
def test_worker_recorder_media_publish(tmp_path):
    """Full flow: worker + detector + recorder (mocked urlopen) -> snapshot media payload."""
    import vision.recorder as rec_mod

    def fake_urlopen(target, timeout=None):
        url = target if isinstance(target, str) else target.full_url
        if "stream.mp4" in url:
            raise RuntimeError("go2rtc down")
        return FakeResp(b'{"path": "/media/snap.jpg"}')

    t = FakeTransport()
    rec = Recorder(1, make_cfg(tmp_path), transport=t)
    orig = rec_mod.urlopen
    rec_mod.urlopen = fake_urlopen  # recorder thread uses module attr at call time
    try:
        frame = np.zeros((4, 4, 3), dtype=np.uint8)
        src = FrameSource.from_frames([frame] * 3, fps=100.0)
        det = MockDetector([[Detection(bbox=(0.1, 0.1, 0.3, 0.4), conf=0.9)]] * 3)
        w = CameraWorker(CameraCfg(camera_id=1, source_url="test://1"), lambda cid: det,
                         t, threading.Event(), "test-node", recorder=rec, emit_person_detect=True)
        w.source = src
        w.start()
        w.join(timeout=10)
        _wait(lambda: len(t.media) >= 1)
        rec.close()
    finally:
        rec_mod.urlopen = orig

    assert len(t.events) == 1
    assert t.media == [{"event_id": t.events[0]["event_id"], "snapshot_path": "/media/snap.jpg"}]
```

Tambahkan di akhir file:

```python
# --- clip insiden per kamera (pre-buffer) -------------------------------------

import os
import time as _time


def _wait(cond, timeout=5.0):
    end = _time.monotonic() + timeout
    while not cond():
        assert _time.monotonic() < end, "timeout"
        _time.sleep(0.01)


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


class FakeRing:
    def __init__(self, healthy=True, cut_ok=True):
        self._healthy = healthy
        self.cut_ok = cut_ok
        self.cuts = []
        self.checks = 0
        self.prunes = []
        self.stopped = self.closed = False

    def healthy(self):
        return self._healthy

    def cut(self, t0, t1, out_path, *, must_cover, include_open=False):
        self.cuts.append((t0, t1, must_cover, include_open))
        if not self.cut_ok:
            return None
        with open(out_path, "wb") as f:
            f.write(b"mp4")
        return out_path

    def check(self):
        self.checks += 1

    def prune(self, keep_from):
        self.prunes.append(keep_from)

    def stop(self):
        self.stopped = True

    def close(self):
        self.closed = True


def _clip_recorder(tmp_path, ring=None, clock=None, **cfg_kw):
    t = FakeTransport()
    rec = Recorder(1, make_cfg(tmp_path, **cfg_kw), t, clip_ring=ring or FakeRing(),
                   clock=clock or Clock(), autostart=False)
    uploads = []

    def upload(path, kind, content_type, **kw):
        uploads.append((kind, kw))
        return f"{kind}s/x"

    rec._upload_one = upload
    return rec, t, uploads


def _sec_ev(eid, tid, snapshot=False, clip=None):
    ev = {"event_id": eid, "type": "intrusion", "severity": "warning",
          "payload": {"track_id": tid, "bbox_norm": [0.1, 0.1, 0.5, 0.6]}, "snapshot": snapshot}
    if clip is not None:
        ev["clip"] = clip
    return ev


def _run_jobs(rec):
    while not rec._q.empty():
        kind, ev = rec._q.get_nowait()
        rec._run_job(kind, ev)


def test_two_events_one_incident_one_clip(tmp_path):
    clock = Clock(1000.0)
    ring = FakeRing()
    rec, t, uploads = _clip_recorder(tmp_path, ring, clock)
    rec.enqueue(_sec_ev("a", 1))
    clock.t = 1005.0
    rec.enqueue(_sec_ev("b", 2))
    clock.t = 1022.9                      # end 1020 + settle 3 s not reached
    rec.tick()
    assert ring.cuts == []
    clock.t = 1023.0
    rec.tick()
    assert ring.cuts == [(990.0, 1020.0, 1000.0, False)]
    assert uploads == [("clip", {})]
    assert t.media == [{"event_id": "a", "clip_path": "clips/x"},
                       {"event_id": "b", "clip_path": "clips/x"}]
    assert os.listdir(tmp_path / "data" / "outbox") == []   # local clip removed after upload


def test_touch_extends_incident(tmp_path):
    clock = Clock(1000.0)
    ring = FakeRing()
    rec, t, _ = _clip_recorder(tmp_path, ring, clock)
    rec.enqueue(_sec_ev("a", 7))
    clock.t = 1010.0
    rec.touch([7])
    clock.t = 1020.0
    rec.touch([99])                       # a passer-by track does not extend
    clock.t = 1027.9
    rec.tick()
    assert ring.cuts == []
    clock.t = 1028.0
    rec.tick()
    assert ring.cuts[0][1] == 1025.0


def test_incident_capped_at_max(tmp_path):
    clock = Clock(1000.0)
    ring = FakeRing()
    rec, _, _ = _clip_recorder(tmp_path, ring, clock, clip_max_s=30.0)
    rec.enqueue(_sec_ev("a", 1))
    clock.t = 1019.0
    rec.touch([1])
    clock.t = 1023.0
    rec.tick()
    assert ring.cuts == [(990.0, 1020.0, 1000.0, False)]


def test_event_after_close_opens_new_incident(tmp_path):
    clock = Clock(1000.0)
    ring = FakeRing()
    rec, t, _ = _clip_recorder(tmp_path, ring, clock)
    rec.enqueue(_sec_ev("a", 1))
    clock.t = 1023.0
    rec.tick()
    clock.t = 1100.0
    rec.enqueue(_sec_ev("b", 1))
    clock.t = 1118.0
    rec.tick()
    assert [c[0] for c in ring.cuts] == [990.0, 1090.0]
    assert [m["event_id"] for m in t.media] == ["a", "b"]


def test_snapshot_published_before_clip(tmp_path):
    rec, t, _ = _clip_recorder(tmp_path)
    rec.push_jpeg(1.0, b"jpeg-bytes")
    rec.enqueue(_sec_ev("a", 1, snapshot=True))
    _run_jobs(rec)
    assert t.media == [{"event_id": "a", "snapshot_path": "snapshots/x"}]
    assert rec._incident is not None     # clip still pending


def test_clip_false_skips_incident(tmp_path):
    clock = Clock(1000.0)
    ring = FakeRing()
    rec, t, _ = _clip_recorder(tmp_path, ring, clock)
    rec.enqueue(_sec_ev("a", 1, clip=False))
    clock.t = 1100.0
    rec.tick()
    assert rec._incident is None and ring.cuts == [] and t.media == []


def test_unhealthy_ring_falls_back_to_live_mainstream(tmp_path, monkeypatch):
    import vision.recorder as rec_mod
    calls = []

    def fake_urlopen(url, timeout=None):
        calls.append(url)
        return FakeResp(b"mp4-bytes")

    monkeypatch.setattr(rec_mod, "urlopen", fake_urlopen)
    rec, t, _ = _clip_recorder(tmp_path, FakeRing(healthy=False))
    rec.enqueue(_sec_ev("a", 1))
    assert rec._incident is None
    _run_jobs(rec)
    assert calls == ["http://go2rtc:1984/api/stream.mp4?src=cam_1_main&duration=15"]
    assert t.media == [{"event_id": "a", "clip_path": "clips/x"}]


def test_ring_miss_publishes_no_clip(tmp_path):
    clock = Clock(1000.0)
    rec, t, uploads = _clip_recorder(tmp_path, FakeRing(cut_ok=False), clock)
    rec.enqueue(_sec_ev("a", 1))
    clock.t = 1023.0
    rec.tick()
    assert uploads == [] and t.media == [] and rec._incident is None


def test_close_finalizes_open_incident(tmp_path):
    clock = Clock(1000.0)
    ring = FakeRing()
    rec, t, uploads = _clip_recorder(tmp_path, ring, clock)
    rec.enqueue(_sec_ev("a", 1))
    clock.t = 1003.0
    rec.close()
    assert ring.stopped and ring.closed
    assert ring.cuts == [(990.0, 1015.0, 1000.0, True)]
    assert uploads == [("clip", {"timeout": 10, "retries": 1})]
    assert t.media == [{"event_id": "a", "clip_path": "clips/x"}]


def test_tick_prunes_to_open_incident_start(tmp_path):
    clock = Clock(1000.0)
    ring = FakeRing()
    rec, _, _ = _clip_recorder(tmp_path, ring, clock)
    clock.t = 1005.0
    rec.tick()
    assert ring.prunes[-1] == 995.0      # no incident: keep the pre window
    rec.enqueue(_sec_ev("a", 1))        # start = 995
    clock.t = 1012.0
    rec.tick()
    assert ring.prunes[-1] == 995.0      # min(open start 995, 1012 - 10)
    assert ring.checks == 2


def test_queue_drops_oldest_when_full(tmp_path):
    rec = Recorder(1, make_cfg(tmp_path), autostart=False)
    for i in range(60):
        rec.enqueue(make_event(f"ev-{i}"))   # no ring: snapshot + live_clip job each
    assert rec._q.qsize() == 50
    assert rec._q.get_nowait()[1]["event_id"] == "ev-35"
    rec.close()
```

- [ ] **Step 3: Jalankan, pastikan gagal**

Run: `backend/.venv/bin/python -m pytest vision/tests/test_recorder.py -q`
Expected: FAIL — `TypeError: Recorder.__init__() got an unexpected keyword argument 'clip_ring'` (dan tes lama yang diubah gagal karena `record_clip_s` hilang).

- [ ] **Step 4: Implementasi**

`vision/vision/recorder.py`:

(a) Import di atas: tambah `import os` dan, setelah `import urllib.request`, baris `from .clipring import SEGMENT_S`. Ubah docstring modul menjadi:

```python
"""Event recorder: snapshot per event right away, one mainstream clip per incident.

An incident opens on the first clip-enabled event of a camera; later events join it and
share its clip. It closes clip_post_s after its tracks were last seen (cap clip_max_s);
the clip is cut from the ClipRing segments. Pure stdlib network (urllib).
"""
```

(b) Setelah `UPLOAD_MAX_QUEUE = 50` tambahkan:

```python
SETTLE_S = SEGMENT_S + 1  # wait until the segment holding the clip end is closed


class _Incident:
    """Clip window of one camera; events that happen while it is open share its clip."""

    def __init__(self, start: float, now: float, event: dict):
        self.start = start
        self.last_active = now
        self.events: list[dict] = []
        self.tracks: set[int] = set()
        self.add(event, now)

    def add(self, event: dict, now: float) -> None:
        self.events.append(event)
        self.last_active = max(self.last_active, now)
        tid = (event.get("payload") or {}).get("track_id")
        if tid is not None:
            self.tracks.add(tid)
```

(c) Ganti `class Recorder` dari docstring sampai akhir `_loop` (termasuk `enqueue`, `_loop`, `capture`) dengan:

```python
class Recorder:
    """Per-camera: snapshot per event right away; one mainstream clip per incident."""

    def __init__(self, camera_id: int, cfg, transport=None, clip_ring=None, *,
                 clock=time.time, autostart: bool = True):
        self.camera_id = camera_id
        self.cfg = cfg
        self.transport = transport  # publish_media on upload success; None = silent
        self.clip_ring = clip_ring  # ClipRing | None (None = live fallback per event)
        self.ring = FrameRing()     # substream JPEGs for snapshots
        self._clock = clock
        self._lock = threading.Lock()
        self._incident: _Incident | None = None
        self._q: queue.Queue = queue.Queue(maxsize=UPLOAD_MAX_QUEUE)
        self._stopped = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name=f"recorder-cam{camera_id}")
        if autostart:
            self._thread.start()

    def push_jpeg(self, ts: float, jpeg: bytes) -> None:
        self.ring.push(ts, jpeg)

    def push_frame(self, ts: float, frame) -> None:
        """Encode ndarray via cv2 (lazy) and push. Skips when cv2 missing."""
        try:
            import cv2
        except ImportError:
            log.debug("cv2 not installed; skipping ring push")
            return
        ok, enc = cv2.imencode(".jpg", frame)
        if ok:
            self.ring.push(ts, enc.tobytes())

    def enqueue(self, event: dict) -> None:
        """Called by the camera worker for every event (non-blocking)."""
        if event.get("snapshot") is not False:
            self._put(("snapshot", event))
        if event.get("clip") is False:
            return
        if self.clip_ring is None or not self.clip_ring.healthy():
            self._put(("live_clip", event))  # degraded: post-only live pull, as before
            return
        now = self._clock()
        with self._lock:
            if self._incident is None:
                self._incident = _Incident(now - self.cfg.clip_pre_s, now, event)
            else:
                self._incident.add(event, now)

    def touch(self, track_ids) -> None:
        """Tracks seen this frame; keeps the incident open while its tracks are visible."""
        with self._lock:
            inc = self._incident
            if inc is not None and not inc.tracks.isdisjoint(track_ids):
                inc.last_active = max(inc.last_active, self._clock())

    def _put(self, job: tuple[str, dict]) -> None:
        try:
            self._q.put_nowait(job)
        except queue.Full:
            # ponytail: drop-oldest via get+retry; racy under concurrent producers,
            # single camera worker per recorder so fine
            try:
                self._q.get_nowait()
                log.warning("recorder cam%s: queue full, dropped oldest", self.camera_id)
            except queue.Empty:
                pass
            self._q.put_nowait(job)

    def _end(self, inc: _Incident) -> float:
        return min(inc.start + self.cfg.clip_max_s, inc.last_active + self.cfg.clip_post_s)

    def tick(self, force: bool = False) -> None:
        """Close the incident once its window has passed (force: now); ring upkeep."""
        now = self._clock()
        with self._lock:
            inc = self._incident
            due = inc is not None and (force or now >= self._end(inc) + SETTLE_S)
            if due:
                self._incident = None
        if due:
            upload_kw = {"timeout": 10, "retries": 1} if force else {}
            self._finish(inc, include_open=force, **upload_kw)
        if self.clip_ring is not None and not force:
            self.clip_ring.check()
            with self._lock:
                open_start = self._incident.start if self._incident else now
            self.clip_ring.prune(min(open_start, now - self.cfg.clip_pre_s))

    def _finish(self, inc: _Incident, *, include_open: bool = False, **upload_kw) -> None:
        first = inc.events[0]["event_id"]
        out = os.path.join(self._outbox_dir(), f"{first}.mp4")
        local = self.clip_ring.cut(inc.start, self._end(inc), out,
                                   must_cover=inc.start + self.cfg.clip_pre_s,
                                   include_open=include_open)
        if local is None:
            log.warning("recorder cam%s: ring missed incident %s, no clip",
                        self.camera_id, first)
            return
        self._ship(local, "clip", "video/mp4", [e["event_id"] for e in inc.events], **upload_kw)

    def _run_job(self, kind: str, event: dict) -> None:
        event_id = event["event_id"]
        outbox = self._outbox_dir()
        if kind == "snapshot":
            local = self._save_snapshot(event_id, outbox, event)
            if local:
                self._ship(local, "snapshot", "image/jpeg", [event_id])
        else:  # live_clip
            local = self._save_clip(event_id, outbox)
            if local:
                self._ship(local, "clip", "video/mp4", [event_id])

    def _ship(self, local: str, kind: str, content_type: str, event_ids: list[str],
              **upload_kw) -> None:
        """Upload once, drop the local file, publish the backend path for every event."""
        try:
            path = self._upload_one(local, kind, content_type, **upload_kw)
        finally:
            try:
                os.remove(local)
            except OSError:
                pass
        if path is None or self.transport is None:
            return
        for event_id in event_ids:
            self.transport.publish_media({"event_id": event_id, f"{kind}_path": path})

    def _loop(self) -> None:
        while not self._stopped.is_set():
            try:
                job = self._q.get(timeout=0.5)
            except queue.Empty:
                job = None
            try:
                if job is not None:
                    self._run_job(*job)
                self.tick()
            except Exception:
                log.exception("recorder cam%s: job failed", self.camera_id)
```

(d) Di `_outbox_dir` dan `_save_snapshot` hapus baris `import os` lokal (sudah di atas).

(e) Ganti `_save_clip` dengan:

```python
    def _save_clip(self, event_id: str, outbox: str) -> str | None:
        """Degraded path (no healthy ring): live mainstream pull starting now."""
        url = (f"{self.cfg.go2rtc_url}/api/stream.mp4"
               f"?src=cam_{self.camera_id}_main&duration={int(self.cfg.clip_post_s)}")
        try:
            with urlopen(url, timeout=60) as resp:
                data = resp.read()
        except Exception as e:
            log.warning("recorder cam%s: go2rtc clip failed (%s), clip skipped",
                        self.camera_id, e)
            return None
        if not data:
            return None
        path = os.path.join(outbox, f"{event_id}.mp4")
        with open(path, "wb") as f:
            f.write(data)
        return path
```

(f) Hapus method `upload` seluruhnya. Hapus `import os` lokal di `upload_bytes` dan `_upload_one`.

(g) Ganti `close` dengan:

```python
    def close(self) -> None:
        self._stopped.set()
        if self._thread.ident is not None:
            self._thread.join(timeout=5.0)
        if self.clip_ring is None:
            return
        self.clip_ring.stop()  # flush the open segment before the final cut
        try:
            self.tick(force=True)
        except Exception:
            log.exception("recorder cam%s: final clip failed", self.camera_id)
        self.clip_ring.close()
```

- [ ] **Step 5: Jalankan, pastikan lulus**

Run: `backend/.venv/bin/python -m pytest vision/tests/test_recorder.py vision/tests/test_clipring.py -q`
Expected: semua passed.

Run: `backend/.venv/bin/python -m pytest vision/tests -q -m "not gpu"`
Expected: semua passed, 3 deselected. Bila ada tes lain yang masih memakai `record_clip_s`, `capture` atau `enqueue(ev, bbox)`: `grep -rn "record_clip_s\|\.capture(\|\.upload(" vision/` harus kosong (kecuali `upload_bytes`).

- [ ] **Step 6: Env example**

Tambahkan di akhir `deploy/vision.env.example`:

```bash
# Event clips (mainstream pre-buffer). Pre/post in seconds; max caps one incident clip.
VISION_CLIP_PRE_S=10
VISION_CLIP_POST_S=15
VISION_CLIP_MAX_S=120
# tmpfs for the per-camera ffmpeg segment ring (needs ffmpeg in PATH).
VISION_CLIP_RING_DIR=/dev/shm/isentinel
```

- [ ] **Step 7: CHANGELOG + commit**

Bullet baru di bagian "Event clip pre-buffer":

```markdown
- **Recorder = insiden per kamera**: snapshot per event langsung diunggah + dipublikasi (dulu tertahan
  ~30 s oleh clip); event ber-clip membuka/bergabung ke satu insiden per kamera, ditutup 15 s setelah
  track insiden terakhir terlihat (cap 120 s), clip dipotong dari `ClipRing`, satu upload, media
  dipublikasi untuk setiap event. Ring tidak sehat → fallback live `cam_<id>_main` (perilaku lama).
  Config `record_clip_s` → `clip_pre_s/clip_post_s/clip_max_s/clip_ring_dir`. **Fix kebocoran
  outbox**: file lokal dihapus setelah upload (server: 582 MB / 2.464 file menumpuk).
  Vision **<angka> passed**.
```

```bash
git add vision/vision/config.py vision/vision/recorder.py vision/tests/test_recorder.py deploy/vision.env.example CHANGELOG.md
git commit -m "feat(vision): recorder insiden per kamera — clip pre-buffer dari ring mainstream"
```

---

### Task 3: Pasang ring + `touch` di node

**Files:**
- Modify: `vision/vision/node.py` (`CameraWorker.run` setelah `tracks = tracker.update(...)` ~baris 146; `VisionNode._start_workers` ~baris 378–381; method baru `_wants_clip`)
- Test: `vision/tests/test_config_apply.py`, `vision/tests/test_recorder.py`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: `ClipRing(camera_id, src_url, ring_dir)` + `.start()` (Task 1); `Recorder(..., clip_ring=...)`, `Recorder.touch(track_ids)` (Task 2); `main_stream_url(source_url)` (sudah ada, `node.py:50`).
- Produces: `VisionNode._wants_clip(analyzers: list) -> bool`.

- [ ] **Step 1: Tulis tes yang gagal**

Tambahkan di akhir `vision/tests/test_config_apply.py`:

```python
def test_clip_ring_only_for_cameras_with_clip_zones(tmp_path, monkeypatch):
    import vision.clipring as cr

    made = []

    class FakeRing:
        def __init__(self, camera_id, src_url, ring_dir):
            made.append((camera_id, src_url, ring_dir))

        def start(self): pass
        def healthy(self): return True
        def check(self): pass
        def prune(self, keep_from): pass
        def stop(self): pass
        def close(self): pass

    monkeypatch.setattr(cr, "ClipRing", FakeRing)
    cfg = NodeSettings(node_id="n1", api_key="k", face_embed=False, data_dir=str(tmp_path),
                       clip_ring_dir=str(tmp_path / "ring"))
    node = VisionNode(cfg=cfg, detector_factory=lambda cid: MockDetector([]),
                      source_factory=lambda cam: FrameSource.from_frames([], fps=5.0),
                      transport=FakeTransportWithCfg())
    poly = [[0, 0], [1, 0], [1, 1], [0, 1]]

    def zone(zid, clip):
        return {"id": zid, "type": "behavior", "active": True, "polygon": poly,
                "behaviors": [{"kind": "intrusion"}], "clip": clip}

    node.apply_config({"cameras": [
        {"camera_id": 1, "source_url": "rtsp://h:8554/cam_1", "zones": [zone(1, True)]},
        {"camera_id": 2, "source_url": "rtsp://h:8554/cam_2", "zones": [zone(2, False)]},
        {"camera_id": 3, "source_url": "rtsp://h:8554/cam_3", "zones": []},
    ]})
    node._stop_workers()
    assert made == [(1, "rtsp://h:8554/cam_1_main", str(tmp_path / "ring"))]
```

(Pastikan import `MockDetector`, `FrameSource`, `NodeSettings`, `VisionNode` sudah ada di kepala file; tambahkan yang belum.)

Tambahkan di akhir `vision/tests/test_recorder.py`:

```python
def test_worker_touches_recorder_with_track_ids():
    class TouchRec:
        def __init__(self):
            self.touches = []

        def push_jpeg(self, ts, jpeg): pass
        def enqueue(self, ev): pass
        def touch(self, ids): self.touches.append(list(ids))

    rec = TouchRec()
    frame = np.zeros((4, 4, 3), dtype=np.uint8)
    src = FrameSource.from_frames([frame] * 3, fps=100.0)
    det = MockDetector([[Detection(bbox=(0.1, 0.1, 0.3, 0.4), conf=0.9)]] * 3)
    w = CameraWorker(CameraCfg(camera_id=1, source_url="test://1"), lambda cid: det,
                     FakeTransport(), threading.Event(), "n", recorder=rec)
    w.source = src
    w.start()
    w.join(timeout=10)
    assert rec.touches and all(len(ids) == 1 for ids in rec.touches)
```

- [ ] **Step 2: Jalankan, pastikan gagal**

Run: `backend/.venv/bin/python -m pytest vision/tests/test_config_apply.py::test_clip_ring_only_for_cameras_with_clip_zones vision/tests/test_recorder.py::test_worker_touches_recorder_with_track_ids -q`
Expected: FAIL — `made == []` dan `rec.touches == []`.

- [ ] **Step 3: Implementasi**

`vision/vision/node.py`, di `CameraWorker.run` tepat setelah `tracks = tracker.update(detections, frame.ts)`:

```python
                if self.recorder is not None and tracks:
                    self.recorder.touch([t.id for t in tracks])
```

Di `VisionNode._start_workers`, ganti blok:

```python
            recorder = None
            if self.cfg.api_key:  # production: upload blobs to backend
                from .recorder import Recorder
                recorder = Recorder(cam.camera_id, self.cfg, self.transport)
```

dengan:

```python
            recorder = None
            if self.cfg.api_key:  # production: upload blobs to backend
                from .recorder import Recorder
                ring = None
                if (analyzers or not gates) and self._wants_clip(analyzers):
                    from . import clipring
                    ring = clipring.ClipRing(cam.camera_id, main_stream_url(cam.source_url),
                                             self.cfg.clip_ring_dir)
                    ring.start()
                recorder = Recorder(cam.camera_id, self.cfg, self.transport, clip_ring=ring)
```

Tambahkan method di `VisionNode` (dekat `_with_media`):

```python
    def _wants_clip(self, analyzers: list) -> bool:
        """Mainstream ring only for cameras whose events can carry a clip."""
        return self.cfg.emit_person_detect or any(
            getattr(a, "media", {}).get("clip", True) for a in analyzers)
```

(`from . import clipring` + `clipring.ClipRing` dipakai agar monkeypatch `vision.clipring.ClipRing` di tes berlaku.)

- [ ] **Step 4: Jalankan, pastikan lulus**

Run: `backend/.venv/bin/python -m pytest vision/tests -q -m "not gpu"`
Expected: semua passed, 3 deselected.

- [ ] **Step 5: CHANGELOG + commit**

```markdown
- **Node memasang ring**: `ClipRing` dari `cam_<id>_main` hanya untuk `CameraWorker` yang punya
  analyzer `clip` aktif (atau `emit_person_detect`); kamera gate-only / tanpa zona clip tidak membuka
  koneksi mainstream. Worker memanggil `recorder.touch(track_ids)` tiap frame inferensi.
  Vision **<angka> passed**.
```

```bash
git add vision/vision/node.py vision/tests/test_config_apply.py vision/tests/test_recorder.py CHANGELOG.md
git commit -m "feat(vision): pasang ClipRing per kamera ber-clip + touch track ke recorder"
```

---

### Task 4: Inbox — placeholder "sedang direkam" + refresh sampai clip datang

**Files:**
- Modify: `frontend/src/features/events/EventsPage.tsx` (setelah `const isAttendance = …` ~baris 135; placeholder ~baris 349)
- Modify: `frontend/src/app/i18n.tsx` (`zones.clip` id/en, key baru `events.clipRecording` id/en)
- Test: `frontend/src/__tests__/events.test.tsx`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: `EventOut.clip_path`, `EventOut.ts_event`, `refresh()` yang sudah ada di `EventsPage`.
- Produces: key i18n `events.clipRecording`.

- [ ] **Step 1: Tulis tes yang gagal**

Tambahkan di `frontend/src/__tests__/events.test.tsx` (setelah tes `detail panel shows placeholder when clip_path null`):

```tsx
test('fresh event without clip shows recording placeholder and refetches', async () => {
  const fresh: EventOut[] = [{ ...EVENTS[0], ts_event: new Date().toISOString() }]
  const fetchMock = stubFetch(fresh)
  vi.stubGlobal('fetch', fetchMock)
  renderPage()

  await screen.findByTestId('event-detail')
  await userEvent.click(screen.getByTestId('event-tab-clip'))
  expect(screen.getByTestId('event-clip-placeholder')).toHaveTextContent('Clip sedang direkam')
  const before = fetchMock.mock.calls.filter(([u]) => String(u).includes('limit=200')).length
  await waitFor(
    () => expect(fetchMock.mock.calls.filter(([u]) => String(u).includes('limit=200')).length)
      .toBeGreaterThan(before),
    { timeout: 7000 },
  )
}, 10000)

test('old event without clip shows unavailable placeholder', async () => {
  vi.stubGlobal('fetch', stubFetch())
  renderPage()

  await screen.findByTestId('event-detail')
  await userEvent.click(screen.getByTestId('event-tab-clip'))
  expect(screen.getByTestId('event-clip-placeholder')).toHaveTextContent('Clip belum tersedia')
})
```

Filter `limit=200` hanya cocok dengan `refresh()` (`listEvents({ limit: 200, since })` → `/events?since=…&limit=200`); poll `useLiveEvents` memakai `limit=50`.

- [ ] **Step 2: Jalankan, pastikan gagal**

Run: `cd frontend && npx vitest run src/__tests__/events.test.tsx`
Expected: FAIL — placeholder berisi "Clip belum tersedia" pada tes event baru.

- [ ] **Step 3: Implementasi**

`frontend/src/features/events/EventsPage.tsx` — konstanta tingkat modul (dekat `DETAIL_TABS`):

```tsx
// Clip insiden baru ada ±15 s setelah orang terakhir terlihat (maks 120 s) — tunggu 3 menit.
const CLIP_PENDING_MS = 3 * 60_000
```

Tepat setelah `const isAttendance = selected?.type === 'attendance'`:

```tsx
  const clipPending =
    !!selected && !selected.clip_path && !isAttendance &&
    Date.now() - new Date(selected.ts_event).getTime() < CLIP_PENDING_MS

  // poll live hanya menambah event baru; clip_path yang datang belakangan perlu refetch
  useEffect(() => {
    if (!clipPending) return
    const timer = setInterval(refresh, 5000)
    return () => clearInterval(timer)
  }, [clipPending, refresh])
```

Placeholder:

```tsx
                  <div data-testid="event-clip-placeholder" className="ev-player ev-player--empty">
                    {t(clipPending ? 'events.clipRecording' : 'events.clipUnavailable')}
                  </div>
```

`frontend/src/app/i18n.tsx`:
- id: `'zones.clip': 'Rekam clip event',` dan tambahkan setelah `'events.clipUnavailable'`: `'events.clipRecording': 'Clip sedang direkam…',`
- en: `'zones.clip': 'Record event clip',` dan `'events.clipRecording': 'Clip is being recorded…',`

(Bila `TKey` diturunkan dari objek `id`, key baru harus ada di kedua bahasa agar `tsc -b` lulus.)

- [ ] **Step 4: Jalankan, pastikan lulus**

Run: `cd frontend && npx vitest run && npm run build && npm run lint`
Expected: 120 passed; build exit 0; lint = set rule+file 22 warning lama (simpan `npm run lint > /tmp/lint-new.txt`, bandingkan pasangan rule+file dengan output `npm run lint` di `main`).

- [ ] **Step 5: CHANGELOG + commit**

```markdown
- **Inbox**: tab Clip menampilkan "Clip sedang direkam…" untuk event keamanan < 3 menit tanpa
  `clip_path`, dan me-refresh daftar tiap 5 s sampai clip datang (poll live hanya menambah event baru,
  sehingga clip/snapshot yang datang belakangan dulu tak pernah tampil tanpa reload). Label zona
  "Rekam clip event" tanpa "(30 detik)". Frontend **<angka> passed**.
```

```bash
git add frontend/src/features/events/EventsPage.tsx frontend/src/app/i18n.tsx frontend/src/__tests__/events.test.tsx CHANGELOG.md
git commit -m "feat(events): placeholder clip sedang direkam + refresh sampai clip tersedia"
```

---

### Task 5: Dokumen + verifikasi suite penuh

**Files:**
- Modify: `ROADMAP.md` (tabel ringkasan baris 20–21, heading R5b ~baris 370, baris baru clip)
- Modify: `README.md:14` (diagram: clip dari mainstream ring) bila perlu
- Modify: `docs/plans/2026-09-08-isentinel-design.md` tidak diubah (dokumen requirement asli)
- Modify: `CHANGELOG.md`

**Interfaces:** —

- [ ] **Step 1: Rapikan ROADMAP**

Tabel ringkasan:
- Baris `| 5 | Hardening … | [~] plan detail siap | — | …` → status `[x] selesai`, selesai `2026-09-21`, bukti "lihat §Fase 5 (retensi + timer, soak 30+ stream, GPU probe) dan CHANGELOG [0.7.0]". Ambil angka bukti dari bagian `## Fase 5 — Hardening — **DONE (2026-09-21)**` (ROADMAP ~baris 289).
- Baris `| R5b | … | [~] lokal selesai, PENDING deploy + verifikasi lapangan | …` → `[x] deploy + tes lapangan`, selesai `2026-09-23`, bukti dari CHANGELOG `### R5b deploy + tes lapangan pertama + permintaan user (2026-09-23)`.
- Heading `## R5b — Attendance face-first — **lokal selesai, PENDING deploy + verifikasi lapangan**` → `**DEPLOY + tes lapangan (2026-09-23)**`.
- Baris baru sebelum `| E | Edge Jetson …`: `| CP | Event clip pre-buffer (ring mainstream, insiden per kamera) | [~] lokal selesai, PENDING deploy + verifikasi lapangan | — | vision/frontend suite hijau lokal; spec + plan 2026-09-24 | |`.

- [ ] **Step 2: README**

Bila README menjelaskan asal clip (cek `grep -n "clip" README.md DESIGN.md`), sesuaikan satu kalimat: clip event = segmen mainstream pre 10 s / post 15 s via ring ffmpeg di vision node, satu clip per insiden per kamera. Bila hanya diagram baris 14, biarkan.

- [ ] **Step 3: Suite penuh**

```bash
cd backend && .venv/bin/python -m pytest tests -q -m "not gpu" > /tmp/be.log 2>&1; grep -oE '[0-9]+ (passed|failed)[^|]*' /tmp/be.log | tail -1; cd ..
backend/.venv/bin/python -m pytest vision/tests -q -m "not gpu" | tail -1
cd frontend && npx vitest run | tail -3 && npm run build > /dev/null; echo build=$?; npm run lint | tail -2; cd ..
```

Expected: backend 339 passed (tidak berubah); vision semua passed, 3 deselected; frontend 120 passed; build 0; lint set lama.

- [ ] **Step 4: CHANGELOG + commit**

```markdown
- **Docs**: ROADMAP tabel ringkasan diperbarui (Fase 5 DONE 2026-09-21, R5b deploy + lapangan
  2026-09-23, baris CP clip pre-buffer). Suite: backend 339, vision <angka>, frontend <angka>,
  build 0, lint set lama.
```

```bash
git add ROADMAP.md README.md CHANGELOG.md
git commit -m "docs(clip): ROADMAP ringkasan + status clip pre-buffer"
```

---

### Task 6: Deploy + verifikasi lapangan (BUTUH IZIN USER per langkah bertanda ⚠)

**Files:**
- Create: `docs/evidence/clip-prebuffer-*.txt|png`
- Modify: `CHANGELOG.md`, `ROADMAP.md` (baris CP → `[x]`)

**Interfaces:** —

Tanyakan izin user sebelum setiap langkah ⚠. Unit vision di server = `vision-node.service` (cgroup `/sys/fs/cgroup/system.slice/vision-node.service`), venv `/home/gspe-ai3/vision-venv`, env di `/home/gspe-ai3/project_cv/I-Sentinel/.env` (tidak memuat `VISION_CLIP_*` → default kode dipakai).

- [ ] **Step 1 ⚠: Push + checkout di server**

```bash
git push -u origin feat/event-clip-prebuffer
ssh gspe-ai3 'cd /home/gspe-ai3/project_cv/I-Sentinel && git fetch && git checkout feat/event-clip-prebuffer && git pull'
```

Cek apakah vision-venv memakai install editable (`/home/gspe-ai3/vision-venv/bin/pip show isentinel-vision | grep -i location`); bila bukan editable, jalankan `pip install -e vision` di venv itu (⚠).

- [ ] **Step 2 ⚠: Restart vision node + frontend dev tidak perlu restart (Vite HMR)**

```bash
ssh gspe-ai3 'kill $(cat /sys/fs/cgroup/system.slice/vision-node.service/cgroup.procs); sleep 8; systemctl status vision-node --no-pager | head -5'
```

- [ ] **Step 3: Ukur ring (baca-saja)**

```bash
ssh gspe-ai3 'ls -la /dev/shm/isentinel/*/ | tail -8; du -sh /dev/shm/isentinel; ps -eo pid,pcpu,rss,cmd | grep "[f]fmpeg -nostdin" | cut -c1-160'
ssh gspe-ai3 'curl -s localhost:1984/api/streams | python3 -c "import json,sys; d=json.load(sys.stdin); print({k: len(v.get(\"consumers\") or []) for k,v in d.items() if k.endswith(\"_main\")})"'
```

Expected: hanya `cam357` punya dir ring (zona 6 aktif dengan clip; cek juga `camera.analyzers` cam 357 = `['attendance']` — bila mask ini membuat analyzer kosong, **tidak ada ring**: laporkan ke user dan minta izin mengaktifkan chip intrusion cam 357 di Deteksi & Model untuk uji). Segmen bergulir tiap ~2 s, jumlah file stabil (prune jalan), CPU ffmpeg < 1 %, `cam_357_main` 1 konsumen. Simpan output ke `docs/evidence/clip-prebuffer-ring.txt`.

- [ ] **Step 4: Uji lapangan bersama user**

Minta user berjalan masuk zona 6 cam 357 (satu orang, lalu dua orang beruntun < 15 s). Setelah ±30 s:

```bash
ssh gspe-ai3 'cd /home/gspe-ai3/project_cv/I-Sentinel-data/api; for f in $(find clips -name "*.mp4" -mmin -5); do ffprobe -v error -select_streams v:0 -show_entries stream=width,height -show_entries format=duration -of csv=p=0 $f | tr "\n" " "; echo $f; done'
```

Expected: 1920×1080; durasi ≈ 10 + lama di zona + 15 s; skenario dua orang → **satu** file, dua event di Inbox menunjuk `clip_path` yang sama; snapshot muncul di Inbox dalam beberapa detik; tab Clip menampilkan "Clip sedang direkam…" lalu video tanpa reload. Putar clip: orang terlihat **sebelum** masuk zona. Screenshot Inbox (login CDP, lihat `temp/prompt-next-features.txt`) ke `docs/evidence/clip-prebuffer-inbox.png`; output ffprobe ke `docs/evidence/clip-prebuffer-ffprobe.txt`.

Tambahan ekspektasi/instruksi verifikasi lapangan:

- Durasi klip ≈ 10 s + lama orang di zona + 15 s, dengan toleransi **−0 s sampai ≈ −4 s**: klip selalu berakhir di batas segmen, dan bila satu segmen berjalan > 3 s ekor post-roll bisa terpotong (lihat Deviasi 8). Jangan anggap itu bug tanpa memeriksa log.
- Periksa juga **akhir** klip (orang masih terlihat setelah keluar zona), bukan hanya bahwa orang terlihat sebelum masuk zona.
- Di Inbox, **pilih event terbaru** saat memeriksa snapshot/klip: auto-refresh 5 s hanya berjalan untuk event terpilih yang masih "sedang direkam".
- Bila satu klip terlihat terlalu pendek/berhenti di tengah gerakan pada batas segmen, catat sebagai temuan lapangan (kandidat perbaikan: concat demuxer, Deviasi 6).

- [ ] **Step 5 ⚠: Bersihkan outbox lama**

Tunjukkan dulu ke user: `ssh gspe-ai3 'du -sh /home/gspe-ai3/project_cv/I-Sentinel-data/vision/outbox; find /home/gspe-ai3/project_cv/I-Sentinel-data/vision/outbox -type f -mmin +60 | wc -l'`. Dengan izin: `find … -type f -mmin +60 -delete`. File ini sisa upload lama (sudah ada di `I-Sentinel-data/api`).

- [ ] **Step 6: CHANGELOG + ROADMAP + commit**

Bullet "Deploy + verifikasi lapangan" dengan angka nyata (CPU/RSS ffmpeg, ukuran tmpfs, durasi/resolusi clip, jumlah file untuk dua event, waktu snapshot muncul); ROADMAP baris CP → `[x] selesai`, tanggal, bukti `docs/evidence/clip-prebuffer-*`.

```bash
git add docs/evidence/clip-prebuffer-* CHANGELOG.md ROADMAP.md
git commit -m "docs(clip): evidence deploy + verifikasi lapangan clip pre-buffer"
```

Setelah user E2E OK: merge `--no-ff` ke `main` (butuh izin), server kembali ke `main`.
