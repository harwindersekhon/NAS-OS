"""End-to-end test of the real wire protocol: a UnixSocketTransport client
talking to the same accept-loop code nasos-agent runs in production.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from nasos.agent import handlers  # noqa: F401  (populates the dispatcher registry)
from nasos.agent.dispatcher import Dispatcher
from nasos.agent.main import _handle_connection
from nasos.agent.state import build_state
from nasos.config import Mode, Settings
from nasos.rpc.client import AgentClient
from nasos.rpc.schemas import AuthLoginResult, RpcContext
from nasos.rpc.transport import RpcCallError, UnixSocketTransport

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


@pytest.fixture
async def socket_path(tmp_path: Path) -> AsyncIterator[str]:
    settings = Settings(
        mode=Mode.test, devusers_file=str(FIXTURES_DIR / "devusers.toml"), state_dir=str(tmp_path)
    )
    state = build_state(settings, lambda topic, data: None, dev=True)
    dispatcher = Dispatcher(state)
    path = str(tmp_path / "agent.sock")
    server = await asyncio.start_unix_server(
        lambda r, w: _handle_connection(r, w, dispatcher, os.getuid()),
        path=path,
    )
    task = asyncio.create_task(server.serve_forever())
    try:
        yield path
    finally:
        task.cancel()
        server.close()
        await server.wait_closed()


async def test_unix_socket_round_trip(socket_path: str) -> None:
    client = AgentClient(UnixSocketTransport(socket_path))
    result = await client.call("system.info", RpcContext())
    assert result.hostname  # type: ignore[attr-defined]
    await client.close()


async def test_unix_socket_auth_login(socket_path: str) -> None:
    client = AgentClient(UnixSocketTransport(socket_path))
    result = await client.call(
        "auth.login", RpcContext(), username="admin", password="adminpass123"
    )
    assert isinstance(result, AuthLoginResult)
    assert result.role == "admin"
    await client.close()


async def test_unix_socket_error_propagates(socket_path: str) -> None:
    transport = UnixSocketTransport(socket_path)
    with pytest.raises(RpcCallError) as excinfo:
        await transport.call("no.such.method", {}, RpcContext())
    assert excinfo.value.code == "unknown_method"
    await transport.close()


async def test_unix_socket_concurrent_calls(socket_path: str) -> None:
    """Several in-flight requests on one connection, multiplexed by request id."""
    transport = UnixSocketTransport(socket_path)
    calls = (transport.call("system.info", {}, RpcContext()) for _ in range(10))
    results = await asyncio.gather(*calls)
    assert all(r["hostname"] for r in results)
    await transport.close()
