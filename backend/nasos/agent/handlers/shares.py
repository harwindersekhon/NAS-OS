"""shares.* RPC methods (PLAN.md §3)."""

from __future__ import annotations

import contextlib
import grp
import os
import shutil
from typing import TYPE_CHECKING

from nasos.agent.dispatcher import handler
from nasos.agent.state import AgentState
from nasos.rpc.schemas import (
    JobStartedResult,
    OkResult,
    RpcContext,
    RpcException,
    ShareCreateParams,
    ShareDeleteParams,
    ShareSetPermissionsParams,
)
from nasos.system.acl import AclError

if TYPE_CHECKING:
    from nasos.agent.jobs import JobHandle

# root:nasos-users, group class empty (system/acl.py has the full rationale:
# mode 2770 would hand every nasos-users member blanket access via group::).
_SHARE_MODE = 0o2700


@handler("shares.create")
async def create(
    params: ShareCreateParams,
    ctx: RpcContext,  # noqa: ARG001
    state: AgentState,
) -> OkResult:
    path = params.path
    if os.path.exists(path):
        raise RpcException("already_exists", f"{path} already exists")

    # Dev/test never has a real nasos-users group (or root) to chown to —
    # the directory still gets created with the right mode, just owned by
    # whoever's actually running the sandbox.
    is_sandboxed = state.settings.is_dev or state.settings.is_test
    gid: int | None = None
    if not is_sandboxed:
        try:
            gid = grp.getgrnam("nasos-users").gr_gid
        except KeyError as exc:
            raise RpcException("system_error", "nasos-users group does not exist") from exc

    try:
        os.makedirs(path, exist_ok=False)
        if gid is not None:
            os.chown(path, 0, gid)
        os.chmod(path, _SHARE_MODE)
    except OSError as exc:
        raise RpcException("system_error", str(exc)) from exc
    return OkResult()


@handler("shares.delete")
async def delete(
    params: ShareDeleteParams,
    ctx: RpcContext,  # noqa: ARG001
    state: AgentState,  # noqa: ARG001
) -> OkResult:
    if params.delete_files:
        with contextlib.suppress(FileNotFoundError):
            shutil.rmtree(params.path)
    return OkResult()


@handler("shares.set_permissions")
async def set_permissions(
    params: ShareSetPermissionsParams,
    ctx: RpcContext,
    state: AgentState,
) -> JobStartedResult:
    entries = [(e.kind, e.numeric_id, e.level) for e in params.entries]

    if not params.recursive:
        # Top level applied synchronously (PLAN.md §3); a full tree re-apply
        # is a job (below) since it can take a long time on a large share.
        try:
            await state.acl.replace_all(params.path, entries, recursive=False)
        except AclError as exc:
            raise RpcException("system_error", str(exc)) from exc
        return JobStartedResult(job_id=None)

    async def body(handle: JobHandle) -> None:
        handle.progress(0.0, "applying permissions recursively")
        try:
            await state.acl.replace_all(params.path, entries, recursive=True)
        except AclError as exc:
            raise RuntimeError(str(exc)) from exc
        handle.progress(1.0, "done")

    job_id = state.jobs.submit(
        "shares.apply_permissions",
        body,
        resource=f"share:{params.path}",
        created_by=ctx.user,
    )
    return JobStartedResult(job_id=job_id)
