"""firewall.* RPC methods (PLAN.md §9)."""

from __future__ import annotations

from nasos.agent.dispatcher import handler
from nasos.agent.state import AgentState
from nasos.rpc.schemas import FirewallEnsureServiceParams, OkResult, RpcContext, RpcException
from nasos.system.firewall import FirewallError


@handler("firewall.ensure_service")
async def ensure_service(
    params: FirewallEnsureServiceParams,
    ctx: RpcContext,  # noqa: ARG001
    state: AgentState,
) -> OkResult:
    try:
        zone = await state.firewall.default_zone()
        await state.firewall.ensure_service(zone, params.service)
    except FirewallError as exc:
        raise RpcException("system_error", str(exc)) from exc
    return OkResult()
