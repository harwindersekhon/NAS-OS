"""Auto-registers the Volume DB row once a `storage.execute_plan` job
finishes (PLAN.md §6: "auto volume registration"). The agent has no DB
access (PLAN.md §4: SQLite is opened only by the web process), so this is
how a plan's result actually lands in the `volumes` table — by watching
the same `job.progress` events the frontend's progress bar already
consumes, rather than the web waiting synchronously on a fire-and-forget
job it just submitted.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Callable

from sqlalchemy.orm import Session as OrmSession

from nasos.db.models import Volume
from nasos.events.bus import EventBus

logger = logging.getLogger(__name__)

TOPIC = "job.progress"
KIND = "storage.execute_plan"


class VolumeAutoRegistrar:
    def __init__(self, bus: EventBus, session_factory: Callable[[], OrmSession]) -> None:
        self._bus = bus
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
        async with self._bus.subscribe(TOPIC) as queue:
            while True:
                event = await queue.get()
                if not isinstance(event, dict):
                    continue
                if event.get("kind") != KIND or event.get("status") != "done":
                    continue
                self._register(event)

    def _register(self, event: dict[str, object]) -> None:
        try:
            info = json.loads(str(event.get("message", "") or "{}"))
        except json.JSONDecodeError:
            logger.warning("storage.execute_plan finished with an unparseable result")
            return

        try:
            with self._session_factory() as db:
                db.add(
                    Volume(
                        name=str(info["name"]),
                        mountpoint=str(info["mountpoint"]),
                        filesystem=str(info["filesystem"]),
                        managed=True,
                        device=str(info["device"]),
                        uuid=str(info["uuid"]) or None,
                        raid_level=str(info["raid_level"]),
                        array_name=info.get("array_name"),
                        disk_serials=info.get("disk_serials"),
                    )
                )
                db.commit()
        except Exception:
            logger.exception("failed to auto-register volume from a finished storage plan")
            return
        logger.info("auto-registered volume %s at %s", info.get("name"), info.get("mountpoint"))
