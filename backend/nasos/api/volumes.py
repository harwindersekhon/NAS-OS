"""volumes REST API (PLAN.md §6, M2 scope: register an existing mounted
filesystem)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session as OrmSession

from nasos.db.models import Session as DbSession
from nasos.db.models import Volume
from nasos.rpc.client import AgentClient
from nasos.rpc.schemas import RpcContext
from nasos.services import volumes as volumes_service
from nasos.services.volumes import VolumeServiceError
from nasos.web.deps import get_agent_client, get_current_session, get_db, require_admin

router = APIRouter(prefix="/api/v1/volumes", tags=["volumes"])


class VolumeOut(BaseModel):
    id: int
    name: str
    mountpoint: str
    filesystem: str
    managed: bool
    raid_level: str | None = None
    """Set only for volumes Storage Manager created (Milestone 4, PLAN.md
    §6) — null for M2's manually-registered ones."""

    @classmethod
    def from_model(cls, volume: Volume) -> VolumeOut:
        return cls(
            id=volume.id,
            name=volume.name,
            mountpoint=volume.mountpoint,
            filesystem=volume.filesystem,
            managed=volume.managed,
            raid_level=volume.raid_level,
        )


class VolumeRegisterRequest(BaseModel):
    name: str
    mountpoint: str


@router.get("", response_model=list[VolumeOut])
def list_volumes(
    db: OrmSession = Depends(get_db),
    session: DbSession = Depends(get_current_session),  # noqa: ARG001
) -> list[VolumeOut]:
    return [VolumeOut.from_model(v) for v in volumes_service.list_volumes(db)]


@router.post("", response_model=VolumeOut)
async def register_volume(
    body: VolumeRegisterRequest,
    db: OrmSession = Depends(get_db),
    agent: AgentClient = Depends(get_agent_client),
    session: DbSession = Depends(require_admin),
) -> VolumeOut:
    ctx = RpcContext(user=session.username, role=session.role)
    try:
        volume = await volumes_service.register_volume(
            db, agent, ctx, name=body.name, mountpoint=body.mountpoint
        )
    except VolumeServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return VolumeOut.from_model(volume)
