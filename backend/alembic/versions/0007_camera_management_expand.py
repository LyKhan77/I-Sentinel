"""expand camera management domain

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-16 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0007"
down_revision: Union[str, Sequence[str], None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "credential_profile",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("username", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("secret_ref", sa.String(length=128), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "location_group",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "stream_source",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False, server_default="unknown"),
        sa.Column("host", sa.String(length=255), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False, server_default="554"),
        sa.Column("vendor", sa.String(length=64), nullable=True),
        sa.Column("default_credential_id", sa.Integer(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["default_credential_id"], ["credential_profile.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.add_column("camera", sa.Column("source_id", sa.Integer(), nullable=True))
    op.add_column("camera", sa.Column("location_group_id", sa.Integer(), nullable=True))
    op.add_column("camera", sa.Column("credential_override_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_camera_source", "camera", "stream_source", ["source_id"], ["id"])
    op.create_foreign_key(
        "fk_camera_location_group", "camera", "location_group", ["location_group_id"], ["id"]
    )
    op.create_foreign_key(
        "fk_camera_credential_override",
        "camera",
        "credential_profile",
        ["credential_override_id"],
        ["id"],
    )
    op.create_index("ix_camera_source_id", "camera", ["source_id"], unique=False)
    op.create_index("ix_camera_location_group_id", "camera", ["location_group_id"], unique=False)
    op.create_index("uq_camera_source_main", "camera", ["source_id", "rtsp_main"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_camera_source_main", table_name="camera")
    op.drop_index("ix_camera_location_group_id", table_name="camera")
    op.drop_index("ix_camera_source_id", table_name="camera")
    op.drop_constraint("fk_camera_credential_override", "camera", type_="foreignkey")
    op.drop_constraint("fk_camera_location_group", "camera", type_="foreignkey")
    op.drop_constraint("fk_camera_source", "camera", type_="foreignkey")
    op.drop_column("camera", "credential_override_id")
    op.drop_column("camera", "location_group_id")
    op.drop_column("camera", "source_id")
    op.drop_table("stream_source")
    op.drop_table("location_group")
    op.drop_table("credential_profile")
