"""zone.dwell_seconds — trigger event setelah N detik di dalam zona (expand-only).

Revision ID: 0013
Revises: 0012
"""

from alembic import op
import sqlalchemy as sa


revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("zone", sa.Column("dwell_seconds", sa.Integer(), nullable=False,
                                    server_default="0"))


def downgrade() -> None:
    op.drop_column("zone", "dwell_seconds")
