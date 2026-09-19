"""Background sampler publishing CPU/memory snapshots onto the EventBus.

M1 scope: one 1s series so the Dashboard has a live graph. Multi-resolution
ring buffers (1s/10s/5min), per-process sampling and history persistence to
`metrics_5m` are Milestone 6 (Resource Monitor + Log Center) — see PLAN.md §7.
"""

from __future__ import annotations

import asyncio
import contextlib

import psutil

from nasos.events.bus import EventBus

TOPIC = "monitor.sample"
INTERVAL_SECONDS = 1.0


class Sampler:
    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        psutil.cpu_percent(interval=None)  # prime the non-blocking counter
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def _run(self) -> None:
        while True:
            sample = await asyncio.to_thread(self._sample)
            self._bus.publish(TOPIC, sample)
            await asyncio.sleep(INTERVAL_SECONDS)

    def _sample(self) -> dict[str, float]:
        mem = psutil.virtual_memory()
        return {
            "cpu_percent": psutil.cpu_percent(interval=None),
            "mem_used": float(mem.used),
            "mem_total": float(mem.total),
        }
