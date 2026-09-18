"""node.detector_device (GPU pin via config push UI): expand-only.

Revision ID: 0010
Revises: 0009
"""

from alembic import op
import sqlalchemy as sa


revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("node", sa.Column("detector_device", sa.String(16), nullable=True))


def downgrade() -> None:
    op.drop_column("node", "detector_device")
