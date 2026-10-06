"""Add optional zone captioning and event AI audit records."""
from alembic import op
import sqlalchemy as sa

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("zone", sa.Column("ai_caption", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("zone", sa.Column("ai_prompt", sa.Text(), nullable=True))
    op.create_table(
        "event_ai",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("event.id"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("preset", sa.String(64), nullable=True),
        sa.Column("question", sa.Text(), nullable=True),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("error", sa.String(255), nullable=True),
        sa.Column("model", sa.String(64), nullable=True),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("actor", sa.String(64), nullable=True),
        sa.Column("frames_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_event_ai_event_kind", "event_ai", ["event_id", "kind"])


def downgrade():
    op.drop_index("ix_event_ai_event_kind", table_name="event_ai")
    op.drop_table("event_ai")
    with op.batch_alter_table("zone") as batch:
        batch.drop_column("ai_prompt")
        batch.drop_column("ai_caption")
