"""Periodic SMART health poll (PLAN.md §6: "SMART every 30 min + on demand
with threshold notifications"). Mirrors monitor/sampler.py's Sampler shape
(start/stop a background asyncio task) one layer up, in the web process,
since that's where the agent client and the DB both live.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable

from sqlalchemy.orm import Session as OrmSession

from nasos.db.models import DiskSeen, Notification
from nasos.rpc.client import AgentClient
from nasos.rpc.schemas import DiskNode, RpcContext, StorageInventoryResult
from nasos.rpc.transport import RpcCallError

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 1800
_ALERT_LEVELS = {"warning": "warning", "critical": "critical"}


class SmartHealthPoller:
    def __init__(self, agent: AgentClient, session_factory: Callable[[], OrmSession]) -> None:
        self._agent = agent
        self._session_factory = session_factory
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def _run(self) -> None:
        # Sleeps *before* the first poll, not after: nothing here is
        # urgent enough to fire an inventory RPC the instant the web
        # process starts (`make dev`'s FakeRunner is non-strict so this
        # wouldn't crash, but a pytest TestClient's is strict — see
        # web/main.py, which only starts this poller outside test mode
        # anyway; the sleep-first order is a second, cheap layer of
        # protection against a stray background call racing a test's own
        # FakeRunner.expect() setup).
        while True:
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
            try:
                await self.poll_once()
            except Exception:
                logger.exception("SMART health poll failed")

    async def poll_once(self) -> None:
        try:
            result: StorageInventoryResult = await self._agent.call(  # type: ignore[assignment]
                "storage.inventory", RpcContext()
            )
        except RpcCallError:
            return

        with self._session_factory() as db:
            for disk in _flatten(result.disks):
                if disk.serial:
                    self._update(db, disk)
            db.commit()

    def _update(self, db: OrmSession, disk: DiskNode) -> None:
        assert disk.serial is not None
        health = disk.smart.health if disk.smart else "unknown"
        row = db.get(DiskSeen, disk.serial)
        previous_health = row.last_health if row is not None else None

        if row is None:
            row = DiskSeen(serial=disk.serial, path=disk.path, model=disk.model, size=disk.size)
            db.add(row)
        row.path = disk.path
        row.model = disk.model
        row.size = disk.size
        row.last_health = health

        if health != previous_health and health in _ALERT_LEVELS:
            db.add(
                Notification(
                    level=_ALERT_LEVELS[health],
                    title=f"Disk health: {health}",
                    message=(
                        f"{disk.model or disk.path} ({disk.serial}) SMART health is now {health}"
                    ),
                    source="storage",
                )
            )


def _flatten(nodes: list[DiskNode]) -> list[DiskNode]:
    found: list[DiskNode] = []
    for node in nodes:
        found.append(node)
        found.extend(_flatten(node.children))
    return found
