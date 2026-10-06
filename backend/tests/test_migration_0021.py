"""Exercise additive AI migration against old rows and repeated upgrade cycles."""
import importlib.util
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_upgrade_downgrade():
    path = Path(__file__).resolve().parents[1] / "alembic/versions/0021_ai_caption.py"
    spec = importlib.util.spec_from_file_location("mig0021", path)
    mig = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mig)
    engine = sa.create_engine("sqlite://")
    meta = sa.MetaData()
    sa.Table("event", meta, sa.Column("id", sa.Integer, primary_key=True))
    sa.Table("zone", meta, sa.Column("id", sa.Integer, primary_key=True))
    meta.create_all(engine)
    with engine.begin() as conn:
        conn.execute(sa.text("INSERT INTO zone (id) VALUES (1)"))
    for _ in range(2):
        with engine.begin() as conn, Operations.context(MigrationContext.configure(conn)):
            mig.upgrade()
        with engine.connect() as conn:
            assert conn.execute(sa.text("SELECT ai_caption, ai_prompt FROM zone")).one() == (0, None)
        inspector = sa.inspect(engine)
        assert "event_ai" in inspector.get_table_names()
        assert any(i["name"] == "ix_event_ai_event_kind" and i["column_names"] == ["event_id", "kind"]
                   for i in inspector.get_indexes("event_ai"))
        with engine.begin() as conn, Operations.context(MigrationContext.configure(conn)):
            mig.downgrade()
        assert "event_ai" not in sa.inspect(engine).get_table_names()
        assert [c["name"] for c in sa.inspect(engine).get_columns("zone")] == ["id"]
