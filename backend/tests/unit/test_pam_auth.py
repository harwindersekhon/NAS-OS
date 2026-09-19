from __future__ import annotations

from pathlib import Path

import pytest

from nasos.system.pam_auth import DevUsersAuthenticator

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def authenticator() -> DevUsersAuthenticator:
    return DevUsersAuthenticator(str(FIXTURES_DIR / "devusers.toml"))


async def test_correct_password_resolves_identity(authenticator: DevUsersAuthenticator) -> None:
    identity = await authenticator.authenticate("admin", "adminpass123")
    assert identity is not None
    assert identity.username == "admin"
    assert identity.role == "admin"
    assert identity.uid == 5000


async def test_wrong_password_rejected(authenticator: DevUsersAuthenticator) -> None:
    assert await authenticator.authenticate("admin", "wrong") is None


async def test_unknown_user_rejected(authenticator: DevUsersAuthenticator) -> None:
    assert await authenticator.authenticate("nobody", "whatever") is None


async def test_missing_file_rejects_everyone() -> None:
    authenticator = DevUsersAuthenticator("/nonexistent/devusers.toml")
    assert await authenticator.authenticate("admin", "adminpass123") is None


async def test_user_role_resolved(authenticator: DevUsersAuthenticator) -> None:
    identity = await authenticator.authenticate("alice", "alicepass123")
    assert identity is not None
    assert identity.role == "user"
