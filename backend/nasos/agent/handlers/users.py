"""users.* RPC methods (PLAN.md §3)."""

from __future__ import annotations

from nasos.agent.dispatcher import handler
from nasos.agent.state import AgentState
from nasos.rpc.schemas import (
    OkResult,
    RpcContext,
    RpcException,
    UserCreateParams,
    UserDeleteParams,
    UserImportParams,
    UserInfo,
    UserSetPasswordParams,
    UserSetSmbEnabledParams,
)
from nasos.system.users import SystemUserError


@handler("users.create")
async def create(params: UserCreateParams, ctx: RpcContext, state: AgentState) -> UserInfo:  # noqa: ARG001
    home_dir = f"/home/{params.username}"
    try:
        uid = await state.users.create(params.username, home_dir, params.description)
        await state.users.set_unix_password(params.username, params.password)
        await state.users.smb_create(params.username, params.password)
    except SystemUserError as exc:
        raise RpcException("system_error", str(exc)) from exc
    return UserInfo(uid=uid, username=params.username)


@handler("users.set_smb_enabled")
async def set_smb_enabled(
    params: UserSetSmbEnabledParams,
    ctx: RpcContext,  # noqa: ARG001
    state: AgentState,
) -> OkResult:
    try:
        await state.users.smb_set_enabled(params.username, params.enabled)
    except SystemUserError as exc:
        raise RpcException("system_error", str(exc)) from exc
    return OkResult()


@handler("users.delete")
async def delete(params: UserDeleteParams, ctx: RpcContext, state: AgentState) -> OkResult:  # noqa: ARG001
    try:
        await state.users.smb_delete(params.username)
    except SystemUserError:
        pass  # a managed user with smb_enabled=False never had a passdb entry
    try:
        await state.users.delete(params.username, delete_home=params.delete_home)
    except SystemUserError as exc:
        raise RpcException("system_error", str(exc)) from exc
    return OkResult()


@handler("users.set_password")
async def set_password(
    params: UserSetPasswordParams,
    ctx: RpcContext,  # noqa: ARG001
    state: AgentState,
) -> OkResult:
    try:
        await state.users.set_unix_password(params.username, params.password)
    except SystemUserError as exc:
        raise RpcException("system_error", str(exc)) from exc
    try:
        await state.users.smb_set_password(params.username, params.password)
    except SystemUserError as exc:
        # Unix password changed; Samba's didn't. The service layer catches
        # this specific code to set smb_password_synced=false + notify,
        # rather than failing the whole password change (PLAN.md §3).
        raise RpcException("smb_password_sync_failed", str(exc)) from exc
    return OkResult()


@handler("users.import_existing")
async def import_existing(
    params: UserImportParams,
    ctx: RpcContext,  # noqa: ARG001
    state: AgentState,
) -> UserInfo:
    uid = await state.users.lookup(params.username)
    if uid is None:
        raise RpcException("not_found", f"no such POSIX account: {params.username}")
    try:
        await state.users.add_to_group(params.username, "nasos-users")
    except SystemUserError as exc:
        raise RpcException("system_error", str(exc)) from exc
    return UserInfo(uid=uid, username=params.username)
