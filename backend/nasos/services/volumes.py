"""volumes.* business logic (PLAN.md §6, M2 scope: register an existing
mounted filesystem). Runs in the web process.
"""

from __future__ import annotations

from typing import cast

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from nasos.db.models import Volume
from nasos.rpc.client import AgentClient
from nasos.rpc.schemas import RpcContext, VolumeInfo
from nasos.rpc.transport import RpcCallError


class VolumeServiceError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def list_volumes(db: OrmSession) -> list[Volume]:
    return list(db.execute(select(Volume)).scalars())


def get_volume(db: OrmSession, volume_id: int) -> Volume | None:
    return db.get(Volume, volume_id)


async def register_volume(
    db: OrmSession, agent: AgentClient, ctx: RpcContext, *, name: str, mountpoint: str
) -> Volume:
    try:
        info = cast(VolumeInfo, await agent.call("volumes.register", ctx, mountpoint=mountpoint))
    except RpcCallError as exc:
        raise VolumeServiceError(exc.code, exc.message) from exc

    volume = Volume(
        name=name, mountpoint=info.mountpoint, filesystem=info.filesystem, managed=False
    )
    db.add(volume)
    db.commit()
    return volume
