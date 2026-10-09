"""Check old detector_setting rows and repeated additive upgrade/downgrade cycles (0025)."""
import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

NEW_COLUMNS = {
    "face_attendance_mode": "legacy",
    "face_attendance_window_s": 1.5,
}


def _mig():
    path = Path(__file__).resolve().parents[1] / "alembic/versions/0025_face_attendance_mode.py"
    spec = importlib.util.spec_from_file_location("mig0025", path)
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)
    return mig


def test_upgrade_fills_defaults_on_old_row_and_downgrade_restores_table():
    mig = _mig()
    assert mig.revision == "0025" and mig.down_revision == "0024"
    engine = sa.create_engine("sqlite://")
    meta = sa.MetaData()
    sa.Table("detector_setting", meta, sa.Column("id", sa.Integer, primary_key=True))
    meta.create_all(engine)
    with engine.begin() as conn:
        conn.execute(sa.text("INSERT INTO detector_setting (id) VALUES (1)"))
    cols = ", ".join(NEW_COLUMNS)
    for _ in range(2):
        with engine.begin() as conn, Operations.context(MigrationContext.configure(conn)):
            mig.upgrade()
        with engine.connect() as conn:
            row = conn.execute(sa.text(f"SELECT {cols} FROM detector_setting WHERE id = 1")).one()
        assert dict(zip(NEW_COLUMNS, row)) == NEW_COLUMNS
        columns = {c["name"]: c for c in sa.inspect(engine).get_columns("detector_setting")}
        for name in NEW_COLUMNS:
            assert columns[name]["nullable"] is False, name
        with engine.begin() as conn, Operations.context(MigrationContext.configure(conn)):
            mig.downgrade()
        assert [c["name"] for c in sa.inspect(engine).get_columns("detector_setting")] == ["id"]
    engine.dispose()
