"""attendance

Revision ID: 0005
Revises: 0004
Create Date: 2026-01-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0005'
down_revision: Union[str, Sequence[str], None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('shift',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('start_time', sa.String(length=5), nullable=False),
    sa.Column('end_time', sa.String(length=5), nullable=False),
    sa.Column('tolerance_min', sa.Integer(), nullable=False, server_default='15'),
    sa.Column('workdays', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )

    op.create_table('employee',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.Column('employee_code', sa.String(length=32), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
    sa.Column('shift_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['shift_id'], ['shift.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('employee_code')
    )

    op.create_table('face_embedding',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('employee_id', sa.Integer(), nullable=False),
    sa.Column('vector', sa.JSON(), nullable=False),
    sa.Column('source_image_path', sa.String(length=255), nullable=True),
    sa.Column('quality', sa.Float(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['employee_id'], ['employee.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_face_embedding_employee_id', 'face_embedding', ['employee_id'])

    op.create_table('attendance_event',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('employee_id', sa.Integer(), nullable=False),
    sa.Column('camera_id', sa.Integer(), nullable=False),
    sa.Column('zone_id', sa.Integer(), nullable=True),
    sa.Column('direction', sa.String(length=8), nullable=False),
    sa.Column('ts_event', sa.DateTime(timezone=True), nullable=False),
    sa.Column('match_score', sa.Float(), nullable=True),
    sa.Column('snapshot_path', sa.String(length=255), nullable=True),
    sa.Column('event_id', sa.String(length=36), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['employee_id'], ['employee.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['camera_id'], ['camera.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('event_id')
    )
    op.create_index('ix_attendance_event_employee_ts', 'attendance_event', ['employee_id', 'ts_event'])

    op.create_table('attendance_day',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('employee_id', sa.Integer(), nullable=False),
    sa.Column('date', sa.Date(), nullable=False),
    sa.Column('first_entry', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_exit', sa.DateTime(timezone=True), nullable=True),
    sa.Column('duration_min', sa.Integer(), nullable=True),
    sa.Column('status', sa.String(length=12), nullable=False, server_default='waiting'),
    sa.Column('late_minutes', sa.Integer(), nullable=True),
    sa.Column('override_note', sa.String(length=255), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['employee_id'], ['employee.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('employee_id', 'date')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('attendance_day')
    op.drop_index('ix_attendance_event_employee_ts', table_name='attendance_event')
    op.drop_table('attendance_event')
    op.drop_index('ix_face_embedding_employee_id', table_name='face_embedding')
    op.drop_table('face_embedding')
    op.drop_table('employee')
    op.drop_table('shift')
