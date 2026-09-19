"""auth API: login (PAM via the agent), logout, current-session info."""

from __future__ import annotations

from typing import cast

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session as OrmSession

from nasos.config import Settings
from nasos.db.models import Session as DbSession
from nasos.rpc.client import AgentClient
from nasos.rpc.schemas import AuthLoginResult, RpcContext
from nasos.rpc.transport import RpcCallError
from nasos.services import audit
from nasos.services.auth import create_session, destroy_session
from nasos.web.deps import (
    SESSION_COOKIE,
    get_agent_client,
    get_current_session,
    get_db,
    get_settings,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class SessionInfo(BaseModel):
    username: str
    role: str
    uid: int


@router.post("/login", response_model=SessionInfo)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: OrmSession = Depends(get_db),
    agent: AgentClient = Depends(get_agent_client),
    settings: Settings = Depends(get_settings),
) -> SessionInfo:
    ip = request.client.host if request.client else None
    ctx = RpcContext(ip=ip)
    try:
        identity = cast(
            AuthLoginResult,
            await agent.call("auth.login", ctx, username=body.username, password=body.password),
        )
    except RpcCallError as exc:
        audit.record(
            db,
            username=body.username,
            role=None,
            ip=ip,
            method="POST",
            path="/api/v1/auth/login",
            action="auth.login",
            status_code=401,
            detail=exc.code,
        )
        raise HTTPException(status_code=401, detail="invalid username or password") from exc

    token = create_session(db, identity, ip=ip, user_agent=request.headers.get("user-agent"))
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        max_age=settings.session_idle_timeout_minutes * 60,
    )
    audit.record(
        db,
        username=identity.username,
        role=identity.role,
        ip=ip,
        method="POST",
        path="/api/v1/auth/login",
        action="auth.login",
        status_code=200,
    )
    return SessionInfo(username=identity.username, role=identity.role, uid=identity.uid)


@router.post("/logout")
def logout(
    request: Request, response: Response, db: OrmSession = Depends(get_db)
) -> dict[str, bool]:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        destroy_session(db, token)
    response.delete_cookie(SESSION_COOKIE)
    return {"ok": True}


@router.get("/me", response_model=SessionInfo)
def me(session: DbSession = Depends(get_current_session)) -> SessionInfo:
    return SessionInfo(username=session.username, role=session.role, uid=session.uid)
