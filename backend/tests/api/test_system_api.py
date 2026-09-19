from __future__ import annotations

from fastapi.testclient import TestClient

from ..conftest import login


def test_system_info_requires_authentication(client: TestClient) -> None:
    assert client.get("/api/v1/system/info").status_code == 401


def test_system_info_after_login(client: TestClient) -> None:
    login(client)
    resp = client.get("/api/v1/system/info")
    assert resp.status_code == 200
    body = resp.json()
    assert body["hostname"]
    assert body["nasos_version"] == "0.1.0"
    assert body["uptime_seconds"] >= 0
