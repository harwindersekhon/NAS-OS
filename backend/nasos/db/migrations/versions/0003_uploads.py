"""uploads

Revision ID: 0003
Revises: 0002
Create Date: 2026-01-03 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "uploads",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("uid", sa.Integer, nullable=False),
        sa.Column("dest_path", sa.String(255), nullable=False),
        sa.Column("size", sa.Integer, nullable=False),
        sa.Column("offset", sa.Integer, nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_uploads_created_at", "uploads", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_uploads_created_at", table_name="uploads")
    op.drop_table("uploads")
