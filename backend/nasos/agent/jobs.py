"""Bounded-concurrency runner for long operations (setfacl -R, mkfs, rsync,
...) the agent executes on the web's behalf (PLAN.md §4).

Every job gets an optional per-resource lock (e.g. "disk:sda", "share:media")
so two operations on the same resource never race, while unrelated jobs run
concurrently up to MAX_CONCURRENCY. Progress is cooperative and throttled to
avoid flooding the event connection; cancellation is cooperative too — a
job's own code decides where it's safe to stop (never mid-mkfs) by checking
`JobHandle.cancel_requested` between steps, rather than being preempted.

`on_event` abstracts away *how* an event reaches the web: in prod it writes
an RpcEvent frame to the agent socket (see agent/broadcaster.py); in dev
mode (DirectTransport, same process) it can just call the web's EventBus
directly. Either way this module only calls `on_event(topic, data)`.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import time
import uuid
from collections import defaultdict
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

MAX_CONCURRENCY = 4
PROGRESS_THROTTLE_SECONDS = 0.5
TOPIC = "job.progress"

JobStatus = Literal["queued", "running", "done", "failed", "cancelled"]


@dataclasses.dataclass
class JobRecord:
    id: str
    kind: str
    resource: str | None
    status: JobStatus = "queued"
    progress: float = 0.0
    message: str = ""
    created_by: str | None = None

    def to_event(self) -> dict[str, object]:
        return {
            "id": self.id,
            "kind": self.kind,
            "resource": self.resource,
            "status": self.status,
            "progress": self.progress,
            "message": self.message,
        }


class JobHandle:
    """Passed into a job body; its only channel back to the runner."""

    def __init__(self, runner: JobRunner, record: JobRecord) -> None:
        self._runner = runner
        self._record = record
        self._last_publish = 0.0
        self.cancel_requested = False

    def progress(self, fraction: float, message: str = "") -> None:
        self._record.progress = max(0.0, min(1.0, fraction))
        if message:
            self._record.message = message
        now = time.monotonic()
        if now - self._last_publish >= PROGRESS_THROTTLE_SECONDS:
            self._last_publish = now
            self._runner._publish(self._record)  # noqa: SLF001  (same module)


JobBody = Callable[[JobHandle], Awaitable[None]]


class JobRunner:
    def __init__(
        self, log_path: str, on_event: Callable[[str, dict[str, object]], None] | None = None
    ) -> None:
        self._log_path = Path(log_path)
        self._on_event = on_event
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
        self._resource_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._jobs: dict[str, JobRecord] = {}
        self._handles: dict[str, JobHandle] = {}

    def list(self) -> list[dict[str, object]]:
        return [record.to_event() for record in self._jobs.values()]

    def request_cancel(self, job_id: str) -> bool:
        handle = self._handles.get(job_id)
        if handle is None:
            return False
        handle.cancel_requested = True
        return True

    def submit(
        self,
        kind: str,
        body: JobBody,
        *,
        resource: str | None = None,
        created_by: str | None = None,
    ) -> str:
        job_id = uuid.uuid4().hex
        record = JobRecord(id=job_id, kind=kind, resource=resource, created_by=created_by)
        self._jobs[job_id] = record
        handle = JobHandle(self, record)
        self._handles[job_id] = handle
        asyncio.create_task(self._run(record, handle, body))
        return job_id

    async def _run(self, record: JobRecord, handle: JobHandle, body: JobBody) -> None:
        lock = self._resource_locks[record.resource] if record.resource else None
        async with self._semaphore:
            if lock is not None:
                await lock.acquire()
            try:
                record.status = "running"
                self._publish(record)
                await body(handle)
                record.status = "cancelled" if handle.cancel_requested else "done"
                if record.status == "done":
                    record.progress = 1.0
            except Exception as exc:
                record.status = "failed"
                record.message = str(exc)
                logger.exception("job %s (%s) failed", record.id, record.kind)
            finally:
                if lock is not None:
                    lock.release()
                self._publish(record)
                self._append_result(record)
                self._handles.pop(record.id, None)

    def _publish(self, record: JobRecord) -> None:
        if self._on_event is not None:
            self._on_event(TOPIC, record.to_event())

    def _append_result(self, record: JobRecord) -> None:
        if record.status not in ("done", "failed", "cancelled"):
            return
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        with self._log_path.open("a") as fh:
            fh.write(json.dumps(record.to_event()) + "\n")
