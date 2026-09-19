"""users REST API (PLAN.md §3)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session as OrmSession

from nasos.db.models import Session as DbSession
from nasos.db.models import User
from nasos.rpc.client import AgentClient
from nasos.rpc.schemas import RpcContext
from nasos.rpc.transport import RpcCallError
from nasos.services import audit
from nasos.services import users as users_service
from nasos.services.users import UserServiceError
from nasos.web.deps import get_agent_client, get_current_session, get_db, require_admin

router = APIRouter(prefix="/api/v1/users", tags=["users"])


class UserOut(BaseModel):
    uid: int
    username: str
    description: str
    smb_enabled: bool
    ftp_enabled: bool
    created_by_nasos: bool
    smb_password_synced: bool

    @classmethod
    def from_model(cls, user: User) -> UserOut:
        return cls(
            uid=user.uid,
            username=user.username,
            description=user.description or "",
            smb_enabled=user.smb_enabled,
            ftp_enabled=user.ftp_enabled,
            created_by_nasos=user.created_by_nasos,
            smb_password_synced=user.smb_password_synced,
        )


class UserCreateRequest(BaseModel):
    username: str
    password: str
    description: str = ""


class UserImportRequest(BaseModel):
    username: str
    description: str = ""


class UserUpdateRequest(BaseModel):
    description: str | None = None
    smb_enabled: bool | None = None


class SetPasswordRequest(BaseModel):
    password: str


def _ctx(session: DbSession) -> RpcContext:
    return RpcContext(user=session.username, role=session.role)


def _get_user_or_404(db: OrmSession, uid: int) -> User:
    user = users_service.get_user(db, uid)
    if user is None:
        raise HTTPException(status_code=404, detail="no such user")
    return user


@router.get("", response_model=list[UserOut])
def list_users(
    db: OrmSession = Depends(get_db),
    session: DbSession = Depends(get_current_session),  # noqa: ARG001
) -> list[UserOut]:
    return [UserOut.from_model(u) for u in users_service.list_users(db)]


@router.post("", response_model=UserOut)
async def create_user(
    body: UserCreateRequest,
    request: Request,
    db: OrmSession = Depends(get_db),
    agent: AgentClient = Depends(get_agent_client),
    session: DbSession = Depends(require_admin),
) -> UserOut:
    try:
        user = await users_service.create_user(
            db,
            agent,
            _ctx(session),
            username=body.username,
            password=body.password,
            description=body.description,
        )
    except UserServiceError as exc:
        audit.record(
            db,
            username=session.username,
            role=session.role,
            ip=request.client.host if request.client else None,
            method="POST",
            path="/api/v1/users",
            action="users.create",
            status_code=400,
            detail=str(exc),
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit.record(
        db,
        username=session.username,
        role=session.role,
        ip=request.client.host if request.client else None,
        method="POST",
        path="/api/v1/users",
        action="users.create",
        status_code=200,
    )
    return UserOut.from_model(user)


@router.post("/import", response_model=UserOut)
async def import_user(
    body: UserImportRequest,
    db: OrmSession = Depends(get_db),
    agent: AgentClient = Depends(get_agent_client),
    session: DbSession = Depends(require_admin),
) -> UserOut:
    try:
        user = await users_service.import_user(
            db, agent, _ctx(session), username=body.username, description=body.description
        )
    except UserServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return UserOut.from_model(user)


@router.patch("/{uid}", response_model=UserOut)
async def update_user(
    uid: int,
    body: UserUpdateRequest,
    db: OrmSession = Depends(get_db),
    agent: AgentClient = Depends(get_agent_client),
    session: DbSession = Depends(require_admin),
) -> UserOut:
    user = _get_user_or_404(db, uid)
    if body.description is not None:
        users_service.update_description(db, user, description=body.description)
    if body.smb_enabled is not None:
        try:
            await users_service.set_smb_enabled(
                db, agent, _ctx(session), user, enabled=body.smb_enabled
            )
        except UserServiceError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    return UserOut.from_model(user)


@router.post("/{uid}/password")
async def set_password(
    uid: int,
    body: SetPasswordRequest,
    db: OrmSession = Depends(get_db),
    agent: AgentClient = Depends(get_agent_client),
    session: DbSession = Depends(get_current_session),
) -> UserOut:
    # Admins can reset anyone's password; a user can only change their own
    # (PLAN.md §3: "nasos-users -> role user (File Station + own password)").
    if session.role != "admin" and session.uid != uid:
        raise HTTPException(status_code=403, detail="can only change your own password")
    user = _get_user_or_404(db, uid)
    try:
        updated = await users_service.set_password(
            db, agent, _ctx(session), user, password=body.password
        )
    except UserServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return UserOut.from_model(updated)


@router.delete("/{uid}")
async def delete_user(
    uid: int,
    delete_home: bool = False,
    db: OrmSession = Depends(get_db),
    agent: AgentClient = Depends(get_agent_client),
    session: DbSession = Depends(require_admin),
) -> dict[str, bool]:
    user = _get_user_or_404(db, uid)
    try:
        await users_service.delete_user(db, agent, _ctx(session), user, delete_home=delete_home)
    except (UserServiceError, RpcCallError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}
