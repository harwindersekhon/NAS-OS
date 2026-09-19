"""Session lifecycle: creation, lookup, idle-timeout enforcement. Tokens are
opaque (`secrets.token_urlsafe` — PLAN.md §3 "no JWT library"); only a
SHA-256 hash is stored, so a stolen DB file doesn't hand out live sessions.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import secrets

from sqlalchemy import delete, select
from sqlalchemy.orm import Session as OrmSession

from nasos.db.models import Session as DbSession
from nasos.rpc.schemas import AuthLoginResult

TOKEN_BYTES = 32


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(
    db: OrmSession, identity: AuthLoginResult, *, ip: str | None, user_agent: str | None
) -> str:
    token = secrets.token_urlsafe(TOKEN_BYTES)
    db.add(
        DbSession(
            token_hash=_hash_token(token),
            uid=identity.uid,
            username=identity.username,
            role=identity.role,
            ip=ip,
            user_agent=user_agent,
        )
    )
    db.commit()
    return token


def resolve_session(db: OrmSession, token: str, *, idle_timeout: dt.timedelta) -> DbSession | None:
    """Looks up a session by token, evicting it past the idle timeout.
    Touches `last_seen` (sliding expiry) on every valid lookup.
    """
    row = db.execute(
        select(DbSession).where(DbSession.token_hash == _hash_token(token))
    ).scalar_one_or_none()
    if row is None:
        return None
    now = dt.datetime.now(dt.UTC)
    last_seen = row.last_seen if row.last_seen.tzinfo else row.last_seen.replace(tzinfo=dt.UTC)
    if now - last_seen > idle_timeout:
        db.delete(row)
        db.commit()
        return None
    row.last_seen = now
    db.commit()
    return row


def destroy_session(db: OrmSession, token: str) -> None:
    db.execute(delete(DbSession).where(DbSession.token_hash == _hash_token(token)))
    db.commit()
