from __future__ import annotations

from pathlib import Path

import pytest

from nasos.agent import handlers  # noqa: F401  (populates the dispatcher registry)
from nasos.agent.dispatcher import Dispatcher
from nasos.agent.state import build_state
from nasos.config import Mode, Settings
from nasos.rpc.schemas import RpcContext, RpcRequest

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def dispatcher(tmp_path: Path) -> Dispatcher:
    settings = Settings(
        mode=Mode.test, devusers_file=str(FIXTURES_DIR / "devusers.toml"), state_dir=str(tmp_path)
    )
    state = build_state(settings, lambda topic, data: None, dev=True)
    return Dispatcher(state)


async def test_unknown_method_rejected(dispatcher: Dispatcher) -> None:
    resp = await dispatcher.handle(RpcRequest(id="1", method="no.such.method", params={}))
    assert not resp.ok
    assert resp.error is not None
    assert resp.error.code == "unknown_method"


async def test_invalid_params_rejected(dispatcher: Dispatcher) -> None:
    resp = await dispatcher.handle(
        RpcRequest(id="1", method="auth.login", params={"username": "admin"})
    )
    assert not resp.ok
    assert resp.error is not None
    assert resp.error.code == "invalid_params"


async def test_extra_param_rejected(dispatcher: Dispatcher) -> None:
    resp = await dispatcher.handle(
        RpcRequest(
            id="1",
            method="auth.login",
            params={"username": "admin", "password": "adminpass123", "extra": "nope"},
        )
    )
    assert not resp.ok
    assert resp.error is not None
    assert resp.error.code == "invalid_params"


async def test_auth_login_success(dispatcher: Dispatcher) -> None:
    resp = await dispatcher.handle(
        RpcRequest(
            id="1",
            method="auth.login",
            params={"username": "admin", "password": "adminpass123"},
            ctx=RpcContext(ip="127.0.0.1"),
        )
    )
    assert resp.ok, resp.error
    assert resp.result is not None
    assert resp.result["role"] == "admin"


async def test_auth_login_bad_credentials(dispatcher: Dispatcher) -> None:
    resp = await dispatcher.handle(
        RpcRequest(id="1", method="auth.login", params={"username": "admin", "password": "wrong"})
    )
    assert not resp.ok
    assert resp.error is not None
    assert resp.error.code == "invalid_credentials"


async def test_system_info(dispatcher: Dispatcher) -> None:
    resp = await dispatcher.handle(RpcRequest(id="1", method="system.info", params={}))
    assert resp.ok, resp.error
    assert resp.result is not None
    assert resp.result["hostname"]
    assert resp.result["uptime_seconds"] >= 0
