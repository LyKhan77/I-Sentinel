"""Keep Telegram message metadata for best-effort AI caption edits."""
from alembic import op
import sqlalchemy as sa

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("alert", sa.Column("message_id", sa.Integer(), nullable=True))
    op.add_column("alert", sa.Column("message_photo", sa.Boolean(), nullable=True))
    op.add_column("alert", sa.Column("ai_synced", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    with op.batch_alter_table("alert") as batch:
        batch.drop_column("ai_synced")
        batch.drop_column("message_photo")
        batch.drop_column("message_id")
