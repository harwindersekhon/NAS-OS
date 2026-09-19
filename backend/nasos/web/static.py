"""Prod static serving: the built SPA at /usr/lib/nasos/ui, with a fallback
to index.html for any path that isn't /api/* or /api/v1/ws (PLAN.md §5).
Hashed assets are immutable; index.html is no-store so a deploy is picked up
on next load. Dev mode always skips this — Vite serves the UI and proxies
/api to this backend.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, Response
from starlette.staticfiles import StaticFiles

from nasos.config import Settings

UI_DIR_PROD = Path("/usr/lib/nasos/ui")


def mount_spa(app: FastAPI, settings: Settings) -> None:
    if settings.is_dev:
        return
    ui_dir = UI_DIR_PROD
    if not ui_dir.is_dir():
        return

    assets_dir = ui_dir / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="ui-assets")

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str, request: Request) -> Response:  # noqa: ARG001
        response = FileResponse(ui_dir / "index.html")
        response.headers["Cache-Control"] = "no-store"
        return response
