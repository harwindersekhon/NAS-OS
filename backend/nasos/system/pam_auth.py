"""Authenticates GUI logins and resolves the caller's NAS-OS identity.

Real mode: PAM (service "nasos", see /etc/pam.d/nasos) checks the password,
then POSIX group membership (`nasos-admin` / `nasos-users`) decides the role
— PLAN.md §3. A user in neither group (including root) is refused.

Dev mode has no PAM stack wired up and no real `nasos-admin`/`nasos-users`
groups, so both checks are replaced by a TOML fixture (PLAN.md §10).
"""

from __future__ import annotations

import asyncio
import tomllib
from pathlib import Path
from typing import Any, Protocol

from nasos.rpc.schemas import AuthLoginResult, Role


class Authenticator(Protocol):
    async def authenticate(self, username: str, password: str) -> AuthLoginResult | None: ...


class PamAuthenticator:
    def __init__(self, service: str = "nasos") -> None:
        self._service = service

    async def authenticate(self, username: str, password: str) -> AuthLoginResult | None:
        return await asyncio.to_thread(self._authenticate_sync, username, password)

    def _authenticate_sync(self, username: str, password: str) -> AuthLoginResult | None:
        import grp
        import pwd

        import pam  # python3-pam, system site-package (see pyproject: venv --system-site-packages)

        if not pam.pam().authenticate(username, password, service=self._service):
            return None
        try:
            pw = pwd.getpwnam(username)
        except KeyError:
            return None
        groups = {g.gr_name for g in grp.getgrall() if username in g.gr_mem}
        try:
            groups.add(grp.getgrgid(pw.pw_gid).gr_name)
        except KeyError:
            pass
        role: Role
        if "nasos-admin" in groups:
            role = "admin"
        elif "nasos-users" in groups:
            role = "user"
        else:
            return None
        display_name = pw.pw_gecos.split(",")[0].strip() or username
        return AuthLoginResult(
            uid=pw.pw_uid, username=username, role=role, display_name=display_name
        )


class DevUsersAuthenticator:
    """Reads `[users.<name>]` entries from devusers.toml. NASOS_MODE=dev only."""

    def __init__(self, path: str) -> None:
        self._path = Path(path)

    async def authenticate(self, username: str, password: str) -> AuthLoginResult | None:
        entry = self._load().get(username)
        if entry is None or entry.get("password") != password:
            return None
        return AuthLoginResult(
            uid=int(entry["uid"]),
            username=username,
            role=entry["role"],
            display_name=str(entry.get("display_name", username)),
        )

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self._path.is_file():
            return {}
        with self._path.open("rb") as fh:
            return tomllib.load(fh).get("users", {})
