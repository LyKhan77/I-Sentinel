"""alert/event camera_id nullable + ON DELETE SET NULL: rows survive camera deletion.

Revision ID: 0008
Revises: 0007
"""

from alembic import op
import sqlalchemy as sa


revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def _rebind(table: str, constraint: str) -> None:
    op.drop_constraint(constraint, table, type_="foreignkey")
    op.create_foreign_key(constraint, table, "camera", ["camera_id"], ["id"], ondelete="SET NULL")


def upgrade() -> None:
    op.alter_column("alert", "camera_id", existing_type=sa.Integer(), nullable=True)
    _rebind("alert", "alert_camera_id_fkey")
    _rebind("event", "event_camera_id_fkey")


def downgrade() -> None:
    op.execute("update alert set camera_id = null where camera_id is not null and camera_id not in (select id from camera)")
    op.execute("update event set camera_id = null where camera_id is not null and camera_id not in (select id from camera)")
    op.drop_constraint("alert_camera_id_fkey", "alert", type_="foreignkey")
    op.create_foreign_key("alert_camera_id_fkey", "alert", "camera", ["camera_id"], ["id"])
    op.drop_constraint("event_camera_id_fkey", "event", type_="foreignkey")
    op.create_foreign_key("event_camera_id_fkey", "event", "camera", ["camera_id"], ["id"])
    op.alter_column("alert", "camera_id", existing_type=sa.Integer(), nullable=False)
