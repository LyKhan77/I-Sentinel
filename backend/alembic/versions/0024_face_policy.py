"""Kolom kebijakan pengenalan wajah di detector_setting (ambang, margin, identitas)."""
from alembic import op
import sqlalchemy as sa

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None

NEW_COLUMNS = (
    ("face_match_threshold", sa.Float(), "0.4"),
    ("face_match_margin", sa.Float(), "0.15"),
    ("face_max_pitch", sa.Float(), "0.3"),
    ("face_best_k", sa.Integer(), "5"),
    ("face_ident_min_width_px", sa.Float(), "60.0"),
    ("face_ident_window_s", sa.Float(), "8.0"),
)


def upgrade():
    for name, type_, default in NEW_COLUMNS:
        op.add_column("detector_setting",
                      sa.Column(name, type_, nullable=False, server_default=sa.text(default)))


def downgrade():
    with op.batch_alter_table("detector_setting") as batch:
        for name, _type, _default in NEW_COLUMNS:
            batch.drop_column(name)
