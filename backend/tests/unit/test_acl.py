from __future__ import annotations

import pytest

from nasos.system.acl import AclError, FakeAcl, SetfaclAcl
from nasos.system.runner import FakeRunner

_ALWAYS = "u::rwx,g::---,m::rwx,d:u::rwx,d:g::---,d:m::rwx,o::---,d:o::---"


@pytest.fixture
def runner() -> FakeRunner:
    return FakeRunner()


async def test_replace_all_resets_then_reapplies_top_level_only(runner: FakeRunner) -> None:
    spec = f"{_ALWAYS},u:6001:rwx,d:u:6001:rwx,g:6002:r-x,d:g:6002:r-x"
    runner.expect(["setfacl", "-b", "/volume1/media"])
    runner.expect(["setfacl", "-m", spec, "/volume1/media"])

    acl = SetfaclAcl(runner)
    await acl.replace_all(
        "/volume1/media", [("user", 6001, "rw"), ("group", 6002, "ro")], recursive=False
    )

    assert runner.calls == [
        ["setfacl", "-b", "/volume1/media"],
        ["setfacl", "-m", spec, "/volume1/media"],
    ]


async def test_replace_all_recursive_uses_dash_r_on_both_calls(runner: FakeRunner) -> None:
    spec = f"{_ALWAYS},u:6001:rwx,d:u:6001:rwx"
    runner.expect(["setfacl", "-b", "-R", "/volume1/media"])
    runner.expect(["setfacl", "-R", "-m", spec, "/volume1/media"])

    acl = SetfaclAcl(runner)
    await acl.replace_all("/volume1/media", [("user", 6001, "rw")], recursive=True)

    assert runner.calls == [
        ["setfacl", "-b", "-R", "/volume1/media"],
        ["setfacl", "-R", "-m", spec, "/volume1/media"],
    ]


async def test_no_mask_flag_is_never_passed(runner: FakeRunner) -> None:
    """-n silently caps effective permissions below the requested level with
    no error (verified during M2 research) — replace_all() must never emit it.
    """
    runner.expect(["setfacl", "-b", "/x"])
    runner.expect(["setfacl", "-m", f"{_ALWAYS},u:1:rwx,d:u:1:rwx", "/x"])
    acl = SetfaclAcl(runner)
    await acl.replace_all("/x", [("user", 1, "rw")], recursive=False)
    assert all("-n" not in call for call in runner.calls)


async def test_reset_failure_raises_acl_error_before_reapply(runner: FakeRunner) -> None:
    runner.expect(
        ["setfacl", "-b", "/x"], returncode=1, stderr="setfacl: /x: Operation not permitted\n"
    )
    acl = SetfaclAcl(runner)
    with pytest.raises(AclError, match="Operation not permitted"):
        await acl.replace_all("/x", [("user", 1, "rw")], recursive=False)
    # Never got to the -m call: the reset step failed first.
    assert runner.calls == [["setfacl", "-b", "/x"]]


async def test_apply_failure_raises_acl_error(runner: FakeRunner) -> None:
    runner.expect(["setfacl", "-b", "/x"])
    runner.expect(
        ["setfacl", "-m", f"{_ALWAYS},u:99999:rwx,d:u:99999:rwx", "/x"],
        returncode=1,
        stderr="setfacl: /x: Invalid argument\n",
    )
    acl = SetfaclAcl(runner)
    with pytest.raises(AclError, match="Invalid argument"):
        await acl.replace_all("/x", [("user", 99999, "rw")], recursive=False)


async def test_fake_acl_replace_all_tracks_state() -> None:
    acl = FakeAcl()
    await acl.replace_all("/x", [("user", 1, "rw"), ("group", 2, "ro")], recursive=False)
    assert acl.entries["/x"] == {("user", 1): "rw", ("group", 2): "ro"}

    await acl.replace_all("/x", [("user", 1, "rw")], recursive=True)
    assert acl.entries["/x"] == {("user", 1): "rw"}


async def test_fake_acl_read_acl_round_trips() -> None:
    acl = FakeAcl()
    await acl.replace_all("/x", [("user", 1000, "rw"), ("group", 1001, "ro")], recursive=False)
    entries = await acl.read_acl("/x")
    assert set(entries) == {("user", 1000, "rw"), ("group", 1001, "ro")}


async def test_fake_acl_read_acl_empty_path_returns_empty() -> None:
    acl = FakeAcl()
    assert await acl.read_acl("/never-set") == []


# Captured verbatim from a real `getfacl -n --absolute-names --omit-header`
# run against a scratch directory during M3 research (system/acl.py's
# _parse_getfacl docstring): owner/group resolved to a name where NSS could
# (harwinder=uid 1000), numeric where a plain uid/gid was set directly.
_REAL_GETFACL_OUTPUT = """user::rwx
user:1000:rwx
group::---
group:1001:r-x
mask::rwx
other::---
default:user::rwx
default:user:1000:rwx
default:group::---
default:group:1001:r-x
default:mask::rwx
default:other::---
"""


async def test_read_acl_parses_real_getfacl_output(runner: FakeRunner) -> None:
    runner.expect(
        ["getfacl", "-n", "--absolute-names", "--omit-header", "/x"],
        stdout=_REAL_GETFACL_OUTPUT,
    )
    acl = SetfaclAcl(runner)
    entries = await acl.read_acl("/x")
    # Bare user::/group:: (empty id), mask::, other::, and every default:
    # line are bookkeeping/mirrors, not principals — only the two named
    # regular entries become results.
    assert set(entries) == {("user", 1000, "rw"), ("group", 1001, "ro")}


async def test_read_acl_raises_on_failure(runner: FakeRunner) -> None:
    runner.expect(
        ["getfacl", "-n", "--absolute-names", "--omit-header", "/missing"],
        returncode=1,
        stderr="getfacl: /missing: No such file or directory\n",
    )
    acl = SetfaclAcl(runner)
    with pytest.raises(AclError, match="No such file or directory"):
        await acl.read_acl("/missing")
