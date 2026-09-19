from __future__ import annotations

from fastapi.testclient import TestClient

from ..conftest import CSRF_HEADERS, login


def test_login_requires_csrf_header(client: TestClient) -> None:
    resp = client.post("/api/v1/auth/login", json={"username": "admin", "password": "adminpass123"})
    assert resp.status_code == 403


def test_login_rejects_bad_password(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "wrong"},
        headers=CSRF_HEADERS,
    )
    assert resp.status_code == 401


def test_login_success_sets_cookie(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "adminpass123"},
        headers=CSRF_HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"username": "admin", "role": "admin", "uid": 5000}
    assert "nasos_session" in resp.cookies


def test_me_requires_authentication(client: TestClient) -> None:
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 401


def test_me_after_login(client: TestClient) -> None:
    login(client)
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 200
    assert resp.json()["username"] == "admin"


def test_logout_clears_session(client: TestClient) -> None:
    login(client)
    resp = client.post("/api/v1/auth/logout", headers=CSRF_HEADERS)
    assert resp.status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 401


def test_get_does_not_require_csrf_header(client: TestClient) -> None:
    # GET is a "safe" method under the CSRF policy; only mutating verbs need the header.
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 401  # unauthenticated, not 403 for missing CSRF header
