from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from ..conftest import login


def test_ws_rejects_unauthenticated(client: TestClient) -> None:
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/v1/ws"):
            pass


def test_ws_streams_monitor_sample(client: TestClient) -> None:
    login(client)
    with client.websocket_connect("/api/v1/ws") as ws:
        ws.send_json({"action": "subscribe", "topic": "monitor.sample"})
        frame = ws.receive_json()
        assert frame["topic"] == "monitor.sample"
        assert "cpu_percent" in frame["data"]
        assert "mem_used" in frame["data"]
