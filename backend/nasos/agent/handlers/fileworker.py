"""agent.fileworker.ensure (PLAN.md §1): spawn-or-reconnect a per-user
nasos-fileworker child, returning the socket the web process should then
talk files.* to directly (not through the agent — see fileworker_supervisor
and agent/fileworker.py for why).
"""

from __future__ import annotations

from nasos.agent.dispatcher import handler
from nasos.agent.state import AgentState
from nasos.rpc.schemas import FileWorkerEnsureParams, FileWorkerEnsureResult, RpcContext


@handler("agent.fileworker.ensure")
async def ensure(
    params: FileWorkerEnsureParams,
    ctx: RpcContext,
    state: AgentState,  # noqa: ARG001
) -> FileWorkerEnsureResult:
    socket_path = await state.fileworkers.ensure(params.uid, params.username)
    return FileWorkerEnsureResult(socket_path=socket_path)
