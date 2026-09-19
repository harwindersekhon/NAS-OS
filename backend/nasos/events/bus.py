"""In-process pub/sub fan-out, keyed by topic, from producers (the resource
monitor sampler, and — from M2 on — agent RPC events like job.progress) to
WebSocket clients (see web/ws.py).
"""

from __future__ import annotations

import asyncio
import contextlib
from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

_QUEUE_MAXSIZE = 64


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[Any]]] = defaultdict(set)

    @asynccontextmanager
    async def subscribe(self, topic: str) -> AsyncIterator[asyncio.Queue[Any]]:
        queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=_QUEUE_MAXSIZE)
        self._subscribers[topic].add(queue)
        try:
            yield queue
        finally:
            self._subscribers[topic].discard(queue)

    def publish(self, topic: str, data: Any) -> None:
        """Best-effort: a full queue means a slow consumer, so the oldest
        pending item is dropped in favour of the new one rather than
        blocking the publisher.
        """
        for queue in self._subscribers.get(topic, ()):
            try:
                queue.put_nowait(data)
            except asyncio.QueueFull:
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
                with contextlib.suppress(asyncio.QueueFull):
                    queue.put_nowait(data)
