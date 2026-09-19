"""Shared pytest fixtures: Settings pointed at an in-memory DB and the
devusers.toml fixture (NASOS_MODE=test uses the same DirectTransport +
DevUsersAuthenticator wiring as `make dev`), plus a FastAPI TestClient.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nasos.agent.state import AgentState
from nasos.config import Mode, Settings
from nasos.web.main import create_app

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        mode=Mode.test,
        db_path=":memory:",
        devusers_file=str(FIXTURES_DIR / "devusers.toml"),
        session_cookie_secure=False,
        # Sandboxes anything that'd otherwise touch a real system path (e.g.
        # samba's nasos.conf via system_path()) under tmp_path instead.
        state_dir=str(tmp_path / "state"),
        devdata_dir=str(tmp_path / "devdata"),
    )


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


@pytest.fixture
def dev_agent_state(app: FastAPI) -> AgentState:
    """The in-process AgentState dev/test mode builds — Fake adapters and
    all — so API tests can reach into e.g. FakeRunner to set expectations,
    the same way there's no real `nasos-agent` process to talk to instead.
    """
    state: AgentState = app.state.dev_agent_state
    return state


CSRF_HEADERS = {"X-NASOS-Request": "1"}


def login(client: TestClient, username: str = "admin", password: str = "adminpass123") -> None:
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
        headers=CSRF_HEADERS,
    )
    assert resp.status_code == 200, resp.text
