"""jobs.* RPC methods: the web reconciles job state via this at startup and
whenever it needs a snapshot beyond what job.progress events have delivered
(PLAN.md §4).
"""

from __future__ import annotations

from nasos.agent.dispatcher import handler
from nasos.agent.state import AgentState
from nasos.rpc.schemas import JobListParams, JobListResult, JobRecordResult, RpcContext


@handler("jobs.list")
async def list_jobs(
    params: JobListParams,  # noqa: ARG001
    ctx: RpcContext,  # noqa: ARG001
    state: AgentState,
) -> JobListResult:
    return JobListResult(
        jobs=[JobRecordResult.model_validate(record) for record in state.jobs.list()]
    )
