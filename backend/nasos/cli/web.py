"""Console-script entry point: nasos-web.

Prod runs two uvicorn servers: HTTPS on settings.https_port (the real app)
and a bare redirect server on settings.http_port — DSM's 5000/5001 split
(PLAN.md §1 ports table). Dev mode skips TLS and the redirect server: a
single plain HTTP port, matching `make dev`'s Vite proxy target.
"""

from __future__ import annotations

import asyncio

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import RedirectResponse
from starlette.routing import Route

from nasos.config import Settings, get_settings
from nasos.web.main import create_app


def _redirect_app(https_port: int) -> Starlette:
    async def redirect(request: Request) -> RedirectResponse:
        host = request.url.hostname or "localhost"
        return RedirectResponse(f"https://{host}:{https_port}{request.url.path}", status_code=308)

    return Starlette(routes=[Route("/{path:path}", redirect)])


async def _run_prod(settings: Settings) -> None:
    app = create_app(settings)
    https_server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="0.0.0.0",
            port=settings.https_port,
            ssl_certfile=settings.tls_cert,
            ssl_keyfile=settings.tls_key,
            log_level="info",
        )
    )
    http_server = uvicorn.Server(
        uvicorn.Config(
            _redirect_app(settings.https_port),
            host="0.0.0.0",
            port=settings.http_port,
            log_level="warning",
        )
    )
    await asyncio.gather(https_server.serve(), http_server.serve())


def _run_dev(settings: Settings) -> None:
    uvicorn.run(create_app(settings), host="127.0.0.1", port=settings.http_port, log_level="info")


def main() -> None:
    settings = get_settings()
    if settings.is_dev:
        _run_dev(settings)
    else:
        asyncio.run(_run_prod(settings))


if __name__ == "__main__":
    main()
