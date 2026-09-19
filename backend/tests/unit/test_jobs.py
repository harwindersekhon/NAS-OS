from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from nasos.agent.jobs import JobBody, JobHandle, JobRunner


@pytest.fixture
def events() -> list[tuple[str, dict[str, object]]]:
    return []


@pytest.fixture
def runner(tmp_path: Path, events: list[tuple[str, dict[str, object]]]) -> JobRunner:
    return JobRunner(str(tmp_path / "jobs.jsonl"), on_event=lambda t, d: events.append((t, d)))


async def _wait_until_done(
    runner: JobRunner, job_id: str, timeout: float = 2.0
) -> dict[str, object]:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        (record,) = [r for r in runner.list() if r["id"] == job_id]
        if record["status"] in ("done", "failed", "cancelled"):
            return record
        await asyncio.sleep(0.01)
    raise AssertionError(f"job {job_id} did not finish in time")


async def test_job_completes_and_logs_result(runner: JobRunner, tmp_path: Path) -> None:
    async def body(handle: JobHandle) -> None:
        handle.progress(0.5, "halfway")

    job_id = runner.submit("test.noop", body)
    record = await _wait_until_done(runner, job_id)

    assert record["status"] == "done"
    assert record["progress"] == 1.0

    lines = (tmp_path / "jobs.jsonl").read_text().splitlines()
    assert len(lines) == 1
    logged = json.loads(lines[0])
    assert logged["id"] == job_id
    assert logged["status"] == "done"


async def test_job_failure_is_captured(runner: JobRunner) -> None:
    async def body(handle: JobHandle) -> None:  # noqa: ARG001
        raise ValueError("boom")

    job_id = runner.submit("test.fails", body)
    record = await _wait_until_done(runner, job_id)

    assert record["status"] == "failed"
    assert record["message"] == "boom"


async def test_same_resource_jobs_serialize(runner: JobRunner) -> None:
    order: list[str] = []

    def make_body(name: str, hold: float) -> JobBody:
        async def inner(handle: JobHandle) -> None:  # noqa: ARG001
            order.append(f"{name}-start")
            await asyncio.sleep(hold)
            order.append(f"{name}-end")

        return inner

    first_id = runner.submit("test.hold", make_body("a", 0.05), resource="share:media")
    second_id = runner.submit("test.hold", make_body("b", 0.0), resource="share:media")

    await _wait_until_done(runner, first_id)
    await _wait_until_done(runner, second_id)

    # b can only start once a has fully finished, since they share a resource lock.
    assert order == ["a-start", "a-end", "b-start", "b-end"]


async def test_different_resource_jobs_overlap(runner: JobRunner) -> None:
    started = asyncio.Event()
    order: list[str] = []

    async def slow(handle: JobHandle) -> None:  # noqa: ARG001
        order.append("slow-start")
        started.set()
        await asyncio.sleep(0.05)
        order.append("slow-end")

    async def fast(handle: JobHandle) -> None:  # noqa: ARG001
        await started.wait()
        order.append("fast-ran-while-slow-in-flight")

    slow_id = runner.submit("test.slow", slow, resource="disk:sda")
    fast_id = runner.submit("test.fast", fast, resource="disk:sdb")

    await _wait_until_done(runner, fast_id)
    await _wait_until_done(runner, slow_id)

    assert order == ["slow-start", "fast-ran-while-slow-in-flight", "slow-end"]


async def test_cancel_is_cooperative(runner: JobRunner) -> None:
    async def body(handle: JobHandle) -> None:
        for _ in range(50):
            if handle.cancel_requested:
                return
            await asyncio.sleep(0.01)

    job_id = runner.submit("test.cancellable", body)
    assert runner.request_cancel(job_id) is True
    record = await _wait_until_done(runner, job_id)

    assert record["status"] == "cancelled"


async def test_request_cancel_unknown_job_returns_false(runner: JobRunner) -> None:
    assert runner.request_cancel("no-such-job") is False


async def test_events_include_start_and_terminal(
    runner: JobRunner, events: list[tuple[str, dict[str, object]]]
) -> None:
    async def body(handle: JobHandle) -> None:  # noqa: ARG001
        pass

    job_id = runner.submit("test.noop", body)
    await _wait_until_done(runner, job_id)

    statuses = [data["status"] for topic, data in events if data["id"] == job_id]
    assert statuses[0] == "running"
    assert statuses[-1] == "done"
