"""health_alert: alert kesehatan Monitoring (S3) — aktif (resolved_at NULL) & riwayat 7 hari.

Revision ID: 0020
Revises: 0019
"""

from alembic import op
import sqlalchemy as sa

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "health_alert",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("rule", sa.String(32), nullable=False),
        sa.Column("target", sa.String(64), nullable=False),
        sa.Column("node_id", sa.Integer(), sa.ForeignKey("node.id", ondelete="CASCADE"), nullable=False),
        sa.Column("camera_id", sa.Integer(), nullable=True),
        sa.Column("label", sa.String(128), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("value", sa.Float(), nullable=True),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("rule", "target", "started_at", name="uq_health_alert_rule_target_start"),
    )
    op.create_index("ix_health_alert_resolved_at", "health_alert", ["resolved_at"])


def downgrade() -> None:
    op.drop_index("ix_health_alert_resolved_at", table_name="health_alert")
    op.drop_table("health_alert")
