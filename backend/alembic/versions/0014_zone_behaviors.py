"""zone.behaviors + trigger_seconds, setelan deteksi per kamera (expand-only).

Kolom lama (`zone.type` nilai `absensi|restricted|free`, `dwell_seconds`,
`loiter_seconds`, `speed_limit_mps`) TIDAK dihapus agar downgrade aman; nilainya
dipetakan ke `behaviors` supaya satu istilah tersisa: `trigger_seconds` per
behavior ("lama di zona sebelum event terbit").

Revision ID: 0014
Revises: 0013
"""

from alembic import op
import sqlalchemy as sa


revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def new_type(old: str | None) -> str:
    """type lama → type baru (`attendance` | `behavior`); nilai baru dilewatkan."""
    if old == "absensi":
        return "attendance"
    if old in ("restricted", "free"):
        return "behavior"
    return old or "behavior"


def zone_behaviors(old_type: str | None, dwell: float | None,
                   loiter: float | None, speed: float | None) -> list[dict]:
    """Petakan kolom zona lama → daftar behavior + trigger_seconds-nya.

    Idempotent untuk type baru: `attendance` dipetakan seperti `absensi` (bila
    migrasi terulang setelah type sudah berubah), sedangkan `behavior` tidak
    ditebak-tebak — perilaku lamanya tidak bisa dipulihkan dari kolom.
    """
    if old_type in ("absensi", "attendance"):
        return [{"kind": "attendance", "trigger_seconds": int(dwell or 0)}]
    if old_type != "restricted":
        return []
    out = [{"kind": "intrusion", "trigger_seconds": int(dwell or 0)}]
    if (loiter or 0) > 0:
        out.append({"kind": "loitering", "trigger_seconds": int(loiter)})
    if (speed or 0) > 0:
        out.append({"kind": "running", "trigger_seconds": int(dwell or 0),
                    "speed_limit_mps": float(speed)})
    return out


def _old_type(new: str | None) -> str:
    """Kebalikan `new_type` — kode lama hanya mengerti absensi|restricted|free."""
    if new == "attendance":
        return "absensi"
    if new == "behavior":
        return "restricted"
    return new or "free"


def upgrade() -> None:
    op.add_column("zone", sa.Column("behaviors", sa.JSON(), nullable=True))
    op.add_column("zone", sa.Column("trigger_seconds", sa.Integer(), nullable=False,
                                    server_default="0"))
    op.add_column("camera", sa.Column("ai_fps", sa.Float(), nullable=True))
    op.add_column("camera", sa.Column("confidence", sa.Float(), nullable=True))
    op.add_column("camera", sa.Column("analyzers", sa.JSON(), nullable=True))
    op.add_column("camera", sa.Column("motion_enabled", sa.Boolean(), nullable=True))

    # Backfill: satu UPDATE per zona (jumlah zona kecil) memakai konstruksi
    # SQLAlchemy ber-tipe agar JSON di-encode benar di Postgres maupun SQLite.
    zone_tbl = sa.table(
        "zone",
        sa.column("id", sa.Integer),
        sa.column("type", sa.String),
        sa.column("behaviors", sa.JSON),
        sa.column("trigger_seconds", sa.Integer),
        sa.column("dwell_seconds", sa.Integer),
        sa.column("loiter_seconds", sa.Integer),
        sa.column("speed_limit_mps", sa.Float),
    )
    bind = op.get_bind()
    rows = bind.execute(sa.select(
        zone_tbl.c.id, zone_tbl.c.type, zone_tbl.c.dwell_seconds,
        zone_tbl.c.loiter_seconds, zone_tbl.c.speed_limit_mps)).all()
    for zid, ztype, dwell, loiter, speed in rows:
        bind.execute(
            zone_tbl.update().where(zone_tbl.c.id == zid).values(
                type=new_type(ztype),
                behaviors=zone_behaviors(ztype, dwell, loiter, speed),
                trigger_seconds=int(dwell or 0),
            )
        )


def downgrade() -> None:
    # Kembalikan type ke kosakata lama supaya kode pra-R5 tetap jalan setelah
    # downgrade (behaviors/trigger hilang bersama kolomnya).
    zone_tbl = sa.table(
        "zone",
        sa.column("id", sa.Integer),
        sa.column("type", sa.String),
    )
    bind = op.get_bind()
    rows = bind.execute(sa.select(zone_tbl.c.id, zone_tbl.c.type)).all()
    for zid, ztype in rows:
        if ztype in ("attendance", "behavior"):
            bind.execute(zone_tbl.update().where(zone_tbl.c.id == zid)
                         .values(type=_old_type(ztype)))

    op.drop_column("camera", "motion_enabled")
    op.drop_column("camera", "analyzers")
    op.drop_column("camera", "confidence")
    op.drop_column("camera", "ai_fps")
    op.drop_column("zone", "trigger_seconds")
    op.drop_column("zone", "behaviors")
