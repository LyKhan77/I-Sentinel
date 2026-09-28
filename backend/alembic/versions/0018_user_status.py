"""user: status aktif, versi token (pencabutan sesi), login terakhir.

Revision ID: 0018
Revises: 0017
"""

from alembic import op
import sqlalchemy as sa

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user", sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("user", sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("user", sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    # batch: SQLite (tes) tidak selalu mendukung DROP COLUMN; Postgres tetap ALTER biasa
    with op.batch_alter_table("user") as batch:
        batch.drop_column("last_login_at")
        batch.drop_column("token_version")
        batch.drop_column("is_active")
