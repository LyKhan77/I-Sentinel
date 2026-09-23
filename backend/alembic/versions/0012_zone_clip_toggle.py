"""zone.clip — toggle rekam clip per zona (expand-only).

Revision ID: 0012
Revises: 0011
"""

from alembic import op
import sqlalchemy as sa


revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("zone", sa.Column("clip", sa.Boolean(), nullable=False,
                                    server_default=sa.true()))


def downgrade() -> None:
    op.drop_column("zone", "clip")
