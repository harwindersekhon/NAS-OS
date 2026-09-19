"""initial: sessions, audit_log, settings, notifications

Revision ID: 0001
Revises:
Create Date: 2026-01-01 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sessions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("uid", sa.Integer, nullable=False),
        sa.Column("username", sa.String(32), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("created", sa.DateTime, nullable=False),
        sa.Column("last_seen", sa.DateTime, nullable=False),
        sa.Column("ip", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(255), nullable=True),
    )
    op.create_index("ix_sessions_token_hash", "sessions", ["token_hash"], unique=True)

    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("ts", sa.DateTime, nullable=False),
        sa.Column("username", sa.String(32), nullable=True),
        sa.Column("role", sa.String(16), nullable=True),
        sa.Column("ip", sa.String(45), nullable=True),
        sa.Column("method", sa.String(8), nullable=False),
        sa.Column("path", sa.String(255), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("status_code", sa.Integer, nullable=False),
        sa.Column("detail", sa.String(1024), nullable=True),
    )
    op.create_index("ix_audit_log_ts", "audit_log", ["ts"])

    op.create_table(
        "settings",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("value", sa.JSON, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )

    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("ts", sa.DateTime, nullable=False),
        sa.Column("level", sa.String(16), nullable=False),
        sa.Column("title", sa.String(128), nullable=False),
        sa.Column("message", sa.String(1024), nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("read_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_notifications_ts", "notifications", ["ts"])


def downgrade() -> None:
    op.drop_table("notifications")
    op.drop_table("settings")
    op.drop_index("ix_audit_log_ts", table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_index("ix_sessions_token_hash", table_name="sessions")
    op.drop_table("sessions")
