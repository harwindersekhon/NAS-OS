"""storage REST API (PLAN.md §6, Milestone 4)."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session as OrmSession

from nasos.config import Settings
from nasos.db.models import Session as DbSession
from nasos.rpc.client import AgentClient
from nasos.rpc.schemas import RpcContext, StorageInventoryResult
from nasos.services import audit
from nasos.services.storage import plan as plan_service
from nasos.services.storage.plan import StorageServiceError
from nasos.web.deps import (
    get_agent_client,
    get_current_session,
    get_db,
    get_settings,
    require_admin,
)

router = APIRouter(prefix="/api/v1/storage", tags=["storage"])


class PlanStepOut(BaseModel):
    description: str
    op: str
    argv: list[str]


class PlanOut(BaseModel):
    id: str
    steps: list[PlanStepOut]
    confirm_token: str
    confirm_text: str
    data_loss_summary: str
    expires_at: float
    volume_name: str
    mountpoint: str


class CreatePlanRequest(BaseModel):
    volume_name: str
    level: Literal["basic", "1", "5", "6", "10"]
    filesystem: Literal["xfs", "ext4"]
    disk_serials: list[str]


class ExecutePlanRequest(BaseModel):
    confirm_token: str
    typed_confirmation: str


class ExecutePlanResponse(BaseModel):
    job_id: str | None


def _ctx(session: DbSession) -> RpcContext:
    return RpcContext(user=session.username, role=session.role)


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.get("/inventory", response_model=StorageInventoryResult)
async def get_inventory(
    agent: AgentClient = Depends(get_agent_client),
    session: DbSession = Depends(get_current_session),
) -> StorageInventoryResult:
    return await agent.call("storage.inventory", _ctx(session))  # type: ignore[return-value]


@router.post("/plans", response_model=PlanOut)
async def create_plan(
    body: CreatePlanRequest,
    request: Request,
    db: OrmSession = Depends(get_db),
    agent: AgentClient = Depends(get_agent_client),
    settings: Settings = Depends(get_settings),
    session: DbSession = Depends(require_admin),
) -> PlanOut:
    try:
        plan, confirm_token = await plan_service.create_plan(
            agent,
            _ctx(session),
            settings,
            volume_name=body.volume_name,
            level=body.level,
            filesystem=body.filesystem,
            disk_serials=body.disk_serials,
        )
    except StorageServiceError as exc:
        audit.record(
            db,
            username=session.username,
            role=session.role,
            ip=_client_ip(request),
            method="POST",
            path="/api/v1/storage/plans",
            action="storage.create_plan",
            status_code=400,
            detail=str(exc),
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    audit.record(
        db,
        username=session.username,
        role=session.role,
        ip=_client_ip(request),
        method="POST",
        path="/api/v1/storage/plans",
        action="storage.create_plan",
        status_code=200,
        detail=plan.data_loss_summary,
    )
    return PlanOut(
        id=plan.id,
        steps=[PlanStepOut(description=s.description, op=s.op, argv=s.argv) for s in plan.steps],
        confirm_token=confirm_token,
        confirm_text=plan.confirm_text,
        data_loss_summary=plan.data_loss_summary,
        expires_at=plan.expires_at,
        volume_name=plan.spec.volume_name,
        mountpoint=plan.spec.mountpoint,
    )


@router.post("/plans/{plan_id}/execute", response_model=ExecutePlanResponse)
async def execute_plan(
    plan_id: str,
    body: ExecutePlanRequest,
    request: Request,
    db: OrmSession = Depends(get_db),
    agent: AgentClient = Depends(get_agent_client),
    session: DbSession = Depends(require_admin),
) -> ExecutePlanResponse:
    try:
        job_id = await plan_service.execute_plan(
            db,
            agent,
            _ctx(session),
            plan_id=plan_id,
            confirm_token=body.confirm_token,
            typed_confirmation=body.typed_confirmation,
        )
    except StorageServiceError as exc:
        audit.record(
            db,
            username=session.username,
            role=session.role,
            ip=_client_ip(request),
            method="POST",
            path=f"/api/v1/storage/plans/{plan_id}/execute",
            action="storage.execute_plan",
            status_code=400,
            detail=str(exc),
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    audit.record(
        db,
        username=session.username,
        role=session.role,
        ip=_client_ip(request),
        method="POST",
        path=f"/api/v1/storage/plans/{plan_id}/execute",
        action="storage.execute_plan",
        status_code=200,
        detail=f"job_id={job_id}",
    )
    return ExecutePlanResponse(job_id=job_id)
