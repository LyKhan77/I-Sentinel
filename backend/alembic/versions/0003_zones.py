"""zones

Revision ID: 0003
Revises: 0002
Create Date: 2026-01-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0003'
down_revision: Union[str, Sequence[str], None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('zone',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('camera_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('type', sa.String(length=16), nullable=False),
    sa.Column('direction', sa.String(length=8), nullable=True),
    sa.Column('polygon', sa.JSON(), nullable=False),
    sa.Column('schedule', sa.JSON(), nullable=True),
    sa.Column('severity', sa.String(length=16), nullable=False),
    sa.Column('rate_limit_min', sa.Integer(), nullable=False),
    sa.Column('snapshot', sa.Boolean(), nullable=False),
    sa.Column('telegram', sa.Boolean(), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['camera_id'], ['camera.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('zone')
