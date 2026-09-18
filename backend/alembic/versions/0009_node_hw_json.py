"""node.hw + node.modules JSON columns (vision heartbeat GPU probe): expand-only.

Revision ID: 0009
Revises: 0008
"""

from alembic import op
import sqlalchemy as sa


revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("node", sa.Column("hw", sa.JSON(), nullable=True))
    op.add_column("node", sa.Column("modules", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("node", "modules")
    op.drop_column("node", "hw")
