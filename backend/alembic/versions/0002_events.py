"""events

Revision ID: 0002
Revises: 0001
Create Date: 2026-01-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0002'
down_revision: Union[str, Sequence[str], None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('event',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('event_id', sa.String(length=36), nullable=False),
    sa.Column('type', sa.String(length=32), nullable=False),
    sa.Column('node_id', sa.Integer(), nullable=True),
    sa.Column('camera_id', sa.Integer(), nullable=True),
    sa.Column('zone_id', sa.Integer(), nullable=True),
    sa.Column('severity', sa.String(length=16), nullable=False),
    sa.Column('ts_event', sa.DateTime(timezone=True), nullable=False),
    sa.Column('payload', sa.JSON(), nullable=True),
    sa.Column('clip_path', sa.String(length=255), nullable=True),
    sa.Column('snapshot_path', sa.String(length=255), nullable=True),
    sa.Column('dedup_key', sa.String(length=128), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['node_id'], ['node.id'], ),
    sa.ForeignKeyConstraint(['camera_id'], ['camera.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('event_id'),
    sa.UniqueConstraint('dedup_key')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('event')
