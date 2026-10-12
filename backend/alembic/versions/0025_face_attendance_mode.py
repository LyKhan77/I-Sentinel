"""Kolom mode dan jendela absensi di detector_setting (saklar legacy/unified, tahap 2)."""
from alembic import op
import sqlalchemy as sa

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None

NEW_COLUMNS = (
    ("face_attendance_mode", sa.String(16), "'legacy'"),
    ("face_attendance_window_s", sa.Float(), "1.5"),
)


def upgrade():
    for name, type_, default in NEW_COLUMNS:
        op.add_column("detector_setting",
                      sa.Column(name, type_, nullable=False, server_default=sa.text(default)))


def downgrade():
    with op.batch_alter_table("detector_setting") as batch:
        for name, _type, _default in NEW_COLUMNS:
            batch.drop_column(name)
