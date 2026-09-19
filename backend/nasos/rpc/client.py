"""Caller-facing RPC clients used by the web process.

`AgentClient` validates outgoing params and incoming results against the
`REGISTRY` in schemas.py, so a caller passing a bad field fails fast with a
Pydantic error instead of a cryptic agent-side rejection.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Protocol

from nasos.agent.workerstate import WorkerState
from nasos.rpc.schemas import REGISTRY, RpcContext, RpcModel
from nasos.rpc.transport import RpcCallError, Transport


class AgentClient:
    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    async def call(self, method: str, ctx: RpcContext, **params: object) -> RpcModel:
        spec = REGISTRY[method]
        validated_params = spec.params.model_validate(params)
        raw = await self._transport.call(method, validated_params.model_dump(mode="json"), ctx)
        return spec.result.model_validate(raw)

    async def close(self) -> None:
        await self._transport.close()


class FileDataClient(Protocol):
    """The raw-byte half of talking to a fileworker: upload_chunk and
    download_range never go through Transport/REGISTRY (see
    agent/fileworker.py's module docstring for why) — this is the client
    side of that separate, hand-rolled framing. Two implementations:
    SocketFileDataClient (prod, a real per-op connection to the worker
    socket) and DirectFileDataClient (dev/test, calls agent.filedata
    in-process — no socket exists at all in dev mode).
    """

    async def write_chunk(self, upload_id: str, offset: int, data: bytes) -> int: ...

    def read_range(self, path: str, offset: int, length: int | None) -> AsyncIterator[bytes]: ...


class SocketFileDataClient:
    """Opens a fresh connection per operation rather than multiplexing onto
    a shared one — simpler than synchronizing binary-frame reads against
    concurrently-pipelined JSON calls, and cheap: these are local AF_UNIX
    connections, not network round trips (see agent/fileworker.py)."""

    def __init__(self, socket_path: str) -> None:
        self._socket_path = socket_path

    async def write_chunk(self, upload_id: str, offset: int, data: bytes) -> int:
        reader, writer = await asyncio.open_unix_connection(self._socket_path)
        try:
            writer.write(
                json.dumps(
                    {"op": "upload_chunk", "upload_id": upload_id, "offset": offset}
                ).encode()
                + b"\n"
            )
            writer.write(json.dumps({"bin": len(data)}).encode() + b"\n")
            writer.write(data)
            await writer.drain()
            response = json.loads(await reader.readline())
        finally:
            writer.close()
        if not response.get("ok"):
            raise RpcCallError("io_error", str(response.get("error")))
        return int(response["offset"])

    async def read_range(self, path: str, offset: int, length: int | None) -> AsyncIterator[bytes]:
        reader, writer = await asyncio.open_unix_connection(self._socket_path)
        try:
            writer.write(
                json.dumps(
                    {"op": "download_range", "path": path, "offset": offset, "length": length}
                ).encode()
                + b"\n"
            )
            await writer.drain()
            while True:
                line = await reader.readline()
                if not line:
                    raise RpcCallError("io_error", "connection closed mid-download")
                frame = json.loads(line)
                if "bin" in frame:
                    yield await reader.readexactly(int(frame["bin"]))
                    continue
                if not frame.get("ok"):
                    raise RpcCallError("io_error", str(frame.get("error")))
                break
        finally:
            writer.close()


class DirectFileDataClient:
    """dev/test mode: no real worker process or socket exists, so this
    calls the same byte-level primitives (agent/filedata.py) the real
    worker's socket handler calls, directly in-process — the WorkerState it
    holds is the same one the dev dispatcher runs files.* handlers against,
    so an upload_id registered by upload_begin is visible here too."""

    def __init__(self, worker_state: WorkerState) -> None:
        self._state = worker_state

    async def write_chunk(self, upload_id: str, offset: int, data: bytes) -> int:
        from nasos.agent import filedata

        handle = self._state.uploads.get(upload_id)
        if handle is None:
            raise RpcCallError("not_found", f"unknown upload_id: {upload_id}")
        return await filedata.write_chunk(handle.part_path, offset, data)

    async def read_range(self, path: str, offset: int, length: int | None) -> AsyncIterator[bytes]:
        from nasos.agent import filedata

        async for chunk in filedata.read_range(path, offset, length):
            yield chunk


class FileWorkerClient:
    """Talks to a single per-uid `nasos-fileworker`: `metadata` for files.*
    RPC methods (AgentClient, works the same way over a real socket or
    DirectTransport), `data` for the raw upload_chunk/download_range ops.
    """

    def __init__(self, metadata: AgentClient, data: FileDataClient) -> None:
        self.metadata = metadata
        self.data = data

    async def close(self) -> None:
        await self.metadata.close()
