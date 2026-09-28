# Behavior Idle Zone + Crowd Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dua behavior baru — Idle Zone (zona kosong ≥ T) dan Crowd (≥ N orang selama ≥ T) — dengan alert + pengingat berkala, jadwal zona yang bisa mengikuti satu Shift, dan perbaikan bug jadwal (ts monotonic dibaca sebagai epoch).

**Architecture:** Vision: helper bersama di `analyzers/base.py` (`wall_time`, `schedule_active`, `persons_in_zone`, pindahan `point_in_polygon`/`ground_point`), analyzer `idle_zone.py` + `crowd.py` di registry `ANALYZERS`, event tanpa track didukung `_merge_event`, snapshot menggambar banyak kotak / poligon zona. Backend: validator kind + `min_count`/`reminder_minutes`, jadwal `{"shift_id"}` diverifikasi di API zona dan di-resolve saat config push, shift PATCH → push ulang, DELETE → 409, caption idle/crowd/pengingat. Frontend: dua baris behavior + mode jadwal "Ikut shift".

**Tech Stack:** Python 3.11 (vision stdlib + OpenCV untuk snapshot), FastAPI/SQLAlchemy/Pydantic v2, pytest; React 19 + Carbon, Vitest.

**Spec:** `docs/superpowers/specs/2026-09-28-behavior-idle-crowd-design.md`

## Global Constraints

- Branch `feat/behavior-idle-crowd` (sudah ada, dari `main` @ `b9fdc55`; spec di `0800718`).
- **Tanpa AI attribution** di commit/kode/docs (`AGENTS.md` §9).
- Tanpa dependensi baru (jangan menambah `supervision`), tanpa migrasi DB. Vision tetap bisa dites tanpa GPU/RTSP.
- **Jangan** menjalankan `uv sync` / `uv lock` / membuat ulang venv (pernah merusak `backend/.venv`). Bila import `vision` gagal: `uv pip install --python backend/.venv/bin/python -e "vision[dev]"`.
- Pipeline wajah (`face_worker.py`) dan perilaku behavior lama (intrusion/loitering/running, kecuali perbaikan jadwal) tidak berubah.
- String UI lewat `i18n.tsx` (`id` + `en`); 390 px tanpa overflow.
- Setiap task: commit Conventional Commits + satu bullet di `CHANGELOG.md` bagian `### Behavior Idle Zone + Crowd (2026-09-28 – …)` (dibuat di Task 1, di atas `### Fix geometri zona (2026-09-28)`).
- Baseline `main` `b9fdc55`: backend **423**, vision **205** (3 deselected), frontend **140**, build 0, lint = set rule+file lama.
- **Eksekutor berhenti setelah `git push`.** Deploy (restart API + vision-node) dan uji lapangan di sesi perencana.

## Deviasi / temuan tambahan dari spec

1. **Event tanpa track**: `_merge_event`/`_PartialTrack`/`_make_event` (`node.py`) mewajibkan `payload.track_id` dan `bbox_norm` → dibuat toleran (`None`). Dedup key memakai `r<reminder>` bila tanpa track (dedup backend per bucket 10 s akan membuang pengingat bila kuncinya sama).
2. `persons_in_zone(tracks, polygon)` tanpa `frame_w/frame_h` (koordinat sudah ternormalisasi).
3. `point_in_polygon` + `ground_point` dipindah ke `base.py` (hindari import melingkar) dan di-*re-export* dari `intrusion.py` (dipakai `face_quality.py`).

## Review Focus

1. **Frame live ber-ts monotonic** → jadwal intrusion/idle/crowd benar. Tes: Task 1 `test_schedule_active_with_monotonic_frame_ts`, `test_intrusion_schedule_with_monotonic_ts`.
2. **Pengingat idle tidak terbuang sebagai duplikat** (dedup key unik per pengingat). Tes: Task 2 `test_merge_event_without_track`.
3. **Crowd berkedip** (jumlah turun ≤ 2 s) tidak me-reset; > 2 s me-reset. Tes: Task 2 `test_crowd_grace_and_reset`.
4. **Shift terhapus di luar API / shift_id tak ada** → simpan zona 422; push mengirim `null` + warning, node tidak crash. Tes: Task 4 `test_zone_schedule_unknown_shift_422`, `test_config_push_missing_shift_sends_null`.
5. **Idle di luar jadwal** tidak alert dan timer tidak berjalan; masuk jadwal → timer mulai dari situ. Tes: Task 2 `test_idle_respects_schedule`.

---

### Task 1: Helper bersama + perbaikan jadwal (ts monotonic)

**Files:**
- Modify: `vision/vision/analyzers/base.py`
- Modify: `vision/vision/analyzers/intrusion.py` (pakai helper; re-export `point_in_polygon`, `ground_point`)
- Modify: `vision/vision/node.py` (`_iso` memakai `wall_time`)
- Test: `vision/tests/test_analyzer_base.py` (baru), `vision/tests/test_intrusion.py`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Produces (`vision.analyzers.base`): `MONOTONIC_MAX = 1_700_000_000`, `wall_time(ts: float) -> float`, `schedule_active(schedule: dict | None, ts: float) -> bool`, `point_in_polygon(pt, poly) -> bool`, `ground_point(track) -> tuple[float, float]`, `persons_in_zone(tracks: list, polygon: list) -> list`.

- [ ] **Step 1: Tulis tes (gagal)**

`vision/tests/test_analyzer_base.py`:

```python
import time
from datetime import datetime

from vision.analyzers import base
from vision.analyzers.base import persons_in_zone, schedule_active, wall_time


class T:
    def __init__(self, tid, bbox):
        self.id = tid
        self.bbox = bbox


def test_wall_time_converts_monotonic_and_keeps_epoch():
    assert abs(wall_time(time.monotonic()) - time.time()) < 1
    epoch = datetime(2026, 9, 28, 10, 0).timestamp()
    assert wall_time(epoch) == epoch


def test_schedule_active_with_monotonic_frame_ts(monkeypatch):
    """Regresi: frame live membawa ts monotonic; dulu dibaca sebagai tanggal 1970."""
    monday_3am = datetime(2024, 1, 15, 3, 0).timestamp()
    monkeypatch.setattr(base.time, "time", lambda: monday_3am)
    monkeypatch.setattr(base.time, "monotonic", lambda: 5000.0)
    assert schedule_active({"days": [1], "start": "02:00", "end": "04:00"}, 5000.0) is True
    assert schedule_active({"days": [1], "start": "04:00", "end": "05:00"}, 5000.0) is False
    assert schedule_active({"days": [2], "start": "00:00", "end": "23:59"}, 5000.0) is False
    assert schedule_active(None, 5000.0) is True


def test_persons_in_zone_uses_ground_point():
    square = [[0.0, 0.0], [0.5, 0.0], [0.5, 0.5], [0.0, 0.5]]
    inside = T(1, (0.1, 0.1, 0.2, 0.4))    # kaki (0.15, 0.4) di dalam
    feet_out = T(2, (0.1, 0.3, 0.2, 0.7))  # badan menyentuh, kaki (0.15, 0.7) di luar
    far = T(3, (0.7, 0.7, 0.8, 0.9))
    assert [t.id for t in persons_in_zone([inside, feet_out, far], square)] == [1]
```

Tambahkan di `vision/tests/test_intrusion.py`:

```python
def test_intrusion_schedule_with_monotonic_ts(monkeypatch):
    from vision.analyzers import base
    monkeypatch.setattr(base.time, "time", lambda: datetime(2024, 1, 15, 3, 0).timestamp())
    monkeypatch.setattr(base.time, "monotonic", lambda: 777.0)
    inside = IntrusionAnalyzer(zone(schedule={"days": [1], "start": "02:00", "end": "04:00"}))
    outside = IntrusionAnalyzer(zone(schedule={"days": [1], "start": "04:00", "end": "05:00"}))
    assert len(inside.on_frame(777.0, one_track(1, (0.5, 0.5)), 640, 480)) == 1
    assert outside.on_frame(777.0, one_track(1, (0.5, 0.5)), 640, 480) == []
```

- [ ] **Step 2: Jalankan, pastikan gagal**

Run: `backend/.venv/bin/python -m pytest vision/tests/test_analyzer_base.py vision/tests/test_intrusion.py -q`
Expected: FAIL — `ImportError: cannot import name 'persons_in_zone'`.

- [ ] **Step 3: Implementasi**

`vision/vision/analyzers/base.py` — ganti isi:

```python
"""Analyzer base + helper zona bersama (titik kaki, point-in-polygon, jadwal, jam dinding)."""
from __future__ import annotations

import time
from datetime import datetime

MONOTONIC_MAX = 1_700_000_000  # ts di bawah ini = detik sejak boot (monotonic), bukan epoch


class Analyzer:
    def on_frame(self, ts: float, tracks: list, frame_w: int, frame_h: int) -> list[dict]:
        """Return partial event dicts: {"zone_id", "type", "severity", "payload"}."""
        raise NotImplementedError


def wall_time(ts: float) -> float:
    """Frame live membawa ts monotonic (pacing); jadwal & label waktu butuh epoch."""
    return ts + (time.time() - time.monotonic()) if ts < MONOTONIC_MAX else ts


def schedule_active(schedule: dict | None, ts: float) -> bool:
    """{"days": [ISO 1-7], "start": "HH:MM", "end": "HH:MM"}; None = 24/7. Tanpa lintas tengah malam."""
    if not schedule:
        return True
    local = datetime.fromtimestamp(wall_time(ts))
    if local.isoweekday() not in schedule.get("days", []):
        return False
    return schedule["start"] <= local.strftime("%H:%M") <= schedule["end"]


def point_in_polygon(pt: tuple[float, float], poly: list) -> bool:
    """Ray casting, handles concave polygons. poly: [[x, y], ...] normalized."""
    x, y = pt
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xin = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < xin:
                inside = not inside
    return inside


def ground_point(track) -> tuple[float, float]:
    """Titik pijak track: tengah sisi bawah bbox (ternormalisasi 0-1).

    Zona digambar di atas LANTAI; semua analyzer zona memakai titik ini supaya
    "di dalam zona" berarti sama di seluruh sistem.
    """
    x1, _, x2, y2 = track.bbox
    return ((x1 + x2) / 2, y2)


def persons_in_zone(tracks: list, polygon: list) -> list:
    """Track yang titik kakinya di dalam poligon zona."""
    return [t for t in tracks if point_in_polygon(ground_point(t), polygon)]
```

`vision/vision/analyzers/intrusion.py`:
- Hapus definisi `point_in_polygon`, `ground_point`, `_schedule_active` dan `from datetime import datetime`.
- Import: `from .base import Analyzer, ground_point, point_in_polygon, schedule_active  # noqa: F401 (re-export)`.
- Di `on_frame`: `if not schedule_active(self.schedule, ts):`.
- `grep -rn "_schedule_active" vision/` harus kosong setelah ini (sesuaikan tes yang memakainya bila ada).

`vision/vision/node.py` `_iso`:

```python
def _iso(ts: float) -> str:
    # Terima ts monotonic (pipeline) atau epoch; wall_time menormalkan ke epoch.
    return datetime.fromtimestamp(wall_time(ts), tz=timezone.utc).isoformat()
```

dengan `from .analyzers.base import wall_time` di kepala file.

- [ ] **Step 4: Jalankan, pastikan lulus**

Run: `backend/.venv/bin/python -m pytest vision/tests -q -m "not gpu"`
Expected: semua passed (205 + 4), 3 deselected.

- [ ] **Step 5: CHANGELOG + commit**

Di atas `### Fix geometri zona (2026-09-28)`:

```markdown
### Behavior Idle Zone + Crowd (2026-09-28 – …)

- **Fix jadwal zona**: frame live membawa ts monotonic, tetapi `_schedule_active` membacanya sebagai epoch (hari/jam
  dari 1970 + uptime) → jadwal intrusion salah di produksi (belum berdampak: 0 zona berjadwal). Helper bersama
  `analyzers/base.py`: `wall_time`, `schedule_active`, `persons_in_zone` (+ `point_in_polygon`/`ground_point` dipindah,
  tetap di-re-export dari `intrusion`). Vision **<angka> passed**.
```

```bash
git add vision/vision/analyzers/base.py vision/vision/analyzers/intrusion.py vision/vision/node.py vision/tests/test_analyzer_base.py vision/tests/test_intrusion.py CHANGELOG.md
git commit -m "fix(vision): jadwal zona memakai jam dinding (ts frame monotonic) + helper zona bersama"
```

---

### Task 2: Analyzer Idle Zone + Crowd + wiring + event tanpa track

**Files:**
- Create: `vision/vision/analyzers/idle_zone.py`, `vision/vision/analyzers/crowd.py`
- Modify: `vision/vision/analyzers/__init__.py` (registry)
- Modify: `vision/vision/node.py` (`_make_analyzers`, `_make_event`, `_merge_event`, `_PartialTrack`)
- Test: `vision/tests/test_idle_crowd.py` (baru)
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: `schedule_active`, `persons_in_zone` (Task 1).
- Produces: `IdleZoneAnalyzer(zone: dict)`, `CrowdAnalyzer(zone: dict)`; `ANALYZERS["idle_zone"]`, `ANALYZERS["crowd"]`; `crowd.GRACE_S = 2.0`.
  - Partial idle: `{"zone_id", "type": "idle_zone", "severity", "payload": {"zone_name", "track_id": None, "bbox_norm": None, "idle_s": int, "reminder": int, "zone_polygon": [[x,y],…]}}`.
  - Partial crowd: `{… "type": "crowd", "payload": {"zone_name", "track_id": None, "bbox_norm": None, "count": int, "min_count": int, "duration_s": int, "reminder": int, "bboxes": [[x1,y1,x2,y2],…]}}`.
  - Spec zona yang diteruskan node: `trigger_seconds`, `reminder_minutes`, `min_count` (dari item behavior).

- [ ] **Step 1: Tulis tes (gagal)**

`vision/tests/test_idle_crowd.py`:

```python
from datetime import datetime

from vision.analyzers import ANALYZERS
from vision.analyzers.crowd import CrowdAnalyzer
from vision.analyzers.idle_zone import IdleZoneAnalyzer

SQUARE = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]
T0 = datetime(2026, 9, 28, 10, 0).timestamp()  # Senin 10:00 (epoch → wall_time apa adanya)


class T:
    def __init__(self, tid, x=0.5):
        self.id = tid
        self.bbox = (x - 0.05, 0.3, x + 0.05, 0.6)  # kaki (x, 0.6) di dalam SQUARE


def zone(**kw):
    z = {"id": 3, "name": "Pos", "severity": "warning", "polygon": SQUARE, "schedule": None,
         "trigger_seconds": 60, "reminder_minutes": 2}
    z.update(kw)
    return z


def run(az, frames):
    """frames: [(detik_setelah_T0, tracks)] → daftar (detik, type, reminder)."""
    out = []
    for sec, tracks in frames:
        for ev in az.on_frame(T0 + sec, tracks, 640, 480):
            out.append((sec, ev["type"], ev["payload"]["reminder"]))
    return out


def test_registry_has_new_kinds():
    assert ANALYZERS["idle_zone"] is IdleZoneAnalyzer and ANALYZERS["crowd"] is CrowdAnalyzer


def test_idle_alerts_after_trigger_then_reminders_and_rearms():
    az = IdleZoneAnalyzer(zone())
    frames = [(s, []) for s in range(0, 301, 2)]  # kosong 0..300 s
    assert run(az, frames) == [(60, "idle_zone", 0), (180, "idle_zone", 1), (300, "idle_zone", 2)]
    assert run(az, [(302, [T(1)])]) == []            # orang masuk → siaga lagi
    assert run(az, [(s, []) for s in range(304, 366, 2)]) == [(364, "idle_zone", 0)]


def test_idle_payload_and_no_reminder_when_zero():
    az = IdleZoneAnalyzer(zone(reminder_minutes=0))
    evs = [ev for s in range(0, 400, 2) for ev in az.on_frame(T0 + s, [], 640, 480)]
    assert len(evs) == 1
    p = evs[0]["payload"]
    assert p["idle_s"] == 60 and p["track_id"] is None and p["bbox_norm"] is None
    assert p["zone_polygon"] == [list(pt) for pt in SQUARE] and evs[0]["zone_id"] == 3


def test_idle_respects_schedule():
    az = IdleZoneAnalyzer(zone(schedule={"days": [1], "start": "10:01", "end": "11:00"}))
    # 10:00–10:01 di luar jadwal → timer belum berjalan; mulai 10:01 → alert 10:02
    assert run(az, [(s, []) for s in range(0, 130, 2)]) == [(120, "idle_zone", 0)]


def test_crowd_alert_payload_and_reminder():
    az = CrowdAnalyzer(zone(min_count=3, trigger_seconds=10, reminder_minutes=1))
    people = [T(i, 0.2 + 0.2 * i) for i in range(3)]
    got = []
    for s in range(0, 71, 2):
        got += [(s, ev) for ev in az.on_frame(T0 + s, people, 640, 480)]
    assert [(s, e["payload"]["reminder"]) for s, e in got] == [(10, 0), (70, 1)]
    p = got[0][1]["payload"]
    assert (p["count"], p["min_count"], p["duration_s"], p["track_id"]) == (3, 3, 10, None)
    assert len(p["bboxes"]) == 3


def test_crowd_below_threshold_never_alerts():
    az = CrowdAnalyzer(zone(min_count=3, trigger_seconds=10))
    assert run(az, [(s, [T(1), T(2)]) for s in range(0, 60, 2)]) == []


def test_crowd_grace_and_reset():
    az = CrowdAnalyzer(zone(min_count=2, trigger_seconds=10, reminder_minutes=0))
    two, one = [T(1, 0.3), T(2, 0.7)], [T(1, 0.3)]
    # 0..6 dua orang, 8 satu orang (≤ 2 s → toleransi), 10 dua orang → alert tepat 10 s
    frames = [(0, two), (2, two), (4, two), (6, two), (8, one), (10, two)]
    assert run(az, frames) == [(10, "crowd", 0)]
    az = CrowdAnalyzer(zone(min_count=2, trigger_seconds=10, reminder_minutes=0))
    # jumlah turun 4 s (> 2 s) → reset; hitung ulang dari 12
    frames = [(0, two), (2, two), (4, one), (6, one), (8, one), (10, two), (12, two), (20, two), (22, two)]
    assert run(az, frames) == [(20, "crowd", 0)]


def test_merge_event_without_track():
    from vision.node import _merge_event
    partial = {"zone_id": 3, "type": "idle_zone", "severity": "warning",
               "payload": {"track_id": None, "bbox_norm": None, "idle_s": 60, "reminder": 2}}
    ev = _merge_event(9, "node", partial, T0)
    assert ev["payload"]["track_id"] is None and ev["payload"]["bbox_norm"] is None
    assert ev["dedup_key"].startswith("9:idle_zone:r2:")


def test_make_analyzers_builds_new_kinds_with_params():
    from vision.config import NodeSettings
    from vision.node import VisionNode
    z = {"id": 5, "name": "Z", "type": "behavior", "polygon": SQUARE, "active": True, "clip": True,
         "behaviors": [{"kind": "idle_zone", "trigger_seconds": 300, "reminder_minutes": 15, "clip": False},
                       {"kind": "crowd", "trigger_seconds": 30, "min_count": 7, "reminder_minutes": 0}]}
    cam = {"camera_id": 1, "source_url": "test://1", "zones": [z]}
    node = VisionNode(NodeSettings(face_embed=False), transport=object(), source_factory=lambda c: None)
    azs = node._make_analyzers(node._cameras_from_config({"cameras": [cam]})[0])
    idle, crowd = azs
    assert (type(idle).__name__, idle.trigger, idle.reminder_s, idle.media["clip"]) == ("IdleZoneAnalyzer", 300.0, 900.0, False)
    assert (type(crowd).__name__, crowd.min_count, crowd.trigger, crowd.reminder_s) == ("CrowdAnalyzer", 7, 30.0, 0.0)
```

- [ ] **Step 2: Jalankan, pastikan gagal**

Run: `backend/.venv/bin/python -m pytest vision/tests/test_idle_crowd.py -q`
Expected: FAIL — modul `idle_zone` tidak ada.

- [ ] **Step 3: Implementasi**

`vision/vision/analyzers/idle_zone.py`:

```python
"""Idle Zone: alert bila zona tanpa orang ≥ trigger_seconds (dalam jadwal), lalu pengingat berkala."""
from __future__ import annotations

from .base import Analyzer, persons_in_zone, schedule_active


class IdleZoneAnalyzer(Analyzer):
    def __init__(self, zone: dict):
        self.zone_id = zone["id"]
        self.zone_name = zone.get("name", "")
        self.severity = zone.get("severity", "warning")
        self.schedule = zone.get("schedule")
        self.polygon = [list(p) for p in zone["polygon"]]
        self.trigger = float(zone.get("trigger_seconds", 0) or 0)
        self.reminder_s = float(zone.get("reminder_minutes", 0) or 0) * 60
        self._empty_since: float | None = None
        self._sent = 0  # event terkirim pada episode kosong ini

    def on_frame(self, ts: float, tracks: list, frame_w: int, frame_h: int) -> list[dict]:
        if not schedule_active(self.schedule, ts) or persons_in_zone(tracks, self.polygon):
            self._empty_since, self._sent = None, 0  # di luar jadwal / ada orang → siaga
            return []
        if self._empty_since is None:
            self._empty_since = ts
        if self._sent and not self.reminder_s:
            return []
        idle = ts - self._empty_since
        if idle < self.trigger + self._sent * self.reminder_s:
            return []
        self._sent += 1
        return [{
            "zone_id": self.zone_id,
            "type": "idle_zone",
            "severity": self.severity,
            "payload": {"zone_name": self.zone_name, "track_id": None, "bbox_norm": None,
                        "idle_s": int(idle), "reminder": self._sent - 1,
                        "zone_polygon": self.polygon},
        }]
```

`vision/vision/analyzers/crowd.py`:

```python
"""Crowd: alert bila ≥ min_count orang di zona selama ≥ trigger_seconds, lalu pengingat berkala."""
from __future__ import annotations

from .base import Analyzer, persons_in_zone, schedule_active

GRACE_S = 2.0  # jumlah turun sesaat (track berkedip/oklusi) tidak me-reset


class CrowdAnalyzer(Analyzer):
    def __init__(self, zone: dict):
        self.zone_id = zone["id"]
        self.zone_name = zone.get("name", "")
        self.severity = zone.get("severity", "warning")
        self.schedule = zone.get("schedule")
        self.polygon = [list(p) for p in zone["polygon"]]
        self.min_count = max(1, int(zone.get("min_count", 5) or 5))
        self.trigger = float(zone.get("trigger_seconds", 0) or 0)
        self.reminder_s = float(zone.get("reminder_minutes", 0) or 0) * 60
        self._reset()

    def _reset(self) -> None:
        self._since: float | None = None
        self._below_since: float | None = None
        self._sent = 0

    def on_frame(self, ts: float, tracks: list, frame_w: int, frame_h: int) -> list[dict]:
        if not schedule_active(self.schedule, ts):
            self._reset()
            return []
        people = persons_in_zone(tracks, self.polygon)
        if len(people) < self.min_count:
            if self._since is not None:
                self._below_since = self._below_since if self._below_since is not None else ts
                if ts - self._below_since > GRACE_S:
                    self._reset()
            return []
        self._below_since = None
        if self._since is None:
            self._since = ts
        if self._sent and not self.reminder_s:
            return []
        duration = ts - self._since
        if duration < self.trigger + self._sent * self.reminder_s:
            return []
        self._sent += 1
        return [{
            "zone_id": self.zone_id,
            "type": "crowd",
            "severity": self.severity,
            "payload": {"zone_name": self.zone_name, "track_id": None, "bbox_norm": None,
                        "count": len(people), "min_count": self.min_count,
                        "duration_s": int(duration), "reminder": self._sent - 1,
                        "bboxes": [list(t.bbox) for t in people]},
        }]
```

`vision/vision/analyzers/__init__.py` — import kedua kelas, tambahkan `"idle_zone": IdleZoneAnalyzer, "crowd": CrowdAnalyzer` ke `ANALYZERS`, dan keduanya ke `__all__`.

`vision/vision/node.py`:
- `_make_event`: `"bbox_norm": list(track.bbox) if track.bbox is not None else None`.
- `_PartialTrack.__init__`: `self.id = partial["payload"].get("track_id")`, `self.bbox = partial["payload"].get("bbox_norm")`.
- `_merge_event`, ganti baris `dedup_key`:

```python
    track = partial["payload"].get("track_id")
    # event zona tanpa orang (idle/crowd): kunci per pengingat, supaya dedup backend tidak membuangnya
    key = track if track is not None else f"r{partial['payload'].get('reminder', 0)}"
    base["dedup_key"] = f"{camera_id}:{partial['type']}:{key}:{int(ts // DEDUP_BUCKET_S)}"
```

- `_make_analyzers`: setelah `spec["trigger_seconds"] = …` tambahkan
  `spec["reminder_minutes"] = b.get("reminder_minutes", 0) or 0` dan `spec["min_count"] = b.get("min_count", 5)`; lalu cabang:

```python
                elif kind in ("idle_zone", "crowd"):
                    out.append(self._with_media(ANALYZERS[kind](spec), media))
```

- [ ] **Step 4: Jalankan, pastikan lulus**

Run: `backend/.venv/bin/python -m pytest vision/tests -q -m "not gpu"`
Expected: semua passed.

- [ ] **Step 5: CHANGELOG + commit**

```markdown
- **Analyzer Idle Zone + Crowd**: idle = zona kosong ≥ `trigger_seconds` (dalam jadwal) → event + pengingat tiap
  `reminder_minutes` (0 = sekali), siaga lagi saat ada orang; crowd = ≥ `min_count` orang ≥ `trigger_seconds`,
  toleransi turun sesaat 2 s, pengingat sama. Event tanpa track didukung node (`bbox_norm` None, dedup key per
  pengingat `r<n>`). Vision **<angka> passed**.
```

```bash
git add vision/vision/analyzers vision/vision/node.py vision/tests/test_idle_crowd.py CHANGELOG.md
git commit -m "feat(vision): analyzer Idle Zone + Crowd dengan pengingat berkala"
```

---

### Task 3: Snapshot — banyak kotak (crowd) dan poligon zona (idle)

**Files:**
- Modify: `vision/vision/recorder.py` (`TYPE_LABEL`, `_draw_track_box`)
- Test: `vision/tests/test_recorder.py`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Tulis tes (gagal)** — tambahkan di `vision/tests/test_recorder.py`:

```python
def test_snapshot_crowd_boxes_and_idle_polygon(tmp_path, monkeypatch):
    import cv2
    labels, rects, polys = [], [], []
    real_put, real_rect, real_poly = cv2.putText, cv2.rectangle, cv2.polylines
    monkeypatch.setattr(cv2, "putText", lambda img, text, *a, **k: labels.append(text) or real_put(img, text, *a, **k))
    monkeypatch.setattr(cv2, "rectangle", lambda img, *a, **k: rects.append(a[:2]) or real_rect(img, *a, **k))
    monkeypatch.setattr(cv2, "polylines", lambda img, pts, *a, **k: polys.append(pts) or real_poly(img, pts, *a, **k))
    rec = Recorder(1, make_cfg(tmp_path), autostart=False)
    ok, buf = cv2.imencode(".jpg", np.full((480, 640, 3), 255, np.uint8))
    crowd = {"type": "crowd", "severity": "warning",
             "payload": {"count": 3, "bboxes": [[0.1, 0.1, 0.2, 0.4], [0.3, 0.1, 0.4, 0.4], [0.5, 0.1, 0.6, 0.4]]}}
    assert rec._draw_track_box(buf.tobytes(), crowd) is not None
    assert len(rects) == 3 and labels == ["CROWD (3)"]
    idle = {"type": "idle_zone", "severity": "warning",
            "payload": {"zone_polygon": [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]]}}
    assert rec._draw_track_box(buf.tobytes(), idle) is not None
    assert len(polys) == 1 and labels[-1] == "IDLE ZONE"
    rec.close()
```

- [ ] **Step 2: Jalankan, pastikan gagal** — `backend/.venv/bin/python -m pytest vision/tests/test_recorder.py -q -k crowd_boxes` → FAIL (tanpa `bbox_norm` fungsi mengembalikan None).

- [ ] **Step 3: Implementasi** — `recorder.py`:
- `TYPE_LABEL` tambah `"idle_zone": "IDLE ZONE", "crowd": "CROWD"`.
- Ganti isi `_draw_track_box` setelah `payload = …`:

```python
        boxes = payload.get("bboxes") or []
        if not boxes and payload.get("bbox_norm") and len(payload["bbox_norm"]) == 4:
            boxes = [payload["bbox_norm"]]
        polygon = payload.get("zone_polygon")
        if not boxes and not polygon:
            return None
        try:
            import cv2
            import numpy as np
            img = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                return None
            h, w = img.shape[:2]
            color = self._TRACK_COLORS.get(event.get("severity", "info"), (0, 200, 0))
            label = self.TYPE_LABEL.get(event.get("type"), str(event.get("type") or "").upper())
            if event.get("type") == "crowd":
                label = f"{label} ({payload.get('count', len(boxes))})"
            anchor = None
            if polygon:
                pts = np.array([[int(x * w), int(y * h)] for x, y in polygon], np.int32)
                cv2.polylines(img, [pts], True, color, 2)
                anchor = (int(pts[0][0]), int(pts[0][1]))
            for i, box in enumerate(boxes):
                x1, y1, x2, y2 = [int(v * s) for v, s in zip(box, (w, h, w, h))]
                cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
                if i == 0:
                    anchor = (x1, y1)
            cv2.putText(img, label, (anchor[0], max(16, anchor[1] - 6)), cv2.FONT_HERSHEY_SIMPLEX,
                        0.6, color, 2, cv2.LINE_AA)
            ok, buf = cv2.imencode(".jpg", img)
            return buf.tobytes() if ok else None
        except Exception:
            log.warning("track box draw gagal — snapshot polos", exc_info=True)
            return None
```

(docstring: "Kotak orang (satu atau banyak) dan/atau poligon zona + label jenis kejadian".)

- [ ] **Step 4: Jalankan, pastikan lulus** — vision suite penuh, semua passed (tes label lama tetap lulus).

- [ ] **Step 5: CHANGELOG + commit**

```markdown
- **Snapshot idle/crowd**: crowd menggambar semua kotak orang + label `CROWD (n)`; idle menggambar garis poligon zona
  + label `IDLE ZONE`. Vision **<angka> passed**.
```

```bash
git add vision/vision/recorder.py vision/tests/test_recorder.py CHANGELOG.md
git commit -m "feat(vision): snapshot idle (poligon zona) dan crowd (semua kotak)"
```

---

### Task 4: Backend — validasi, jadwal ikut shift, push, shift API

**Files:**
- Modify: `backend/app/schemas/zone.py` (`VALID_BEHAVIOR_KINDS`, `_validate_behaviors`, `_validate_schedule`)
- Modify: `backend/app/api/zones.py` (cek shift ada)
- Modify: `backend/app/services/config_push.py` (resolve jadwal)
- Modify: `backend/app/api/shifts.py` (PATCH → push; DELETE → 409 bila dipakai zona)
- Test: `backend/tests/test_zones_api.py`, `backend/tests/test_config_push.py`, `backend/tests/test_employees_api.py`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Produces: `config_push.resolve_schedule(db, schedule) -> dict | None`; `shifts._zones_using(db, shift_id) -> list[Zone]`.

- [ ] **Step 1: Tulis tes (gagal)**

`backend/tests/test_zones_api.py` — tambah:

```python
def _behavior_zone(client, h, cam_id, behaviors, schedule=None):
    return client.post("/api/v1/zones", json={**VALID, "camera_id": cam_id, "type": "behavior",
                                              "behaviors": behaviors, "schedule": schedule}, headers=h)


def test_idle_and_crowd_kinds_validation(client):
    h = _admin_headers(client)
    cam = _camera(client, h)
    ok = _behavior_zone(client, h, cam["id"], [
        {"kind": "idle_zone", "trigger_seconds": 300, "reminder_minutes": 15},
        {"kind": "crowd", "trigger_seconds": 30, "min_count": 5, "reminder_minutes": 0}])
    assert ok.status_code == 200
    for bad in ([{"kind": "crowd", "trigger_seconds": 30}],                       # min_count wajib
                [{"kind": "crowd", "trigger_seconds": 30, "min_count": 0}],
                [{"kind": "idle_zone", "trigger_seconds": 60, "reminder_minutes": -1}],
                [{"kind": "idle_zone", "trigger_seconds": 60, "reminder_minutes": "15"}]):
        assert _behavior_zone(client, h, cam["id"], bad).status_code == 422


def test_zone_schedule_follows_shift(client):
    h = _admin_headers(client)
    cam = _camera(client, h)
    shift = client.post("/api/v1/shifts", json={"name": "Pagi", "start_time": "08:00", "end_time": "17:00"},
                        headers=h).json()
    r = _behavior_zone(client, h, cam["id"], [{"kind": "idle_zone", "trigger_seconds": 60}],
                       schedule={"shift_id": shift["id"]})
    assert r.status_code == 200 and r.json()["schedule"] == {"shift_id": shift["id"]}


def test_zone_schedule_unknown_shift_422(client):
    h = _admin_headers(client)
    cam = _camera(client, h)
    r = _behavior_zone(client, h, cam["id"], [], schedule={"shift_id": 999})
    assert r.status_code == 422 and "shift" in str(r.json()["detail"])
    assert _behavior_zone(client, h, cam["id"], [], schedule={"shift_id": "x"}).status_code == 422
```

`backend/tests/test_config_push.py` — tambah:

```python
def test_config_push_resolves_shift_schedule(db):
    from app.models.shift import Shift
    n = _node(db)
    cam = _cam(db, n.id)
    sh = Shift(name="Pagi", start_time="08:00", end_time="17:00", workdays=[1, 2, 3, 4, 5]); db.add(sh); db.commit()
    db.add(Zone(camera_id=cam.id, name="Pos", type="behavior", polygon=[[0, 0], [1, 0], [1, 1]],
                behaviors=[{"kind": "idle_zone", "trigger_seconds": 60}], schedule={"shift_id": sh.id}))
    db.commit()
    zone = config_push.build_node_config(db, n)["cameras"][0]["zones"][0]
    assert zone["schedule"] == {"days": [1, 2, 3, 4, 5], "start": "08:00", "end": "17:00"}


def test_config_push_missing_shift_sends_null(db, caplog):
    n = _node(db)
    cam = _cam(db, n.id)
    db.add(Zone(camera_id=cam.id, name="Pos", type="behavior", polygon=[[0, 0], [1, 0], [1, 1]],
                behaviors=[], schedule={"shift_id": 424242}))
    db.commit()
    assert config_push.build_node_config(db, n)["cameras"][0]["zones"][0]["schedule"] is None
    assert "424242" in caplog.text
```

`backend/tests/test_employees_api.py` — tambah:

```python
def test_shift_used_by_zone_blocks_delete_and_patch_repushes(client, monkeypatch):
    import app.api.shifts as shifts_api
    h = _admin_headers(client)
    cam = _camera(client, h)
    shift = _shift(client, h).json()
    client.post("/api/v1/zones", json={"camera_id": cam["id"], "name": "Pos Satpam", "type": "behavior",
                                       "polygon": [[0.1, 0.1], [0.5, 0.1], [0.5, 0.5]],
                                       "behaviors": [], "schedule": {"shift_id": shift["id"]}}, headers=h)
    pushed = []
    monkeypatch.setattr(shifts_api, "publish_node_config_for_camera", lambda db, cid: pushed.append(cid) or True)
    assert client.patch(f"/api/v1/shifts/{shift['id']}", json={"end_time": "18:00"}, headers=h).status_code == 200
    assert pushed == [cam["id"]]
    r = client.delete(f"/api/v1/shifts/{shift['id']}", headers=h)
    assert r.status_code == 409 and "Pos Satpam" in r.json()["detail"]
```

(Helper `_admin_headers`, `_camera`, `_shift`, `VALID` sudah ada di file tes masing-masing; `_node`/`_cam` di `test_config_push.py`.)

- [ ] **Step 2: Jalankan, pastikan gagal** — `cd backend && .venv/bin/python -m pytest tests/test_zones_api.py tests/test_config_push.py tests/test_employees_api.py -q` → FAIL.

- [ ] **Step 3: Implementasi**

`backend/app/schemas/zone.py`:
- `VALID_BEHAVIOR_KINDS = {"intrusion", "loitering", "running", "attendance", "idle_zone", "crowd"}`.
- Di loop `_validate_behaviors`, setelah validasi flag:

```python
        min_count = b.get("min_count")
        if b.get("kind") == "crowd" and min_count is None:
            raise ValueError("crowd requires min_count")
        if min_count is not None and (not isinstance(min_count, int) or isinstance(min_count, bool) or min_count < 1):
            raise ValueError("min_count must be an int >= 1")
        reminder = b.get("reminder_minutes")
        if reminder is not None and (not isinstance(reminder, int) or isinstance(reminder, bool) or reminder < 0):
            raise ValueError("reminder_minutes must be an int >= 0")
```

- `_validate_schedule`, di awal setelah `if v is None: return v`:

```python
    if isinstance(v, dict) and set(v) == {"shift_id"}:
        sid = v["shift_id"]
        if not isinstance(sid, int) or isinstance(sid, bool) or sid < 1:
            raise ValueError("schedule.shift_id must be a positive int")
        return v
```

  dan pesan error format manual menyebut juga `or {"shift_id": N}`.

`backend/app/api/zones.py` — helper + panggilan di `create_zone` (sebelum `db.add`) dan `update_zone` (setelah loop `setattr`, sebelum commit):

```python
from app.models.shift import Shift


def _check_shift(db: Session, zone: Zone) -> None:
    sched = zone.schedule
    if isinstance(sched, dict) and "shift_id" in sched and db.get(Shift, sched["shift_id"]) is None:
        db.rollback()
        raise HTTPException(422, "schedule shift not found")
```

`backend/app/services/config_push.py`:

```python
from app.models.shift import Shift


def resolve_schedule(db: Session, schedule: dict | None) -> dict | None:
    """Jadwal zona `{"shift_id": N}` → `{days, start, end}` dari Shift (vision tidak tahu shift)."""
    if isinstance(schedule, dict) and "shift_id" in schedule:
        shift = db.get(Shift, schedule["shift_id"])
        if shift is None:
            logger.warning("zone schedule refers to missing shift %s; sent as 24/7", schedule["shift_id"])
            return None
        return {"days": list(shift.workdays or []), "start": shift.start_time, "end": shift.end_time}
    return schedule
```

  dan di pembentukan zona: `"schedule": resolve_schedule(db, z.schedule),`.

`backend/app/api/shifts.py`:

```python
import logging

from app.models.zone import Zone
from app.services.config_push import publish_node_config_for_camera

logger = logging.getLogger(__name__)


def _zones_using(db: Session, shift_id: int) -> list[Zone]:
    # ponytail: filter JSON di Python (jumlah zona kecil); pindah ke query JSON bila zona ribuan
    return [z for z in db.query(Zone).all()
            if isinstance(z.schedule, dict) and z.schedule.get("shift_id") == shift_id]
```

- `update_shift`: setelah `db.refresh(shift)`:

```python
    for camera_id in sorted({z.camera_id for z in _zones_using(db, shift_id)}):
        try:
            publish_node_config_for_camera(db, camera_id)
        except Exception:
            logger.warning("config push after shift change failed (camera %s)", camera_id, exc_info=True)
```

- `delete_shift`: setelah cek karyawan:

```python
    zones = _zones_using(db, shift_id)
    if zones:
        raise HTTPException(409, "shift in use by zones: " + ", ".join(z.name for z in zones))
```

  (Bila import melingkar muncul, pindahkan `from app.services.config_push import …` ke dalam fungsi dan monkeypatch di tes ke `app.services.config_push.publish_node_config_for_camera`; catat deviasi.)

- [ ] **Step 4: Jalankan, pastikan lulus** — backend suite penuh.

- [ ] **Step 5: CHANGELOG + commit**

```markdown
- **Backend idle/crowd + jadwal ikut shift**: kind `idle_zone`/`crowd` (crowd wajib `min_count` ≥ 1,
  `reminder_minutes` ≥ 0); `schedule` boleh `{"shift_id": N}` (shift tak ada → 422), di-resolve ke
  `{days, start, end}` saat config push (shift hilang → `null` + warning); ubah shift → push ulang kamera terkait;
  hapus shift yang dipakai zona → 409 dengan nama zona. Backend **<angka> passed**.
```

```bash
git add backend/app/schemas/zone.py backend/app/api/zones.py backend/app/services/config_push.py backend/app/api/shifts.py backend/tests/test_zones_api.py backend/tests/test_config_push.py backend/tests/test_employees_api.py CHANGELOG.md
git commit -m "feat(zone): kind idle/crowd + jadwal zona ikut shift"
```

---

### Task 5: Caption Telegram idle/crowd + pengingat

**Files:**
- Modify: `backend/app/services/telegram.py` (`TYPE_TITLE`, `format_caption`)
- Test: `backend/tests/test_telegram.py`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Tulis tes (gagal)** — tambah di `backend/tests/test_telegram.py`:

```python
def test_caption_idle_and_crowd_with_reminder():
    idle = _event(type="idle_zone", payload={"idle_s": 750, "reminder": 0})
    lines = telegram.format_caption(idle, "Pos Depan", "Pos-1", None, tz=WIB).splitlines()
    assert lines[0] == "🚨 <b>IDLE ZONE</b>"
    assert "<b>Kosong</b>: 12 menit" in lines
    crowd = _event(type="crowd", payload={"count": 7, "min_count": 5, "reminder": 2})
    lines = telegram.format_caption(crowd, "Kantin", "Antrean", None, tz=WIB).splitlines()
    assert lines[0] == "🚨 <b>CROWD</b> (pengingat ke-2)"
    assert "<b>Jumlah</b>: 7 orang (min 5)" in lines
    short = _event(type="idle_zone", payload={"idle_s": 45})
    assert "<b>Kosong</b>: 45 detik" in telegram.format_caption(short, "C", None, None, tz=WIB)
```

- [ ] **Step 2: Jalankan, pastikan gagal** — `cd backend && .venv/bin/python -m pytest tests/test_telegram.py -q`.

- [ ] **Step 3: Implementasi** — `telegram.py`:
- `TYPE_TITLE` tambah `"idle_zone": "IDLE ZONE", "crowd": "CROWD"`.
- Di `format_caption`, setelah title cabang `else` (behavior) dibentuk:

```python
        if payload.get("reminder"):
            title += f" (pengingat ke-{int(payload['reminder'])})"
```

- Setelah baris `Zona` ditambahkan:

```python
    if event.type == "idle_zone" and payload.get("idle_s") is not None:
        secs = int(payload["idle_s"])
        rows.append(("Kosong", f"{secs // 60} menit" if secs >= 60 else f"{secs} detik"))
    if event.type == "crowd" and payload.get("count") is not None:
        rows.append(("Jumlah", f"{int(payload['count'])} orang (min {int(payload.get('min_count', 0))})"))
```

- [ ] **Step 4: Jalankan, pastikan lulus** — backend suite penuh.

- [ ] **Step 5: CHANGELOG + commit**

```markdown
- **Caption idle/crowd**: judul `IDLE ZONE` / `CROWD`, baris `Kosong: n menit` / `Jumlah: n orang (min m)`,
  pengingat ditandai `(pengingat ke-n)`. Backend **<angka> passed**.
```

```bash
git add backend/app/services/telegram.py backend/tests/test_telegram.py CHANGELOG.md
git commit -m "feat(telegram): caption idle/crowd dan tanda pengingat"
```

---

### Task 6: Frontend — baris Idle/Crowd + jadwal "Ikut shift"

**Files:**
- Modify: `frontend/src/api/zones.ts` (`BehaviorKind`, `Behavior`, `Zone.schedule`)
- Modify: `frontend/src/features/config/ZonesPage.tsx`
- Modify: `frontend/src/app/i18n.tsx`
- Test: `frontend/src/__tests__/zones.test.tsx`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: `listShifts()` + `Shift` dari `frontend/src/api/employees.ts`.
- Produces: `BehaviorKind = 'intrusion' | 'loitering' | 'running' | 'idle_zone' | 'crowd'`; `Behavior.min_count?`, `Behavior.reminder_minutes?`; `ZoneSchedule = Schedule | { shift_id: number }`.

- [ ] **Step 1: Tulis tes (gagal)** — di `zones.test.tsx`, tambahkan respons `if (u.endsWith('/shifts')) return { ok: true, status: 200, json: () => Promise.resolve([{ id: 3, name: 'Shift 1', start_time: '08:00', end_time: '17:00', tolerance_min: 15, workdays: [1, 2, 3, 4, 5] }]) }` di `stubFetch` (sebelum fallback 404), lalu:

```tsx
test('Idle dan Crowd: default saat dicentang, dikirim di behaviors', async () => {
  const fetchMock = await selectZone([zoneFix()])
  fireEvent.click(screen.getByTestId('zone-behavior-idle_zone'))
  fireEvent.click(screen.getByTestId('zone-behavior-crowd'))
  fireEvent.change(await screen.findByTestId('zone-min-count'), { target: { value: '8' } })
  fireEvent.click(screen.getByTestId('zone-save'))
  await waitFor(() => expect(patchBody(fetchMock).behaviors).toEqual([
    { kind: 'idle_zone', trigger_seconds: 300, reminder_minutes: 15, clip: false },
    { kind: 'crowd', trigger_seconds: 30, min_count: 8, reminder_minutes: 15 },
  ]))
})

test('jadwal Ikut shift mengirim shift_id', async () => {
  const fetchMock = await selectZone([zoneFix()])
  fireEvent.click(screen.getByText('24/7'))
  fireEvent.click(await screen.findByText('Ikut shift'))
  const select = (await screen.findByLabelText('Shift')) as HTMLSelectElement
  expect(select.value).toBe('3')
  fireEvent.click(screen.getByTestId('zone-save'))
  await waitFor(() => expect(patchBody(fetchMock).schedule).toEqual({ shift_id: 3 }))
})
```

(Dropdown Carbon jadwal dibuka dengan klik item terpilih; bila pola tes jadwal yang ada berbeda, ikuti pola itu dan catat.)

- [ ] **Step 2: Jalankan, pastikan gagal** — `cd frontend && npx vitest run src/__tests__/zones.test.tsx`.

- [ ] **Step 3: Implementasi**

`frontend/src/api/zones.ts`:

```ts
export type BehaviorKind = 'intrusion' | 'loitering' | 'running' | 'idle_zone' | 'crowd'
```

`Behavior` tambah `min_count?: number // crowd` dan `reminder_minutes?: number // idle/crowd, 0 = tanpa pengingat`; `export type ZoneSchedule = Schedule | { shift_id: number }` dan `Zone.schedule` / `ZonePayload.schedule` bertipe `ZoneSchedule | null`.

`ZonesPage.tsx`:
- `const BEHAVIOR_KINDS: BehaviorKind[] = ['intrusion', 'loitering', 'running', 'idle_zone', 'crowd']`.
- Default per jenis (ganti sisipan `running` di `setBehavior`):

```tsx
const BEHAVIOR_DEFAULTS: Partial<Record<BehaviorKind, Partial<Behavior>>> = {
  running: { speed_limit_mps: DEFAULT_SPEED_MPS },
  // clip zona kosong tidak informatif → default off (tetap bisa dinyalakan)
  idle_zone: { trigger_seconds: 300, reminder_minutes: 15, clip: false },
  crowd: { trigger_seconds: 30, min_count: 5, reminder_minutes: 15 },
}
// di entry(): { kind, trigger_seconds: 0, ...BEHAVIOR_DEFAULTS[kind], ...current, ...patch }
```

- Di baris behavior (blok `{b && …}`): label `NumberInput` trigger per jenis — `idle_zone` → `t('zones.idleSeconds')`, `crowd` → `t('zones.crowdSeconds')`, lainnya `t('zones.trigger')`. Tambahkan:

```tsx
                              {kind === 'crowd' && (
                                <NumberInput id="zone-min-count" data-testid="zone-min-count" size="sm"
                                  label={t('zones.minCount')} min={1} step={1} value={b.min_count ?? 5}
                                  onChange={(_, state) => {
                                    const n = Number(state.value)
                                    if (Number.isInteger(n) && n >= 1) setBehavior('crowd', { min_count: n })
                                  }} />
                              )}
                              {(kind === 'idle_zone' || kind === 'crowd') && (
                                <NumberInput id={`zone-reminder-${kind}`} data-testid={`zone-reminder-${kind}`} size="sm"
                                  label={t('zones.reminder')} helperText={t('zones.reminderHint')} min={0} step={1}
                                  value={b.reminder_minutes ?? 15}
                                  onChange={(_, state) => {
                                    const n = Number(state.value)
                                    if (Number.isInteger(n) && n >= 0) setBehavior(kind, { reminder_minutes: n })
                                  }} />
                              )}
```

- Jadwal: muat shift sekali (`listShifts().then(setShifts).catch(() => setShifts([]))` di effect awal). `schedItems` tambah `{ id: 'shift', label: t('zones.schedShift') }`. Mode terpilih: `!schedule → always`, `'shift_id' in schedule → shift`, selain itu `hours`. Pilih `shift` → `patchSelected({ schedule: { shift_id: shifts[0]?.id } })` (nonaktifkan item bila `shifts.length === 0`). Saat mode `shift` tampilkan:

```tsx
                  <Select id="zone-sched-shift" labelText={t('zones.shift')} value={selected.schedule.shift_id}
                    onChange={(e) => patchSelected({ schedule: { shift_id: Number(e.target.value) } })}>
                    {shifts.map((s) => <SelectItem key={s.id} value={s.id} text={`${s.name} (${s.start_time}–${s.end_time})`} />)}
                  </Select>
```

  Blok jam manual (start/end/hari) hanya tampil bila schedule manual (`'days' in schedule`) — sesuaikan akses `selected.schedule.start` dsb. agar lolos `tsc` dengan tipe union.

`i18n.tsx` — `id`: `'zones.behavior.idle_zone': 'Zona kosong (Idle)'`, `'zones.behavior.crowd': 'Kerumunan (Crowd)'`, `'zones.idleSeconds': 'Kosong selama (detik)'`, `'zones.crowdSeconds': 'Selama (detik)'`, `'zones.minCount': 'Minimal orang'`, `'zones.reminder': 'Pengingat tiap (menit)'`, `'zones.reminderHint': '0 = tanpa pengingat'`, `'zones.schedShift': 'Ikut shift'`, `'zones.shift': 'Shift'`. `en`: `'Empty zone (Idle)'`, `'Crowd'`, `'Empty for (seconds)'`, `'For (seconds)'`, `'Minimum people'`, `'Remind every (minutes)'`, `'0 = no reminder'`, `'Follow shift'`, `'Shift'`.

- [ ] **Step 4: Jalankan, pastikan lulus** — `cd frontend && npx vitest run && npm run build && npm run lint` → semua passed, build 0, lint set sama. Cek 390 px Zona Deteksi dengan kelima behavior tercentang.

- [ ] **Step 5: CHANGELOG + commit**

```markdown
- **Zona Deteksi**: baris **Zona kosong (Idle)** (kosong selama, pengingat; clip default off) dan **Kerumunan
  (Crowd)** (minimal orang, selama, pengingat); jadwal **Ikut shift** (`{shift_id}`) di samping 24/7 dan jam manual.
  Frontend **<angka> passed**, build 0, lint set sama.
```

```bash
git add frontend/src/api/zones.ts frontend/src/features/config/ZonesPage.tsx frontend/src/app/i18n.tsx frontend/src/__tests__/zones.test.tsx CHANGELOG.md
git commit -m "feat(zone): UI behavior Idle/Crowd + jadwal ikut shift"
```

---

### Task 7: Suite penuh + dokumen + push (eksekutor berhenti di sini)

- [ ] **Step 1: Suite penuh**

```bash
cd backend && .venv/bin/python -m pytest tests -q -m "not gpu" > /tmp/be.log 2>&1; grep -oE '[0-9]+ (passed|failed)[^|]*' /tmp/be.log | tail -1; cd ..
backend/.venv/bin/python -m pytest vision/tests -q -m "not gpu" | tail -1
cd frontend && npx vitest run | tail -3 && npm run build > /dev/null; echo build=$?; npm run lint | tail -2; cd ..
```

- [ ] **Step 2: Dokumen** — README §aturan deteksi/zona: behavior Idle Zone dan Crowd (parameter, pengingat), jadwal ikut shift (shift malam belum didukung), perbaikan jadwal jam dinding. `ROADMAP.md`: baris `| BH | Behavior Idle Zone + Crowd (+ jadwal ikut shift) | [~] lokal selesai, PENDING deploy + verifikasi | — | spec + plan 2026-09-28 | |` sebelum `| E | Edge Jetson …`. Commit:

```bash
git add README.md ROADMAP.md CHANGELOG.md
git commit -m "docs(behavior): Idle Zone + Crowd + jadwal ikut shift"
```

- [ ] **Step 3: Push** — `git push -u origin feat/behavior-idle-crowd` (diizinkan). **Jangan** deploy, ssh, atau merge. Catatan untuk sesi perencana: deploy butuh restart **isentinel-api dan vision-node**.
