"""disks_seen; volumes gains device/uuid/raid_level/array_name/disk_serials

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-19 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "disks_seen",
        sa.Column("serial", sa.String(128), primary_key=True),
        sa.Column("path", sa.String(255), nullable=False),
        sa.Column("model", sa.String(255), nullable=True),
        sa.Column("size", sa.Integer, nullable=True),
        sa.Column("first_seen_at", sa.DateTime, nullable=False),
        sa.Column("last_seen_at", sa.DateTime, nullable=False),
        sa.Column("last_health", sa.String(16), nullable=True),
    )

    with op.batch_alter_table("volumes") as batch_op:
        batch_op.add_column(sa.Column("device", sa.String(255), nullable=True))
        batch_op.add_column(sa.Column("uuid", sa.String(64), nullable=True))
        batch_op.add_column(sa.Column("raid_level", sa.String(16), nullable=True))
        batch_op.add_column(sa.Column("array_name", sa.String(64), nullable=True))
        batch_op.add_column(sa.Column("disk_serials", sa.JSON, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("volumes") as batch_op:
        batch_op.drop_column("disk_serials")
        batch_op.drop_column("array_name")
        batch_op.drop_column("raid_level")
        batch_op.drop_column("uuid")
        batch_op.drop_column("device")

    op.drop_table("disks_seen")
