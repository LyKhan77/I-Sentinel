# Monitoring Resource S3 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Aturan kesehatan yang bisa diatur (8 aturan) dievaluasi tiap menit dari sampel S2; pelanggaran yang berlangsung sepanjang durasi menjadi alert (event web + Telegram per aturan) dan pulih setelah 2 menit normal; tab "Aturan & alert" dan badge tile Live View/TV.

**Architecture:** `health_rules` (setting `health_rules`, katalog tetap + batas) menjadi satu sumber ambang — dipakai `monitoring.snapshot` (S1) dan `health_alerts.evaluate`. `evaluate` dipanggil `HistorySampler.run_once` setelah menulis sampel: membaca jendela sampel per node, menyalakan/memulihkan baris `health_alert` (migrasi 0020) secara **stateless dari data jendela** (idempoten), memancarkan event `system` `payload.kind = "health"` + Telegram. Frontend: `AlertsTab` (tab ketiga Monitoring), hook `useCameraHealthAlerts` untuk badge `CameraTile`, label notifikasi kesehatan.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, pytest; React 19 + TypeScript + Carbon + Vitest.

**Spec:** `docs/superpowers/specs/2026-09-30-monitoring-s3-design.md`

## Global Constraints

- Tanpa dependensi baru. Satu migrasi: **0020** (`down_revision = "0019"`), tabel `health_alert`.
- Katalog aturan & default persis tabel spec §3.1 (kunci: `camera_no_frames`, `camera_low_fps`, `gpu_temp`,
  `gpu_vram`, `node_ram`, `node_cpu`, `infer_latency`, `mqtt_backlog`); `duration_min` 1–60; severity
  `warning|critical`; semua default `enabled: true`.
- Menyala: **setiap** menit selesai dalam jendela `duration_min` punya sampel node dan melanggar. Pulih: `RESOLVE_MIN = 2`
  menit terakhir punya sampel dan normal. Evaluasi **stateless dari jendela** → dua kali evaluasi di menit yang sama tidak
  mengubah hasil.
- Node `offline` **atau** tanpa sampel sama sekali di jendela lookback → **ditahan** (tidak menyala, tidak pulih, tidak
  ditutup).
- Event kesehatan = `type: "system"`, `payload.kind = "health"`, `payload.state ∈ {"firing","resolved"}`; resolved
  severity `info`. Event kesehatan **tidak** membuat chip/banner node offline dan **tidak** memengaruhi arsir S2.
- Telegram hanya bila `telegram: true` untuk aturan itu (saat menyala & pulih); penutupan karena aturan dinonaktifkan /
  target hilang tanpa Telegram. Tanpa pengingat ulang.
- `GET /monitoring/rules`, `GET /monitoring/alerts` semua user; `PUT /monitoring/rules` admin (`require_admin`).
- Halaman S1 memakai ambang `health_rules` (default `camera_low_fps` 50 % → issue `low_fps` S1 kini < 50 % target —
  perubahan kontrak disengaja).
- String UI lewat `i18n.tsx` (id + en); REST lewat `src/api/*`; 390 px tanpa overflow.
- Commit Conventional Commits **tanpa** atribusi AI; prefix `rtk`; jangan `uv sync`/`uv lock`.
- Baseline `main` `a3693db`: backend 549, vision 233 (3 deselected), frontend 223, build 0.

## Review Focus

1. **Restart API / sampel belum ada** tidak boleh menutup atau memulihkan alert aktif (tahan bila node tanpa sampel di
   jendela) — tes Task 3.
2. **Satu node mati** tidak boleh memicu belasan alert kamera/GPU (ditahan saat offline) — tes Task 3.
3. **Evaluasi ganda di menit yang sama** (restart sampler, dua proses) tidak membuat alert/event/Telegram ganda — tes
   Task 3.
4. **Event kesehatan di notifikasi web** tidak boleh menyalakan chip "Node X offline" (provider saat ini membuat chip
   untuk semua event `system` non-pulih) — tes Task 6.
5. **Nilai aturan rusak di DB / PUT di luar batas** tidak boleh mematikan evaluasi atau halaman S1 — tes Task 1 & 4.

---

## File Structure

| File | Tanggung jawab |
|---|---|
| Create `backend/app/services/health_rules.py` | Katalog aturan, `get`/`put` + validasi |
| Modify `backend/app/services/monitoring.py` | Ambang dari `health_rules`; helper `analyzed_camera_ids(db)` |
| Create `backend/alembic/versions/0020_health_alert.py`, `backend/app/models/health_alert.py` | Tabel alert |
| Create `backend/app/services/health_alerts.py` | `evaluate`, emit event, Telegram, `prune` |
| Modify `backend/app/services/monitoring_history.py` | Panggil `evaluate` + prune alert di sampler |
| Modify `backend/app/schemas/monitoring.py`, `backend/app/api/monitoring.py` | Rules/alerts API |
| Create `backend/tests/test_health_rules.py`, `test_health_alerts.py`, `test_migration_0020.py` | Tes backend |
| Create `frontend/src/features/monitoring/AlertsTab.tsx`, `useCameraHealthAlerts.ts` | Tab + hook badge |
| Modify `frontend/src/features/monitoring/MonitoringPage.tsx`, `frontend/src/api/monitoring.ts` | Tab ketiga, API |
| Modify `frontend/src/features/live/LiveWall.tsx` | Badge kesehatan di `CameraTile` |
| Modify `frontend/src/features/notifications/{labels.ts,EventAlertsProvider.tsx}` | Label & guard event kesehatan |
| Modify `frontend/src/app/i18n.tsx`, `app/theme.scss` | String & gaya |
| Create `frontend/src/__tests__/monitoring-alerts.test.tsx` | Tes frontend |

---

### Task 1: `health_rules` + ambang halaman S1

**Files:**
- Create: `backend/app/services/health_rules.py`
- Modify: `backend/app/services/monitoring.py`
- Test: `backend/tests/test_health_rules.py`, `backend/tests/test_monitoring.py`

**Interfaces:**
- Produces:
  - `health_rules.CATALOG: dict[str, dict]` — per rule `{"target": "camera"|"gpu"|"node", "unit": str, "min": float,
    "max": float, "default": {"enabled", "threshold", "duration_min", "severity", "telegram"}}` (urutan = urutan UI).
  - `health_rules.get(db) -> dict[str, dict]` — nilai efektif `{enabled, threshold, duration_min, severity, telegram}`.
  - `health_rules.put(db, patch: dict[str, dict]) -> dict[str, dict]` — `ValueError(msg)` bila kunci/nilai tidak valid.
  - `health_rules.as_list(rules) -> list[dict]` — efektif + `rule, unit, min, max, target` (untuk API).
  - `monitoring.analyzed_camera_ids(db) -> set[int]`.

- [ ] **Step 1: Tes (gagal)**

`backend/tests/test_health_rules.py`:

```python
import pytest

from app.models.setting import Setting
from app.services import health_rules as hr


def test_defaults_match_catalog():
    rules = hr.get_defaults()
    assert list(rules) == ["camera_no_frames", "camera_low_fps", "gpu_temp", "gpu_vram", "node_ram", "node_cpu",
                           "infer_latency", "mqtt_backlog"]
    assert rules["camera_no_frames"] == {"enabled": True, "threshold": 30, "duration_min": 2,
                                         "severity": "critical", "telegram": True}
    assert rules["gpu_temp"]["threshold"] == 85 and rules["gpu_temp"]["telegram"] is True
    assert rules["camera_low_fps"]["threshold"] == 50 and rules["camera_low_fps"]["telegram"] is False
    assert rules["infer_latency"]["threshold"] == 50 and rules["mqtt_backlog"]["threshold"] == 0


def test_get_merges_stored_and_replaces_corrupt(db):
    db.add(Setting(key=hr.KEY, value={"gpu_temp": {"threshold": 80, "telegram": False},
                                      "node_cpu": {"threshold": "abc", "duration_min": 999, "severity": "loud"},
                                      "unknown_rule": {"enabled": False}}))
    db.commit()
    rules = hr.get(db)
    assert rules["gpu_temp"]["threshold"] == 80 and rules["gpu_temp"]["telegram"] is False
    assert rules["gpu_temp"]["duration_min"] == 5  # default untuk field yang tidak disimpan
    assert rules["node_cpu"] == hr.get_defaults()["node_cpu"]  # nilai rusak → default
    assert "unknown_rule" not in rules


def test_put_partial_and_validation(db):
    out = hr.put(db, {"gpu_temp": {"threshold": 75, "duration_min": 3}, "mqtt_backlog": {"enabled": False}})
    assert out["gpu_temp"]["threshold"] == 75 and out["gpu_temp"]["duration_min"] == 3
    assert out["mqtt_backlog"]["enabled"] is False
    assert hr.get(db)["gpu_temp"]["threshold"] == 75  # tersimpan
    for bad in ({"nope": {"enabled": True}}, {"gpu_temp": {"threshold": 200}}, {"gpu_temp": {"duration_min": 0}},
                {"gpu_temp": {"severity": "info"}}, {"gpu_temp": {"enabled": "yes"}}, {"gpu_temp": {"color": 1}}):
        with pytest.raises(ValueError):
            hr.put(db, bad)
    assert hr.get(db)["gpu_temp"]["threshold"] == 75  # PUT gagal tidak mengubah apa pun
```

Tambahkan di `backend/tests/test_monitoring.py`:

```python
def test_page_thresholds_follow_health_rules(db):
    from app.services import health_rules
    n = _node(db, hw={"gpus": [{"idx": 0, "temp_c": 80, "vram_used_mb": 1, "vram_total_mb": 10}], "host": {}})
    assert "gpu_hot" not in monitoring.snapshot(db, now=NOW)["nodes"][0]["issues"]  # default 85 °C
    health_rules.put(db, {"gpu_temp": {"threshold": 75}})
    monitoring.reset_cache()
    assert "gpu_hot" in monitoring.snapshot(db, now=NOW)["nodes"][0]["issues"]
```

Ubah tes parametrik S1 `({"fps": 3.0}, "low_fps", "warning")` menjadi `({"fps": 2.0}, "low_fps", "warning")`
(ambang default kini 50 % dari target 5.0 → 2.5) dan tambahkan kasus `({"fps": 3.0}, None, "ok")` bila bentuk
parametrik mengizinkan — atau tes terpisah bahwa fps 3.0/5.0 kini sehat.

Run: `rtk bash -c "cd backend && .venv/bin/python -m pytest tests/test_health_rules.py tests/test_monitoring.py -q"`
Expected: FAIL — `ImportError: cannot import name 'health_rules'`.

- [ ] **Step 2: Implementasi `health_rules.py`**

```python
"""Aturan kesehatan Monitoring (S3): katalog tetap + nilai yang bisa diatur (tabel setting, key "health_rules").

Satu sumber ambang untuk halaman "Kondisi saat ini" (S1) dan evaluator alert. Nilai tersimpan yang rusak diganti
default saat dibaca, jadi data buruk di DB tidak mematikan evaluasi atau halaman.
"""
from __future__ import annotations

import logging

from app.models.setting import Setting

logger = logging.getLogger(__name__)

KEY = "health_rules"
SEVERITIES = ("warning", "critical")
DURATION_RANGE = (1, 60)
FIELDS = ("enabled", "threshold", "duration_min", "severity", "telegram")


def _rule(target, unit, lo, hi, threshold, duration, severity, telegram):
    return {"target": target, "unit": unit, "min": lo, "max": hi,
            "default": {"enabled": True, "threshold": threshold, "duration_min": duration,
                        "severity": severity, "telegram": telegram}}


CATALOG: dict[str, dict] = {
    "camera_no_frames": _rule("camera", "s", 10, 600, 30, 2, "critical", True),
    "camera_low_fps": _rule("camera", "%", 10, 100, 50, 10, "warning", False),
    "gpu_temp": _rule("gpu", "°C", 50, 110, 85, 5, "critical", True),
    "gpu_vram": _rule("gpu", "%", 50, 100, 90, 10, "warning", False),
    "node_ram": _rule("node", "%", 50, 100, 90, 10, "warning", False),
    "node_cpu": _rule("node", "%", 50, 100, 90, 10, "warning", False),
    "infer_latency": _rule("node", "ms", 5, 2000, 50, 5, "warning", False),
    "mqtt_backlog": _rule("node", "", 0, 10000, 0, 5, "warning", True),
}


def get_defaults() -> dict[str, dict]:
    return {k: dict(c["default"]) for k, c in CATALOG.items()}


def _check(rule: str, field: str, value):
    """Nilai field valid → dikembalikan (dinormalkan); tidak valid → ValueError."""
    c = CATALOG[rule]
    if field in ("enabled", "telegram"):
        if not isinstance(value, bool):
            raise ValueError(f"{rule}.{field} must be a boolean")
        return value
    if field == "severity":
        if value not in SEVERITIES:
            raise ValueError(f"{rule}.severity must be one of {SEVERITIES}")
        return value
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{rule}.{field} must be a number")
    lo, hi = (c["min"], c["max"]) if field == "threshold" else DURATION_RANGE
    if field == "duration_min" and value != int(value):
        raise ValueError(f"{rule}.duration_min must be an integer")
    if not lo <= value <= hi:
        raise ValueError(f"{rule}.{field} must be within {lo}-{hi}")
    return int(value) if field == "duration_min" else value


def _stored(db) -> dict:
    row = db.get(Setting, KEY)
    return dict(row.value or {}) if row is not None and isinstance(row.value, dict) else {}


def get(db) -> dict[str, dict]:
    out = get_defaults()
    for rule, fields in _stored(db).items():
        if rule not in CATALOG or not isinstance(fields, dict):
            continue
        for field, value in fields.items():
            if field not in FIELDS:
                continue
            try:
                out[rule][field] = _check(rule, field, value)
            except ValueError:
                logger.warning("health rule %s.%s rusak (%r) — memakai default", rule, field, value)
    return out


def put(db, patch: dict) -> dict[str, dict]:
    if not isinstance(patch, dict):
        raise ValueError("body must be an object")
    stored = _stored(db)
    for rule, fields in patch.items():
        if rule not in CATALOG:
            raise ValueError(f"unknown rule {rule!r}")
        if not isinstance(fields, dict):
            raise ValueError(f"{rule} must be an object")
        for field, value in fields.items():
            if field not in FIELDS:
                raise ValueError(f"unknown field {rule}.{field}")
            _check(rule, field, value)
    for rule, fields in patch.items():  # validasi dulu semua, baru tulis (PUT gagal tidak mengubah apa pun)
        stored[rule] = {**(stored.get(rule) if isinstance(stored.get(rule), dict) else {}), **fields}
    row = db.get(Setting, KEY)
    if row is None:
        db.add(Setting(key=KEY, value=stored))
    else:
        row.value = stored
    db.commit()
    return get(db)


def as_list(rules: dict[str, dict]) -> list[dict]:
    return [{"rule": k, **rules[k], "unit": c["unit"], "min": c["min"], "max": c["max"], "target": c["target"]}
            for k, c in CATALOG.items()]
```

- [ ] **Step 3: Ambang halaman S1 dari `health_rules`**

Di `monitoring.py`:
- Ekstrak blok `analyzed_ids` di `snapshot` menjadi fungsi modul
  `def analyzed_camera_ids(db) -> set[int]` (zona `active` dengan `behaviors` list tidak kosong; pertahankan fallback
  exception yang ada) dan pakai di `snapshot`.
- `snapshot` membaca `rules = health_rules.get(db)` (dalam `try`; gagal → `health_rules.get_defaults()`) dan membuat
  `th = {"frame_stale_s": rules["camera_no_frames"]["threshold"], "low_fps_ratio": rules["camera_low_fps"]["threshold"] / 100,
  "gpu_temp_c": rules["gpu_temp"]["threshold"], "vram_pct": rules["gpu_vram"]["threshold"],
  "ram_pct": rules["node_ram"]["threshold"], "cpu_pct": rules["node_cpu"]["threshold"]}`.
- `_camera_row(..., th)` dan `_node_row(node, now, th)` memakai `th[...]` menggantikan `FRAME_STALE_S`,
  `LOW_FPS_RATIO`, `GPU_TEMP_WARN_C`, `VRAM_WARN_PCT`, `RAM_WARN_PCT`, `CPU_WARN_PCT` (hapus konstanta itu;
  `RECONNECT_WARN`, `HEARTBEAT_LATE_S` tetap). Beri `th` default `None` → `_default_thresholds()` agar pemanggil lain
  (bila ada) tidak rusak.

Run: `rtk bash -c "cd backend && .venv/bin/python -m pytest tests -q -m 'not gpu'"` → PASS.

- [ ] **Step 4: Commit**

```bash
rtk git add backend/
rtk git commit -m "feat(monitoring): aturan kesehatan yang bisa diatur sebagai sumber ambang halaman"
```

---

### Task 2: Migrasi 0020 + model `HealthAlert`

**Files:**
- Create: `backend/alembic/versions/0020_health_alert.py`, `backend/app/models/health_alert.py`
- Modify: `backend/app/models/__init__.py`
- Test: `backend/tests/test_migration_0020.py`

**Interfaces:**
- Produces: `HealthAlert(id, rule: str, target: str, node_id: int, camera_id: int | None, label: str, severity: str,
  value: float | None, threshold: float, started_at: datetime, resolved_at: datetime | None)`.

- [ ] **Step 1: Tes migrasi (gagal)** — pola `test_migration_0019.py`: tabel `node` minimal + PRAGMA FK, `upgrade`,
  insert satu alert, unique `(rule, target, started_at)` menolak duplikat, hapus node → alert ikut terhapus (cascade),
  `downgrade` → tabel hilang.

```python
"""0020: tabel health_alert (alert kesehatan Monitoring S3)."""
import importlib.util
import pathlib

import sqlalchemy as sa

_PATH = pathlib.Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0020_health_alert.py"
_spec = importlib.util.spec_from_file_location("mig0020", _PATH)
mig = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mig)


def test_upgrade_downgrade_unique_and_cascade():
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
    row = ("INSERT INTO health_alert (rule, target, node_id, label, severity, threshold, started_at) "
           "VALUES ('gpu_temp', 'gpu:1:0', 1, 'GPU 0 · server', 'critical', 85, '2026-09-30 08:00:00')")
    with engine.begin() as c:
        c.execute(sa.text(row))
    with engine.begin() as c:
        try:
            c.execute(sa.text(row))
            raise AssertionError("duplikat (rule, target, started_at) seharusnya ditolak")
        except sa.exc.IntegrityError:
            pass
    with engine.begin() as c:
        c.execute(sa.text("DELETE FROM node WHERE id = 1"))
        assert c.execute(sa.text("SELECT count(*) FROM health_alert")).scalar() == 0
    run(mig.downgrade)
    assert "health_alert" not in sa.inspect(engine).get_table_names()
```

- [ ] **Step 2: Migrasi + model**

```python
"""health_alert: alert kesehatan Monitoring (S3) — aktif (resolved_at NULL) & riwayat 7 hari.

Revision ID: 0020
Revises: 0019
"""

from alembic import op
import sqlalchemy as sa

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "health_alert",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("rule", sa.String(32), nullable=False),
        sa.Column("target", sa.String(64), nullable=False),
        sa.Column("node_id", sa.Integer(), sa.ForeignKey("node.id", ondelete="CASCADE"), nullable=False),
        sa.Column("camera_id", sa.Integer(), nullable=True),
        sa.Column("label", sa.String(128), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("rule", "target", "started_at", name="uq_health_alert_rule_target_start"),
    )
    op.create_index("ix_health_alert_resolved_at", "health_alert", ["resolved_at"])


def downgrade() -> None:
    op.drop_index("ix_health_alert_resolved_at", table_name="health_alert")
    op.drop_table("health_alert")
```

`backend/app/models/health_alert.py`:

```python
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class HealthAlert(Base):
    """Alert kesehatan Monitoring: aktif bila resolved_at NULL; riwayat dipangkas setelah 7 hari."""
    __tablename__ = "health_alert"
    __table_args__ = (UniqueConstraint("rule", "target", "started_at", name="uq_health_alert_rule_target_start"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    rule: Mapped[str] = mapped_column(String(32))
    target: Mapped[str] = mapped_column(String(64))
    node_id: Mapped[int] = mapped_column(Integer, ForeignKey("node.id", ondelete="CASCADE"))
    camera_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    label: Mapped[str] = mapped_column(String(128))
    severity: Mapped[str] = mapped_column(String(16))
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    threshold: Mapped[float] = mapped_column(Float)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
```

Registrasi di `app/models/__init__.py`. (Samakan import `Base` dengan `monitoring_sample.py`.)

Run: tes migrasi + suite backend → PASS.

- [ ] **Step 3: Commit**

```bash
rtk git add backend/alembic/versions/0020_health_alert.py backend/app/models backend/tests/test_migration_0020.py
rtk git commit -m "feat(monitoring): tabel health_alert untuk alert kesehatan"
```

---

### Task 3: Evaluator alert + hook sampler

**Files:**
- Create: `backend/app/services/health_alerts.py`
- Modify: `backend/app/services/monitoring_history.py` (`run_once`: evaluate + prune alert)
- Test: `backend/tests/test_health_alerts.py`

**Interfaces:**
- Consumes: `health_rules.get`, `CATALOG` (Task 1); `monitoring.analyzed_camera_ids` (Task 1); `HealthAlert` (Task 2);
  `MonitoringSample`, `_minute`/`_utc` dari `monitoring_history`; `ingest_event`, `hub`, `EventOut`, `telegram.send_text`.
- Produces: `RESOLVE_MIN = 2`, `RETENTION_DAYS = 7`, `TITLES: dict[str, str]`;
  `evaluate(db, now: datetime | None = None, send=None) -> dict` (`{"fired": [...], "resolved": [...], "closed": [...]}`
  berisi `(rule, target)`); `prune(db, now) -> int`.

- [ ] **Step 1: Tes (gagal)**

`backend/tests/test_health_alerts.py`:

```python
from datetime import datetime, timedelta, timezone

import pytest

from app.models.camera import Camera
from app.models.event import Event
from app.models.health_alert import HealthAlert
from app.models.monitoring_sample import MonitoringSample
from app.models.node import Node
from app.models.zone import Zone
from app.services import health_alerts as ha
from app.services import health_rules
from app.ws.hub import hub

NOW = datetime(2026, 9, 30, 8, 0, 30, tzinfo=timezone.utc)  # menit berjalan 08:00 → menit selesai terakhir 07:59
MIN = timedelta(minutes=1)


@pytest.fixture
def sent(monkeypatch):
    out = {"ws": [], "tg": []}
    async def fake_broadcast(payload):
        out["ws"].append(payload)
    monkeypatch.setattr(hub, "broadcast", fake_broadcast)
    return out


def _tg(out):
    return lambda db, text: out["tg"].append(text) or True


def _node(db, status="online"):
    n = Node(name="server", status=status)
    db.add(n)
    db.commit()
    return n


def _cam(db, node, cid=3, name="Lorong"):
    db.add(Camera(id=cid, name=name, host="1.2.3.4", node_id=node.id, enabled=True, ai_fps=5.0))
    db.add(Zone(camera_id=cid, name="z", type="behavior", polygon=[[0, 0], [1, 0], [1, 1]],
                behaviors=[{"kind": "intrusion"}], active=True))
    db.commit()


def _samples(db, node, minutes: int, make, end=NOW):
    """minutes sampel menit selesai terakhir (…, 07:58, 07:59); make(i) → data (i=0 paling lama)."""
    last = end.replace(second=0, microsecond=0) - MIN
    for i in range(minutes):
        ts = last - (minutes - 1 - i) * MIN
        db.add(MonitoringSample(node_id=node.id, ts=ts, data=make(i)))
    db.commit()


def gpu(temp):
    return {"gpus": {"0": {"temp_c": {"max": temp}}}}


def _active(db):
    return db.query(HealthAlert).filter(HealthAlert.resolved_at.is_(None)).all()


def _health_events(db):
    return [e for e in db.query(Event).filter_by(type="system").order_by(Event.id) if (e.payload or {}).get("kind") == "health"]


def test_gpu_temp_fires_after_full_window_with_event_and_telegram(db, sent):
    n = _node(db)
    _samples(db, n, 5, lambda i: gpu(90))                    # default 85 °C, 5 menit
    r = ha.evaluate(db, now=NOW, send=_tg(sent))
    assert r["fired"] == [("gpu_temp", f"gpu:{n.id}:0")]
    [a] = _active(db)
    assert a.label == "GPU 0 · server" and a.severity == "critical" and a.value == 90 and a.threshold == 85
    [ev] = _health_events(db)
    assert ev.severity == "critical" and ev.payload["state"] == "firing" and ev.payload["rule"] == "gpu_temp"
    assert sent["ws"] and len(sent["tg"]) == 1 and "GPU panas" in sent["tg"][0] and "90" in sent["tg"][0]


def test_one_normal_minute_or_missing_minute_blocks_firing(db, sent):
    n = _node(db)
    _samples(db, n, 5, lambda i: gpu(70 if i == 2 else 90))
    assert ha.evaluate(db, now=NOW, send=_tg(sent))["fired"] == []
    db.query(MonitoringSample).delete()
    db.commit()
    _samples(db, n, 4, lambda i: gpu(90))                    # jendela 5 menit tapi hanya 4 sampel
    assert ha.evaluate(db, now=NOW, send=_tg(sent))["fired"] == []


def test_idempotent_same_minute(db, sent):
    n = _node(db)
    _samples(db, n, 5, lambda i: gpu(90))
    ha.evaluate(db, now=NOW, send=_tg(sent))
    ha.evaluate(db, now=NOW + timedelta(seconds=10), send=_tg(sent))
    assert len(_active(db)) == 1 and len(_health_events(db)) == 1 and len(sent["tg"]) == 1


def test_resolves_after_two_normal_minutes(db, sent):
    n = _node(db)
    _samples(db, n, 5, lambda i: gpu(90))
    ha.evaluate(db, now=NOW, send=_tg(sent))
    _samples(db, n, 1, lambda i: gpu(60), end=NOW + MIN)       # 1 menit normal
    assert ha.evaluate(db, now=NOW + MIN, send=_tg(sent))["resolved"] == []
    _samples(db, n, 1, lambda i: gpu(60), end=NOW + 2 * MIN)   # 2 menit normal
    r = ha.evaluate(db, now=NOW + 2 * MIN, send=_tg(sent))
    assert r["resolved"] == [("gpu_temp", f"gpu:{n.id}:0")] and _active(db) == []
    ev = _health_events(db)[-1]
    assert ev.severity == "info" and ev.payload["state"] == "resolved"
    assert "normal" in sent["tg"][-1]


def test_node_offline_or_without_samples_holds(db, sent):
    n = _node(db)
    _samples(db, n, 5, lambda i: gpu(90))
    ha.evaluate(db, now=NOW, send=_tg(sent))
    n.status = "offline"
    db.commit()
    later = NOW + 30 * MIN  # tidak ada sampel baru
    r = ha.evaluate(db, now=later, send=_tg(sent))
    assert r == {"fired": [], "resolved": [], "closed": []} and len(_active(db)) == 1
    n.status = "online"
    db.commit()
    r = ha.evaluate(db, now=later, send=_tg(sent))           # online tapi tanpa sampel di jendela (API baru restart)
    assert r == {"fired": [], "resolved": [], "closed": []} and len(_active(db)) == 1


def test_offline_node_cameras_do_not_fire(db, sent):
    n = _node(db, status="offline")
    _cam(db, n)
    _samples(db, n, 5, lambda i: {"cameras": {}})
    assert ha.evaluate(db, now=NOW, send=_tg(sent))["fired"] == []


def test_camera_no_frames_missing_or_stale(db, sent):
    n = _node(db)
    _cam(db, n, 3, "Lorong")
    _cam(db, n, 4, "Gudang")
    _samples(db, n, 2, lambda i: {"cameras": {"4": {"frame_age_s": {"max": 45.0}, "fps": {"min": 5, "avg": 5},
                                                    "target_fps": 5.0}}})  # cam 3 hilang, cam 4 basi
    fired = sorted(ha.evaluate(db, now=NOW, send=_tg(sent))["fired"])
    assert fired == [("camera_no_frames", "cam:3"), ("camera_no_frames", "cam:4")]
    assert {a.camera_id for a in _active(db)} == {3, 4}
    assert all(e.camera_id in (3, 4) for e in _health_events(db))


def test_camera_low_fps_skips_starting_and_no_target(db, sent):
    n = _node(db)
    _cam(db, n, 3)
    health_rules.put(db, {"camera_low_fps": {"duration_min": 2}})
    _samples(db, n, 2, lambda i: {"cameras": {"3": {"fps": {"min": 1.0, "avg": 2.0}, "target_fps": 5.0,
                                                    "frame_age_s": {"max": 0.2}, "state": "starting"}}})
    assert ha.evaluate(db, now=NOW, send=_tg(sent))["fired"] == []
    db.query(MonitoringSample).delete()
    db.commit()
    _samples(db, n, 2, lambda i: {"cameras": {"3": {"fps": {"min": 1.0, "avg": 2.0}, "target_fps": 5.0,
                                                    "frame_age_s": {"max": 0.2}, "state": "streaming"}}})
    assert ha.evaluate(db, now=NOW, send=_tg(sent))["fired"] == [("camera_low_fps", "cam:3")]
    assert sent["tg"] == []  # telegram default OFF
    assert _active(db)[0].value == 20.0  # % dari target


@pytest.mark.parametrize("rule, data, target", [
    ("gpu_vram", {"gpus": {"0": {"vram_pct": {"max": 95.0}}}}, "gpu:{n}:0"),
    ("node_ram", {"ram_pct": {"avg": 95.0, "max": 96.0}}, "node:{n}"),
    ("node_cpu", {"cpu_pct": {"avg": 95.0, "max": 99.0}}, "node:{n}"),
    ("infer_latency", {"ms_avg": {"avg": 80.0}}, "node:{n}"),
    ("mqtt_backlog", {"mqtt_backlog": {"max": 3}}, "node:{n}"),
])
def test_node_and_gpu_rules(db, sent, rule, data, target):
    n = _node(db)
    health_rules.put(db, {rule: {"duration_min": 2}})
    _samples(db, n, 2, lambda i: data)
    assert (rule, target.format(n=n.id)) in ha.evaluate(db, now=NOW, send=_tg(sent))["fired"]


def test_disabled_rule_or_unanalyzed_camera_closes_without_telegram(db, sent):
    n = _node(db)
    _samples(db, n, 5, lambda i: gpu(90))
    ha.evaluate(db, now=NOW, send=_tg(sent))
    health_rules.put(db, {"gpu_temp": {"enabled": False}})
    tg_before = len(sent["tg"])
    r = ha.evaluate(db, now=NOW + timedelta(seconds=5), send=_tg(sent))
    assert r["closed"] == [("gpu_temp", f"gpu:{n.id}:0")] and _active(db) == []
    assert len(sent["tg"]) == tg_before
    assert _health_events(db)[-1].payload["state"] == "resolved"


def test_disabled_rule_does_not_fire(db, sent):
    n = _node(db)
    health_rules.put(db, {"gpu_temp": {"enabled": False}})
    _samples(db, n, 5, lambda i: gpu(99))
    assert ha.evaluate(db, now=NOW, send=_tg(sent))["fired"] == []


def test_prune_resolved_older_than_7_days(db):
    n = _node(db)
    db.add_all([
        HealthAlert(rule="gpu_temp", target="gpu:1:0", node_id=n.id, label="x", severity="critical", threshold=85,
                    started_at=NOW - timedelta(days=9), resolved_at=NOW - timedelta(days=8)),
        HealthAlert(rule="gpu_temp", target="gpu:1:0", node_id=n.id, label="x", severity="critical", threshold=85,
                    started_at=NOW - timedelta(days=2), resolved_at=NOW - timedelta(days=1)),
        HealthAlert(rule="node_cpu", target="node:1", node_id=n.id, label="x", severity="warning", threshold=90,
                    started_at=NOW - timedelta(days=10)),  # aktif: tidak dipangkas
    ])
    db.commit()
    assert ha.prune(db, NOW) == 1 and db.query(HealthAlert).count() == 2


def test_sampler_runs_evaluate_and_survives_its_error(db, monkeypatch):
    from app.services import monitoring_history as mh
    calls = []
    monkeypatch.setattr(ha, "evaluate", lambda db, now=None, send=None: calls.append(now) or (_ for _ in ()).throw(RuntimeError("x")))
    n = _node(db)
    mh.record(n.id, {"host": {"cpu_pct": 1.0}}, None, now=NOW - MIN)
    s = mh.HistorySampler(session_factory=lambda: db)
    assert s.run_once(now=NOW) == 1  # sampel tetap tertulis walau evaluate gagal
    assert calls
```

Run: `rtk bash -c "cd backend && .venv/bin/python -m pytest tests/test_health_alerts.py -q"` → FAIL (import).

- [ ] **Step 2: Implementasi `health_alerts.py`**

```python
"""Alert kesehatan Monitoring (S3): evaluasi aturan dari sampel menit S2 → baris health_alert + event + Telegram.

Stateless terhadap jendela data: menyala bila setiap menit dalam jendela durasi melanggar; pulih bila RESOLVE_MIN
menit terakhir normal. Karena tidak ada counter, evaluasi ulang di menit yang sama tidak mengubah hasil (idempoten).
Node offline / tanpa sampel di jendela → ditahan (restart API tidak menutup alert).
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone

from app.models.camera import Camera
from app.models.health_alert import HealthAlert
from app.models.monitoring_sample import MonitoringSample
from app.models.node import Node
from app.schemas.event import EventOut
from app.services import health_rules, telegram
from app.services.ingest import ingest_event
from app.services.monitoring import analyzed_camera_ids
from app.services.monitoring_history import _dict, _minute, _num, _utc
from app.ws.hub import hub

logger = logging.getLogger(__name__)

RESOLVE_MIN = 2
RETENTION_DAYS = 7
TITLES = {"camera_no_frames": "Kamera tanpa frame", "camera_low_fps": "FPS kamera rendah", "gpu_temp": "GPU panas",
          "gpu_vram": "VRAM GPU tinggi", "node_ram": "RAM node tinggi", "node_cpu": "CPU node tinggi",
          "infer_latency": "Latensi inferensi tinggi", "mqtt_backlog": "Event tertahan di node"}
OPS = {"camera_no_frames": ">", "camera_low_fps": "<", "mqtt_backlog": ">"}  # lainnya "≥"


def _check(rule: str, data: dict | None, key: str, threshold: float) -> tuple[bool | None, float | None]:
    """(melanggar?, nilai) untuk satu menit; (None, None) = menit tanpa data (bukan pelanggaran, bukan normal)."""
    if data is None:
        return None, None
    if rule == "camera_no_frames":
        cam = _dict(_dict(data.get("cameras")).get(key))
        if not cam:
            return True, None  # sampel node ada, kamera tidak ada di heartbeat
        age = _num(_dict(cam.get("frame_age_s")).get("max"))
        return (age is not None and age > threshold), age
    if rule == "camera_low_fps":
        cam = _dict(_dict(data.get("cameras")).get(key))
        fps, target = _num(_dict(cam.get("fps")).get("min")), _num(cam.get("target_fps"))
        if fps is None or not target or cam.get("state") == "starting":
            return None, None
        pct = round(fps / target * 100, 1)
        return pct < threshold, pct
    if rule in ("gpu_temp", "gpu_vram"):
        field = "temp_c" if rule == "gpu_temp" else "vram_pct"
        v = _num(_dict(_dict(_dict(data.get("gpus")).get(key)).get(field)).get("max"))
    elif rule in ("node_ram", "node_cpu"):
        v = _num(_dict(data.get("ram_pct" if rule == "node_ram" else "cpu_pct")).get("avg"))
    elif rule == "infer_latency":
        v = _num(_dict(data.get("ms_avg")).get("avg"))
    else:  # mqtt_backlog
        v = _num(_dict(data.get("mqtt_backlog")).get("max"))
    if v is None:
        return None, None
    return (v > threshold if rule == "mqtt_backlog" else v >= threshold), v


def _targets(node: Node, by_min: dict, cams: list[Camera]) -> list[tuple[str, str, str, int | None, str]]:
    """[(rule, target, label, camera_id, key)] untuk satu node. key = id kamera / idx GPU / '' (node)."""
    out = []
    for rule in ("node_ram", "node_cpu", "infer_latency", "mqtt_backlog"):
        out.append((rule, f"node:{node.id}", node.name, None, ""))
    gpu_idx = sorted({g for d in by_min.values() for g in _dict(d.get("gpus"))}, key=lambda s: (len(s), s))
    for idx in gpu_idx:
        for rule in ("gpu_temp", "gpu_vram"):
            out.append((rule, f"gpu:{node.id}:{idx}", f"GPU {idx} · {node.name}", None, idx))
    for cam in cams:
        for rule in ("camera_no_frames", "camera_low_fps"):
            out.append((rule, f"cam:{cam.id}", cam.name, cam.id, str(cam.id)))
    return out


def _emit(db, node: Node, camera_id, severity: str, payload: dict, now: datetime) -> None:
    status, ev = ingest_event(db, {"event_id": str(uuid.uuid4()), "type": "system", "node_id": node.id,
                                   "camera_id": camera_id, "severity": severity, "ts_event": now.isoformat(),
                                   "payload": payload})
    if status == "created" and ev is not None:
        try:
            asyncio.run(hub.broadcast(EventOut.model_validate(ev).model_dump(mode="json")))
        except Exception:
            logger.exception("health event broadcast failed")


def _fmt(v) -> str:
    return "—" if v is None else (f"{v:.0f}" if float(v).is_integer() else f"{v:.1f}")


def evaluate(db, now: datetime | None = None, send=None) -> dict:
    now = _utc(now or datetime.now(timezone.utc))
    cur = _minute(now)
    send = send or telegram.send_text
    rules = health_rules.get(db)
    enabled = {k: r for k, r in rules.items() if r["enabled"]}
    lookback = cur - timedelta(minutes=max([r["duration_min"] for r in rules.values()] + [RESOLVE_MIN]))
    samples: dict[int, dict[datetime, dict]] = {}
    for s in db.query(MonitoringSample).filter(MonitoringSample.ts >= lookback, MonitoringSample.ts < cur):
        samples.setdefault(s.node_id, {})[_utc(s.ts)] = _dict(s.data)
    analyzed = analyzed_camera_ids(db)
    cams_by_node: dict[int, list[Camera]] = {}
    for c in db.query(Camera).filter(Camera.enabled.is_(True), Camera.node_id.isnot(None)).order_by(Camera.id):
        if c.id in analyzed:
            cams_by_node.setdefault(c.node_id, []).append(c)
    active = {(a.rule, a.target): a for a in db.query(HealthAlert).filter(HealthAlert.resolved_at.is_(None))}
    result = {"fired": [], "resolved": [], "closed": []}
    keep: set[tuple[str, str]] = set()
    nodes = db.query(Node).order_by(Node.id).all()

    def payload(a_rule, target, label, value, threshold, state, extra=None):
        unit = health_rules.CATALOG[a_rule]["unit"]
        return {"kind": "health", "rule": a_rule, "target": target, "label": label, "value": value,
                "threshold": threshold, "unit": unit, "duration_min": rules[a_rule]["duration_min"],
                "state": state, **(extra or {})}

    for node in nodes:
        by_min = samples.get(node.id, {})
        if node.status == "offline" or not by_min:
            keep |= {k for k, a in active.items() if a.node_id == node.id}  # ditahan
            continue
        for rule, target, label, cam_id, key in _targets(node, by_min, cams_by_node.get(node.id, [])):
            r = enabled.get(rule)
            if r is None:
                continue
            keep.add((rule, target))
            th = r["threshold"]
            window = [cur - i * timedelta(minutes=1) for i in range(r["duration_min"], 0, -1)]
            checks = [_check(rule, by_min.get(m), key, th) for m in window]
            last_val = checks[-1][1]
            a = active.get((rule, target))
            if a is None:
                if all(v is True for v, _ in checks):
                    a = HealthAlert(rule=rule, target=target, node_id=node.id, camera_id=cam_id, label=label,
                                    severity=r["severity"], value=last_val, threshold=th, started_at=now)
                    db.add(a)
                    db.commit()
                    _emit(db, node, cam_id, r["severity"], payload(rule, target, label, last_val, th, "firing"), now)
                    unit = health_rules.CATALOG[rule]["unit"]
                    if r["telegram"]:
                        send(db, f"⚠️ {TITLES[rule]}: {label} — {_fmt(last_val)}{unit} "
                                 f"({OPS.get(rule, '≥')} {_fmt(th)}{unit} selama {r['duration_min']} menit)")
                    result["fired"].append((rule, target))
                continue
            recent = [_check(rule, by_min.get(cur - i * timedelta(minutes=1)), key, th)
                      for i in range(RESOLVE_MIN, 0, -1)]
            if recent[-1][0] is True and last_val is not None:
                a.value = last_val
                db.commit()
            if all(v is False for v, _ in recent):
                a.resolved_at = now
                db.commit()
                lasted = max(1, round((now - _utc(a.started_at)).total_seconds() / 60))
                _emit(db, node, a.camera_id, "info",
                      payload(rule, target, a.label, recent[-1][1], a.threshold, "resolved", {"lasted_min": lasted}), now)
                if r["telegram"]:
                    send(db, f"✅ {TITLES[rule]} normal: {a.label} — {lasted} menit")
                result["resolved"].append((rule, target))

    node_by_id = {n.id: n for n in nodes}
    for k, a in active.items():
        if k in keep or a.resolved_at is not None:
            continue
        a.resolved_at = now  # aturan dinonaktifkan / target hilang → tutup tanpa Telegram
        db.commit()
        node = node_by_id.get(a.node_id)
        if node is not None:
            _emit(db, node, a.camera_id, "info",
                  payload(a.rule, a.target, a.label, a.value, a.threshold, "resolved", {"closed": True}), now)
        result["closed"].append(k)
    return result


def prune(db, now: datetime) -> int:
    n = db.query(HealthAlert).filter(HealthAlert.resolved_at.isnot(None),
                                     HealthAlert.resolved_at < now - timedelta(days=RETENTION_DAYS)).delete(
        synchronize_session=False)
    db.commit()
    return n
```

Catatan:
- Import melingkar: `health_alerts` mengimpor `monitoring` & `monitoring_history`; `monitoring_history` memanggil
  `health_alerts` **di dalam** `run_once` (import lokal) — jangan impor di level modul.
- `ingest_event` menerima `camera_id` untuk kamera yang ada (FK) — kamera dianalisis selalu ada.
- `_fmt` dipakai juga di pesan pulih bila perlu. Perbandingan `MonitoringSample.ts` dengan `cur` aware: gunakan pola
  yang sudah lulus di S2 (`query`) untuk SQLite/Postgres; bila SQLite menolak, catat deviasi.

- [ ] **Step 3: Hook sampler**

Di `monitoring_history.HistorySampler.run_once`, setelah `added = write(db, rows)` (sebelum prune):

```python
            try:
                from app.services import health_alerts  # lokal: hindari import melingkar
                health_alerts.evaluate(db, now)
            except Exception:
                db.rollback()
                logger.warning("health alert evaluation failed", exc_info=True)
```

dan di blok prune per jam tambahkan `health_alerts.prune(db, now)` (import lokal yang sama, dalam `try` terpisah).

Run: `rtk bash -c "cd backend && .venv/bin/python -m pytest tests -q -m 'not gpu'"` → PASS.

- [ ] **Step 4: Commit**

```bash
rtk git add backend/
rtk git commit -m "feat(monitoring): evaluator alert kesehatan per menit dengan event dan Telegram per aturan"
```

---

### Task 4: API rules & alerts

**Files:**
- Modify: `backend/app/schemas/monitoring.py`, `backend/app/api/monitoring.py`
- Test: `backend/tests/test_health_rules.py` (tambah tes endpoint)

**Interfaces:**
- Produces: `GET /api/v1/monitoring/rules` → `list[HealthRuleOut]`; `PUT /api/v1/monitoring/rules` (admin) body
  `dict[str, HealthRulePatch]` → `list[HealthRuleOut]`; `GET /api/v1/monitoring/alerts` → `HealthAlertsOut
  {active: list[HealthAlertOut], recent: list[HealthAlertOut]}`.

- [ ] **Step 1: Tes (gagal)**

```python
def test_rules_endpoints(client, admin_headers, viewer_headers):
    r = client.get("/api/v1/monitoring/rules", headers=viewer_headers)
    assert r.status_code == 200 and [x["rule"] for x in r.json()][0] == "camera_no_frames"
    assert {"unit", "min", "max", "target", "threshold", "duration_min"} <= set(r.json()[0])
    body = {"gpu_temp": {"threshold": 80, "telegram": False}}
    assert client.put("/api/v1/monitoring/rules", json=body, headers=viewer_headers).status_code == 403
    r = client.put("/api/v1/monitoring/rules", json=body, headers=admin_headers)
    assert r.status_code == 200
    assert next(x for x in r.json() if x["rule"] == "gpu_temp")["threshold"] == 80
    for bad in ({"gpu_temp": {"threshold": 999}}, {"nope": {}}, {"gpu_temp": {"color": "red"}}):
        assert client.put("/api/v1/monitoring/rules", json=bad, headers=admin_headers).status_code == 422
    assert client.get("/api/v1/monitoring/rules").status_code == 401


def test_alerts_endpoint_active_and_recent(client, db, viewer_headers):
    from datetime import datetime, timedelta, timezone
    from app.models.health_alert import HealthAlert
    from app.models.node import Node
    n = Node(name="server", status="online")
    db.add(n)
    db.commit()
    t = datetime.now(timezone.utc)
    db.add_all([
        HealthAlert(rule="gpu_temp", target=f"gpu:{n.id}:0", node_id=n.id, label="GPU 0 · server", severity="critical",
                    value=90, threshold=85, started_at=t - timedelta(minutes=5)),
        HealthAlert(rule="node_cpu", target=f"node:{n.id}", node_id=n.id, label="server", severity="warning",
                    value=95, threshold=90, started_at=t - timedelta(hours=2), resolved_at=t - timedelta(hours=1)),
    ])
    db.commit()
    body = client.get("/api/v1/monitoring/alerts", headers=viewer_headers).json()
    assert [a["rule"] for a in body["active"]] == ["gpu_temp"] and body["active"][0]["unit"] == "°C"
    assert [a["rule"] for a in body["recent"]] == ["node_cpu"]
```

(Fixture `client`/`admin_headers`/`viewer_headers` — pakai dari conftest atau salin fixture `client` dari
`test_monitoring.py` seperti S2.)

- [ ] **Step 2: Schema + router**

`schemas/monitoring.py`:

```python
from typing import Literal


class HealthRuleOut(BaseModel):
    rule: str
    enabled: bool
    threshold: float
    duration_min: int
    severity: str
    telegram: bool
    unit: str
    min: float
    max: float
    target: str


class HealthRulePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool | None = None
    threshold: float | None = None
    duration_min: int | None = None
    severity: Literal["warning", "critical"] | None = None
    telegram: bool | None = None


class HealthAlertOut(BaseModel):
    id: int
    rule: str
    target: str
    label: str
    node_id: int
    camera_id: int | None = None
    severity: str
    value: float | None = None
    threshold: float
    unit: str
    started_at: datetime
    resolved_at: datetime | None = None


class HealthAlertsOut(BaseModel):
    active: list[HealthAlertOut]
    recent: list[HealthAlertOut]
```

`api/monitoring.py`:

```python
from fastapi import HTTPException

from app.api.deps import require_admin
from app.models.health_alert import HealthAlert
from app.schemas.monitoring import HealthAlertOut, HealthAlertsOut, HealthRuleOut, HealthRulePatch
from app.services import health_rules

SEV_ORDER = {"critical": 0, "warning": 1}


@router.get("/rules", response_model=list[HealthRuleOut])
def get_rules(user=Depends(get_current_user), db=Depends(get_db)):
    """Aturan kesehatan efektif (semua user; read-only)."""
    return health_rules.as_list(health_rules.get(db))


@router.put("/rules", response_model=list[HealthRuleOut])
def put_rules(body: dict[str, HealthRulePatch], admin=Depends(require_admin), db=Depends(get_db)):
    """Ubah aturan (admin). Parsial; kunci/nilai di luar batas → 422."""
    patch = {rule: p.model_dump(exclude_none=True) for rule, p in body.items()}
    try:
        rules = health_rules.put(db, patch)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    logger.info("health rules updated by %s: %s", admin.username, patch)
    return health_rules.as_list(rules)


def _alert_out(a: HealthAlert) -> dict:
    return {**{c: getattr(a, c) for c in ("id", "rule", "target", "label", "node_id", "camera_id", "severity",
                                          "value", "threshold", "started_at", "resolved_at")},
            "unit": health_rules.CATALOG.get(a.rule, {}).get("unit", "")}


@router.get("/alerts", response_model=HealthAlertsOut)
def get_alerts(user=Depends(get_current_user), db=Depends(get_db)):
    """Alert kesehatan aktif + 50 terakhir yang sudah pulih (semua user)."""
    active = db.query(HealthAlert).filter(HealthAlert.resolved_at.is_(None)).all()
    active.sort(key=lambda a: (SEV_ORDER.get(a.severity, 2), a.started_at))
    recent = (db.query(HealthAlert).filter(HealthAlert.resolved_at.isnot(None))
              .order_by(HealthAlert.resolved_at.desc()).limit(50).all())
    return {"active": [_alert_out(a) for a in active], "recent": [_alert_out(a) for a in recent]}
```

(`logger = logging.getLogger(__name__)` di router bila belum ada. Kunci rule tak dikenal di body lolos Pydantic
`dict[str, …]` lalu ditolak `health_rules.put` → 422. Sesuaikan agar "tanpa SQL di router" (AGENTS.md): pindahkan
query `get_alerts` ke `health_alerts.list_alerts(db) -> dict` bila reviewer menandainya.)

Run: suite backend → PASS.

- [ ] **Step 3: Commit**

```bash
rtk git add backend/
rtk git commit -m "feat(monitoring): API aturan kesehatan dan daftar alert"
```

---

### Task 5: Tab "Aturan & alert"

**Files:**
- Create: `frontend/src/features/monitoring/AlertsTab.tsx`
- Modify: `frontend/src/features/monitoring/MonitoringPage.tsx`, `frontend/src/api/monitoring.ts`,
  `frontend/src/app/i18n.tsx`, `frontend/src/app/theme.scss`
- Test: `frontend/src/__tests__/monitoring-alerts.test.tsx`

**Interfaces:**
- Consumes: API Task 4; `Me` role dari `useOutletContext` (pola `ConfigurationPage`) atau `getMe()`.
- Produces: `getHealthRules(): Promise<HealthRule[]>`, `putHealthRules(patch: Record<string, Partial<HealthRuleEdit>>):
  Promise<HealthRule[]>` (422 → `Error('invalid')`), `getHealthAlerts(): Promise<HealthAlerts>`; tipe `HealthRule`,
  `HealthAlert`, `HealthAlerts`; `ALERTS_POLL_MS = 30_000`; test id `mon-tab-alerts`, `alerts-active`,
  `alert-row-<id>`, `alerts-recent`, `rule-row-<rule>`, `rules-save`, `rules-saved`, `rules-error`.

- [ ] **Step 1: Tes (gagal)**

```tsx
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import '@testing-library/jest-dom/vitest'
import { I18nProvider } from '../app/i18n'
import MonitoringPage from '../features/monitoring/MonitoringPage'

const RULES = [
  { rule: 'camera_no_frames', enabled: true, threshold: 30, duration_min: 2, severity: 'critical', telegram: true,
    unit: 's', min: 10, max: 600, target: 'camera' },
  { rule: 'gpu_temp', enabled: true, threshold: 85, duration_min: 5, severity: 'critical', telegram: true,
    unit: '°C', min: 50, max: 110, target: 'gpu' },
]
const ALERTS = {
  active: [{ id: 1, rule: 'gpu_temp', target: 'gpu:1:0', label: 'GPU 0 · server', node_id: 1, camera_id: null,
    severity: 'critical', value: 90, threshold: 85, unit: '°C', started_at: '2026-09-30T07:50:00Z', resolved_at: null }],
  recent: [{ id: 2, rule: 'camera_no_frames', target: 'cam:3', label: 'Lorong', node_id: 1, camera_id: 3,
    severity: 'critical', value: null, threshold: 30, unit: 's', started_at: '2026-09-30T06:00:00Z',
    resolved_at: '2026-09-30T06:12:00Z' }],
}

let puts: unknown[]
let putStatus = 200
function stub(role: 'admin' | 'viewer') {
  puts = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    const u = String(url)
    if (u.endsWith('/auth/me')) return { ok: true, status: 200, json: () => Promise.resolve({ id: 1, username: 'u', role }) }
    if (u.endsWith('/monitoring/rules') && init?.method === 'PUT') {
      puts.push(JSON.parse(String(init.body)))
      return putStatus === 200
        ? { ok: true, status: 200, json: () => Promise.resolve(RULES) }
        : { ok: false, status: 422, json: () => Promise.resolve({ detail: 'x' }) }
    }
    if (u.endsWith('/monitoring/rules')) return { ok: true, status: 200, json: () => Promise.resolve(RULES) }
    if (u.endsWith('/monitoring/alerts')) return { ok: true, status: 200, json: () => Promise.resolve(ALERTS) }
    return { ok: false, status: 404, json: () => Promise.resolve(null) }
  }))
}
afterEach(() => { vi.unstubAllGlobals(); putStatus = 200 })

const renderTab = (role: 'admin' | 'viewer') => {
  stub(role)
  return render(
    <I18nProvider>
      <MemoryRouter initialEntries={['/monitoring?tab=alerts']}>
        <Routes><Route path="/monitoring" element={<MonitoringPage me={{ id: 1, username: 'u', role }} />} /></Routes>
      </MemoryRouter>
    </I18nProvider>)
}

test('alert aktif & riwayat tampil', async () => {
  renderTab('viewer')
  const row = await screen.findByTestId('alert-row-1')
  expect(row).toHaveTextContent('GPU panas')
  expect(row).toHaveTextContent('GPU 0 · server')
  expect(row).toHaveTextContent('90')
  expect(within(screen.getByTestId('alerts-recent')).getByText('Lorong')).toBeInTheDocument()
})

test('admin mengubah ambang lalu simpan → PUT parsial + pesan sukses', async () => {
  renderTab('admin')
  const row = await screen.findByTestId('rule-row-gpu_temp')
  const input = within(row).getByLabelText(/ambang/i)
  await userEvent.clear(input)
  await userEvent.type(input, '80')
  await userEvent.click(screen.getByTestId('rules-save'))
  await waitFor(() => expect(puts).toEqual([{ gpu_temp: { threshold: 80 } }]))
  expect(await screen.findByTestId('rules-saved')).toBeInTheDocument()
})

test('422 → pesan error', async () => {
  renderTab('admin')
  putStatus = 422
  const row = await screen.findByTestId('rule-row-gpu_temp')
  await userEvent.click(within(row).getByRole('switch', { name: /telegram/i }))
  await userEvent.click(screen.getByTestId('rules-save'))
  expect(await screen.findByTestId('rules-error')).toBeInTheDocument()
})

test('viewer read-only: kontrol nonaktif, tanpa tombol simpan', async () => {
  renderTab('viewer')
  const row = await screen.findByTestId('rule-row-gpu_temp')
  expect(within(row).getByLabelText(/ambang/i)).toBeDisabled()
  expect(screen.queryByTestId('rules-save')).toBeNull()
})
```

Catatan: cara `MonitoringPage` mengetahui role — ikuti pola repo (`ConfigurationPage` memakai
`useOutletContext<Me | null>()`). Bila `MonitoringPage` tidak menerima prop `me`, render di dalam `<Route element=
{<Outlet context={me} />}>` pada tes; sesuaikan harness, catat deviasinya. Label NumberInput harus memuat kata
"Ambang" (i18n `health.col.threshold`), dan Toggle Telegram berlabel "Telegram".

- [ ] **Step 2: API + tab**

`api/monitoring.ts`:

```ts
export type HealthRule = { rule: string; enabled: boolean; threshold: number; duration_min: number
  severity: 'warning' | 'critical'; telegram: boolean; unit: string; min: number; max: number
  target: 'camera' | 'gpu' | 'node' }
export type HealthRuleEdit = Pick<HealthRule, 'enabled' | 'threshold' | 'duration_min' | 'severity' | 'telegram'>
export type HealthAlert = { id: number; rule: string; target: string; label: string; node_id: number
  camera_id: number | null; severity: string; value: number | null; threshold: number; unit: string
  started_at: string; resolved_at: string | null }
export type HealthAlerts = { active: HealthAlert[]; recent: HealthAlert[] }

export async function getHealthRules(): Promise<HealthRule[]> {
  const res = await apiFetch('/monitoring/rules')
  if (!res.ok) throw new Error(`rules failed: ${res.status}`)
  return res.json()
}

export async function putHealthRules(patch: Record<string, Partial<HealthRuleEdit>>): Promise<HealthRule[]> {
  const res = await apiFetch('/monitoring/rules', { method: 'PUT', body: JSON.stringify(patch) })
  if (res.status === 422) throw new Error('invalid')
  if (!res.ok) throw new Error(`rules save failed: ${res.status}`)
  return res.json()
}

export async function getHealthAlerts(): Promise<HealthAlerts> {
  const res = await apiFetch('/monitoring/alerts')
  if (!res.ok) throw new Error(`alerts failed: ${res.status}`)
  return res.json()
}
```

`MonitoringPage.tsx`: `TABS = ['current', 'trend', 'alerts']`, `<Tab data-testid="mon-tab-alerts">{t('mon.tab.alerts')}</Tab>`,
panel `{tab === 'alerts' && <AlertsTab isAdmin={me?.role === 'admin'} />}` (role dari outlet context).

`AlertsTab.tsx` — struktur:
- State `alerts`, `rules` (server), `edit: Record<rule, Partial<HealthRuleEdit>>` (hanya field yang diubah),
  `saved`, `error`, `busy`.
- Polling `getHealthAlerts` 30 s; `getHealthRules` sekali saat mount.
- Kartu **Alert aktif** (`data-testid="alerts-active"`): tabel kolom aturan (`t('health.rule.<rule>')`), target
  (`label`), severity (`HealthTag` gaya S1 — critical merah, warning kuning), nilai (`value` + unit, "—" bila null),
  ambang (`op` + threshold + unit), sejak (`started_at` jam lokal + durasi "N mnt"). Kosong → `t('health.noActive')`.
- Kartu **Riwayat** (`data-testid="alerts-recent"`): aturan, target, mulai, selesai, durasi. Kosong → teks.
- Kartu **Aturan**: keterangan `t('health.hint')`; tabel baris `rule-row-<rule>`: nama aturan + satuan,
  `Toggle` aktif (labelText `t('health.col.enabled')`), `NumberInput` ambang (`label={t('health.col.threshold')}`, min/max
  dari API, `step` 1, `disabled={!isAdmin}`), `NumberInput` durasi menit (1–60), `Select` severity, `Toggle` Telegram
  (`labelText="Telegram"`); nilai tampil = `{...rule, ...edit[rule]}`. Tombol **Simpan** hanya admin, `disabled` bila
  `edit` kosong / `busy`; klik → `putHealthRules(edit)` → set `rules`, kosongkan `edit`, tampil
  `InlineNotification success` (`rules-saved`); `Error('invalid')` → `InlineNotification error` `rules-error`
  (`t('health.invalid')`), lainnya `t('common.error')`.
- Semua kartu memakai `.mon-card` / `.mon-table` (S1) agar konsisten; tabel dalam `.mon-table-wrap`.

i18n (id / en, kunci sama):

```
'mon.tab.alerts' 'Aturan & alert' / 'Rules & alerts'
'health.active' 'Alert aktif' / 'Active alerts', 'health.recent' 'Riwayat (7 hari)' / 'History (7 days)',
'health.rules' 'Aturan' / 'Rules', 'health.noActive' 'Tidak ada alert aktif' / 'No active alerts',
'health.noRecent' 'Belum ada riwayat alert' / 'No alert history yet',
'health.hint' 'Alert menyala bila kondisi berlangsung sepanjang durasi; pulih setelah 2 menit normal. Telegram hanya untuk aturan yang dinyalakan.' /
  'An alert fires when the condition lasts for the whole duration and clears after 2 normal minutes. Telegram only for rules with it enabled.'
'health.col.rule' 'Aturan'/'Rule', 'health.col.target' 'Target', 'health.col.severity' 'Severity',
'health.col.value' 'Nilai'/'Value', 'health.col.threshold' 'Ambang'/'Threshold', 'health.col.since' 'Sejak'/'Since',
'health.col.start' 'Mulai'/'Started', 'health.col.end' 'Selesai'/'Resolved', 'health.col.lasted' 'Durasi'/'Duration',
'health.col.enabled' 'Aktif'/'Enabled', 'health.col.duration' 'Durasi (menit)'/'Duration (min)'
'health.save' 'Simpan aturan' / 'Save rules', 'health.saved' 'Aturan tersimpan' / 'Rules saved',
'health.invalid' 'Nilai di luar batas yang diizinkan' / 'Value out of allowed range'
'health.sev.warning' 'Peringatan'/'Warning', 'health.sev.critical' 'Kritis'/'Critical'
'health.rule.camera_no_frames' 'Kamera tanpa frame' / 'Camera without frames'
'health.rule.camera_low_fps' 'FPS kamera rendah' / 'Low camera FPS'
'health.rule.gpu_temp' 'GPU panas' / 'GPU hot', 'health.rule.gpu_vram' 'VRAM GPU tinggi' / 'High GPU VRAM'
'health.rule.node_ram' 'RAM node tinggi' / 'High node RAM', 'health.rule.node_cpu' 'CPU node tinggi' / 'High node CPU'
'health.rule.infer_latency' 'Latensi inferensi tinggi' / 'High inference latency'
'health.rule.mqtt_backlog' 'Event tertahan di node' / 'Events queued on node'
'health.normal' '{rule} normal' / '{rule} back to normal'
'health.badge.camera_no_frames' 'Tanpa frame' / 'No frames', 'health.badge.camera_low_fps' 'FPS rendah' / 'Low FPS'
```

Gaya: gunakan kelas yang ada (`mon-card`, `mon-table`, `mon-table-wrap`, `mon-tag`); tambahkan hanya
`.health-rules input { max-inline-size: 110px; }` bila perlu agar tabel aturan muat.

Run: `rtk bash -c "cd frontend && npx vitest run src/__tests__/monitoring-alerts.test.tsx src/__tests__/monitoring.test.tsx src/__tests__/monitoring-trend.test.tsx"` → PASS.

- [ ] **Step 3: Commit**

```bash
rtk git add frontend/src
rtk git commit -m "feat(monitoring): tab Aturan & alert (alert aktif, riwayat, pengaturan aturan)"
```

---

### Task 6: Badge Live View + notifikasi kesehatan

**Files:**
- Create: `frontend/src/features/monitoring/useCameraHealthAlerts.ts`
- Modify: `frontend/src/features/live/LiveWall.tsx`, `frontend/src/features/notifications/labels.ts`,
  `frontend/src/features/notifications/EventAlertsProvider.tsx`, `frontend/src/app/theme.scss`
- Test: `frontend/src/__tests__/monitoring-alerts.test.tsx`, `frontend/src/__tests__/event-alerts.test.tsx`

**Interfaces:**
- Consumes: `getHealthAlerts()` (Task 5).
- Produces: `useCameraHealthAlerts(): Record<number, { rule: string; severity: string }>` (polling 30 s, gagal → `{}`);
  `CameraTile` prop `health?: { rule: string; severity: string }` → badge `data-testid="cam-health-<id>"`;
  `labels.isHealthEvent(e)`, `labels.eventTitleKey` / `eventWhere` menangani kesehatan.

- [ ] **Step 1: Tes (gagal)**

Di `monitoring-alerts.test.tsx`:

```tsx
import LiveViewPage from '../features/live/LiveViewPage'

test('Live View: badge kesehatan di tile kamera beralert; kamera lain tidak; fetch gagal → tanpa badge', async () => {
  const CAMS = [3, 4].map((id) => ({ id, name: `CAM-${id}`, location: null, host: 'h', rtsp_main: null, rtsp_sub: null,
    node_id: 1, enabled: true, status: 'online', probe_main: null, probe_sub: null }))
  let fail = false
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    const u = String(url)
    if (u.endsWith('/cameras')) return { ok: true, status: 200, json: () => Promise.resolve(CAMS) }
    if (u.endsWith('/monitoring/alerts')) {
      return fail ? { ok: false, status: 500, json: () => Promise.resolve(null) }
        : { ok: true, status: 200, json: () => Promise.resolve({ active: [{ ...ALERTS.recent[0], id: 9, resolved_at: null }], recent: [] }) }
    }
    return { ok: false, status: 404, json: () => Promise.resolve(null) }
  }))
  const { unmount } = render(<I18nProvider><MemoryRouter><LiveViewPage /></MemoryRouter></I18nProvider>)
  expect(await screen.findByTestId('cam-health-3')).toHaveTextContent('Tanpa frame')
  expect(screen.queryByTestId('cam-health-4')).toBeNull()
  unmount()
  fail = true
  render(<I18nProvider><MemoryRouter><LiveViewPage /></MemoryRouter></I18nProvider>)
  await screen.findByText('CAM-3')
  expect(screen.queryByTestId('cam-health-3')).toBeNull()
})
```

Di `event-alerts.test.tsx` (helper `renderWith`, `send`, `ev`, `shell` yang sudah ada):

```tsx
test('event kesehatan: berlabel aturan, tanpa chip node offline; resolved → "… normal"', async () => {
  renderWith(<><LiveViewPage />{shell}</>, '/live')
  expect(await screen.findByText('CAM-01')).toBeInTheDocument()
  await waitFor(() => expect(screen.getByTestId('recent')).toHaveTextContent('11,10'))
  const health = (id: number, state: string, severity: string) => ev(id, { type: 'system', camera_id: null, zone_id: null,
    severity, payload: { kind: 'health', rule: 'gpu_temp', target: 'gpu:1:0', label: 'GPU 0 · server', state } })
  send(health(40, 'firing', 'critical'))
  expect(screen.getByTestId('toast-40')).toHaveTextContent('GPU panas')
  expect(screen.getByTestId('toast-40')).toHaveTextContent('GPU 0 · server')
  expect(screen.queryByTestId('alert-chip-node')).toBeNull()
  send(health(41, 'resolved', 'info'))
  expect(screen.getByTestId('toast-41')).toHaveTextContent('GPU panas normal')
})
```

Run → FAIL.

- [ ] **Step 2: Implementasi**

`useCameraHealthAlerts.ts`:

```ts
import { useEffect, useState } from 'react'
import { getHealthAlerts } from '../../api/monitoring'

export const HEALTH_POLL_MS = 30_000
export type CameraHealth = { rule: string; severity: string }

/** Alert kesehatan aktif per kamera (badge tile Live View/TV). Gagal memuat → tanpa badge. */
export function useCameraHealthAlerts(): Record<number, CameraHealth> {
  const [byCam, setByCam] = useState<Record<number, CameraHealth>>({})
  useEffect(() => {
    let alive = true
    const load = () => getHealthAlerts()
      .then((a) => {
        if (!alive) return
        const out: Record<number, CameraHealth> = {}
        for (const x of a.active) {
          if (x.camera_id == null) continue
          // satu badge per kamera: tanpa frame (critical) diutamakan dari fps rendah
          if (!out[x.camera_id] || x.rule === 'camera_no_frames') out[x.camera_id] = { rule: x.rule, severity: x.severity }
        }
        setByCam(out)
      })
      .catch(() => { if (alive) setByCam({}) })
    load()
    const timer = setInterval(load, HEALTH_POLL_MS)
    return () => { alive = false; clearInterval(timer) }
  }, [])
  return byCam
}
```

`LiveWall.tsx`: di `LiveWall` panggil `const health = useCameraHealthAlerts()` sekali; teruskan
`health={health[cam.id]}` ke `CameraTile` grid (tile modal debugger juga boleh menerima `health[debugCam.id]`).
`CameraTile` prop `health?: CameraHealth`; render (setelah blok outline event, sebelum bar nama) bila ada:

```tsx
      {health && (
        <span data-testid={`cam-health-${cam.id}`} className={`lv-health lv-health--${sevClass(health.severity)}`}
          style={{ fontSize: tv ? 'clamp(11px, 0.8vw, 28px)' : 11 }}>
          ⚠ {t(`health.badge.${health.rule}` as TKey)}
        </span>
      )}
```

Gaya:

```scss
/* Badge kesehatan kamera (alert S3 aktif) — pojok kiri bawah di atas bar nama; beda dari outline event. */
.lv-health {
  position: absolute;
  left: 8px;
  bottom: 32px;
  z-index: 2;
  padding: 2px 8px;
  font-weight: 600;
  pointer-events: none;

  &--critical { background: #fa4d56; color: #fff; }
  &--warning, &--info { background: #f1c21b; color: #161616; }
}
```

`labels.ts`:

```ts
/** Event system dari alert kesehatan Monitoring (S3). */
export const isHealthEvent = (e: EventOut): boolean => e.type === 'system' && e.payload?.kind === 'health'
```

- `eventTitleKey(e)`: bila `isHealthEvent(e)` → `health.rule.<rule>`; untuk `state === 'resolved'` judul memakai
  `health.normal` (`'{rule} normal'`) — karena `eventTitleKey` mengembalikan `TKey`, tambahkan fungsi
  `eventTitle(e, t): string` yang menangani penggantian `{rule}` dan pakai di `NotificationBell` & `EventToasts`
  (ganti `t(eventTitleKey(e))` → `eventTitle(e, t)`).
- `eventWhere(e, …)`: bila `isHealthEvent(e)` → `String(e.payload?.label ?? '')`.

`EventAlertsProvider.tsx` di `fire()`: cabang `if (e.type === 'system')` hanya memperbarui chip node bila **bukan**
event kesehatan:

```ts
    if (e.type === 'system') {
      if (e.payload?.kind !== 'health') {
        const node = String(e.payload?.node ?? '?')
        setNodes((prev) => [
          ...prev.filter((n) => n.node !== node),
          ...(e.payload?.reason === 'online' ? [] : [{ eventId: e.id, node, until: now + ACTIVE_MS }]),
        ])
      }
    } else if (e.camera_id != null) {
```

(Toast/bunyi/lonceng tetap untuk event kesehatan.)

Run: `rtk bash -c "cd frontend && npx vitest run"` → PASS semua.

- [ ] **Step 3: Commit**

```bash
rtk git add frontend/src
rtk git commit -m "feat(monitoring): badge kesehatan tile Live View dan label notifikasi alert kesehatan"
```

---

### Task 7: Verifikasi, dokumentasi, push

**Files:** `README.md`, `docs/runbooks/monitoring.md`, `ROADMAP.md`, `CHANGELOG.md`

- [ ] **Step 1: Suite penuh**

```bash
rtk bash -c "cd backend && .venv/bin/python -m pytest tests -q -m 'not gpu' > /tmp/be.log 2>&1; grep -oE '[0-9]+ (passed|failed)[^|]*' /tmp/be.log | tail -1"
rtk backend/.venv/bin/python -m pytest vision/tests -q -m "not gpu"
rtk bash -c "cd frontend && npx vitest run && npm run build && npm run lint"
```

Expected: backend > 549, vision 233 (tidak berubah), frontend > 223, build 0, lint tanpa error baru;
`rtk git diff --stat main -- vision` kosong.

- [ ] **Step 2: Cek visual** — `/monitoring?tab=alerts` 1440 & 390 px (stub data: 1 alert aktif, riwayat, aturan
  admin & viewer), badge di `/live` dan `/live/tv`. Screenshot `docs/evidence/2026-09-30-monitoring-alerts-*.png`.
  Matikan server dev.

- [ ] **Step 3: Dokumentasi**
  - `README.md` Monitoring: tab **Aturan & alert** (8 aturan + default, menyala/pulih, Telegram per aturan, badge
    Live View, ambang halaman ikut aturan).
  - `docs/runbooks/monitoring.md`: tabel aturan (arti + tindakan), cara uji (turunkan ambang GPU sementara), bagaimana
    alert ditahan saat node offline, rollback 0020.
  - `ROADMAP.md`: baris **MO3** setelah MO2 (`[ ] menunggu deploy + verifikasi user`, migrasi 0020, restart API).
  - `CHANGELOG.md`: entri teratas `### Monitoring Resource S3 (2026-09-30)` (konteks, perubahan termasuk perubahan
    ambang `low_fps` halaman 80 % → 50 % default, file, bukti suite nyata, dampak, deploy, rollback `alembic downgrade 0019`).

- [ ] **Step 4: Commit + push (berhenti di sini)**

```bash
rtk git add README.md ROADMAP.md CHANGELOG.md docs/runbooks/monitoring.md docs/evidence
rtk git commit -m "docs(monitoring): README, runbook, ROADMAP, CHANGELOG Monitoring S3"
rtk git push -u origin feat/monitoring-s3
```

Deploy (alembic 0020 + restart API), uji lapangan, dan merge dilakukan sesi perencana — **jangan** deploy atau merge.
