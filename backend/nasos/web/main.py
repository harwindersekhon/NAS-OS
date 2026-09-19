"""FastAPI application factory: wires the DB, the agent RPC client, the
event bus, the resource-monitor sampler, session/RBAC/CSRF, and the API
routers together. See PLAN.md §1 for the process/privilege model this
composes.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from nasos.agent.dispatcher import Dispatcher
from nasos.agent.state import AgentState, build_state
from nasos.agent.workerstate import WorkerState, build_worker_state
from nasos.api import auth as auth_api
from nasos.api import files as files_api
from nasos.api import groups as groups_api
from nasos.api import shares as shares_api
from nasos.api import storage as storage_api
from nasos.api import system as system_api
from nasos.api import uploads as uploads_api
from nasos.api import users as users_api
from nasos.api import volumes as volumes_api
from nasos.config import Settings
from nasos.config import get_settings as load_settings
from nasos.db.models import Base
from nasos.db.session import make_engine, make_session_factory
from nasos.events.bus import EventBus
from nasos.monitor.sampler import Sampler
from nasos.rpc.client import (
    AgentClient,
    DirectFileDataClient,
    FileWorkerClient,
    SocketFileDataClient,
)
from nasos.rpc.schemas import RpcContext, RpcEvent
from nasos.rpc.transport import DirectTransport, UnixSocketTransport
from nasos.services.storage.completion import VolumeAutoRegistrar
from nasos.services.storage.health import SmartHealthPoller
from nasos.web import static
from nasos.web.ws import router as ws_router

logger = logging.getLogger(__name__)

_UNPROTECTED_METHODS = {"GET", "HEAD", "OPTIONS"}
_CSRF_HEADER = "x-nasos-request"

FileWorkerClientFactory = Callable[[RpcContext, int, str], Awaitable[FileWorkerClient]]


def _build_agent_client(settings: Settings, bus: EventBus) -> tuple[AgentClient, AgentState | None]:
    if settings.is_dev or settings.is_test:
        # Same process, no root agent: run the dispatcher in-process against
        # dev/test adapters (PLAN.md §10 "Dev without passwordless sudo").
        # No socket to broadcast events over, so the job runner publishes
        # straight to this process's own EventBus.
        from nasos.agent import handlers  # noqa: F401  (populates the registry)

        state = build_state(settings, bus.publish, dev=True)
        dispatcher = Dispatcher(state)
        # `state` is also stashed on app.state (below) so dev/test-mode
        # callers — namely tests — can reach the Fake adapters directly to
        # set up expectations, since there's no real agent process to talk
        # to instead.
        return AgentClient(DirectTransport(dispatcher.handle)), state

    def on_event(evt: RpcEvent) -> None:
        bus.publish(evt.topic, evt.data)

    client = AgentClient(UnixSocketTransport(settings.agent_socket, on_event=on_event))
    return client, None


def _build_file_worker_client_factory(
    settings: Settings,
    agent_client: AgentClient,
    bus: EventBus,
    dev_agent_state: AgentState | None,
) -> tuple[FileWorkerClientFactory, WorkerState | None]:
    """Mirrors _build_agent_client's dev/prod split one layer up: in prod, a
    FileWorkerClient is built fresh per call to whatever socket
    agent.fileworker.ensure hands back (PLAN.md §1 — files.* is never
    proxied through the agent itself); in dev mode there's no real worker
    process, so files.* handlers run through a second in-process
    Dispatcher/WorkerState (see agent/workerstate.py's build_worker_state).
    """
    if settings.is_dev or settings.is_test:
        from nasos.agent.handlers import files as _files_handlers  # noqa: F401
        from nasos.agent.handlers import uploads as _upload_handlers  # noqa: F401

        assert dev_agent_state is not None
        worker_state = build_worker_state(settings, bus.publish, acl=dev_agent_state.acl)
        dispatcher = Dispatcher(worker_state)

        async def get_dev_client(ctx: RpcContext, uid: int, username: str) -> FileWorkerClient:  # noqa: ARG001
            return FileWorkerClient(
                AgentClient(DirectTransport(dispatcher.handle)),
                DirectFileDataClient(worker_state),
            )

        return get_dev_client, worker_state

    async def get_prod_client(ctx: RpcContext, uid: int, username: str) -> FileWorkerClient:
        result = await agent_client.call("agent.fileworker.ensure", ctx, uid=uid, username=username)
        socket_path = result.socket_path  # type: ignore[attr-defined]
        return FileWorkerClient(
            AgentClient(UnixSocketTransport(socket_path)), SocketFileDataClient(socket_path)
        )

    return get_prod_client, None


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()

    engine = make_engine(settings.db_path)
    if settings.is_dev or settings.is_test:
        # Convenience only: real deployments apply `alembic upgrade head`.
        Base.metadata.create_all(engine)
    session_factory = make_session_factory(engine)

    bus = EventBus()
    agent_client, dev_agent_state = _build_agent_client(settings, bus)
    file_worker_client_factory, dev_worker_state = _build_file_worker_client_factory(
        settings, agent_client, bus, dev_agent_state
    )
    sampler = Sampler(bus)
    volume_registrar = VolumeAutoRegistrar(bus, session_factory)
    health_poller = SmartHealthPoller(agent_client, session_factory)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        sampler.start()
        volume_registrar.start()
        # Not in test mode: its first poll would otherwise race a test's
        # own FakeRunner.expect() setup with an unstubbed "lsblk" call
        # (services/storage/health.py's _run has the full rationale).
        if not settings.is_test:
            health_poller.start()
        try:
            yield
        finally:
            await health_poller.stop()  # no-op if never started (test mode)
            await volume_registrar.stop()
            await sampler.stop()
            await agent_client.close()

    app = FastAPI(title="NAS-OS", lifespan=lifespan)
    app.state.settings = settings
    app.state.session_factory = session_factory
    app.state.agent_client = agent_client
    app.state.file_worker_client_factory = file_worker_client_factory
    app.state.event_bus = bus
    app.state.dev_agent_state = dev_agent_state  # None outside dev/test — see _build_agent_client
    app.state.dev_worker_state = dev_worker_state  # ditto, for files.* — see build_worker_state

    @app.middleware("http")
    async def csrf_guard(request: Request, call_next: RequestResponseEndpoint) -> Response:
        if (
            request.method not in _UNPROTECTED_METHODS
            and request.url.path.startswith("/api/")
            and request.headers.get(_CSRF_HEADER) != "1"
        ):
            return JSONResponse({"detail": "missing X-NASOS-Request header"}, status_code=403)
        return await call_next(request)

    app.include_router(auth_api.router)
    app.include_router(system_api.router)
    app.include_router(users_api.router)
    app.include_router(groups_api.router)
    app.include_router(volumes_api.router)
    app.include_router(shares_api.router)
    app.include_router(storage_api.router)
    app.include_router(files_api.router)
    app.include_router(uploads_api.router)
    app.include_router(ws_router)

    static.mount_spa(app, settings)

    return app
