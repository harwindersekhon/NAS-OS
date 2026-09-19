"""groups.* business logic (PLAN.md §3: custom groups beyond nasos-admin /
nasos-users, usable as share_permissions principals). Runs in the web process.
"""

from __future__ import annotations

from typing import cast

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from nasos.db.models import GroupMeta
from nasos.rpc.client import AgentClient
from nasos.rpc.schemas import GroupInfo, RpcContext
from nasos.rpc.transport import RpcCallError


class GroupServiceError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def list_groups(db: OrmSession) -> list[GroupMeta]:
    return list(db.execute(select(GroupMeta)).scalars())


def get_group(db: OrmSession, gid: int) -> GroupMeta | None:
    return db.get(GroupMeta, gid)


async def create_group(
    db: OrmSession, agent: AgentClient, ctx: RpcContext, *, name: str, description: str
) -> GroupMeta:
    try:
        info = cast(GroupInfo, await agent.call("groups.create", ctx, name=name))
    except RpcCallError as exc:
        raise GroupServiceError(exc.code, exc.message) from exc

    group = GroupMeta(gid=info.gid, name=info.name, description=description, created_by_nasos=True)
    db.add(group)
    db.commit()
    return group


async def delete_group(
    db: OrmSession, agent: AgentClient, ctx: RpcContext, group: GroupMeta
) -> None:
    try:
        await agent.call("groups.delete", ctx, name=group.name)
    except RpcCallError as exc:
        raise GroupServiceError(exc.code, exc.message) from exc
    db.delete(group)
    db.commit()


async def add_member(
    agent: AgentClient, ctx: RpcContext, group: GroupMeta, *, username: str
) -> None:
    try:
        await agent.call("groups.add_member", ctx, name=group.name, username=username)
    except RpcCallError as exc:
        raise GroupServiceError(exc.code, exc.message) from exc


async def remove_member(
    agent: AgentClient, ctx: RpcContext, group: GroupMeta, *, username: str
) -> None:
    try:
        await agent.call("groups.remove_member", ctx, name=group.name, username=username)
    except RpcCallError as exc:
        raise GroupServiceError(exc.code, exc.message) from exc
