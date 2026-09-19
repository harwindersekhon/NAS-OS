"""groups REST API (PLAN.md §3)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as OrmSession

from nasos.db.models import GroupMeta
from nasos.db.models import Session as DbSession
from nasos.rpc.client import AgentClient
from nasos.rpc.schemas import RpcContext
from nasos.services import groups as groups_service
from nasos.services.groups import GroupServiceError
from nasos.web.deps import get_agent_client, get_current_session, get_db, require_admin

router = APIRouter(prefix="/api/v1/groups", tags=["groups"])


class GroupOut(BaseModel):
    gid: int
    name: str
    description: str
    created_by_nasos: bool

    @classmethod
    def from_model(cls, group: GroupMeta) -> GroupOut:
        return cls(
            gid=group.gid,
            name=group.name,
            description=group.description or "",
            created_by_nasos=group.created_by_nasos,
        )


class GroupCreateRequest(BaseModel):
    name: str
    description: str = ""


class MembershipRequest(BaseModel):
    username: str


def _ctx(session: DbSession) -> RpcContext:
    return RpcContext(user=session.username, role=session.role)


def _get_group_or_404(db: OrmSession, gid: int) -> GroupMeta:
    group = groups_service.get_group(db, gid)
    if group is None:
        raise HTTPException(status_code=404, detail="no such group")
    return group


@router.get("", response_model=list[GroupOut])
def list_groups(
    db: OrmSession = Depends(get_db),
    session: DbSession = Depends(get_current_session),  # noqa: ARG001
) -> list[GroupOut]:
    return [GroupOut.from_model(g) for g in groups_service.list_groups(db)]


@router.post("", response_model=GroupOut)
async def create_group(
    body: GroupCreateRequest,
    db: OrmSession = Depends(get_db),
    agent: AgentClient = Depends(get_agent_client),
    session: DbSession = Depends(require_admin),
) -> GroupOut:
    try:
        group = await groups_service.create_group(
            db, agent, _ctx(session), name=body.name, description=body.description
        )
    except GroupServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return GroupOut.from_model(group)


@router.delete("/{gid}")
async def delete_group(
    gid: int,
    db: OrmSession = Depends(get_db),
    agent: AgentClient = Depends(get_agent_client),
    session: DbSession = Depends(require_admin),
) -> dict[str, bool]:
    group = _get_group_or_404(db, gid)
    try:
        await groups_service.delete_group(db, agent, _ctx(session), group)
    except GroupServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}


@router.post("/{gid}/members")
async def add_member(
    gid: int,
    body: MembershipRequest,
    db: OrmSession = Depends(get_db),
    agent: AgentClient = Depends(get_agent_client),
    session: DbSession = Depends(require_admin),
) -> dict[str, bool]:
    group = _get_group_or_404(db, gid)
    try:
        await groups_service.add_member(agent, _ctx(session), group, username=body.username)
    except GroupServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}


@router.delete("/{gid}/members/{username}")
async def remove_member(
    gid: int,
    username: str,
    db: OrmSession = Depends(get_db),
    agent: AgentClient = Depends(get_agent_client),
    session: DbSession = Depends(require_admin),
) -> dict[str, bool]:
    group = _get_group_or_404(db, gid)
    try:
        await groups_service.remove_member(agent, _ctx(session), group, username=username)
    except GroupServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}
