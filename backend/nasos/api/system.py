"""system API: host info surfaced on the Dashboard / Control Panel -> Info Center."""

from __future__ import annotations

from typing import cast

from fastapi import APIRouter, Depends

from nasos.db.models import Session as DbSession
from nasos.rpc.client import AgentClient
from nasos.rpc.schemas import RpcContext, SystemInfoResult
from nasos.web.deps import get_agent_client, get_current_session

router = APIRouter(prefix="/api/v1/system", tags=["system"])


@router.get("/info", response_model=SystemInfoResult)
async def info(
    session: DbSession = Depends(get_current_session),
    agent: AgentClient = Depends(get_agent_client),
) -> SystemInfoResult:
    ctx = RpcContext(user=session.username, role=session.role)
    return cast(SystemInfoResult, await agent.call("system.info", ctx))
