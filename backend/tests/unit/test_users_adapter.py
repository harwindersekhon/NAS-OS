from __future__ import annotations

import pytest

from nasos.system.runner import FakeRunner
from nasos.system.users import RealPosixUsers, SystemUserError


@pytest.fixture
def runner() -> FakeRunner:
    return FakeRunner()


async def test_create_runs_useradd_then_looks_up_uid(runner: FakeRunner) -> None:
    runner.expect(
        [
            "useradd",
            "-m",
            "-d",
            "/volume1/homes/alice",
            "-s",
            "/sbin/nologin",
            "-G",
            "nasos-users",
            "-c",
            "Alice",
            "alice",
        ]
    )
    runner.expect(["id", "-u", "alice"], stdout="5001\n")

    users = RealPosixUsers(runner)
    uid = await users.create("alice", "/volume1/homes/alice", "Alice")

    assert uid == 5001
    assert runner.calls[0][0] == "useradd"
    assert runner.calls[1] == ["id", "-u", "alice"]


async def test_create_raises_on_useradd_failure(runner: FakeRunner) -> None:
    runner.expect(
        [
            "useradd",
            "-m",
            "-d",
            "/volume1/homes/alice",
            "-s",
            "/sbin/nologin",
            "-G",
            "nasos-users",
            "-c",
            "Alice",
            "alice",
        ],
        returncode=9,
        stderr="useradd: user 'alice' already exists\n",
    )
    users = RealPosixUsers(runner)
    with pytest.raises(SystemUserError, match="already exists"):
        await users.create("alice", "/volume1/homes/alice", "Alice")


async def test_set_unix_password_stdin_format(runner: FakeRunner) -> None:
    runner.expect(["chpasswd"])
    users = RealPosixUsers(runner)
    await users.set_unix_password("alice", "hunter2")
    # chpasswd stdin: one "username:password\n" line per user (verified against
    # shadow-utils' own man page during M2 research).
    assert runner.calls == [["chpasswd"]]
    assert runner.inputs == ["alice:hunter2\n"]


async def test_smb_create_sends_password_twice_no_old_password_line(runner: FakeRunner) -> None:
    """smbpasswd -s -a: traced through smbpasswd.c during M2 research —
    LOCAL_SET_PASSWORD is set unconditionally and the old-password prompt is
    skipped for local -a, so stdin is exactly the new password twice.
    """
    runner.expect(["smbpasswd", "-s", "-a", "alice"])
    users = RealPosixUsers(runner)
    await users.smb_create("alice", "hunter2")
    assert runner.calls == [["smbpasswd", "-s", "-a", "alice"]]
    assert runner.inputs == ["hunter2\nhunter2\n"]


async def test_smb_set_password_omits_dash_a(runner: FakeRunner) -> None:
    runner.expect(["smbpasswd", "-s", "alice"])
    users = RealPosixUsers(runner)
    await users.smb_set_password("alice", "newpass")
    assert runner.calls == [["smbpasswd", "-s", "alice"]]
    assert runner.inputs == ["newpass\nnewpass\n"]


async def test_smb_create_failure_raises(runner: FakeRunner) -> None:
    runner.expect(
        ["smbpasswd", "-s", "-a", "alice"],
        returncode=1,
        stderr="Mismatch - password unchanged.\n",
    )
    users = RealPosixUsers(runner)
    with pytest.raises(SystemUserError, match="Mismatch"):
        await users.smb_create("alice", "hunter2")


async def test_smb_enable_disable_flags(runner: FakeRunner) -> None:
    runner.expect(["smbpasswd", "-e", "alice"])
    runner.expect(["smbpasswd", "-d", "alice"])
    users = RealPosixUsers(runner)
    await users.smb_set_enabled("alice", True)
    await users.smb_set_enabled("alice", False)
    assert runner.calls == [["smbpasswd", "-e", "alice"], ["smbpasswd", "-d", "alice"]]


async def test_delete_with_and_without_home(runner: FakeRunner) -> None:
    runner.expect(["userdel", "-r", "alice"])
    runner.expect(["userdel", "bob"])
    users = RealPosixUsers(runner)
    await users.delete("alice", delete_home=True)
    await users.delete("bob", delete_home=False)
    assert runner.calls == [["userdel", "-r", "alice"], ["userdel", "bob"]]


async def test_group_create_parses_gid_from_getent(runner: FakeRunner) -> None:
    runner.expect(["groupadd", "family"])
    runner.expect(["getent", "group", "family"], stdout="family:x:6010:\n")
    users = RealPosixUsers(runner)
    gid = await users.group_create("family")
    assert gid == 6010
