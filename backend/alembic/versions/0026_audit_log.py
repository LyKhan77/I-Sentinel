"""Tabel audit_log: jejak audit aksi user dengan rantai hash anti-tamper."""
from alembic import op
import sqlalchemy as sa
import sqlalchemy.dialects.postgresql

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("category", sa.String(16), nullable=False),
        sa.Column("action", sa.String(48), nullable=False),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column("actor_label", sa.String(64), nullable=False),
        sa.Column("target_type", sa.String(32), nullable=True),
        sa.Column("target_id", sa.String(64), nullable=True),
        sa.Column("target_label", sa.String(128), nullable=True),
        sa.Column("changes", sa.JSON().with_variant(sa.dialects.postgresql.JSONB(), "postgresql"), nullable=True),
        sa.Column("ip", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(255), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("prev_hash", sa.String(64), nullable=False),
        sa.Column("hash", sa.String(64), nullable=False),
    )
    op.create_index("ix_audit_log_ts", "audit_log", ["ts"])
    op.create_index("ix_audit_log_category_ts", "audit_log", ["category", "ts"])
    op.create_index("ix_audit_log_actor_label", "audit_log", ["actor_label"])
    op.create_index("ix_audit_log_target", "audit_log", ["target_type", "target_id"])


def downgrade():
    op.drop_index("ix_audit_log_target", table_name="audit_log")
    op.drop_index("ix_audit_log_actor_label", table_name="audit_log")
    op.drop_index("ix_audit_log_category_ts", table_name="audit_log")
    op.drop_index("ix_audit_log_ts", table_name="audit_log")
    op.drop_table("audit_log")
