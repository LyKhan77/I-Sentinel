"""monitoring_sample: riwayat metrik Monitoring per node per menit (S2), disimpan 7 hari.

Revision ID: 0019
Revises: 0018
"""

from alembic import op
import sqlalchemy as sa

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "monitoring_sample",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("node_id", sa.Integer(), sa.ForeignKey("node.id", ondelete="CASCADE"), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.UniqueConstraint("node_id", "ts", name="uq_monitoring_sample_node_ts"),
    )
    op.create_index("ix_monitoring_sample_ts", "monitoring_sample", ["ts"])


def downgrade() -> None:
    op.drop_index("ix_monitoring_sample_ts", table_name="monitoring_sample")
    op.drop_table("monitoring_sample")
