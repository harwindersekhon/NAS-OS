"""volumes.* RPC methods (PLAN.md §6, M2 scope: register an existing
mounted filesystem; full disk/RAID/LVM orchestration is Storage Manager,
Milestone 4). "allowed if it is a mountpoint and not / or /boot*; NAS-OS
never manages its mount."
"""

from __future__ import annotations

from nasos.agent.dispatcher import handler
from nasos.agent.state import AgentState
from nasos.rpc.schemas import RpcContext, RpcException, VolumeInfo, VolumeRegisterParams

_FORBIDDEN_PREFIXES = ("/boot",)


def _is_forbidden(mountpoint: str) -> bool:
    if mountpoint == "/":
        return True
    return any(mountpoint == p or mountpoint.startswith(p + "/") for p in _FORBIDDEN_PREFIXES)


@handler("volumes.register")
async def register(
    params: VolumeRegisterParams,
    ctx: RpcContext,  # noqa: ARG001
    state: AgentState,
) -> VolumeInfo:
    mountpoint = params.mountpoint.rstrip("/") or "/"
    if _is_forbidden(mountpoint):
        raise RpcException("forbidden", f"{mountpoint} cannot be registered as a NAS-OS volume")
    if not await state.mounts.is_mountpoint(mountpoint):
        raise RpcException("not_a_mountpoint", f"{mountpoint} is not a mountpoint")
    filesystem = await state.mounts.filesystem_type(mountpoint)
    if filesystem is None:
        raise RpcException("not_a_mountpoint", f"{mountpoint} is not in /proc/mounts")
    return VolumeInfo(mountpoint=mountpoint, filesystem=filesystem)
