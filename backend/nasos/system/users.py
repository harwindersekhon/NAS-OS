"""POSIX account + Samba passdb management (PLAN.md §3): useradd, chpasswd,
smbpasswd, userdel, pdbedit, plus group membership primitives shared by
user-import and (later) groups CRUD.

Password stdin formats were verified during M2 research directly against
the real binaries and, for `smbpasswd`, upstream source
(`source3/utils/smbpasswd.c`) rather than assumed:
  - `chpasswd`: one line `"username:password\n"` per user.
  - `smbpasswd -s -a` (create) and `smbpasswd -s` (change) both read the new
    password twice — `"PASSWORD\nPASSWORD\n"` — with no separate old-password
    line for local `-a`; smbpasswd's own mismatch check is what a wrong
    second line trips, not NAS-OS's.
`useradd` first is mandatory (both `chpasswd` and `smbpasswd -a` require the
Unix account to already exist); order between chpasswd/smbpasswd doesn't
matter beyond that (separate backends).
"""

from __future__ import annotations

from typing import Protocol

from nasos.system.runner import Runner


class SystemUserError(Exception):
    pass


class PosixUsers(Protocol):
    async def lookup(self, username: str) -> int | None: ...
    async def create(self, username: str, home_dir: str, description: str) -> int: ...
    async def delete(self, username: str, *, delete_home: bool) -> None: ...
    async def set_unix_password(self, username: str, password: str) -> None: ...
    async def add_to_group(self, username: str, group: str) -> None: ...
    async def remove_from_group(self, username: str, group: str) -> None: ...

    async def smb_create(self, username: str, password: str) -> None: ...
    async def smb_set_password(self, username: str, password: str) -> None: ...
    async def smb_delete(self, username: str) -> None: ...
    async def smb_set_enabled(self, username: str, enabled: bool) -> None: ...

    async def group_create(self, name: str) -> int: ...
    async def group_delete(self, name: str) -> None: ...


class RealPosixUsers:
    def __init__(self, runner: Runner) -> None:
        self._runner = runner

    async def lookup(self, username: str) -> int | None:
        import pwd

        try:
            return pwd.getpwnam(username).pw_uid
        except KeyError:
            return None

    async def create(self, username: str, home_dir: str, description: str) -> int:
        await self._run(
            [
                "useradd",
                "-m",
                "-d",
                home_dir,
                "-s",
                "/sbin/nologin",
                "-G",
                "nasos-users",
                "-c",
                description,
                username,
            ],
            f"useradd failed for {username}",
        )
        id_result = await self._runner.run(["id", "-u", username])
        if not id_result.ok:
            raise SystemUserError(id_result.stderr.strip() or f"id -u failed for {username}")
        return int(id_result.stdout.strip())

    async def delete(self, username: str, *, delete_home: bool) -> None:
        args = ["userdel", "-r", username] if delete_home else ["userdel", username]
        await self._run(args, f"userdel failed for {username}")

    async def set_unix_password(self, username: str, password: str) -> None:
        await self._run(
            ["chpasswd"], f"chpasswd failed for {username}", input=f"{username}:{password}\n"
        )

    async def add_to_group(self, username: str, group: str) -> None:
        await self._run(["usermod", "-aG", group, username], f"usermod failed for {username}")

    async def remove_from_group(self, username: str, group: str) -> None:
        await self._run(["gpasswd", "-d", username, group], f"gpasswd -d failed for {username}")

    async def smb_create(self, username: str, password: str) -> None:
        await self._run(
            ["smbpasswd", "-s", "-a", username],
            f"smbpasswd -a failed for {username}",
            input=f"{password}\n{password}\n",
        )

    async def smb_set_password(self, username: str, password: str) -> None:
        await self._run(
            ["smbpasswd", "-s", username],
            f"smbpasswd failed for {username}",
            input=f"{password}\n{password}\n",
        )

    async def smb_delete(self, username: str) -> None:
        await self._run(["pdbedit", "-x", "-u", username], f"pdbedit -x failed for {username}")

    async def smb_set_enabled(self, username: str, enabled: bool) -> None:
        flag = "-e" if enabled else "-d"
        await self._run(["smbpasswd", flag, username], f"smbpasswd {flag} failed for {username}")

    async def group_create(self, name: str) -> int:
        await self._run(["groupadd", name], f"groupadd failed for {name}")
        getent = await self._runner.run(["getent", "group", name])
        if not getent.ok:
            raise SystemUserError(f"getent group failed for {name}")
        return int(getent.stdout.strip().split(":")[2])  # "name:x:gid:members"

    async def group_delete(self, name: str) -> None:
        await self._run(["groupdel", name], f"groupdel failed for {name}")

    async def _run(self, argv: list[str], error: str, *, input: str | None = None) -> None:
        result = await self._runner.run(argv, input=input)
        if not result.ok:
            raise SystemUserError(result.stderr.strip() or error)


class FakePosixUsers:
    """In-memory POSIX user/group state for dev mode / unit tests."""

    def __init__(self) -> None:
        self._next_uid = 5000
        self._next_gid = 6000
        self.users: dict[str, int] = {}
        self.groups: dict[str, int] = {}
        self.memberships: dict[str, set[str]] = {}
        self.unix_passwords: dict[str, str] = {}
        self.smb_passwords: dict[str, str] = {}
        self.smb_enabled: dict[str, bool] = {}
        self.calls: list[str] = []

    async def lookup(self, username: str) -> int | None:
        return self.users.get(username)

    async def create(self, username: str, home_dir: str, description: str) -> int:  # noqa: ARG002
        self.calls.append(f"create:{username}")
        uid = self._next_uid
        self._next_uid += 1
        self.users[username] = uid
        self.memberships.setdefault(username, set()).add("nasos-users")
        return uid

    async def delete(self, username: str, *, delete_home: bool) -> None:  # noqa: ARG002
        self.calls.append(f"delete:{username}")
        self.users.pop(username, None)
        self.memberships.pop(username, None)
        self.unix_passwords.pop(username, None)
        self.smb_passwords.pop(username, None)
        self.smb_enabled.pop(username, None)

    async def set_unix_password(self, username: str, password: str) -> None:
        self.calls.append(f"set_unix_password:{username}")
        self.unix_passwords[username] = password

    async def add_to_group(self, username: str, group: str) -> None:
        self.calls.append(f"add_to_group:{username}:{group}")
        self.memberships.setdefault(username, set()).add(group)

    async def remove_from_group(self, username: str, group: str) -> None:
        self.calls.append(f"remove_from_group:{username}:{group}")
        self.memberships.get(username, set()).discard(group)

    async def smb_create(self, username: str, password: str) -> None:
        self.calls.append(f"smb_create:{username}")
        self.smb_passwords[username] = password
        self.smb_enabled[username] = True

    async def smb_set_password(self, username: str, password: str) -> None:
        self.calls.append(f"smb_set_password:{username}")
        self.smb_passwords[username] = password

    async def smb_delete(self, username: str) -> None:
        self.calls.append(f"smb_delete:{username}")
        self.smb_passwords.pop(username, None)
        self.smb_enabled.pop(username, None)

    async def smb_set_enabled(self, username: str, enabled: bool) -> None:
        self.calls.append(f"smb_set_enabled:{username}:{enabled}")
        self.smb_enabled[username] = enabled

    async def group_create(self, name: str) -> int:
        self.calls.append(f"group_create:{name}")
        gid = self._next_gid
        self._next_gid += 1
        self.groups[name] = gid
        return gid

    async def group_delete(self, name: str) -> None:
        self.calls.append(f"group_delete:{name}")
        self.groups.pop(name, None)
