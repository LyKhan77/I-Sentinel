"""global detector settings singleton.

Revision ID: 0015
Revises: 0014
"""

from alembic import op
import sqlalchemy as sa

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "detector_setting",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("default_ai_fps", sa.Float(), nullable=False),
        sa.Column("default_confidence", sa.Float(), nullable=False),
        sa.Column("motion_enabled", sa.Boolean(), nullable=False),
        sa.Column("motion_threshold", sa.Float(), nullable=False),
        sa.Column("motion_min_area", sa.Float(), nullable=False),
        sa.Column("motion_force_interval_s", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("detector_setting")
