"""detector_setting: gerbang wajah attendance (R5b) + buang embedding payload lama.

Revision ID: 0016
Revises: 0015
"""

from alembic import op
import sqlalchemy as sa

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

FACE_COLUMNS = (
    ("face_min_width_px", sa.Float(), "80"),
    ("face_min_det_score", sa.Float(), "0.6"),
    ("face_max_yaw", sa.Float(), "0.35"),
    ("face_blur_min", sa.Float(), "120"),
    ("face_min_frames", sa.Integer(), "3"),
)


def strip_embedding(payload):
    """Return payload without embedding, or None if no removal needed."""
    if not isinstance(payload, dict) or "embedding" not in payload:
        return None
    return {key: value for key, value in payload.items() if key != "embedding"}


def upgrade() -> None:
    for name, type_, default in FACE_COLUMNS:
        op.add_column("detector_setting",
                      sa.Column(name, type_, nullable=False, server_default=default))
    # Biometric vectors are intentionally unrecoverable after this migration.
    event = sa.table("event", sa.column("id", sa.Integer), sa.column("type", sa.String),
                     sa.column("payload", sa.JSON))
    bind = op.get_bind()
    rows = bind.execute(sa.select(event.c.id, event.c.payload).where(event.c.type == "attendance"))
    for row_id, payload in rows.fetchall():
        cleaned = strip_embedding(payload)
        if cleaned is not None:
            bind.execute(event.update().where(event.c.id == row_id).values(payload=cleaned))


def downgrade() -> None:
    for name, _, _ in reversed(FACE_COLUMNS):
        op.drop_column("detector_setting", name)
