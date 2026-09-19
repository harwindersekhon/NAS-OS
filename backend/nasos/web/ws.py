"""WebSocket endpoint: /api/v1/ws. Auth uses the same session cookie as the
REST API. Clients subscribe/unsubscribe to topics by name; the server
forwards whatever `EventBus.publish()` sends on each as
`{"topic": ..., "data": ...}` frames.
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from nasos.services.auth import resolve_session
from nasos.web.deps import SESSION_COOKIE

logger = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/api/v1/ws")
async def ws_endpoint(websocket: WebSocket) -> None:
    settings = websocket.app.state.settings
    session_factory = websocket.app.state.session_factory
    bus = websocket.app.state.event_bus

    token = websocket.cookies.get(SESSION_COOKIE)
    idle_timeout = dt.timedelta(minutes=settings.session_idle_timeout_minutes)
    authenticated = False
    if token:
        with session_factory() as db:
            authenticated = resolve_session(db, token, idle_timeout=idle_timeout) is not None
    if not authenticated:
        await websocket.close(code=4401)
        return

    await websocket.accept()
    forwarders: dict[str, asyncio.Task[None]] = {}

    async def forward(topic: str) -> None:
        async with bus.subscribe(topic) as queue:
            while True:
                data = await queue.get()
                await websocket.send_json({"topic": topic, "data": data})

    try:
        while True:
            msg = await websocket.receive_json()
            topic = msg.get("topic")
            if not isinstance(topic, str):
                continue
            if msg.get("action") == "subscribe" and topic not in forwarders:
                forwarders[topic] = asyncio.create_task(forward(topic))
            elif msg.get("action") == "unsubscribe" and topic in forwarders:
                forwarders.pop(topic).cancel()
    except WebSocketDisconnect:
        pass
    finally:
        for task in forwarders.values():
            task.cancel()
        for task in forwarders.values():
            with contextlib.suppress(asyncio.CancelledError):
                await task
