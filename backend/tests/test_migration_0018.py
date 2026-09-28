"""0018: status akun, versi token, login terakhir pada tabel user lama."""
import importlib.util
import pathlib

import sqlalchemy as sa

_PATH = pathlib.Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0018_user_status.py"
_spec = importlib.util.spec_from_file_location("mig0018", _PATH)
mig = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mig)


def test_upgrade_downgrade_on_old_user_table():
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    engine = sa.create_engine("sqlite://")
    meta = sa.MetaData()
    sa.Table("user", meta,
             sa.Column("id", sa.Integer, primary_key=True),
             sa.Column("username", sa.String(64)),
             sa.Column("password_hash", sa.String(255)),
             sa.Column("role", sa.String(16)),
             sa.Column("locale", sa.String(8)),
             sa.Column("created_at", sa.DateTime(timezone=True)))
    meta.create_all(engine)
    with engine.begin() as c:
        c.execute(sa.text("INSERT INTO \"user\" (id, username, password_hash, role, locale) VALUES (1, 'a', 'h', 'admin', 'id')"))

    def run(fn):
        with engine.begin() as conn, Operations.context(MigrationContext.configure(conn)):
            fn()

    run(mig.upgrade)
    with engine.connect() as c:
        row = c.execute(sa.text("SELECT is_active, token_version, last_login_at FROM \"user\" WHERE id = 1")).one()
    assert bool(row.is_active) is True and row.token_version == 0 and row.last_login_at is None

    run(mig.downgrade)
    cols = {col["name"] for col in sa.inspect(engine).get_columns("user")}
    assert not cols & {"is_active", "token_version", "last_login_at"}
    assert {"id", "username", "password_hash", "role"} <= cols
