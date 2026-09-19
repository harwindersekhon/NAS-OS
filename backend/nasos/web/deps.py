"""FastAPI dependencies: a DB session per request, the shared agent client /
event bus, and session/RBAC enforcement. CSRF itself is a middleware (see
web/main.py) since it has to run before routing, not as a per-route Depends.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import AsyncIterator, Iterator

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session as OrmSession

from nasos.config import Settings
from nasos.db.models import Session as DbSession
from nasos.events.bus import EventBus
from nasos.rpc.client import AgentClient, FileWorkerClient
from nasos.rpc.schemas import RpcContext
from nasos.services.auth import resolve_session

SESSION_COOKIE = "nasos_session"


def get_settings(request: Request) -> Settings:
    return request.app.state.settings  # type: ignore[no-any-return]


def get_db(request: Request) -> Iterator[OrmSession]:
    session_factory = request.app.state.session_factory
    with session_factory() as db:
        yield db


def get_agent_client(request: Request) -> AgentClient:
    return request.app.state.agent_client  # type: ignore[no-any-return]


def get_event_bus(request: Request) -> EventBus:
    return request.app.state.event_bus  # type: ignore[no-any-return]


def get_current_session(
    request: Request,
    db: OrmSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> DbSession:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="not authenticated")
    idle_timeout = dt.timedelta(minutes=settings.session_idle_timeout_minutes)
    session = resolve_session(db, token, idle_timeout=idle_timeout)
    if session is None:
        raise HTTPException(status_code=401, detail="session expired")
    return session


def require_admin(session: DbSession = Depends(get_current_session)) -> DbSession:
    if session.role != "admin":
        raise HTTPException(status_code=403, detail="admin role required")
    return session


async def get_file_worker_client(
    request: Request, session: DbSession = Depends(get_current_session)
) -> AsyncIterator[FileWorkerClient]:
    """File Station is available to every logged-in user, not just admins
    (PLAN.md §3: "nasos-users -> role user (File Station + own password)"),
    scoped to *their own* fileworker — the uid this session belongs to, not
    a resource an admin route would otherwise gate.
    """
    factory = request.app.state.file_worker_client_factory
    ctx = RpcContext(user=session.username, role=session.role)
    client = await factory(ctx, session.uid, session.username)
    try:
        yield client
    finally:
        await client.close()
