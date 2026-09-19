"""Fan-out of unsolicited agent -> web events (job.progress, and later
storage.changed / service.state) to every currently-connected RPC client.
There's typically exactly one — the web process's single long-lived
AgentClient connection (PLAN.md §1) — but this broadcasts to all in case
more than one is ever connected (e.g. a future nasos-cli watcher).

Dev mode (DirectTransport, same process) doesn't go through this at all —
see agent/jobs.py's module docstring.
"""

from __future__ import annotations

import asyncio
import logging

from nasos.rpc.schemas import RpcEvent

logger = logging.getLogger(__name__)


class EventBroadcaster:
    def __init__(self) -> None:
        self._writers: set[asyncio.StreamWriter] = set()

    def register(self, writer: asyncio.StreamWriter) -> None:
        self._writers.add(writer)

    def unregister(self, writer: asyncio.StreamWriter) -> None:
        self._writers.discard(writer)

    def publish(self, topic: str, data: dict[str, object]) -> None:
        event = RpcEvent(topic=topic, data=data)
        payload = event.model_dump_json().encode() + b"\n"
        for writer in list(self._writers):
            try:
                writer.write(payload)
            except Exception:
                logger.warning("dropping a connection from the event broadcast: write failed")
                self._writers.discard(writer)
