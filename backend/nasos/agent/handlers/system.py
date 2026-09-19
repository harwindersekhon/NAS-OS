"""system.* RPC methods."""

from __future__ import annotations

import platform

from nasos import __version__
from nasos.agent.dispatcher import handler
from nasos.agent.state import AgentState
from nasos.rpc.schemas import RpcContext, SystemInfoParams, SystemInfoResult


def _uptime_seconds() -> float:
    with open("/proc/uptime") as fh:
        return float(fh.readline().split()[0])


@handler("system.info")
async def info(params: SystemInfoParams, ctx: RpcContext, state: AgentState) -> SystemInfoResult:  # noqa: ARG001
    return SystemInfoResult(
        hostname=state.distro.hostname(),
        os_pretty_name=state.distro.os_pretty_name(),
        kernel=platform.release(),
        nasos_version=__version__,
        uptime_seconds=_uptime_seconds(),
    )
