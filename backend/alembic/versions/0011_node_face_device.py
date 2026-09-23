"""node.face_device (GPU pin face recognition via config push UI): expand-only.

Revision ID: 0011
Revises: 0010
"""

from alembic import op
import sqlalchemy as sa


revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("node", sa.Column("face_device", sa.String(16), nullable=True))


def downgrade() -> None:
    op.drop_column("node", "face_device")
