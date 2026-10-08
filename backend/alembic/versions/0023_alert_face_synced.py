"""Keep Telegram message metadata for best-effort AI caption edits."""
from alembic import op
import sqlalchemy as sa

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("alert", sa.Column("face_synced", sa.Boolean(), nullable=False,
                                     server_default=sa.false()))


def downgrade():
    with op.batch_alter_table("alert") as batch:
        batch.drop_column("face_synced")
