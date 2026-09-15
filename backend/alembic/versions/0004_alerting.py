"""alerting

Revision ID: 0004
Revises: 0003
Create Date: 2026-01-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0004'
down_revision: Union[str, Sequence[str], None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('zone', sa.Column('loiter_seconds', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('zone', sa.Column('speed_limit_mps', sa.Float(), nullable=False, server_default='0'))
    op.add_column('camera', sa.Column('meters_per_pixel', sa.Float(), nullable=True))

    op.create_table('telegram_chat',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('label', sa.String(length=64), nullable=False),
    sa.Column('chat_id', sa.String(length=64), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('chat_id')
    )

    op.create_table('alert',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('event_id', sa.Integer(), nullable=False),
    sa.Column('camera_id', sa.Integer(), nullable=False),
    sa.Column('zone_id', sa.Integer(), nullable=True),
    sa.Column('type', sa.String(length=32), nullable=False),
    sa.Column('severity', sa.String(length=16), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('error', sa.String(length=255), nullable=True),
    sa.Column('chat_id', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['event_id'], ['event.id'], ),
    sa.ForeignKeyConstraint(['camera_id'], ['camera.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('event_id')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('alert')
    op.drop_table('telegram_chat')
    op.drop_column('camera', 'meters_per_pixel')
    op.drop_column('zone', 'speed_limit_mps')
    op.drop_column('zone', 'loiter_seconds')
