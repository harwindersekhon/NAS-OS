"""storage.* business logic (PLAN.md §6): two-phase plan/execute with a
confirm token. Runs in the web process — the agent re-derives everything
safety-critical itself (agent/handlers/storage.py) rather than trusting
this preview, so this module's `PlanStore` only has to be tamper-evident
(HMAC'd), not the actual authority on what's safe to execute.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
import uuid
from dataclasses import dataclass, field
from typing import cast

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from nasos.config import Settings
from nasos.db.models import Volume
from nasos.rpc.client import AgentClient
from nasos.rpc.schemas import (
    DiskNode,
    JobStartedResult,
    RpcContext,
    StorageInventoryResult,
    StoragePlanSpec,
)
from nasos.rpc.transport import RpcCallError
from nasos.system.storage_plan import PlanStep, build_steps

PLAN_TTL_SECONDS = 300

_LEVEL_MIN_DISKS = {"basic": 1, "1": 2, "5": 3, "6": 4, "10": 4}


class StorageServiceError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class Plan:
    id: str
    spec: StoragePlanSpec
    steps: list[PlanStep]
    expected_sizes: dict[str, int]
    data_loss_summary: str
    confirm_text: str
    created_at: float = field(default_factory=time.monotonic)
    """Monotonic clock — this is what TTL enforcement (`PlanStore._gc`)
    actually compares against, immune to wall-clock adjustments."""
    created_at_wall: float = field(default_factory=time.time)
    """Wall-clock creation time, only for computing `expires_at` to show
    the user — monotonic time has no fixed epoch a client could render."""

    @property
    def expires_at(self) -> float:
        return self.created_at_wall + PLAN_TTL_SECONDS


class PlanStore:
    """In-memory, single-process — plans are short-lived (5-min TTL,
    PLAN.md §6) and there's exactly one web process; unlike everything
    else here, a plan doesn't need to survive a restart, which is why
    there's no `plans` table in PLAN.md's table list."""

    def __init__(self) -> None:
        self._plans: dict[str, Plan] = {}
        self._key = secrets.token_bytes(32)

    def put(self, plan: Plan) -> str:
        self._gc()
        self._plans[plan.id] = plan
        return self.confirm_token(plan)

    def get(self, plan_id: str) -> Plan | None:
        self._gc()
        return self._plans.get(plan_id)

    def pop(self, plan_id: str) -> Plan | None:
        self._gc()
        return self._plans.pop(plan_id, None)

    def confirm_token(self, plan: Plan) -> str:
        payload = json.dumps(
            {"id": plan.id, "spec": plan.spec.model_dump(mode="json")}, sort_keys=True
        ).encode()
        return hmac.new(self._key, payload, hashlib.sha256).hexdigest()

    def _gc(self) -> None:
        cutoff = time.monotonic() - PLAN_TTL_SECONDS
        expired = [plan_id for plan_id, plan in self._plans.items() if plan.created_at < cutoff]
        for plan_id in expired:
            del self._plans[plan_id]


_store = PlanStore()


def get_store() -> PlanStore:
    return _store


def _flatten(nodes: list[DiskNode]) -> list[DiskNode]:
    found: list[DiskNode] = []
    for node in nodes:
        found.append(node)
        found.extend(_flatten(node.children))
    return found


async def create_plan(
    agent: AgentClient,
    ctx: RpcContext,
    settings: Settings,
    *,
    volume_name: str,
    level: str,
    filesystem: str,
    disk_serials: list[str],
) -> tuple[Plan, str]:
    if level not in _LEVEL_MIN_DISKS:
        raise StorageServiceError("invalid_level", f"unsupported RAID level: {level}")
    minimum = _LEVEL_MIN_DISKS[level]
    if len(disk_serials) < minimum:
        raise StorageServiceError(
            "not_enough_disks", f"level {level} needs at least {minimum} disk(s)"
        )
    if level == "basic" and len(disk_serials) != 1:
        raise StorageServiceError("invalid_disk_count", "basic (single-disk) needs exactly 1 disk")
    if level == "10" and len(disk_serials) % 2 != 0:
        raise StorageServiceError("invalid_disk_count", "level 10 needs an even number of disks")

    try:
        result = cast(StorageInventoryResult, await agent.call("storage.inventory", ctx))
    except RpcCallError as exc:
        raise StorageServiceError(exc.code, exc.message) from exc

    by_serial = {node.serial: node for node in _flatten(result.disks) if node.serial}

    disk_paths: list[str] = []
    expected_sizes: dict[str, int] = {}
    summary_lines: list[str] = []
    for serial in disk_serials:
        node = by_serial.get(serial)
        if node is None:
            raise StorageServiceError("not_found", f"no such disk: {serial}")
        if node.protected:
            raise StorageServiceError(
                "device_protected", f"{node.path} ({serial}) is protected: {node.protected_reason}"
            )
        disk_paths.append(node.path)
        expected_sizes[serial] = node.size
        summary_lines.append(f"{node.path} ({serial}, {_format_bytes(node.size)})")

    mountpoint = settings.system_path(f"{settings.volumes_root}/{volume_name}")
    spec = StoragePlanSpec(
        volume_name=volume_name,
        level=level,  # type: ignore[arg-type]
        filesystem=filesystem,  # type: ignore[arg-type]
        disk_paths=disk_paths,
        disk_serials=disk_serials,
        array_name=volume_name,
        vg_name=f"nasos_{volume_name}",
        lv_name=volume_name,
        mountpoint=mountpoint,
    )
    steps = build_steps(spec)

    data_loss_summary = (
        f"This will ERASE ALL DATA on: {', '.join(summary_lines)}. "
        f"A new {'single-disk' if level == 'basic' else f'RAID {level}'} "
        f"{filesystem} volume {volume_name!r} will be created at {mountpoint}."
    )
    confirm_text = disk_serials[0] if len(disk_serials) == 1 else "ERASE"

    plan = Plan(
        id=uuid.uuid4().hex,
        spec=spec,
        steps=steps,
        expected_sizes=expected_sizes,
        data_loss_summary=data_loss_summary,
        confirm_text=confirm_text,
    )
    confirm_token = _store.put(plan)
    return plan, confirm_token


async def execute_plan(
    db: OrmSession,
    agent: AgentClient,
    ctx: RpcContext,
    *,
    plan_id: str,
    confirm_token: str,
    typed_confirmation: str,
) -> str | None:
    plan = _store.get(plan_id)
    if plan is None:
        raise StorageServiceError("plan_not_found", "plan not found or expired")
    if not hmac.compare_digest(_store.confirm_token(plan), confirm_token):
        raise StorageServiceError("bad_confirm_token", "confirm token does not match this plan")
    if typed_confirmation != plan.confirm_text:
        raise StorageServiceError(
            "confirmation_mismatch", f"type {plan.confirm_text!r} exactly to confirm"
        )

    managed_mountpoints = [
        volume.mountpoint
        for volume in db.execute(select(Volume).where(Volume.managed.is_(True))).scalars()
    ]
    managed_mountpoints.append(plan.spec.mountpoint)

    try:
        result = cast(
            JobStartedResult,
            await agent.call(
                "storage.execute_plan",
                ctx,
                spec=plan.spec.model_dump(mode="json"),
                expected_sizes=plan.expected_sizes,
                managed_mountpoints=managed_mountpoints,
            ),
        )
    except RpcCallError as exc:
        raise StorageServiceError(exc.code, exc.message) from exc

    _store.pop(plan_id)
    return result.job_id


def _format_bytes(size: int) -> str:
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB", "PiB"):
        if value < 1024 or unit == "PiB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} {unit}"
        value /= 1024
    return f"{value:.1f} PiB"
