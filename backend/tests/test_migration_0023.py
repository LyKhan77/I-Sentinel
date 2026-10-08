"""Check old alert rows and repeated additive migration upgrade/downgrade cycles (0023)."""
import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def _mig():
    path = Path(__file__).resolve().parents[1] / "alembic/versions/0023_alert_face_synced.py"
    spec = importlib.util.spec_from_file_location("mig0023", path)
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)
    return mig


def test_upgrade_downgrade():
    mig = _mig()
    assert mig.revision == "0023" and mig.down_revision == "0022"
    engine = sa.create_engine("sqlite://")
    meta = sa.MetaData()
    sa.Table("alert", meta, sa.Column("id", sa.Integer, primary_key=True))
    meta.create_all(engine)
    with engine.begin() as conn:
        conn.execute(sa.text("INSERT INTO alert (id) VALUES (1)"))
    for _ in range(2):
        with engine.begin() as conn, Operations.context(MigrationContext.configure(conn)):
            mig.upgrade()
        with engine.connect() as conn:
            assert conn.execute(sa.text("SELECT face_synced FROM alert")).one() == (0,)
        columns = {c["name"]: c for c in sa.inspect(engine).get_columns("alert")}
        assert columns["face_synced"]["nullable"] is False
        with engine.begin() as conn, Operations.context(MigrationContext.configure(conn)):
            mig.downgrade()
        assert [c["name"] for c in sa.inspect(engine).get_columns("alert")] == ["id"]
    engine.dispose()
