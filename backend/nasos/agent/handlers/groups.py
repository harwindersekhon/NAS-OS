"""groups.* RPC methods (PLAN.md §3: custom groups beyond nasos-admin /
nasos-users, usable as share_permissions principals).
"""

from __future__ import annotations

from nasos.agent.dispatcher import handler
from nasos.agent.state import AgentState
from nasos.rpc.schemas import (
    GroupCreateParams,
    GroupDeleteParams,
    GroupInfo,
    GroupMembershipParams,
    OkResult,
    RpcContext,
    RpcException,
)
from nasos.system.users import SystemUserError


@handler("groups.create")
async def create(params: GroupCreateParams, ctx: RpcContext, state: AgentState) -> GroupInfo:  # noqa: ARG001
    try:
        gid = await state.users.group_create(params.name)
    except SystemUserError as exc:
        raise RpcException("system_error", str(exc)) from exc
    return GroupInfo(gid=gid, name=params.name)


@handler("groups.delete")
async def delete(params: GroupDeleteParams, ctx: RpcContext, state: AgentState) -> OkResult:  # noqa: ARG001
    try:
        await state.users.group_delete(params.name)
    except SystemUserError as exc:
        raise RpcException("system_error", str(exc)) from exc
    return OkResult()


@handler("groups.add_member")
async def add_member(
    params: GroupMembershipParams,
    ctx: RpcContext,  # noqa: ARG001
    state: AgentState,
) -> OkResult:
    try:
        await state.users.add_to_group(params.username, params.name)
    except SystemUserError as exc:
        raise RpcException("system_error", str(exc)) from exc
    return OkResult()


@handler("groups.remove_member")
async def remove_member(
    params: GroupMembershipParams,
    ctx: RpcContext,  # noqa: ARG001
    state: AgentState,
) -> OkResult:
    try:
        await state.users.remove_from_group(params.username, params.name)
    except SystemUserError as exc:
        raise RpcException("system_error", str(exc)) from exc
    return OkResult()
