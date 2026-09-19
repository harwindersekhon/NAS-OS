"""Integration-style tests for the M2 RPC surface: request -> Dispatcher ->
handler -> Fake adapter, exercising the same wiring `nasos-agent` runs in
production (just with fakes standing in for real system calls).
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from nasos.agent import handlers  # noqa: F401  (populates the dispatcher registry)
from nasos.agent.dispatcher import Dispatcher
from nasos.agent.state import AgentState, build_state
from nasos.config import Mode, Settings
from nasos.rpc.schemas import RpcRequest
from nasos.system.acl import FakeAcl
from nasos.system.firewall import FakeFirewall
from nasos.system.mounts import FakeMounts
from nasos.system.runner import FakeRunner
from nasos.system.samba import NASOS_CONF
from nasos.system.systemd import FakeSystemd
from nasos.system.users import FakePosixUsers

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def state(tmp_path: Path) -> AgentState:
    settings = Settings(
        mode=Mode.test,
        devusers_file=str(FIXTURES_DIR / "devusers.toml"),
        state_dir=str(tmp_path / "state"),
        devdata_dir=str(tmp_path / "devdata"),
    )
    return build_state(settings, lambda topic, data: None, dev=True)


@pytest.fixture
def dispatcher(state: AgentState) -> Dispatcher:
    return Dispatcher(state)


async def call(dispatcher: Dispatcher, method: str, **params: object) -> dict[str, object]:
    resp = await dispatcher.handle(RpcRequest(id="1", method=method, params=params))
    assert resp.ok, resp.error
    assert resp.result is not None
    return resp.result


async def call_error(dispatcher: Dispatcher, method: str, **params: object) -> str:
    resp = await dispatcher.handle(RpcRequest(id="1", method=method, params=params))
    assert not resp.ok
    assert resp.error is not None
    return resp.error.code


# --- users -------------------------------------------------------------


async def test_user_create_creates_unix_and_smb_accounts(
    dispatcher: Dispatcher, state: AgentState
) -> None:
    result = await call(
        dispatcher, "users.create", username="alice", password="hunter2", description="Alice"
    )
    assert result["username"] == "alice"

    users = cast(FakePosixUsers, state.users)
    assert "alice" in users.users
    assert users.unix_passwords["alice"] == "hunter2"
    assert users.smb_passwords["alice"] == "hunter2"
    assert "nasos-users" in users.memberships["alice"]


async def test_user_delete_removes_account(dispatcher: Dispatcher, state: AgentState) -> None:
    await call(dispatcher, "users.create", username="bob", password="x", description="")
    await call(dispatcher, "users.delete", username="bob", delete_home=True)
    users = cast(FakePosixUsers, state.users)
    assert "bob" not in users.users


async def test_user_set_password_reports_smb_sync_failure(
    dispatcher: Dispatcher, state: AgentState
) -> None:
    await call(dispatcher, "users.create", username="carol", password="x", description="")
    users = cast(FakePosixUsers, state.users)

    async def broken_smb_set_password(username: str, password: str) -> None:  # noqa: ARG001
        from nasos.system.users import SystemUserError

        raise SystemUserError("smbpasswd unreachable")

    users.smb_set_password = broken_smb_set_password  # type: ignore[method-assign]

    code = await call_error(dispatcher, "users.set_password", username="carol", password="new")
    assert code == "smb_password_sync_failed"
    # Unix password still changed even though Samba sync failed.
    assert users.unix_passwords["carol"] == "new"


async def test_user_import_existing_rejects_unknown_account(dispatcher: Dispatcher) -> None:
    code = await call_error(dispatcher, "users.import_existing", username="nosuchuser")
    assert code == "not_found"


# --- groups --------------------------------------------------------------


async def test_group_create_and_membership(dispatcher: Dispatcher, state: AgentState) -> None:
    result = await call(dispatcher, "groups.create", name="family", description="")
    assert result["name"] == "family"

    await call(dispatcher, "users.create", username="dave", password="x", description="")
    await call(dispatcher, "groups.add_member", name="family", username="dave")

    users = cast(FakePosixUsers, state.users)
    assert "family" in users.memberships["dave"]

    await call(dispatcher, "groups.remove_member", name="family", username="dave")
    assert "family" not in users.memberships["dave"]


# --- volumes ---------------------------------------------------------------


async def test_volume_register_rejects_root(dispatcher: Dispatcher) -> None:
    code = await call_error(dispatcher, "volumes.register", mountpoint="/")
    assert code == "forbidden"


async def test_volume_register_rejects_boot(dispatcher: Dispatcher) -> None:
    code = await call_error(dispatcher, "volumes.register", mountpoint="/boot")
    assert code == "forbidden"


async def test_volume_register_rejects_non_mountpoint(dispatcher: Dispatcher) -> None:
    code = await call_error(dispatcher, "volumes.register", mountpoint="/not/a/mount")
    assert code == "not_a_mountpoint"


async def test_volume_register_accepts_real_mountpoint(
    dispatcher: Dispatcher, state: AgentState
) -> None:
    mounts = cast(FakeMounts, state.mounts)
    mounts.mounts["/volume1"] = "xfs"

    result = await call(dispatcher, "volumes.register", mountpoint="/volume1")
    assert result == {"mountpoint": "/volume1", "filesystem": "xfs"}


# --- shares ------------------------------------------------------------------


async def test_share_create_then_set_permissions_sync(
    dispatcher: Dispatcher, state: AgentState, tmp_path: Path
) -> None:
    share_path = str(tmp_path / "media")
    await call(dispatcher, "shares.create", path=share_path)

    result = await call(
        dispatcher,
        "shares.set_permissions",
        path=share_path,
        entries=[{"kind": "user", "numeric_id": 5001, "level": "rw"}],
        recursive=False,
    )
    assert result["job_id"] is None

    acl = cast(FakeAcl, state.acl)
    assert acl.entries[share_path] == {("user", 5001): "rw"}


async def test_share_create_twice_fails(dispatcher: Dispatcher, tmp_path: Path) -> None:
    share_path = str(tmp_path / "media")
    await call(dispatcher, "shares.create", path=share_path)
    code = await call_error(dispatcher, "shares.create", path=share_path)
    assert code == "already_exists"


async def test_share_set_permissions_recursive_runs_as_job(
    dispatcher: Dispatcher, state: AgentState, tmp_path: Path
) -> None:
    share_path = str(tmp_path / "media")
    await call(dispatcher, "shares.create", path=share_path)

    result = await call(
        dispatcher,
        "shares.set_permissions",
        path=share_path,
        entries=[{"kind": "group", "numeric_id": 6001, "level": "ro"}],
        recursive=True,
    )
    job_id = result["job_id"]
    assert isinstance(job_id, str)

    import asyncio

    for _ in range(100):
        (record,) = [j for j in state.jobs.list() if j["id"] == job_id]
        if record["status"] in ("done", "failed"):
            break
        await asyncio.sleep(0.01)
    assert record["status"] == "done"

    acl = cast(FakeAcl, state.acl)
    assert acl.entries[share_path] == {("group", 6001): "ro"}


async def test_share_delete_removes_files_when_requested(
    dispatcher: Dispatcher, tmp_path: Path
) -> None:
    share_path = str(tmp_path / "media")
    await call(dispatcher, "shares.create", path=share_path)
    assert Path(share_path).is_dir()

    await call(dispatcher, "shares.delete", path=share_path, delete_files=True)
    assert not Path(share_path).exists()


# --- samba -----------------------------------------------------------------


async def test_samba_apply_config_success(dispatcher: Dispatcher, state: AgentState) -> None:
    runner = cast(FakeRunner, state.runner)
    runner.expect(
        ["testparm", "-s", "--suppress-prompt", "/etc/samba/smb.conf"],
        stdout="Loaded services file OK.\n",
    )
    nasos_conf_path = str(Path(state.settings.system_path(NASOS_CONF)))
    runner.expect(["restorecon", nasos_conf_path])

    result = await call(dispatcher, "samba.apply_config", content="[global]\n", restart=False)
    assert "sha256" in result

    systemd = cast(FakeSystemd, state.systemd)
    assert await systemd.active_state("smb.service") == "active"


async def test_samba_apply_config_validation_failure_surfaces_detail(
    dispatcher: Dispatcher, state: AgentState
) -> None:
    runner = cast(FakeRunner, state.runner)
    runner.expect(
        ["testparm", "-s", "--suppress-prompt", "/etc/samba/smb.conf"],
        returncode=1,
        stderr="Error loading services.\n",
    )
    nasos_conf_path = str(Path(state.settings.system_path(NASOS_CONF)))
    runner.expect(["restorecon", nasos_conf_path])

    resp_code = await call_error(dispatcher, "samba.apply_config", content="bad", restart=False)
    assert resp_code == "config_invalid"


# --- firewall ----------------------------------------------------------------


async def test_firewall_ensure_service_opens_default_zone(
    dispatcher: Dispatcher, state: AgentState
) -> None:
    await call(dispatcher, "firewall.ensure_service", service="samba")

    firewall = cast(FakeFirewall, state.firewall)
    assert await firewall.has_service("public", "samba") is True
