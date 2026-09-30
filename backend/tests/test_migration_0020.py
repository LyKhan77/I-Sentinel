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
