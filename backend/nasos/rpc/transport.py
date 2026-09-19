"""Wire-level transports: a real AF_UNIX connection and an in-process one.

Both speak the same newline-delimited JSON protocol defined by the
RpcRequest/RpcResponse/RpcEvent envelopes in schemas.py; `DirectTransport`
just skips the socket and calls the dispatcher directly, so dev mode and
tests exercise the same validation path as production without a real
`nasos-agent` process running.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from nasos.rpc.schemas import RpcContext, RpcEvent, RpcException, RpcRequest, RpcResponse

logger = logging.getLogger(__name__)

EventHandler = Callable[[RpcEvent], None]


class RpcCallError(RpcException):
    """Raised on the caller side when the agent responds with ok=False."""


class Transport(Protocol):
    async def call(
        self, method: str, params: dict[str, Any], ctx: RpcContext
    ) -> dict[str, Any]: ...

    async def close(self) -> None: ...


class UnixSocketTransport:
    """Newline-delimited JSON RPC over an AF_UNIX stream socket.

    One connection multiplexes many concurrent calls by request id. Drops
    are not retried here: `_ensure_connected` reconnects lazily on the next
    call, but a call in flight when the connection drops fails immediately
    (ConnectionError) and the caller decides whether to retry.
    """

    def __init__(self, socket_path: str, on_event: EventHandler | None = None) -> None:
        self._socket_path = socket_path
        self._on_event = on_event
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._pending: dict[str, asyncio.Future[RpcResponse]] = {}
        self._connect_lock = asyncio.Lock()
        self._reader_task: asyncio.Task[None] | None = None

    async def _ensure_connected(self) -> None:
        if self._writer is not None and not self._writer.is_closing():
            return
        async with self._connect_lock:
            if self._writer is not None and not self._writer.is_closing():
                return
            reader, writer = await asyncio.open_unix_connection(self._socket_path)
            self._reader, self._writer = reader, writer
            self._reader_task = asyncio.create_task(self._read_loop())

    async def _read_loop(self) -> None:
        assert self._reader is not None
        try:
            while True:
                line = await self._reader.readline()
                if not line:
                    break
                self._dispatch_frame(json.loads(line))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("agent connection read loop failed")
        finally:
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(ConnectionError("agent connection closed"))
            self._pending.clear()
            self._writer = None
            self._reader = None

    def _dispatch_frame(self, raw: dict[str, Any]) -> None:
        frame_type = raw.get("type")
        if frame_type == "response":
            resp = RpcResponse.model_validate(raw)
            fut = self._pending.pop(resp.id, None)
            if fut is not None and not fut.done():
                fut.set_result(resp)
        elif frame_type == "event":
            if self._on_event is not None:
                self._on_event(RpcEvent.model_validate(raw))
        else:
            logger.warning("dropping unknown rpc frame type=%r", frame_type)

    async def call(self, method: str, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        await self._ensure_connected()
        assert self._writer is not None
        req = RpcRequest(id=uuid.uuid4().hex, method=method, params=params, ctx=ctx)
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[RpcResponse] = loop.create_future()
        self._pending[req.id] = fut
        self._writer.write(req.model_dump_json().encode() + b"\n")
        await self._writer.drain()
        try:
            resp = await fut
        finally:
            self._pending.pop(req.id, None)
        if not resp.ok:
            assert resp.error is not None
            raise RpcCallError(resp.error.code, resp.error.message)
        return resp.result or {}

    async def close(self) -> None:
        if self._reader_task is not None:
            self._reader_task.cancel()
        if self._writer is not None:
            self._writer.close()


class DirectTransport:
    """In-process transport: calls the agent dispatcher directly.

    Used for NASOS_MODE=dev (single process, no root agent) and for unit
    tests. Params/result still round-trip through the Pydantic models so a
    schema mismatch fails the same way it would over the real socket.
    """

    def __init__(self, dispatch: Callable[[RpcRequest], Awaitable[RpcResponse]]) -> None:
        self._dispatch = dispatch

    async def call(self, method: str, params: dict[str, Any], ctx: RpcContext) -> dict[str, Any]:
        req = RpcRequest(id=uuid.uuid4().hex, method=method, params=params, ctx=ctx)
        resp = await self._dispatch(req)
        if not resp.ok:
            assert resp.error is not None
            raise RpcCallError(resp.error.code, resp.error.message)
        return resp.result or {}

    async def close(self) -> None:
        return None
