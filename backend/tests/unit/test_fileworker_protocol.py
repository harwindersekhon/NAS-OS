"""Exercises agent/fileworker.py's connection-handling loop over a real
AF_UNIX socket — the wire protocol (JSON-line RPC + the hand-rolled binary
frame ops) without privilege dropping or process spawning, the same spirit
as testing SetfaclAcl's argv against a real getfacl/setfacl rather than
mocking subprocess. What's real here: the socket, the dispatcher, the
filesystem under tmp_path. What's skipped: _drop_privileges (this process
isn't root and shouldn't need to be to test framing) and main()'s argv/fd
plumbing (covered by fileworker_supervisor's own spawn-argv tests).
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from nasos.agent.broadcaster import EventBroadcaster
from nasos.agent.dispatcher import Dispatcher
from nasos.agent.fileworker import _handle_connection, _IdleTracker
from nasos.agent.handlers import files as _files_handlers  # noqa: F401
from nasos.agent.handlers import uploads as _upload_handlers  # noqa: F401
from nasos.agent.jobs import JobRunner
from nasos.agent.workerstate import WorkerState
from nasos.system.acl import FakeAcl


@pytest.fixture
def worker_state(tmp_path: Path) -> WorkerState:
    jobs = JobRunner(str(tmp_path / "jobs.jsonl"), on_event=lambda *_a: None)
    return WorkerState(uid=os.getuid(), username="tester", jobs=jobs, acl=FakeAcl(), uploads={})


@pytest.fixture
async def server_socket_path(tmp_path: Path, worker_state: WorkerState) -> AsyncIterator[str]:
    dispatcher = Dispatcher(worker_state)
    broadcaster = EventBroadcaster()
    idle = _IdleTracker()
    sock_path = str(tmp_path / "worker.sock")

    server = await asyncio.start_unix_server(
        lambda r, w: _handle_connection(
            r, w, dispatcher, worker_state, os.getuid(), broadcaster, idle
        ),
        path=sock_path,
    )
    async with server:
        yield sock_path


async def _rpc(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, method: str, **params):
    writer.write(
        json.dumps({"type": "request", "id": "1", "method": method, "params": params}).encode()
        + b"\n"
    )
    await writer.drain()
    line = await reader.readline()
    return json.loads(line)


async def test_rpc_request_over_real_socket(server_socket_path: str, tmp_path: Path) -> None:
    reader, writer = await asyncio.open_unix_connection(server_socket_path)
    try:
        target = str(tmp_path / "newdir")
        resp = await _rpc(reader, writer, "files.mkdir", path=target)
        assert resp["ok"] is True
        assert os.path.isdir(target)
    finally:
        writer.close()


async def test_upload_chunk_op_writes_bytes_and_returns_offset(
    server_socket_path: str, tmp_path: Path
) -> None:
    reader, writer = await asyncio.open_unix_connection(server_socket_path)
    try:
        dest = str(tmp_path / "photo.bin")
        begin = await _rpc(
            reader, writer, "files.upload_begin", upload_id="u1", dest_path=dest, size=10
        )
        assert begin["ok"] is True

        data = b"0123456789"
        writer.write(
            json.dumps({"op": "upload_chunk", "upload_id": "u1", "offset": 0}).encode() + b"\n"
        )
        writer.write(json.dumps({"bin": len(data)}).encode() + b"\n")
        writer.write(data)
        await writer.drain()
        resp = json.loads(await reader.readline())
        assert resp == {"ok": True, "offset": 10}

        part_path = tmp_path / ".nasos-upload-u1.part"
        assert part_path.read_bytes() == data

        complete = await _rpc(reader, writer, "files.upload_complete", upload_id="u1")
        assert complete["ok"] is True
        assert Path(dest).read_bytes() == data
    finally:
        writer.close()


async def test_upload_chunk_unknown_id_reports_error_without_crashing_connection(
    server_socket_path: str,
) -> None:
    reader, writer = await asyncio.open_unix_connection(server_socket_path)
    try:
        writer.write(
            json.dumps({"op": "upload_chunk", "upload_id": "ghost", "offset": 0}).encode() + b"\n"
        )
        writer.write(json.dumps({"bin": 3}).encode() + b"\n")
        writer.write(b"abc")
        await writer.drain()
        resp = json.loads(await reader.readline())
        assert resp["ok"] is False

        # Connection must still be alive for further requests afterwards.
        resp2 = await _rpc(reader, writer, "files.upload_offset", upload_id="also-ghost")
        assert resp2["ok"] is False
        assert resp2["error"]["code"] == "not_found"
    finally:
        writer.close()


async def test_download_range_op_streams_whole_file(
    server_socket_path: str, tmp_path: Path
) -> None:
    f = tmp_path / "data.bin"
    f.write_bytes(bytes(range(256)) * 10)  # 2560 bytes

    reader, writer = await asyncio.open_unix_connection(server_socket_path)
    try:
        writer.write(
            json.dumps(
                {"op": "download_range", "path": str(f), "offset": 0, "length": None}
            ).encode()
            + b"\n"
        )
        await writer.drain()

        received = bytearray()
        while True:
            line = await reader.readline()
            frame = json.loads(line)
            if "bin" in frame:
                received += await reader.readexactly(int(frame["bin"]))
                continue
            assert frame == {"ok": True}
            break
        assert bytes(received) == f.read_bytes()
    finally:
        writer.close()


async def test_download_range_op_respects_offset_and_length(
    server_socket_path: str, tmp_path: Path
) -> None:
    f = tmp_path / "data.bin"
    f.write_bytes(b"0123456789")

    reader, writer = await asyncio.open_unix_connection(server_socket_path)
    try:
        writer.write(
            json.dumps({"op": "download_range", "path": str(f), "offset": 3, "length": 4}).encode()
            + b"\n"
        )
        await writer.drain()

        received = bytearray()
        while True:
            frame = json.loads(await reader.readline())
            if "bin" in frame:
                received += await reader.readexactly(int(frame["bin"]))
                continue
            assert frame == {"ok": True}
            break
        assert bytes(received) == b"3456"
    finally:
        writer.close()


async def test_untrusted_peer_uid_is_rejected(tmp_path: Path, worker_state: WorkerState) -> None:
    """Same real socket, but the handler is told to trust a *different*
    uid than the one this test process actually runs as — exercising the
    SO_PEERCRED rejection branch for real (SO_PEERCRED reports our actual
    uid; only the *expected* uid is faked)."""
    dispatcher = Dispatcher(worker_state)
    broadcaster = EventBroadcaster()
    idle = _IdleTracker()
    sock_path = str(tmp_path / "worker.sock")
    not_us = os.getuid() + 1

    server = await asyncio.start_unix_server(
        lambda r, w: _handle_connection(r, w, dispatcher, worker_state, not_us, broadcaster, idle),
        path=sock_path,
    )
    async with server:
        reader, writer = await asyncio.open_unix_connection(sock_path)
        try:
            line = await reader.readline()
            assert line == b""  # connection closed immediately, no response sent
        finally:
            writer.close()
