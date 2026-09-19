"""shares REST API (PLAN.md §3)."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as OrmSession

from nasos.db.models import Session as DbSession
from nasos.db.models import Share
from nasos.rpc.client import AgentClient
from nasos.rpc.schemas import RpcContext
from nasos.services import shares as shares_service
from nasos.services.shares import ShareServiceError
from nasos.web.deps import get_agent_client, get_current_session, get_db, require_admin

router = APIRouter(prefix="/api/v1/shares", tags=["shares"])


class ShareOut(BaseModel):
    id: int
    name: str
    volume_id: int
    path: str
    description: str
    smb_enabled: bool

    @classmethod
    def from_model(cls, share: Share) -> ShareOut:
        return cls(
            id=share.id,
            name=share.name,
            volume_id=share.volume_id,
            path=share.path,
            description=share.description or "",
            smb_enabled=share.smb_enabled,
        )


class ShareCreateRequest(BaseModel):
    name: str
    volume_id: int
    description: str = ""


class PermissionEntry(BaseModel):
    principal_type: Literal["user", "group"]
    principal: str
    level: Literal["rw", "ro"]


class SetPermissionsRequest(BaseModel):
    permissions: list[PermissionEntry]
    recursive: bool = False


class SetPermissionsResponse(BaseModel):
    job_id: str | None


def _ctx(session: DbSession) -> RpcContext:
    return RpcContext(user=session.username, role=session.role)


def _get_share_or_404(db: OrmSession, share_id: int) -> Share:
    share = shares_service.get_share(db, share_id)
    if share is None:
        raise HTTPException(status_code=404, detail="no such share")
    return share


@router.get("", response_model=list[ShareOut])
def list_shares(
    db: OrmSession = Depends(get_db),
    session: DbSession = Depends(get_current_session),  # noqa: ARG001
) -> list[ShareOut]:
    return [ShareOut.from_model(s) for s in shares_service.list_shares(db)]


@router.post("", response_model=ShareOut)
async def create_share(
    body: ShareCreateRequest,
    db: OrmSession = Depends(get_db),
    agent: AgentClient = Depends(get_agent_client),
    session: DbSession = Depends(require_admin),
) -> ShareOut:
    ctx = _ctx(session)
    try:
        share = await shares_service.create_share(
            db, agent, ctx, name=body.name, volume_id=body.volume_id, description=body.description
        )
        # Idempotent: wires smb.conf's include + starts/enables smb/nmb +
        # opens firewalld, safe (and cheap) to (re-)run on every share create.
        await shares_service.ensure_samba_enabled(agent, ctx)
    except ShareServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ShareOut.from_model(share)


@router.delete("/{share_id}")
async def delete_share(
    share_id: int,
    delete_files: bool = False,
    db: OrmSession = Depends(get_db),
    agent: AgentClient = Depends(get_agent_client),
    session: DbSession = Depends(require_admin),
) -> dict[str, bool]:
    share = _get_share_or_404(db, share_id)
    try:
        await shares_service.delete_share(
            db, agent, _ctx(session), share, delete_files=delete_files
        )
    except ShareServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}


@router.get("/{share_id}/permissions", response_model=list[PermissionEntry])
def list_permissions(
    share_id: int,
    db: OrmSession = Depends(get_db),
    session: DbSession = Depends(get_current_session),  # noqa: ARG001
) -> list[PermissionEntry]:
    _get_share_or_404(db, share_id)
    return [
        PermissionEntry(principal_type=p.principal_type, principal=p.principal, level=p.level)  # type: ignore[arg-type]
        for p in shares_service.list_permissions(db, share_id)
    ]


@router.put("/{share_id}/permissions", response_model=SetPermissionsResponse)
async def set_permissions(
    share_id: int,
    body: SetPermissionsRequest,
    db: OrmSession = Depends(get_db),
    agent: AgentClient = Depends(get_agent_client),
    session: DbSession = Depends(require_admin),
) -> SetPermissionsResponse:
    share = _get_share_or_404(db, share_id)
    permissions = [(p.principal_type, p.principal, p.level) for p in body.permissions]
    try:
        job_id = await shares_service.set_share_permissions(
            db, agent, _ctx(session), share, permissions=permissions, recursive=body.recursive
        )
    except ShareServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SetPermissionsResponse(job_id=job_id)
