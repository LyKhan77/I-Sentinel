# Monitoring Resource S2 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Riwayat metrik Monitoring (agregasi heartbeat per menit, disimpan 7 hari) dan tab "Tren" berisi grafik SVG untuk hardware node, inferensi AI, dan per kamera.

**Architecture:** Handler heartbeat MQTT memanggil `monitoring_history.record()` yang mengagregasi nilai ke bucket menit di memori; `HistorySampler` (thread 60 s) mem-flush bucket selesai ke tabel `monitoring_sample` dan memangkas > 7 hari. `monitoring_history.query()` men-downsample per rentang dan menurunkan periode offline dari event `system`; endpoint `GET /api/v1/monitoring/history`. Frontend: `MonitoringPage` jadi dua tab (`CurrentTab` = isi S1, `TrendTab` baru) dengan komponen `LineChart` SVG sendiri.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, pytest; React 19 + TypeScript + Carbon + Vitest.

**Spec:** `docs/superpowers/specs/2026-09-30-monitoring-s2-design.md`

## Global Constraints

- Tanpa dependensi baru (frontend maupun backend); grafik = SVG buatan sendiri.
- Migrasi **0019** (`down_revision = "0018"`): tabel `monitoring_sample (id, ts, node_id FK node ON DELETE CASCADE, data JSON)`,
  unique + index `(node_id, ts)`.
- Konstanta: `SAMPLE_INTERVAL_S = 60`, `RETENTION_DAYS = 7`, `PRUNE_EVERY_S = 3600`.
- Rentang → `bucket_s`: `1h`→60, `6h`→60, `24h`→300, `7d`→1800; `range` lain → 422; default UI `6h`.
- Agregasi (kunci terakhir path): `cpu_pct`/`ram_pct`/`util_pct` → `avg`,`max`; `vram_pct`/`temp_c`/`ms_max`/`mqtt_backlog`/
  `frame_age_s` → `max`; `ms_avg`/`infer_fps` → `avg`; kamera `fps` → `min`,`avg`; `target_fps` → terakhir;
  `state` → terburuk (`reconnecting` > `stalled` > `starting` > `streaming`).
- Nilai `null` / bukan angka / `bool` dilewati; metrik tanpa nilai tidak ditulis.
- Endpoint untuk semua user login; server pusat **tidak** masuk riwayat.
- Tab: `?tab=current|trend` (default `current`), `?range=1h|6h|24h|7d` (default `6h`); refresh tren **60 s**;
  polling S1 (10 s) hanya saat tab current aktif.
- Semua string lewat `i18n.tsx` (id + en); REST lewat `src/api/*`; 390 px tanpa overflow horizontal.
- Commit Conventional Commits **tanpa** atribusi AI; prefix shell `rtk`; jangan `uv sync`/`uv lock`.
- Baseline `main` `c5fa3a6`: backend 532, vision 233 (3 deselected), frontend 211, build 0.

## Review Focus

1. **Thread sampler/monitor menyentuh DB nyata saat tes** — conftest wajib menonaktifkan interval sampler dan
   mereset bucket memori antar tes (tes Task 3).
2. **Node terhapus di antara `record` dan `write`** — FK gagal tidak boleh membatalkan seluruh batch / mematikan
   thread (tes Task 3).
3. **Datetime naive (SQLite) vs aware (Postgres)** di filter `ts`, pembulatan bucket, dan periode offline
   (tes Task 3 & 4 memakai waktu UTC eksplisit).
4. **Loncatan data (node offline / belum ada sampel)** harus tampil sebagai celah, bukan garis lurus menyambung
   (tes Task 5).
5. **Heartbeat format lama / JSON rusak** tidak membuat handler MQTT error (tes Task 2).

---

## File Structure

| File | Tanggung jawab |
|---|---|
| Create `backend/alembic/versions/0019_monitoring_sample.py` | Tabel riwayat |
| Create `backend/app/models/monitoring_sample.py` | Model ORM |
| Modify `backend/app/models/__init__.py` | Registrasi model |
| Create `backend/app/services/monitoring_history.py` | `record`/`flush`, `write`/`prune`, `HistorySampler`, `query` |
| Modify `backend/app/services/events_consumer.py` | Panggil `record` di handler heartbeat |
| Modify `backend/app/schemas/monitoring.py` | `MonitoringHistoryOut` dkk. |
| Modify `backend/app/api/monitoring.py` | `GET /history` |
| Modify `backend/app/main.py` | Start/stop sampler |
| Modify `backend/tests/conftest.py` | Nonaktifkan sampler + reset bucket |
| Create `backend/tests/test_monitoring_history.py`, `backend/tests/test_migration_0019.py` | Tes backend |
| Create `frontend/src/components/LineChart.tsx` | Grafik garis SVG |
| Create `frontend/src/features/monitoring/CurrentTab.tsx` | Isi S1 dipindah dari `MonitoringPage` |
| Create `frontend/src/features/monitoring/TrendTab.tsx` | Tab Tren |
| Modify `frontend/src/features/monitoring/MonitoringPage.tsx` | Header + Tabs |
| Modify `frontend/src/api/monitoring.ts`, `app/i18n.tsx`, `app/theme.scss` | API, string, gaya |
| Create `frontend/src/__tests__/linechart.test.tsx`, `frontend/src/__tests__/monitoring-trend.test.tsx` | Tes frontend |

---

### Task 1: Migrasi 0019 + model

**Files:**
- Create: `backend/alembic/versions/0019_monitoring_sample.py`, `backend/app/models/monitoring_sample.py`
- Modify: `backend/app/models/__init__.py`
- Test: `backend/tests/test_migration_0019.py`

**Interfaces:**
- Produces: `MonitoringSample(id: int, ts: datetime, node_id: int, data: dict)` (tabel `monitoring_sample`).

- [ ] **Step 1: Tes migrasi (gagal)**

```python
"""0019: tabel monitoring_sample (riwayat Monitoring S2)."""
import importlib.util
import pathlib

import sqlalchemy as sa

_PATH = pathlib.Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0019_monitoring_sample.py"
_spec = importlib.util.spec_from_file_location("mig0019", _PATH)
mig = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mig)


def test_upgrade_downgrade_and_cascade():
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    engine = sa.create_engine("sqlite://")

    @sa.event.listens_for(engine, "connect")
    def _fk(dbapi_conn, _record):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    meta = sa.MetaData()
    sa.Table("node", meta, sa.Column("id", sa.Integer, primary_key=True), sa.Column("name", sa.String(64)))
    meta.create_all(engine)
    with engine.begin() as c:
        c.execute(sa.text("INSERT INTO node (id, name) VALUES (1, 'server')"))

    def run(fn):
        with engine.begin() as conn, Operations.context(MigrationContext.configure(conn)):
            fn()

    run(mig.upgrade)
    with engine.begin() as c:
        c.execute(sa.text("INSERT INTO monitoring_sample (ts, node_id, data) VALUES ('2026-09-30 08:00:00', 1, '{}')"))
    with engine.begin() as c:  # unique (node_id, ts)
        try:
            c.execute(sa.text("INSERT INTO monitoring_sample (ts, node_id, data) VALUES ('2026-09-30 08:00:00', 1, '{}')"))
            raise AssertionError("duplikat (node_id, ts) seharusnya ditolak")
        except sa.exc.IntegrityError:
            pass
    with engine.begin() as c:
        c.execute(sa.text("DELETE FROM node WHERE id = 1"))
        assert c.execute(sa.text("SELECT count(*) FROM monitoring_sample")).scalar() == 0  # cascade

    run(mig.downgrade)
    assert "monitoring_sample" not in sa.inspect(engine).get_table_names()
```

Run: `rtk bash -c "cd backend && .venv/bin/python -m pytest tests/test_migration_0019.py -q"`
Expected: FAIL — file migrasi tidak ada.

- [ ] **Step 2: Migrasi + model**

`backend/alembic/versions/0019_monitoring_sample.py`:

```python
"""monitoring_sample: riwayat metrik Monitoring per node per menit (S2), disimpan 7 hari.

Revision ID: 0019
Revises: 0018
"""

from alembic import op
import sqlalchemy as sa

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "monitoring_sample",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("node_id", sa.Integer(), sa.ForeignKey("node.id", ondelete="CASCADE"), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.UniqueConstraint("node_id", "ts", name="uq_monitoring_sample_node_ts"),
    )
    op.create_index("ix_monitoring_sample_ts", "monitoring_sample", ["ts"])


def downgrade() -> None:
    op.drop_index("ix_monitoring_sample_ts", table_name="monitoring_sample")
    op.drop_table("monitoring_sample")
```

(Unique `(node_id, ts)` sudah membuat index komposit; index `ts` terpisah untuk prune lintas node.)

`backend/app/models/monitoring_sample.py`:

```python
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class MonitoringSample(Base):
    """Satu menit metrik satu node (agregat heartbeat) — riwayat grafik tren, dipangkas setelah 7 hari."""
    __tablename__ = "monitoring_sample"
    __table_args__ = (UniqueConstraint("node_id", "ts", name="uq_monitoring_sample_node_ts"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    node_id: Mapped[int] = mapped_column(Integer, ForeignKey("node.id", ondelete="CASCADE"))
    data: Mapped[dict] = mapped_column(JSON)
```

(Sesuaikan import `Base` dengan model lain — cek `app/models/node.py`.) Tambahkan
`from app.models.monitoring_sample import MonitoringSample` di `app/models/__init__.py`.

Run: tes Step 1 → PASS; `rtk bash -c "cd backend && .venv/bin/python -m pytest tests -q -m 'not gpu'"` → PASS.

- [ ] **Step 3: Commit**

```bash
rtk git add backend/alembic/versions/0019_monitoring_sample.py backend/app/models backend/tests/test_migration_0019.py
rtk git commit -m "feat(monitoring): tabel monitoring_sample untuk riwayat metrik"
```

---

### Task 2: Agregasi per menit (`record` / `flush`) + hook heartbeat

**Files:**
- Create: `backend/app/services/monitoring_history.py` (bagian agregasi)
- Modify: `backend/app/services/events_consumer.py` (cabang heartbeat)
- Modify: `backend/tests/conftest.py`
- Test: `backend/tests/test_monitoring_history.py`, `backend/tests/test_events_consumer.py`

**Interfaces:**
- Produces: `monitoring_history.record(node_id: int, hw: dict | None, modules: dict | None, now: datetime | None = None) -> None`;
  `monitoring_history.flush(now: datetime | None = None) -> list[tuple[int, datetime, dict]]`;
  `monitoring_history.reset() -> None` (tes); konstanta `STATE_RANK`.

- [ ] **Step 1: Tes (gagal)**

`backend/tests/test_monitoring_history.py` (bagian atas dipakai Task 3 & 4 juga):

```python
import uuid
from datetime import datetime, timedelta, timezone

from app.models.camera import Camera
from app.models.event import Event
from app.models.monitoring_sample import MonitoringSample
from app.models.node import Node
from app.services import monitoring_history as mh

T0 = datetime(2026, 9, 30, 8, 0, tzinfo=timezone.utc)


def _hb(cpu=10.0, ram=(1000, 4000), gpus=None, det=None, backlog=0, cams=None):
    hw = {"host": {"cpu_pct": cpu, "ram_used_mb": ram[0], "ram_total_mb": ram[1]},
          "gpus": gpus if gpus is not None else
          [{"idx": 0, "util_pct": 40, "vram_used_mb": 20, "vram_total_mb": 100, "temp_c": 60}]}
    mods = {"detector": det or {"ms_avg": 8.0, "ms_max": 12.0, "infer_fps": 40.0},
            "mqtt_backlog": backlog, "cameras": cams if cams is not None else []}
    return hw, mods


def test_record_aggregates_minute_bucket():
    mh.record(1, *_hb(cpu=10, det={"ms_avg": 8, "ms_max": 12, "infer_fps": 40}), now=T0 + timedelta(seconds=5))
    mh.record(1, *_hb(cpu=30, det={"ms_avg": 10, "ms_max": 30, "infer_fps": 20},
                      gpus=[{"idx": 0, "util_pct": 80, "vram_used_mb": 50, "vram_total_mb": 100, "temp_c": 70}]),
              now=T0 + timedelta(seconds=15))
    assert mh.flush(T0 + timedelta(seconds=30)) == []  # bucket berjalan tidak di-flush
    [(node_id, ts, data)] = mh.flush(T0 + timedelta(minutes=1))
    assert node_id == 1 and ts == T0
    assert data["cpu_pct"] == {"avg": 20.0, "max": 30.0}
    assert data["ram_pct"] == {"avg": 25.0, "max": 25.0}
    assert data["gpus"]["0"] == {"util_pct": {"avg": 60.0, "max": 80.0}, "vram_pct": {"max": 50.0},
                                 "temp_c": {"max": 70.0}}
    assert data["ms_avg"] == {"avg": 9.0} and data["ms_max"] == {"max": 30.0}
    assert data["infer_fps"] == {"avg": 30.0} and data["mqtt_backlog"] == {"max": 0}
    assert mh.flush(T0 + timedelta(minutes=5)) == []  # sudah dikeluarkan


def test_camera_workers_merged_and_state_worst():
    cams = [{"id": 3, "worker": "detect", "state": "streaming", "fps": 5.0, "target_fps": 5.0, "last_frame_age_s": 0.2},
            {"id": 3, "worker": "face", "state": "stalled", "fps": 2.0, "target_fps": 5.0, "last_frame_age_s": 12.0}]
    mh.record(1, *_hb(cams=cams), now=T0)
    mh.record(1, *_hb(cams=[{**cams[0], "fps": 4.0}]), now=T0 + timedelta(seconds=10))
    [(_, _, data)] = mh.flush(T0 + timedelta(minutes=1))
    cam = data["cameras"]["3"]
    assert cam["fps"] == {"min": 2.0, "avg": 3.0}  # hb1: min worker 2.0, hb2: 4.0
    assert cam["frame_age_s"] == {"max": 12.0}
    assert cam["target_fps"] == 5.0 and cam["state"] == "stalled"


def test_nodes_and_minutes_separate():
    mh.record(1, *_hb(cpu=10), now=T0)
    mh.record(2, *_hb(cpu=50), now=T0)
    mh.record(1, *_hb(cpu=90), now=T0 + timedelta(minutes=1))
    rows = mh.flush(T0 + timedelta(minutes=2))
    assert [(n, ts, d["cpu_pct"]["avg"]) for n, ts, d in rows] == [
        (1, T0, 10.0), (1, T0 + timedelta(minutes=1), 90.0), (2, T0, 50.0)]


def test_garbage_and_nulls_skipped():
    mh.record(1, {"host": "x", "gpus": [{"idx": "a"}, 5]}, {"detector": 3, "cameras": "junk", "mqtt_backlog": True},
              now=T0)
    mh.record(1, {"host": {"cpu_pct": None, "ram_used_mb": 5, "ram_total_mb": 0}}, None, now=T0)
    mh.record(2, None, None, now=T0)
    assert all(data == {} for *_, data in mh.flush(T0 + timedelta(minutes=1)))
```

Di `tests/test_events_consumer.py` tambahkan:

```python
def test_heartbeat_records_history(db, broadcast):
    from app.services import monitoring_history as mh
    db.add(Node(name="vision-1", status="online"))
    db.commit()
    hb = {"ts": "x", "hw": {"host": {"cpu_pct": 42.0}, "gpus": []},
          "modules": {"detector": {"ms_avg": 7.0}}, "cameras": [], "mqtt_backlog": 0}
    handle_message(db, "isentinel/nodes/vision-1/heartbeat", json.dumps(hb).encode())
    handle_message(db, "isentinel/nodes/vision-1/heartbeat", json.dumps({"ts": "x"}).encode())  # format lama
    node = db.query(Node).filter_by(name="vision-1").one()
    rows = mh.flush(datetime.now(timezone.utc) + timedelta(minutes=2))
    assert [(n, d["cpu_pct"]["avg"]) for n, _, d in rows] == [(node.id, 42.0)]
```

(import `timedelta` di atas file bila belum.)

`tests/conftest.py` — tambahkan fixture autouse:

```python
@pytest.fixture(autouse=True)
def _quiet_history():
    """Bucket riwayat di memori modul: kosongkan antar tes; sampler latar tidak boleh menyentuh DB nyata."""
    from app.services import monitoring_history
    monitoring_history.reset()
    old = monitoring_history.sampler.interval_s
    monitoring_history.sampler.interval_s = 3600
    yield
    monitoring_history.sampler.interval_s = old
    monitoring_history.reset()
```

(`sampler` baru ada di Task 3; untuk Task 2 tambahkan fixture tanpa baris `sampler` dulu, lengkapi di Task 3 — atau
tambahkan `sampler` placeholder sekarang dan implementasi penuhnya di Task 3.)

Run: `rtk bash -c "cd backend && .venv/bin/python -m pytest tests/test_monitoring_history.py tests/test_events_consumer.py -q"`
Expected: FAIL — `ImportError: cannot import name 'monitoring_history'`.

- [ ] **Step 2: Implementasi agregasi**

`backend/app/services/monitoring_history.py`:

```python
"""Riwayat Monitoring (S2): heartbeat → bucket menit di memori → baris monitoring_sample → deret tren.

Heartbeat 10 s membawa nilai per jendela 10 s; menyimpan nilai terakhir per menit akan membuang lonjakan, jadi tiap
metrik diagregasi (avg/max/min) selama semenit. Bucket menit berjalan hilang saat API restart (≤ 1 menit).
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

STATE_RANK = {"streaming": 0, "starting": 1, "stalled": 2, "reconnecting": 3}
# kunci terakhir path metrik → agregasi yang disimpan
AGG = {"cpu_pct": ("avg", "max"), "ram_pct": ("avg", "max"), "util_pct": ("avg", "max"),
       "vram_pct": ("max",), "temp_c": ("max",), "ms_avg": ("avg",), "ms_max": ("max",),
       "infer_fps": ("avg",), "mqtt_backlog": ("max",), "fps": ("min", "avg"), "frame_age_s": ("max",)}


def _num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _dict(v) -> dict:
    return v if isinstance(v, dict) else {}


def _list(v) -> list:
    return v if isinstance(v, list) else []


def _minute(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc).replace(second=0, microsecond=0)


class _Acc:
    """Akumulator satu metrik dalam satu bucket."""
    __slots__ = ("sum", "n", "max", "min")

    def __init__(self):
        self.sum, self.n, self.max, self.min = 0.0, 0, None, None

    def add(self, v: float) -> None:
        self.sum += v
        self.n += 1
        self.max = v if self.max is None else max(self.max, v)
        self.min = v if self.min is None else min(self.min, v)

    def value(self, kind: str) -> float:
        return round(self.sum / self.n if kind == "avg" else getattr(self, kind), 1)


_lock = threading.Lock()
_buckets: dict[tuple[int, datetime], dict] = {}  # (node_id, awal menit UTC) → {"acc": {path: _Acc}, "cams": {id: meta}}


def reset() -> None:
    with _lock:
        _buckets.clear()


def _extract(hw, modules) -> tuple[list[tuple[str, float]], dict[int, dict]]:
    """Heartbeat → [(path, nilai)] + meta kamera (target_fps, state). Tipe ngawur dilewati."""
    hw, mods = _dict(hw), _dict(modules)
    out: list[tuple[str, float]] = []

    def add(path, v):
        v = _num(v)
        if v is not None:
            out.append((path, v))

    host = _dict(hw.get("host"))
    add("cpu_pct", host.get("cpu_pct"))
    used, total = _num(host.get("ram_used_mb")), _num(host.get("ram_total_mb"))
    if used is not None and total:
        add("ram_pct", used / total * 100)
    for g in _list(hw.get("gpus")):
        idx = _num(_dict(g).get("idx"))
        if idx is None:
            continue
        i = int(idx)
        add(f"gpus.{i}.util_pct", g.get("util_pct"))
        vu, vt = _num(g.get("vram_used_mb")), _num(g.get("vram_total_mb"))
        if vu is not None and vt:
            add(f"gpus.{i}.vram_pct", vu / vt * 100)
        add(f"gpus.{i}.temp_c", g.get("temp_c"))
    det = _dict(mods.get("detector"))
    add("ms_avg", det.get("ms_avg"))
    add("ms_max", det.get("ms_max"))
    add("infer_fps", det.get("infer_fps"))
    add("mqtt_backlog", mods.get("mqtt_backlog"))
    cams: dict[int, dict] = {}
    for c in _list(mods.get("cameras")):
        if not isinstance(c, dict) or not isinstance(c.get("id"), int) or isinstance(c.get("id"), bool):
            continue
        m = cams.setdefault(c["id"], {"fps": None, "age": None, "target_fps": None, "state": None})
        fps, age, target = _num(c.get("fps")), _num(c.get("last_frame_age_s")), _num(c.get("target_fps"))
        if fps is not None:  # detect + face satu kamera → fps terendah
            m["fps"] = fps if m["fps"] is None else min(m["fps"], fps)
        if age is not None:
            m["age"] = age if m["age"] is None else max(m["age"], age)
        if target is not None:
            m["target_fps"] = target
        st = c.get("state")
        if st in STATE_RANK and (m["state"] is None or STATE_RANK[st] > STATE_RANK[m["state"]]):
            m["state"] = st
    for cid, m in cams.items():
        add(f"cameras.{cid}.fps", m["fps"])
        add(f"cameras.{cid}.frame_age_s", m["age"])
    return out, {cid: {"target_fps": m["target_fps"], "state": m["state"]} for cid, m in cams.items()}


def record(node_id: int, hw, modules, now: datetime | None = None) -> None:
    """Tambah satu heartbeat ke bucket menit node. Tidak pernah raise (dipanggil handler MQTT)."""
    try:
        values, cams = _extract(hw, modules)
        key = (node_id, _minute(now or datetime.now(timezone.utc)))
        with _lock:
            b = _buckets.setdefault(key, {"acc": {}, "cams": {}})
            for path, v in values:
                b["acc"].setdefault(path, _Acc()).add(v)
            for cid, meta in cams.items():
                cur = b["cams"].setdefault(cid, {"target_fps": None, "state": None})
                if meta["target_fps"] is not None:
                    cur["target_fps"] = meta["target_fps"]
                st = meta["state"]
                if st is not None and (cur["state"] is None or STATE_RANK[st] > STATE_RANK[cur["state"]]):
                    cur["state"] = st
    except Exception:
        logger.warning("monitoring history record failed", exc_info=True)


def _summarize(bucket: dict) -> dict:
    data: dict = {}
    for path, acc in bucket["acc"].items():
        parts = path.split(".")
        node = data
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        node[parts[-1]] = {k: acc.value(k) for k in AGG[parts[-1]]}
    for cid, meta in bucket["cams"].items():
        cam = data.setdefault("cameras", {}).setdefault(str(cid), {})
        if meta["target_fps"] is not None:
            cam["target_fps"] = meta["target_fps"]
        if meta["state"] is not None:
            cam["state"] = meta["state"]
    return data


def flush(now: datetime | None = None) -> list[tuple[int, datetime, dict]]:
    """Keluarkan bucket yang sudah selesai (menit < menit berjalan), urut (node, ts)."""
    current = _minute(now or datetime.now(timezone.utc))
    with _lock:
        done = sorted(k for k in _buckets if k[1] < current)
        items = [(k, _buckets.pop(k)) for k in done]
    return [(node_id, ts, _summarize(b)) for (node_id, ts), b in items]
```

- [ ] **Step 3: Hook heartbeat**

Di `events_consumer.py` cabang heartbeat: import `from app.services import monitoring_history` (gabung dengan import
`services` yang ada). Simpan `modules = None` sebelum blok `if isinstance(data.get("modules"), dict):` (variabel
lokal yang sudah dibangun di blok itu), lalu setelah `db.commit()` dan sebelum `node_health.mark_online(...)`:

```python
            # riwayat S2: nilai heartbeat ini ke bucket menit (modules gabungan: cameras + mqtt_backlog)
            monitoring_history.record(node.id, data.get("hw") if isinstance(data.get("hw"), dict) else None, modules)
```

Run: tes Step 1 → PASS.

- [ ] **Step 4: Commit**

```bash
rtk git add backend/app/services/monitoring_history.py backend/app/services/events_consumer.py backend/tests
rtk git commit -m "feat(monitoring): agregasi heartbeat per menit untuk riwayat"
```

---

### Task 3: Sampler — tulis, pangkas, thread

**Files:**
- Modify: `backend/app/services/monitoring_history.py` (tambah `write`, `prune`, `HistorySampler`, `sampler`)
- Modify: `backend/app/main.py` (lifespan), `backend/tests/conftest.py` (lengkapi fixture)
- Test: `backend/tests/test_monitoring_history.py`

**Interfaces:**
- Consumes: `flush()` (Task 2), `MonitoringSample` (Task 1).
- Produces: `SAMPLE_INTERVAL_S = 60`, `RETENTION_DAYS = 7`, `PRUNE_EVERY_S = 3600`;
  `write(db, rows) -> int`; `prune(db, now) -> int`;
  `HistorySampler(interval_s=SAMPLE_INTERVAL_S, session_factory=SessionLocal)` dengan `run_once(now=None) -> int`,
  `start()`, `stop()`; instance modul `sampler`.

- [ ] **Step 1: Tes (gagal)**

Tambahkan di `test_monitoring_history.py`:

```python
def _node(db, name="server"):
    n = Node(name=name, status="online")
    db.add(n)
    db.commit()
    return n


def _naive(dt):
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _ts_list(db):
    return [_naive(r.ts) if r.ts.tzinfo else r.ts for r in db.query(MonitoringSample).order_by(MonitoringSample.ts)]


def test_sampler_writes_skips_duplicate_and_prunes_hourly(db):
    n = _node(db)
    db.add(MonitoringSample(node_id=n.id, ts=T0 - timedelta(days=8), data={"cpu_pct": {"avg": 1.0}}))
    db.commit()
    s = mh.HistorySampler(session_factory=lambda: db)
    mh.record(n.id, *_hb(), now=T0)
    assert s.run_once(now=T0 + timedelta(minutes=1)) == 1
    assert _ts_list(db) == [_naive(T0)]  # sampel 8 hari dipangkas pada run pertama

    mh.record(n.id, *_hb(), now=T0)  # bucket menit yang sama datang terlambat → duplikat diabaikan
    db.add(MonitoringSample(node_id=n.id, ts=T0 - timedelta(days=9), data={}))
    db.commit()
    assert s.run_once(now=T0 + timedelta(minutes=2)) == 0
    assert len(_ts_list(db)) == 2  # prune belum jalan (< 1 jam sejak prune terakhir)
    s.run_once(now=T0 + timedelta(minutes=62))
    assert _ts_list(db) == [_naive(T0)]


def test_sampler_skips_unknown_node_and_empty(db):
    n = _node(db)
    mh.record(999, *_hb(), now=T0)            # node sudah dihapus
    mh.record(n.id, None, None, now=T0)       # heartbeat tanpa metrik
    s = mh.HistorySampler(session_factory=lambda: db)
    assert s.run_once(now=T0 + timedelta(minutes=1)) == 0
    assert _ts_list(db) == []


def test_sampler_thread_survives_error_and_stops(monkeypatch):
    calls = []

    def boom():
        calls.append(1)
        raise RuntimeError("db down")

    s = mh.HistorySampler(interval_s=0.01, session_factory=boom)
    s.start()
    import time
    deadline = time.monotonic() + 2
    while len(calls) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    s.stop()
    assert len(calls) >= 2 and not s._thread.is_alive()
```

Run: `rtk bash -c "cd backend && .venv/bin/python -m pytest tests/test_monitoring_history.py -q -k sampler"`
Expected: FAIL — `AttributeError: module ... has no attribute 'HistorySampler'`.

- [ ] **Step 2: Implementasi**

Tambahkan ke `monitoring_history.py` (import `timedelta`, `SessionLocal`, `MonitoringSample`, `Node`):

```python
SAMPLE_INTERVAL_S = 60
RETENTION_DAYS = 7
PRUNE_EVERY_S = 3600


def write(db, rows: list[tuple[int, datetime, dict]]) -> int:
    """Simpan bucket selesai; node tak dikenal / data kosong / duplikat (node, ts) dilewati."""
    rows = [r for r in rows if r[2]]
    if not rows:
        return 0
    known = {nid for (nid,) in db.query(Node.id).filter(Node.id.in_({r[0] for r in rows}))}
    added = 0
    for node_id, ts, data in rows:
        if node_id not in known:
            continue
        if db.query(MonitoringSample.id).filter_by(node_id=node_id, ts=ts).first() is not None:
            continue
        db.add(MonitoringSample(node_id=node_id, ts=ts, data=data))
        added += 1
    db.commit()
    return added


def prune(db, now: datetime) -> int:
    n = db.query(MonitoringSample).filter(MonitoringSample.ts < now - timedelta(days=RETENTION_DAYS)).delete(
        synchronize_session=False)
    db.commit()
    return n


class HistorySampler:
    """Thread latar: tiap interval_s tulis bucket selesai; pangkas > RETENTION_DAYS sekali per jam."""

    def __init__(self, interval_s: float = SAMPLE_INTERVAL_S, session_factory=SessionLocal):
        self.interval_s = interval_s
        self._session_factory = session_factory
        self._last_prune: datetime | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def run_once(self, now: datetime | None = None) -> int:
        now = now or datetime.now(timezone.utc)
        rows = flush(now)  # dikeluarkan dulu: bila DB gagal, bucket dibuang (memori tidak menumpuk)
        db = self._session_factory()
        try:
            try:
                added = write(db, rows)
            except Exception:
                db.rollback()
                raise
            if self._last_prune is None or (now - self._last_prune).total_seconds() >= PRUNE_EVERY_S:
                prune(db, now)
                self._last_prune = now
            return added
        finally:
            db.close()

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="monitoring-history")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def _loop(self) -> None:
        while not self._stop.wait(self.interval_s):
            try:
                self.run_once()
            except Exception:
                logger.warning("monitoring history sample failed", exc_info=True)


sampler = HistorySampler()
```

Catatan: `session_factory` yang melempar (tes `boom`) terjadi di `run_once` sebelum `try` → ditangkap `_loop`. Pada
SQLite tes `ts` tersimpan naive; `filter_by(ts=ts)` membandingkan string — pastikan duplikat terdeteksi (tes Step 1);
bila tidak, bandingkan dengan `ts.replace(tzinfo=None)` saat dialect SQLite dan catat deviasinya.

`main.py` lifespan: setelah `node_monitor.start()` tambahkan
`from app.services.monitoring_history import sampler as history_sampler` + `history_sampler.start()`; di `finally`
`history_sampler.stop()` sebelum `node_monitor.stop()`.

Lengkapi fixture `_quiet_history` di `conftest.py` (baris `sampler.interval_s`) bila belum.

Run: `rtk bash -c "cd backend && .venv/bin/python -m pytest tests -q -m 'not gpu'"` → PASS; durasi suite tidak naik
berarti.

- [ ] **Step 3: Commit**

```bash
rtk git add backend/
rtk git commit -m "feat(monitoring): sampler riwayat per menit dengan retensi 7 hari"
```

---

### Task 4: `query()` + `GET /api/v1/monitoring/history`

**Files:**
- Modify: `backend/app/services/monitoring_history.py` (tambah `RANGES`, `query`)
- Modify: `backend/app/schemas/monitoring.py`, `backend/app/api/monitoring.py`
- Test: `backend/tests/test_monitoring_history.py`

**Interfaces:**
- Consumes: `MonitoringSample`, `Event` (`type="system"`, `node_id`, `payload.reason`), `Camera`.
- Produces: `RANGES = {"1h": (timedelta(hours=1), 60), "6h": (..., 60), "24h": (..., 300), "7d": (timedelta(days=7), 1800)}`;
  `query(db, range_key: str, now: datetime | None = None) -> dict` (bentuk spec §3.3; titik `{"t": "…Z", <agg>: v}`);
  endpoint `GET /api/v1/monitoring/history?range=` → `MonitoringHistoryOut`.

- [ ] **Step 1: Tes (gagal)**

```python
def _sample(db, node, ts, **data):
    db.add(MonitoringSample(node_id=node.id, ts=ts, data=data))
    db.commit()


def _event(db, node, ts, reason):
    db.add(Event(event_id=str(uuid.uuid4()), type="system", node_id=node.id,
                 severity="info" if reason == "online" else "warning", ts_event=ts,
                 payload={"node": node.name, "reason": reason}))
    db.commit()


def _z(dt):
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def test_query_downsample_per_range(db):
    n = _node(db)
    for i in range(30):  # 07:30 .. 07:59, satu sampel per menit
        _sample(db, n, T0 - timedelta(minutes=i + 1), cpu_pct={"avg": float(i), "max": float(i) + 1})
    r = mh.query(db, "1h", now=T0)
    assert r["bucket_s"] == 60 and len(r["nodes"][0]["series"]["cpu_pct"]) == 30
    assert r["from"] == _z(T0 - timedelta(hours=1)) and r["to"] == _z(T0)
    r24 = mh.query(db, "24h", now=T0)
    pts = r24["nodes"][0]["series"]["cpu_pct"]
    assert r24["bucket_s"] == 300 and len(pts) == 6
    # bucket 07:30 berisi menit 07:30..07:34 (i = 29..25): avg dari avg, max dari max
    assert pts[0] == {"t": "2026-09-30T07:30:00Z", "avg": 27.0, "max": 30.0}
    assert mh.query(db, "7d", now=T0)["bucket_s"] == 1800


def test_query_gaps_not_filled_and_gpu_camera_series(db):
    n = _node(db)
    db.add(Camera(id=3, name="Lorong", host="1.2.3.4"))
    db.commit()
    cam = {"fps": {"min": 4.0, "avg": 5.0}, "target_fps": 5.0, "frame_age_s": {"max": 0.3}, "state": "streaming"}
    _sample(db, n, T0 - timedelta(minutes=10), gpus={"0": {"temp_c": {"max": 60.0}}},
            cameras={"3": cam, "99": cam})
    _sample(db, n, T0 - timedelta(minutes=5), gpus={"0": {"temp_c": {"max": 70.0}}}, cameras={"3": cam})
    node = mh.query(db, "1h", now=T0)["nodes"][0]
    assert [p["max"] for p in node["series"]["gpus"]["0"]["temp_c"]] == [60.0, 70.0]  # 2 titik, celah tidak diisi
    cams = {c["id"]: c for c in node["cameras"]}
    assert cams[3]["name"] == "Lorong" and cams[3]["target_fps"] == 5.0
    assert cams[3]["fps"][0] == {"t": _z(T0 - timedelta(minutes=10)), "min": 4.0, "avg": 5.0}
    assert cams[99]["name"] == "#99"  # kamera terhapus


def test_query_merge_state_and_min(db):
    n = _node(db)
    ts = T0 - timedelta(minutes=20)  # dua menit dalam satu bucket 5 menit (24h)
    _sample(db, n, ts, cameras={"3": {"fps": {"min": 5.0, "avg": 5.0}, "state": "streaming"}})
    _sample(db, n, ts + timedelta(minutes=1), cameras={"3": {"fps": {"min": 1.0, "avg": 3.0}, "state": "stalled"}})
    cam = mh.query(db, "24h", now=T0)["nodes"][0]["cameras"][0]
    assert cam["fps"] == [{"t": _z(ts), "min": 1.0, "avg": 4.0}]


def test_offline_periods_from_system_events(db):
    n = _node(db)
    _event(db, n, T0 - timedelta(hours=3), "timeout")   # sebelum rentang: node offline di awal rentang 1h
    _event(db, n, T0 - timedelta(minutes=50), "online")
    _event(db, n, T0 - timedelta(minutes=20), "lwt")    # belum pulih
    offline = mh.query(db, "1h", now=T0)["nodes"][0]["offline"]
    assert offline == [{"from": _z(T0 - timedelta(hours=1)), "to": _z(T0 - timedelta(minutes=50))},
                       {"from": _z(T0 - timedelta(minutes=20)), "to": None}]


def test_node_without_samples_listed_empty(db):
    _node(db)
    node = mh.query(db, "6h", now=T0)["nodes"][0]
    assert node["series"]["cpu_pct"] == [] and node["cameras"] == [] and node["offline"] == []


def test_history_endpoint_auth_and_validation(client, viewer_headers):
    assert client.get("/api/v1/monitoring/history").status_code == 401
    r = client.get("/api/v1/monitoring/history?range=1h", headers=viewer_headers)
    assert r.status_code == 200 and r.json()["bucket_s"] == 60
    assert client.get("/api/v1/monitoring/history?range=2h", headers=viewer_headers).status_code == 422
    assert client.get("/api/v1/monitoring/history", headers=viewer_headers).json()["range"] == "6h"
```

Fixture `client` + `viewer_headers`: salin fixture `client` yang dipakai `tests/test_monitoring.py` (S1) ke file ini
bila tidak tersedia dari conftest.

Run: `rtk bash -c "cd backend && .venv/bin/python -m pytest tests/test_monitoring_history.py -q"` → FAIL (`query` belum ada).

- [ ] **Step 2: Implementasi `query`**

Tambahkan ke `monitoring_history.py` (import `Camera`, `Event`):

```python
RANGES = {"1h": (timedelta(hours=1), 60), "6h": (timedelta(hours=6), 60),
          "24h": (timedelta(hours=24), 300), "7d": (timedelta(days=7), 1800)}
NODE_KEYS = ("cpu_pct", "ram_pct", "ms_avg", "ms_max", "infer_fps", "mqtt_backlog")
GPU_KEYS = ("util_pct", "vram_pct", "temp_c")


def _utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _z(dt: datetime) -> str:
    return _utc(dt).isoformat().replace("+00:00", "Z")


def _floor(dt: datetime, bucket_s: int) -> datetime:
    ts = int(_utc(dt).timestamp())
    return datetime.fromtimestamp(ts - ts % bucket_s, tz=timezone.utc)


def _merge(parts: list) -> dict | None:
    """Gabung agregat beberapa menit: avg → rata-rata, max → maks, min → min."""
    parts = [p for p in parts if isinstance(p, dict)]
    out = {}
    for kind, fn in (("avg", lambda v: sum(v) / len(v)), ("max", max), ("min", min)):
        vals = [_num(p.get(kind)) for p in parts if _num(p.get(kind)) is not None]
        if vals:
            out[kind] = round(fn(vals), 1)
    return out or None


def _offline(db, node: Node, start: datetime, now: datetime) -> list[dict]:
    """Periode offline dari event system node: offline → online berikutnya; tanpa pasangan → to None."""
    base = db.query(Event).filter(Event.type == "system", Event.node_id == node.id)
    before = base.filter(Event.ts_event < start).order_by(Event.ts_event.desc()).first()
    within = base.filter(Event.ts_event >= start, Event.ts_event <= now).order_by(Event.ts_event).all()
    is_off = lambda e: _dict(e.payload).get("reason") != "online"
    periods, cur = [], (start if before is not None and is_off(before) else None)
    for e in within:
        ts = _utc(e.ts_event)
        if is_off(e) and cur is None:
            cur = ts
        elif not is_off(e) and cur is not None:
            periods.append({"from": _z(cur), "to": _z(ts)})
            cur = None
    if cur is not None:
        periods.append({"from": _z(cur), "to": None})
    return periods


def query(db, range_key: str, now: datetime | None = None) -> dict:
    """Deret tren per node untuk satu rentang (downsample ke bucket_s; bucket kosong tidak dikirim)."""
    span, bucket_s = RANGES[range_key]
    now = _utc(now or datetime.now(timezone.utc))
    start = now - span
    nodes = db.query(Node).order_by(Node.name).all()
    names = {cid: name for cid, name in db.query(Camera.id, Camera.name)}
    grouped: dict[int, dict[datetime, list[dict]]] = {}
    for r in db.query(MonitoringSample).filter(MonitoringSample.ts >= start).order_by(MonitoringSample.ts):
        grouped.setdefault(r.node_id, {}).setdefault(_floor(r.ts, bucket_s), []).append(_dict(r.data))
    out = []
    for n in nodes:
        series = {k: [] for k in NODE_KEYS}
        gpus: dict[str, dict] = {}
        cams: dict[str, dict] = {}
        for b, datas in sorted(grouped.get(n.id, {}).items()):
            t = _z(b)
            for k in NODE_KEYS:
                if (pt := _merge([d.get(k) for d in datas])) is not None:
                    series[k].append({"t": t, **pt})
            for gi in sorted({g for d in datas for g in _dict(d.get("gpus"))}):
                for k in GPU_KEYS:
                    pt = _merge([_dict(_dict(d.get("gpus")).get(gi)).get(k) for d in datas])
                    if pt is not None:
                        gpus.setdefault(gi, {key: [] for key in GPU_KEYS})[k].append({"t": t, **pt})
            for ci in {c for d in datas for c in _dict(d.get("cameras")) if str(c).isdigit()}:
                entries = [_dict(_dict(d.get("cameras")).get(ci)) for d in datas]
                cam = cams.setdefault(ci, {"fps": [], "frame_age_s": [], "target_fps": None})
                for k in ("fps", "frame_age_s"):
                    if (pt := _merge([e.get(k) for e in entries])) is not None:
                        cam[k].append({"t": t, **pt})
                targets = [_num(e.get("target_fps")) for e in entries if _num(e.get("target_fps")) is not None]
                if targets:
                    cam["target_fps"] = targets[-1]
        cam_rows = [{"id": int(ci), "name": names.get(int(ci), f"#{ci}"), **c} for ci, c in cams.items()]
        cam_rows.sort(key=lambda c: c["name"])
        out.append({"id": n.id, "name": n.name, "series": {**series, "gpus": gpus}, "cameras": cam_rows,
                    "offline": _offline(db, n, start, now)})
    return {"range": range_key, "bucket_s": bucket_s, "from": _z(start), "to": _z(now), "nodes": out}
```

Catatan: `state` kamera disimpan di sampel (untuk S3) tetapi tidak dikirim di deret S2 — grafik hanya fps & umur
frame. Tes `test_query_merge_state_and_min` memverifikasi min/avg; bila executor ingin mengirim `state` per titik,
itu di luar scope (jangan ditambahkan).

- [ ] **Step 3: Schema + endpoint**

`schemas/monitoring.py`:

```python
from pydantic import ConfigDict, Field


class PointOut(BaseModel):
    t: str
    avg: float | None = None
    max: float | None = None
    min: float | None = None


class GpuSeriesOut(BaseModel):
    util_pct: list[PointOut] = []
    vram_pct: list[PointOut] = []
    temp_c: list[PointOut] = []


class NodeSeriesOut(BaseModel):
    cpu_pct: list[PointOut]
    ram_pct: list[PointOut]
    ms_avg: list[PointOut]
    ms_max: list[PointOut]
    infer_fps: list[PointOut]
    mqtt_backlog: list[PointOut]
    gpus: dict[str, GpuSeriesOut]


class CameraSeriesOut(BaseModel):
    id: int
    name: str
    fps: list[PointOut]
    frame_age_s: list[PointOut]
    target_fps: float | None = None


class OfflineOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    from_: str = Field(alias="from")
    to: str | None = None


class NodeHistoryOut(BaseModel):
    id: int
    name: str
    series: NodeSeriesOut
    cameras: list[CameraSeriesOut]
    offline: list[OfflineOut]


class MonitoringHistoryOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    range: str
    bucket_s: int
    from_: str = Field(alias="from")
    to: str
    nodes: list[NodeHistoryOut]
```

`api/monitoring.py`:

```python
from typing import Literal

from fastapi import Query

from app.schemas.monitoring import MonitoringHistoryOut
from app.services import monitoring_history


@router.get("/history", response_model=MonitoringHistoryOut)
def get_history(range_: Literal["1h", "6h", "24h", "7d"] = Query("6h", alias="range"),
                user=Depends(get_current_user), db=Depends(get_db)):
    """Deret tren Monitoring (riwayat 7 hari, downsample per rentang). Semua user login; read-only."""
    return monitoring_history.query(db, range_)
```

Pastikan response JSON memakai kunci `from` (FastAPI `response_model_by_alias=True` default) — tes endpoint
mengecek `range` & `bucket_s`; tambahkan `assert "from" in r.json()`.

Run: `rtk bash -c "cd backend && .venv/bin/python -m pytest tests -q -m 'not gpu'"` → PASS.

- [ ] **Step 4: Commit**

```bash
rtk git add backend/
rtk git commit -m "feat(monitoring): endpoint riwayat tren per rentang dengan periode offline"
```

---

### Task 5: `LineChart` (SVG)

**Files:**
- Create: `frontend/src/components/LineChart.tsx`
- Modify: `frontend/src/app/theme.scss` (gaya `.lc*`)
- Test: `frontend/src/__tests__/linechart.test.tsx`

**Interfaces:**
- Produces:
  - `type ChartPoint = { t: number; v: number }`
  - `type ChartSeries = { key: string; label: string; color: string; points: ChartPoint[]; dashed?: boolean }`
  - `export const PALETTE = ['#6929c4', '#1192e8', '#005d5d', '#9f1853', '#fa4d56', '#570408']`
  - `LineChart(props: { title: string; series: ChartSeries[]; from: number; to: number; bucketMs: number;
    yMin?: number; yMax?: number; unit?: string; shaded?: { from: number; to: number }[]; height?: number;
    refLine?: { v: number; label: string }; locale: string; testId?: string })`
  - test id: `lc-line-<key>`, `lc-offline`, `lc-ref`, `lc-tip`; svg `role="img"`.

- [ ] **Step 1: Tes (gagal)**

```tsx
import { fireEvent, render, screen } from '@testing-library/react'
import '@testing-library/jest-dom/vitest'
import LineChart, { type ChartSeries } from '../components/LineChart'

const MIN = 60_000
const FROM = Date.UTC(2026, 8, 30, 8, 0)
const TO = FROM + 60 * MIN
const pts = (minutes: number[], v = (i: number) => i) => minutes.map((m, i) => ({ t: FROM + m * MIN, v: v(i) }))

const base = (series: ChartSeries[], extra = {}) => render(
  <LineChart title="CPU" series={series} from={FROM} to={TO} bucketMs={MIN} yMin={0} yMax={100} unit=" %"
    locale="id" testId="chart" {...extra} />)

test('satu path per seri; loncatan > 1,5 bucket jadi celah (M baru)', () => {
  base([{ key: 'cpu', label: 'CPU', color: '#6929c4', points: pts([0, 1, 2, 10, 11]) }])
  const d = screen.getByTestId('lc-line-cpu').getAttribute('d')!
  expect(d.match(/M/g)).toHaveLength(2)  // 0-2 bersambung, 10-11 segmen baru
  expect(d.match(/L/g)).toHaveLength(3)
})

test('seri dashed memakai stroke-dasharray; arsir offline tergambar', () => {
  base([{ key: 'fps', label: 'fps', color: '#1192e8', points: pts([0, 1]) },
        { key: 'target', label: 'target', color: '#8d8d8d', points: pts([0, 1]), dashed: true }],
       { shaded: [{ from: FROM + 20 * MIN, to: FROM + 30 * MIN }] })
  expect(screen.getByTestId('lc-line-target')).toHaveAttribute('stroke-dasharray')
  expect(screen.getByTestId('lc-line-fps')).not.toHaveAttribute('stroke-dasharray')
  expect(screen.getAllByTestId('lc-offline')).toHaveLength(1)
})

test('refLine digambar sebagai garis horizontal putus-putus dan ikut tooltip', () => {
  base([{ key: 'fps', label: 'fps', color: '#1192e8', points: pts([0, 30]) }], { refLine: { v: 50, label: 'target' } })
  const ref = screen.getByTestId('lc-ref')
  expect(ref).toHaveAttribute('stroke-dasharray')
  expect(ref.getAttribute('y1')).toBe(ref.getAttribute('y2'))
  fireEvent.mouseMove(screen.getByRole('img'), { clientX: 300 })
  expect(screen.getByTestId('lc-tip')).toHaveTextContent('target: 50.0 %')
})

test('hover menampilkan tooltip nilai tiap seri; keluar menutup', () => {
  base([{ key: 'cpu', label: 'CPU', color: '#6929c4', points: pts([0, 30, 59], (i) => [10, 55, 90][i]) }])
  const svg = screen.getByRole('img')
  // lebar default 600, padding kiri 40 → x tengah ≈ menit 30
  fireEvent.mouseMove(svg, { clientX: 40 + (600 - 52) / 2 })
  expect(screen.getByTestId('lc-tip')).toHaveTextContent('CPU: 55.0 %')
  fireEvent.mouseLeave(svg)
  expect(screen.queryByTestId('lc-tip')).toBeNull()
})

test('aria-label merangkum nilai terakhir; tanpa data tetap render', () => {
  base([{ key: 'cpu', label: 'CPU', color: '#6929c4', points: pts([0, 1], (i) => [10, 42][i]) }])
  expect(screen.getByRole('img')).toHaveAttribute('aria-label', expect.stringContaining('CPU 42.0 %'))
  base([{ key: 'x', label: 'X', color: '#000', points: [] }])
  expect(screen.getAllByRole('img')).toHaveLength(2)
})
```

Run: `rtk bash -c "cd frontend && npx vitest run src/__tests__/linechart.test.tsx"` → FAIL (import).

- [ ] **Step 2: Implementasi**

```tsx
import { useEffect, useRef, useState } from 'react'

export type ChartPoint = { t: number; v: number }
export type ChartSeries = { key: string; label: string; color: string; points: ChartPoint[]; dashed?: boolean }
export const PALETTE = ['#6929c4', '#1192e8', '#005d5d', '#9f1853', '#fa4d56', '#570408']

const PAD = { l: 40, r: 12, t: 8, b: 22 }

/** 3–5 angka sumbu Y yang "bulat" (1/2/5 × 10^n). */
function ticks(lo: number, hi: number): number[] {
  const raw = (hi - lo) / 4 || 1
  const mag = 10 ** Math.floor(Math.log10(raw))
  const step = [1, 2, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? raw
  const out: number[] = []
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(Number(v.toFixed(6)))
  return out
}

type Props = {
  title: string; series: ChartSeries[]; from: number; to: number; bucketMs: number
  yMin?: number; yMax?: number; unit?: string; shaded?: { from: number; to: number }[]
  height?: number; refLine?: { v: number; label: string }; locale: string; testId?: string
}

/** Grafik garis SVG ringan (tanpa dependensi): celah saat data kosong, arsir offline, tooltip hover. */
export default function LineChart({ title, series, from, to, bucketMs, yMin, yMax, unit = '', shaded = [],
  height = 180, refLine, locale, testId }: Props) {
  const ref = useRef<HTMLDivElement | null>(null)
  const [width, setWidth] = useState(600)
  const [hover, setHover] = useState<number | null>(null)

  useEffect(() => {
    const el = ref.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(([entry]) => {
      const w = Math.round(entry.contentRect.width)
      if (w > 0) setWidth(w)
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const values = [...series.flatMap((s) => s.points.map((p) => p.v)), ...(refLine ? [refLine.v] : [])]
  const lo = yMin ?? Math.min(0, ...values)
  const top = values.length ? Math.max(...values) : lo + 1
  const hi = yMax ?? (top <= lo ? lo + 1 : top * 1.1)
  const w = Math.max(1, width - PAD.l - PAD.r)
  const h = height - PAD.t - PAD.b
  const span = to - from || 1
  const x = (t: number) => PAD.l + ((t - from) / span) * w
  const y = (v: number) => PAD.t + h - ((Math.min(Math.max(v, lo), hi) - lo) / (hi - lo || 1)) * h

  const path = (points: ChartPoint[]) => {
    let d = ''
    let prev: number | null = null
    for (const p of points) {
      d += `${prev === null || p.t - prev > bucketMs * 1.5 ? 'M' : 'L'}${x(p.t).toFixed(1)},${y(p.v).toFixed(1)}`
      prev = p.t
    }
    return d
  }
  const fmtTime = (t: number) => new Date(t).toLocaleString(locale, span > 26 * 3600e3
    ? { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }
    : { hour: '2-digit', minute: '2-digit' })
  const nearest = (s: ChartSeries, t: number) => {
    let best: ChartPoint | null = null
    for (const p of s.points) if (!best || Math.abs(p.t - t) < Math.abs(best.t - t)) best = p
    return best && Math.abs(best.t - t) <= bucketMs ? best : null
  }
  const fmtV = (v: number) => `${v.toFixed(1)}${unit}`
  const aria = `${title}: ${series.map((s) => {
    const last = s.points.at(-1)
    return `${s.label} ${last ? fmtV(last.v) : '—'}`
  }).join(', ')}`

  return (
    <div className="lc" ref={ref} data-testid={testId}>
      <svg width={width} height={height} role="img" aria-label={aria}
        onMouseMove={(e) => {
          const r = e.currentTarget.getBoundingClientRect()
          const t = from + ((e.clientX - r.left - PAD.l) / w) * span
          setHover(t < from || t > to ? null : t)
        }}
        onMouseLeave={() => setHover(null)}>
        {shaded.map((r, i) => {
          const a = x(Math.max(r.from, from))
          const b = x(Math.min(r.to, to))
          return b > a || b === a ? (
            <rect key={i} className="lc__offline" data-testid="lc-offline" x={a} y={PAD.t} width={Math.max(2, b - a)} height={h} />
          ) : null
        })}
        {ticks(lo, hi).map((v) => (
          <g key={v}>
            <line className="lc__grid" x1={PAD.l} x2={PAD.l + w} y1={y(v)} y2={y(v)} />
            <text className="lc__label" x={PAD.l - 6} y={y(v) + 4} textAnchor="end">{v}</text>
          </g>
        ))}
        {[0, 1, 2, 3, 4].map((i) => {
          const t = from + (span * i) / 4
          return (
            <text key={i} className="lc__label" x={x(t)} y={height - 6}
              textAnchor={i === 0 ? 'start' : i === 4 ? 'end' : 'middle'}>{fmtTime(t)}</text>
          )
        })}
        {series.map((s) => (
          <path key={s.key} data-testid={`lc-line-${s.key}`} d={path(s.points)} fill="none" stroke={s.color}
            strokeWidth={1.5} strokeDasharray={s.dashed ? '4 3' : undefined} />
        ))}
        {refLine && (
          <line data-testid="lc-ref" className="lc__ref" x1={PAD.l} x2={PAD.l + w} y1={y(refLine.v)} y2={y(refLine.v)}
            strokeDasharray="4 3" />
        )}
        {hover !== null && <line className="lc__cursor" x1={x(hover)} x2={x(hover)} y1={PAD.t} y2={PAD.t + h} />}
      </svg>
      {hover !== null && (
        <div className="lc__tip" data-testid="lc-tip" style={{ left: Math.max(0, Math.min(x(hover) + 8, width - 170)) }}>
          <div className="lc__tip-time">{fmtTime(hover)}</div>
          {series.map((s) => {
            const p = nearest(s, hover)
            return p && (
              <div key={s.key}><span className="lc__swatch" style={{ background: s.color }} />{s.label}: {fmtV(p.v)}</div>
            )
          })}
          {refLine && <div><span className="lc__swatch lc__swatch--ref" />{refLine.label}: {fmtV(refLine.v)}</div>}
        </div>
      )}
    </div>
  )
}
```

Gaya (akhir `theme.scss`):

```scss
/* LineChart (SVG): grafik tren Monitoring S2. */
.lc {
  position: relative;
  inline-size: 100%;

  svg {
    display: block;
    max-inline-size: 100%;
  }
}

.lc__grid {
  stroke: var(--cds-border-subtle);
  stroke-width: 1;
}

.lc__label {
  fill: var(--cds-text-secondary);
  font-size: 11px;
}

.lc__offline {
  fill: rgba(250, 77, 86, 0.15);
}

.lc__ref {
  stroke: var(--cds-text-secondary);
  stroke-width: 1;
}

.lc__swatch--ref {
  background: var(--cds-text-secondary);
}

.lc__cursor {
  stroke: var(--cds-text-secondary);
  stroke-dasharray: 2 2;
}

.lc__tip {
  position: absolute;
  top: 8px;
  z-index: 1;
  min-inline-size: 150px;
  padding: 8px 12px;
  background: var(--cds-layer-02, #393939);
  border: 1px solid var(--cds-border-subtle);
  color: var(--cds-text-primary);
  font-size: 12px;
  line-height: 1.6;
  pointer-events: none;
}

.lc__tip-time {
  color: var(--cds-text-secondary);
}

.lc__swatch {
  display: inline-block;
  inline-size: 8px;
  block-size: 8px;
  margin-inline-end: 6px;
}
```

Catatan: jsdom `getBoundingClientRect` = 0 dan `ResizeObserver` stub → lebar 600 dipakai; tes hover menghitung
`clientX` dari itu. Bila perhitungan tooltip meleset satu titik, sesuaikan `clientX` tes, jangan melonggarkan
`nearest`.

Run: tes Step 1 → PASS.

- [ ] **Step 3: Commit**

```bash
rtk git add frontend/src/components/LineChart.tsx frontend/src/app/theme.scss frontend/src/__tests__/linechart.test.tsx
rtk git commit -m "feat(monitoring): komponen LineChart SVG tanpa dependensi"
```

---

### Task 6: Tab "Tren" di halaman Monitoring

**Files:**
- Create: `frontend/src/features/monitoring/CurrentTab.tsx`, `frontend/src/features/monitoring/TrendTab.tsx`
- Modify: `frontend/src/features/monitoring/MonitoringPage.tsx`, `frontend/src/api/monitoring.ts`,
  `frontend/src/app/i18n.tsx`, `frontend/src/app/theme.scss`
- Test: `frontend/src/__tests__/monitoring-trend.test.tsx`, `frontend/src/__tests__/monitoring.test.tsx` (tetap hijau)

**Interfaces:**
- Consumes: `LineChart`, `PALETTE` (Task 5); `GET /api/v1/monitoring/history` (Task 4).
- Produces: `getMonitoringHistory(range: HistoryRange): Promise<MonitoringHistory>`; tipe `HistoryRange =
  '1h' | '6h' | '24h' | '7d'`, `HistPoint = { t: string; avg?: number | null; max?: number | null; min?: number | null }`,
  `MonitoringHistory`; `TREND_POLL_MS = 60_000`; test id `mon-tab-current`, `mon-tab-trend`, `trend-range-<r>`,
  `trend-empty`, `trend-error`, `trend-chart-<key>`, `trend-cam-<id>`.

- [ ] **Step 1: Tes (gagal)**

`frontend/src/__tests__/monitoring-trend.test.tsx`:

```tsx
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, useLocation } from 'react-router-dom'
import '@testing-library/jest-dom/vitest'
import { I18nProvider } from '../app/i18n'
import MonitoringPage from '../features/monitoring/MonitoringPage'

const p = (m: number, v: Record<string, number>) => ({ t: new Date(Date.UTC(2026, 8, 30, 7, m)).toISOString(), ...v })
const cam = (id: number) => ({ id, name: `CAM-${id}`, target_fps: 5, fps: [p(0, { min: 4, avg: 5 })],
  frame_age_s: [p(0, { max: 0.3 })] })
const HIST = {
  range: '6h', bucket_s: 60, from: '2026-09-30T02:00:00Z', to: '2026-09-30T08:00:00Z',
  nodes: [{ id: 1, name: 'server',
    series: { cpu_pct: [p(0, { avg: 20, max: 30 })], ram_pct: [p(0, { avg: 18, max: 18 })],
      ms_avg: [p(0, { avg: 8 })], ms_max: [p(0, { max: 19 })], infer_fps: [p(0, { avg: 40 })],
      mqtt_backlog: [p(0, { max: 0 })],
      gpus: { '0': { util_pct: [p(0, { avg: 40, max: 70 })], vram_pct: [p(0, { max: 21 })], temp_c: [p(0, { max: 61 })] } } },
    cameras: [cam(1), cam(2), cam(3), cam(4), cam(5)],
    offline: [{ from: '2026-09-30T07:30:00Z', to: '2026-09-30T07:31:00Z' }] }],
}
const EMPTY = { ...HIST, nodes: [{ ...HIST.nodes[0], cameras: [], offline: [],
  series: { cpu_pct: [], ram_pct: [], ms_avg: [], ms_max: [], infer_fps: [], mqtt_backlog: [], gpus: {} } }] }

let reply: () => Promise<unknown>
let calls: string[]
beforeEach(() => {
  calls = []
  reply = async () => ({ ok: true, status: 200, json: () => Promise.resolve(HIST) })
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    calls.push(String(url))
    if (String(url).includes('/monitoring/history')) return reply()
    return { ok: false, status: 404, json: () => Promise.resolve(null) }
  }))
})
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

function Loc() {
  const l = useLocation()
  return <span data-testid="loc">{l.search}</span>
}
const renderAt = (entry: string) => render(
  <I18nProvider><MemoryRouter initialEntries={[entry]}><MonitoringPage /><Loc /></MemoryRouter></I18nProvider>)

test('?tab=trend membuka Tren: default 6 jam, grafik node + maks 4 kamera, arsir offline; S1 tidak di-polling', async () => {
  renderAt('/monitoring?tab=trend')
  expect(await screen.findByTestId('trend-chart-cpu')).toBeInTheDocument()
  expect(calls.some((u) => u.includes('/monitoring/history?range=6h'))).toBe(true)
  expect(calls.some((u) => /\/monitoring$/.test(u.split('?')[0]))).toBe(false)
  for (const k of ['gpu-0', 'gputemp', 'latency', 'inferfps', 'backlog']) {
    expect(screen.getByTestId(`trend-chart-${k}`)).toBeInTheDocument()
  }
  expect(screen.getAllByTestId(/^trend-cam-\d+$/)).toHaveLength(4)
  expect(screen.getAllByTestId('lc-offline').length).toBeGreaterThan(0)
  expect(screen.getByTestId('trend-range-6h')).toHaveAttribute('aria-pressed', 'true')
})

test('ganti rentang → request baru + URL', async () => {
  renderAt('/monitoring?tab=trend')
  await screen.findByTestId('trend-chart-cpu')
  await userEvent.click(screen.getByTestId('trend-range-24h'))
  await waitFor(() => expect(calls.some((u) => u.includes('range=24h'))).toBe(true))
  expect(screen.getByTestId('loc')).toHaveTextContent('tab=trend')
  expect(screen.getByTestId('loc')).toHaveTextContent('range=24h')
})

test('belum ada sampel → teks kosong', async () => {
  reply = async () => ({ ok: true, status: 200, json: () => Promise.resolve(EMPTY) })
  renderAt('/monitoring?tab=trend')
  expect(await screen.findByTestId('trend-empty')).toBeInTheDocument()
})

test('refresh 60 s; gagal → pesan error, grafik lama tetap', async () => {
  vi.useFakeTimers()
  renderAt('/monitoring?tab=trend')
  await act(async () => { await vi.advanceTimersByTimeAsync(0) })
  expect(screen.getByTestId('trend-chart-cpu')).toBeInTheDocument()
  reply = async () => ({ ok: false, status: 500, json: () => Promise.resolve(null) })
  await act(async () => { await vi.advanceTimersByTimeAsync(60_000) })
  expect(screen.getByTestId('trend-error')).toBeInTheDocument()
  expect(screen.getByTestId('trend-chart-cpu')).toBeInTheDocument()
})

test('klik tab Tren dari Kondisi saat ini mengubah URL', async () => {
  renderAt('/monitoring')
  await userEvent.click(screen.getByRole('tab', { name: 'Tren' }))
  expect(screen.getByTestId('loc')).toHaveTextContent('tab=trend')
})
```

Run: `rtk bash -c "cd frontend && npx vitest run src/__tests__/monitoring-trend.test.tsx"` → FAIL.

- [ ] **Step 2: API + i18n**

`api/monitoring.ts` tambah:

```ts
export type HistoryRange = '1h' | '6h' | '24h' | '7d'
export type HistPoint = { t: string; avg?: number | null; max?: number | null; min?: number | null }
export type GpuHistory = { util_pct: HistPoint[]; vram_pct: HistPoint[]; temp_c: HistPoint[] }
export type NodeHistory = { id: number; name: string
  series: { cpu_pct: HistPoint[]; ram_pct: HistPoint[]; ms_avg: HistPoint[]; ms_max: HistPoint[]
    infer_fps: HistPoint[]; mqtt_backlog: HistPoint[]; gpus: Record<string, GpuHistory> }
  cameras: { id: number; name: string; target_fps: number | null; fps: HistPoint[]; frame_age_s: HistPoint[] }[]
  offline: { from: string; to: string | null }[] }
export type MonitoringHistory = { range: HistoryRange; bucket_s: number; from: string; to: string; nodes: NodeHistory[] }

export async function getMonitoringHistory(range: HistoryRange): Promise<MonitoringHistory> {
  const res = await apiFetch(`/monitoring/history?range=${range}`)
  if (!res.ok) throw new Error(`monitoring history failed: ${res.status}`)
  return res.json()
}
```

i18n (id / en, kunci sama):

```
'mon.tab.current' 'Kondisi saat ini' / 'Current status'
'mon.tab.trend' 'Tren' / 'Trends'
'trend.range.1h' '1 jam' / '1 hour', 'trend.range.6h' '6 jam' / '6 hours', 'trend.range.24h' '24 jam' / '24 hours',
'trend.range.7d' '7 hari' / '7 days'
'trend.node' 'Node'
'trend.cameras' 'Kamera' / 'Cameras'
'trend.updated' 'Diperbarui {time} · riwayat 7 hari' / 'Updated {time} · 7-day history'
'trend.empty' 'Belum ada data riwayat — sampel pertama muncul ±1 menit setelah node mengirim heartbeat' /
  'No history yet — the first sample appears about 1 minute after the node sends a heartbeat'
'trend.error' 'Gagal memuat riwayat — menampilkan data terakhir' / 'Failed to load history — showing last data'
'trend.offlineNote' 'Arsir merah = node offline' / 'Red shading = node offline'
'trend.chart.cpu' 'CPU & RAM' , 'trend.chart.gpu' 'GPU {idx} — util & VRAM', 'trend.chart.gputemp' 'Suhu GPU' / 'GPU temperature',
'trend.chart.latency' 'Latensi inferensi' / 'Inference latency', 'trend.chart.inferfps' 'fps inferensi' / 'Inference fps',
'trend.chart.backlog' 'Backlog MQTT' / 'MQTT backlog', 'trend.chart.camfps' 'fps' , 'trend.chart.camage' 'Umur frame' / 'Frame age'
'trend.s.cpu' 'CPU', 'trend.s.ram' 'RAM', 'trend.s.util' 'Util', 'trend.s.vram' 'VRAM', 'trend.s.avg' 'rata-rata' / 'avg',
'trend.s.max' 'maks' / 'max', 'trend.s.fps' 'aktual (min)' / 'actual (min)', 'trend.s.target' 'target'
```

- [ ] **Step 3: `CurrentTab` + `MonitoringPage` bertab**

Pindahkan seluruh isi `MonitoringPage` saat ini (state `data/failed/onlyIssues`, efek polling 10 s, dan JSX setelah
header — notifikasi error sampai kartu layanan) ke `CurrentTab.tsx` (`export default function CurrentTab()`),
tanpa mengubah perilaku/test id. `MonitoringPage.tsx` menjadi:

```tsx
import { Tab, TabList, TabPanel, TabPanels, Tabs } from '@carbon/react'
import { useSearchParams } from 'react-router-dom'
import { useT } from '../../app/i18n'
import CurrentTab from './CurrentTab'
import TrendTab from './TrendTab'

const TABS = ['current', 'trend'] as const
type MonTab = (typeof TABS)[number]

/** System › Monitoring: "Kondisi saat ini" (S1) dan "Tren" (S2). Hanya tab aktif yang di-mount → polling terpisah. */
export default function MonitoringPage() {
  const { t } = useT()
  const [params, setParams] = useSearchParams()
  const raw = params.get('tab')
  const tab: MonTab = TABS.includes(raw as MonTab) ? (raw as MonTab) : 'current'
  return (
    <div className="app-page mon-page">
      <div className="app-page__head">
        <div>
          <h1 className="app-page__title">{t('mon.title')}</h1>
          <p className="app-page__sub">{t('mon.subtitle')}</p>
        </div>
      </div>
      <Tabs selectedIndex={TABS.indexOf(tab)}
        onChange={({ selectedIndex }) => {
          const next = TABS[selectedIndex]
          if (next !== tab) setParams({ tab: next })
        }}>
        <TabList aria-label={t('mon.title')}>
          <Tab data-testid="mon-tab-current">{t('mon.tab.current')}</Tab>
          <Tab data-testid="mon-tab-trend">{t('mon.tab.trend')}</Tab>
        </TabList>
        <TabPanels>
          <TabPanel className="mon-tabpanel">{tab === 'current' && <CurrentTab />}</TabPanel>
          <TabPanel className="mon-tabpanel">{tab === 'trend' && <TrendTab />}</TabPanel>
        </TabPanels>
      </Tabs>
    </div>
  )
}
```

`CurrentTab` membungkus isinya dengan `<div className="mon-page">` (flex + gap 16) agar jarak antar blok sama seperti
sebelumnya; `.mon-tabpanel.cds--tab-content { padding: 16px 0 0 }`.

Jalankan `monitoring.test.tsx` lama → harus tetap PASS (default tab current).

- [ ] **Step 4: `TrendTab.tsx`**

```tsx
import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Dropdown, InlineNotification, MultiSelect } from '@carbon/react'
import { useT, type TKey } from '../../app/i18n'
import { getMonitoringHistory, type HistPoint, type HistoryRange, type MonitoringHistory } from '../../api/monitoring'
import LineChart, { PALETTE, type ChartSeries } from '../../components/LineChart'

export const TREND_POLL_MS = 60_000
const RANGES: HistoryRange[] = ['1h', '6h', '24h', '7d']
const MAX_CAMS = 4

const pts = (arr: HistPoint[], k: 'avg' | 'max' | 'min') =>
  arr.filter((p) => p[k] != null).map((p) => ({ t: Date.parse(p.t), v: p[k] as number }))

/** Tab Tren: grafik riwayat per node (hardware, inferensi, kamera). Refresh 60 s; gagal → data terakhir tetap. */
export default function TrendTab() {
  const { t, locale } = useT()
  const [params, setParams] = useSearchParams()
  const raw = params.get('range')
  const range: HistoryRange = RANGES.includes(raw as HistoryRange) ? (raw as HistoryRange) : '6h'
  const [data, setData] = useState<MonitoringHistory | null>(null)
  const [failed, setFailed] = useState(false)
  const [nodeId, setNodeId] = useState<number | null>(null)
  const [camIds, setCamIds] = useState<number[] | null>(null) // null = default (maks 4 pertama)

  useEffect(() => {
    let alive = true
    const load = () => getMonitoringHistory(range)
      .then((d) => { if (alive) { setData(d); setFailed(false) } })
      .catch(() => { if (alive) setFailed(true) })
    load()
    const timer = setInterval(load, TREND_POLL_MS)
    return () => { alive = false; clearInterval(timer) }
  }, [range])

  const node = data?.nodes.find((n) => n.id === nodeId) ?? data?.nodes[0]
  const from = data ? Date.parse(data.from) : 0
  const to = data ? Date.parse(data.to) : 0
  const bucketMs = (data?.bucket_s ?? 60) * 1000
  const shaded = (node?.offline ?? []).map((o) => ({ from: Date.parse(o.from), to: o.to ? Date.parse(o.to) : to }))
  const s = node?.series
  const empty = !!node && !!s && Object.entries(s).every(([k, v]) =>
    k === 'gpus' ? Object.keys(v as object).length === 0 : (v as HistPoint[]).length === 0) && node.cameras.length === 0
  const cams = node ? node.cameras.filter((c) => (camIds ?? node.cameras.slice(0, MAX_CAMS).map((x) => x.id)).includes(c.id)) : []
  const common = { from, to, bucketMs, shaded, locale }
  const line = (key: string, label: string, i: number, points: ChartSeries['points'], dashed = false): ChartSeries =>
    ({ key, label, color: PALETTE[i % PALETTE.length], points, dashed })

  const card = (key: string, title: string, chart: JSX.Element) => (
    <section key={key} className="mon-card" data-testid={`trend-chart-${key}`}>
      <h3 className="mon-card__title">{title}</h3>
      {chart}
    </section>
  )

  return (
    <div className="mon-page">
      <div className="trend-toolbar">
        <div className="lv-chips" role="group" aria-label={t('mon.tab.trend')}>
          {RANGES.map((r) => (
            <button key={r} type="button" data-testid={`trend-range-${r}`} aria-pressed={range === r}
              className={range === r ? 'lv-chip lv-chip--sel' : 'lv-chip'}
              onClick={() => setParams({ tab: 'trend', range: r })}>{t(`trend.range.${r}` as TKey)}</button>
          ))}
        </div>
        {data && data.nodes.length > 1 && (
          <Dropdown id="trend-node" titleText={t('trend.node')} label="" size="sm" items={data.nodes}
            itemToString={(n) => n?.name ?? ''} selectedItem={node}
            onChange={({ selectedItem }) => { setNodeId(selectedItem?.id ?? null); setCamIds(null) }} />
        )}
        {data && (
          <span className="en-muted">
            {t('trend.updated').replace('{time}', new Date(data.to).toLocaleTimeString(locale))} · {t('trend.offlineNote')}
          </span>
        )}
      </div>
      {failed && <div data-testid="trend-error"><InlineNotification kind="error" lowContrast hideCloseButton title={t('trend.error')} /></div>}
      {empty && <p className="en-muted" data-testid="trend-empty">{t('trend.empty')}</p>}
      {node && s && !empty && (
        <>
          <div className="trend-grid">
            {card('cpu', t('trend.chart.cpu'), <LineChart {...common} title={t('trend.chart.cpu')} yMin={0} yMax={100} unit=" %"
              series={[line('cpu', t('trend.s.cpu'), 0, pts(s.cpu_pct, 'avg')), line('ram', t('trend.s.ram'), 1, pts(s.ram_pct, 'avg'))]} />)}
            {Object.entries(s.gpus).map(([idx, g]) => card(`gpu-${idx}`, t('trend.chart.gpu').replace('{idx}', idx),
              <LineChart {...common} title={t('trend.chart.gpu').replace('{idx}', idx)} yMin={0} yMax={100} unit=" %"
                series={[line('util', t('trend.s.util'), 0, pts(g.util_pct, 'avg')), line('vram', t('trend.s.vram'), 1, pts(g.vram_pct, 'max'))]} />))}
            {card('gputemp', t('trend.chart.gputemp'), <LineChart {...common} title={t('trend.chart.gputemp')} unit=" °C"
              series={Object.entries(s.gpus).map(([idx, g], i) => line(`temp-${idx}`, `GPU ${idx}`, i, pts(g.temp_c, 'max')))} />)}
            {card('latency', t('trend.chart.latency'), <LineChart {...common} title={t('trend.chart.latency')} unit=" ms"
              series={[line('msavg', t('trend.s.avg'), 0, pts(s.ms_avg, 'avg')), line('msmax', t('trend.s.max'), 3, pts(s.ms_max, 'max'))]} />)}
            {card('inferfps', t('trend.chart.inferfps'), <LineChart {...common} title={t('trend.chart.inferfps')}
              series={[line('ifps', t('trend.chart.inferfps'), 2, pts(s.infer_fps, 'avg'))]} />)}
            {card('backlog', t('trend.chart.backlog'), <LineChart {...common} title={t('trend.chart.backlog')}
              series={[line('backlog', t('trend.chart.backlog'), 4, pts(s.mqtt_backlog, 'max'))]} />)}
          </div>
          {node.cameras.length > 0 && (
            <section className="mon-card">
              <header className="mon-card__head">
                <h3 className="mon-card__title">{t('trend.cameras')}</h3>
                <MultiSelect<NonNullable<typeof node>['cameras'][number]> id="trend-cams" titleText="" label={t('trend.cameras')}
                  size="sm" items={node.cameras} itemToString={(c) => c?.name ?? ''} initialSelectedItems={cams}
                  onChange={({ selectedItems }) => setCamIds((selectedItems ?? []).slice(0, MAX_CAMS).map((c) => c.id))} />
              </header>
              <div className="trend-cams">
                {cams.map((c) => (
                  <div key={c.id} className="trend-cam" data-testid={`trend-cam-${c.id}`}>
                    <h4 className="mon-group__title">{c.name}</h4>
                    <div className="trend-cam__charts">
                      <LineChart {...common} height={140} title={`${c.name} ${t('trend.chart.camfps')}`} yMin={0}
                        series={[line('fps', t('trend.s.fps'), 1, pts(c.fps, 'min'))]}
                        refLine={c.target_fps != null ? { v: c.target_fps, label: t('trend.s.target') } : undefined} />
                      <LineChart {...common} height={140} title={`${c.name} ${t('trend.chart.camage')}`} yMin={0} unit=" s"
                        series={[line('age', t('trend.chart.camage'), 3, pts(c.frame_age_s, 'max'))]} />
                    </div>
                  </div>
                ))}
              </div>
            </section>
          )}
        </>
      )}
    </div>
  )
}
```

Catatan untuk executor:
- `JSX.Element` → gunakan `ReactElement` dari `react` bila tipe global `JSX` tidak tersedia.
- Default kamera: kamera yang punya deret (backend sudah hanya mengirim kamera dengan sampel), maks 4, urut nama.

Gaya (akhir `theme.scss`):

```scss
/* Tab Tren Monitoring (S2). */
.mon-tabpanel.cds--tab-content {
  padding: 16px 0 0;
}

.trend-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px 16px;
}

.trend-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(420px, 100%), 1fr));
  gap: 16px;
}

.trend-cams {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.trend-cam__charts {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(320px, 100%), 1fr));
  gap: 16px;
}
```

Run: `rtk bash -c "cd frontend && npx vitest run"` → PASS semua (termasuk `monitoring.test.tsx` lama).

- [ ] **Step 5: Commit**

```bash
rtk git add frontend/src
rtk git commit -m "feat(monitoring): tab Tren dengan grafik hardware, inferensi, dan kamera"
```

---

### Task 7: Verifikasi, dokumentasi, push

**Files:**
- Modify: `README.md` (bagian Monitoring Resource), `docs/runbooks/monitoring.md`, `ROADMAP.md`, `CHANGELOG.md`

- [ ] **Step 1: Suite penuh**

```bash
rtk bash -c "cd backend && .venv/bin/python -m pytest tests -q -m 'not gpu' > /tmp/be.log 2>&1; grep -oE '[0-9]+ (passed|failed)[^|]*' /tmp/be.log | tail -1"
rtk backend/.venv/bin/python -m pytest vision/tests -q -m "not gpu"
rtk bash -c "cd frontend && npx vitest run && npm run build && npm run lint"
```

Expected: backend > 532, vision 233 (3 deselected, tidak berubah), frontend > 211, build 0, lint tanpa error baru;
durasi backend tidak naik berarti. `rtk git diff --stat main -- vision` kosong.

- [ ] **Step 2: Cek visual**

Dev server + stub API (atau backend lokal dengan sampel tiruan) → `/monitoring?tab=trend` 1440 px & 390 px:
halaman tanpa overflow horizontal, grafik mengikuti lebar kartu, tooltip hover, arsir offline. Simpan
`docs/evidence/2026-09-30-monitoring-trend-*.png`. Matikan server dev.

- [ ] **Step 3: Dokumentasi**

- `README.md` bagian Monitoring: paragraf tab **Tren** (rentang 1 jam–7 hari, agregasi per menit, retensi 7 hari,
  arsir = node offline, celah = tidak ada data).
- `docs/runbooks/monitoring.md`: cara membaca grafik (fps min vs target, ms maks = lonjakan), catatan data hilang ≤
  1 menit saat API restart, cara cek tabel (`SELECT count(*) FROM monitoring_sample`), dan rollback migrasi 0019.
- `ROADMAP.md`: baris **MO2** setelah `MO1`:
  `| MO2 | Monitoring Resource S2 (riwayat 7 hari + grafik tren) | [ ] menunggu deploy + verifikasi user | — | spec + plan 2026-09-30; migrasi 0019, restart API | — |`
- `CHANGELOG.md`: entri teratas `### Monitoring Resource S2 (2026-09-30)` — konteks, perubahan, file, bukti suite
  (angka nyata), dampak (1 thread sampler, ±1.440 baris/node/hari, retensi 7 hari), deploy (migrasi 0019 + restart
  API, vision tidak), rollback (`alembic downgrade 0018`).

- [ ] **Step 4: Commit + push (berhenti di sini)**

```bash
rtk git add README.md ROADMAP.md CHANGELOG.md docs/runbooks/monitoring.md docs/evidence
rtk git commit -m "docs(monitoring): README, runbook, ROADMAP, CHANGELOG Monitoring S2"
rtk git push -u origin feat/monitoring-s2
```

Deploy (alembic 0019 + restart API), uji lapangan, dan merge dilakukan sesi perencana — **jangan** deploy atau merge.
