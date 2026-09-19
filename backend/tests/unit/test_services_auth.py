from __future__ import annotations

import datetime as dt
from collections.abc import Iterator

import pytest
from sqlalchemy.orm import Session as OrmSession

from nasos.db.models import Base
from nasos.db.session import make_engine, make_session_factory
from nasos.rpc.schemas import AuthLoginResult
from nasos.services.auth import create_session, destroy_session, resolve_session


@pytest.fixture
def db() -> Iterator[OrmSession]:
    engine = make_engine(":memory:")
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    with factory() as session:
        yield session


IDENTITY = AuthLoginResult(uid=5000, username="admin", role="admin", display_name="Dev Admin")


def test_create_then_resolve_round_trips(db: OrmSession) -> None:
    token = create_session(db, IDENTITY, ip="127.0.0.1", user_agent="pytest")
    resolved = resolve_session(db, token, idle_timeout=dt.timedelta(minutes=30))
    assert resolved is not None
    assert resolved.username == "admin"
    assert resolved.role == "admin"


def test_resolve_unknown_token_returns_none(db: OrmSession) -> None:
    assert resolve_session(db, "not-a-real-token", idle_timeout=dt.timedelta(minutes=30)) is None


def test_resolve_expired_session_evicted(db: OrmSession) -> None:
    token = create_session(db, IDENTITY, ip=None, user_agent=None)
    # Idle timeout of zero: the session is already "expired" the instant it's checked.
    assert resolve_session(db, token, idle_timeout=dt.timedelta(seconds=-1)) is None
    # And it's gone for good, not just rejected this once.
    assert resolve_session(db, token, idle_timeout=dt.timedelta(minutes=30)) is None


def test_destroy_session_invalidates_token(db: OrmSession) -> None:
    token = create_session(db, IDENTITY, ip=None, user_agent=None)
    destroy_session(db, token)
    assert resolve_session(db, token, idle_timeout=dt.timedelta(minutes=30)) is None
