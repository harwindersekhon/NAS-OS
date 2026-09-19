"""users, groups_meta, volumes, shares, share_permissions, jobs, managed_files

Revision ID: 0002
Revises: 0001
Create Date: 2026-01-02 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("uid", sa.Integer, primary_key=True),
        sa.Column("username", sa.String(32), nullable=False),
        sa.Column("description", sa.String(255), nullable=True),
        sa.Column("smb_enabled", sa.Boolean, nullable=False),
        sa.Column("ftp_enabled", sa.Boolean, nullable=False),
        sa.Column("created_by_nasos", sa.Boolean, nullable=False),
        sa.Column("smb_password_synced", sa.Boolean, nullable=False),
    )
    op.create_index("ix_users_username", "users", ["username"], unique=True)

    op.create_table(
        "groups_meta",
        sa.Column("gid", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(32), nullable=False),
        sa.Column("description", sa.String(255), nullable=True),
        sa.Column("created_by_nasos", sa.Boolean, nullable=False),
    )
    op.create_index("ix_groups_meta_name", "groups_meta", ["name"], unique=True)

    op.create_table(
        "volumes",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("mountpoint", sa.String(255), nullable=False),
        sa.Column("filesystem", sa.String(16), nullable=False),
        sa.Column("managed", sa.Boolean, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("name"),
        sa.UniqueConstraint("mountpoint"),
    )

    op.create_table(
        "shares",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("volume_id", sa.Integer, sa.ForeignKey("volumes.id"), nullable=False),
        sa.Column("path", sa.String(255), nullable=False),
        sa.Column("description", sa.String(255), nullable=True),
        sa.Column("smb_enabled", sa.Boolean, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("name"),
        sa.UniqueConstraint("path"),
    )
    op.create_index("ix_shares_name", "shares", ["name"])

    op.create_table(
        "share_permissions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "share_id", sa.Integer, sa.ForeignKey("shares.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("principal_type", sa.String(8), nullable=False),
        sa.Column("principal", sa.String(32), nullable=False),
        sa.Column("level", sa.String(8), nullable=False),
        sa.UniqueConstraint("share_id", "principal_type", "principal"),
    )
    op.create_index("ix_share_permissions_share_id", "share_permissions", ["share_id"])

    op.create_table(
        "jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("resource", sa.String(128), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("progress", sa.Float, nullable=False),
        sa.Column("message", sa.String(255), nullable=True),
        sa.Column("created_by", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )

    op.create_table(
        "managed_files",
        sa.Column("path", sa.String(255), primary_key=True),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("managed_files")
    op.drop_table("jobs")
    op.drop_index("ix_share_permissions_share_id", table_name="share_permissions")
    op.drop_table("share_permissions")
    op.drop_index("ix_shares_name", table_name="shares")
    op.drop_table("shares")
    op.drop_table("volumes")
    op.drop_index("ix_groups_meta_name", table_name="groups_meta")
    op.drop_table("groups_meta")
    op.drop_index("ix_users_username", table_name="users")
    op.drop_table("users")
