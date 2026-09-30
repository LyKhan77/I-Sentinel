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
