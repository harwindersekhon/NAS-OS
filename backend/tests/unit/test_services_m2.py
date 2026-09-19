"""End-to-end tests for the M2 services layer: services -> AgentClient ->
Dispatcher -> Fake adapters, with a real (in-memory) DB — the same stack
`create_app` wires together minus the FastAPI/HTTP layer.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import cast

import pytest
from sqlalchemy.orm import Session as OrmSession

from nasos.agent import handlers  # noqa: F401  (populates the dispatcher registry)
from nasos.agent.dispatcher import Dispatcher
from nasos.agent.state import AgentState, build_state
from nasos.config import Mode, Settings
from nasos.db.models import Base, Volume
from nasos.db.session import make_engine, make_session_factory
from nasos.rpc.client import AgentClient
from nasos.rpc.schemas import RpcContext
from nasos.rpc.transport import DirectTransport
from nasos.services import shares as shares_service
from nasos.services import users as users_service
from nasos.services import volumes as volumes_service
from nasos.system.acl import FakeAcl
from nasos.system.mounts import FakeMounts
from nasos.system.runner import FakeRunner
from nasos.system.samba import NASOS_CONF
from nasos.system.users import FakePosixUsers, SystemUserError

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"
CTX = RpcContext(user="admin", role="admin")


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
def agent(state: AgentState) -> AgentClient:
    dispatcher = Dispatcher(state)
    return AgentClient(DirectTransport(dispatcher.handle))


@pytest.fixture
def db() -> Iterator[OrmSession]:
    engine = make_engine(":memory:")
    Base.metadata.create_all(engine)
    factory = make_session_factory(engine)
    with factory() as session:
        yield session


def _expect_samba_apply(state: AgentState) -> None:
    runner = cast(FakeRunner, state.runner)
    runner.expect(
        ["testparm", "-s", "--suppress-prompt", "/etc/samba/smb.conf"],
        stdout="Loaded services file OK.\n",
    )
    nasos_conf_path = str(Path(state.settings.system_path(NASOS_CONF)))
    runner.expect(["restorecon", nasos_conf_path])
    # First apply finds smb.service inactive and starts it (no smbcontrol
    # call); every apply after that finds it already active and reloads.
    runner.expect(["smbcontrol", "all", "reload-config"])


async def _register_volume(
    db: OrmSession, agent: AgentClient, state: AgentState, tmp_path: Path
) -> Volume:
    mounts = cast(FakeMounts, state.mounts)
    mountpoint = str(tmp_path / "vol1")
    mounts.mounts[mountpoint] = "xfs"
    return await volumes_service.register_volume(
        db, agent, CTX, name="volume1", mountpoint=mountpoint
    )


async def test_create_share_creates_directory_and_applies_samba_config(
    db: OrmSession, agent: AgentClient, state: AgentState, tmp_path: Path
) -> None:
    volume = await _register_volume(db, agent, state, tmp_path)
    _expect_samba_apply(state)

    share = await shares_service.create_share(
        db, agent, CTX, name="media", volume_id=volume.id, description=""
    )

    assert share.path == f"{tmp_path}/vol1/media"
    assert Path(share.path).is_dir()

    nasos_conf_path = Path(state.settings.system_path(NASOS_CONF))
    assert "[media]" in nasos_conf_path.read_text()


async def test_set_share_permissions_resolves_uid_and_updates_db(
    db: OrmSession, agent: AgentClient, state: AgentState, tmp_path: Path
) -> None:
    volume = await _register_volume(db, agent, state, tmp_path)
    _expect_samba_apply(state)
    share = await shares_service.create_share(
        db, agent, CTX, name="media", volume_id=volume.id, description=""
    )

    user = await users_service.create_user(
        db, agent, CTX, username="alice", password="hunter2", description=""
    )

    _expect_samba_apply(state)  # set_share_permissions re-applies the config too
    job_id = await shares_service.set_share_permissions(
        db, agent, CTX, share, permissions=[("user", "alice", "rw")], recursive=False
    )
    assert job_id is None

    acl = cast(FakeAcl, state.acl)
    assert acl.entries[share.path] == {("user", user.uid): "rw"}

    perms = shares_service.list_permissions(db, share.id)
    assert [(p.principal, p.level) for p in perms] == [("alice", "rw")]


async def test_set_share_permissions_rejects_unknown_user(
    db: OrmSession, agent: AgentClient, state: AgentState, tmp_path: Path
) -> None:
    volume = await _register_volume(db, agent, state, tmp_path)
    _expect_samba_apply(state)
    share = await shares_service.create_share(
        db, agent, CTX, name="media", volume_id=volume.id, description=""
    )

    with pytest.raises(shares_service.ShareServiceError, match="no such NAS-OS user"):
        await shares_service.set_share_permissions(
            db, agent, CTX, share, permissions=[("user", "ghost", "rw")], recursive=False
        )


async def test_delete_share_removes_db_row_and_directory(
    db: OrmSession, agent: AgentClient, state: AgentState, tmp_path: Path
) -> None:
    volume = await _register_volume(db, agent, state, tmp_path)
    _expect_samba_apply(state)
    share = await shares_service.create_share(
        db, agent, CTX, name="media", volume_id=volume.id, description=""
    )
    share_id = share.id

    _expect_samba_apply(state)
    await shares_service.delete_share(db, agent, CTX, share, delete_files=True)

    assert not Path(f"{tmp_path}/vol1/media").exists()
    assert shares_service.get_share(db, share_id) is None


async def test_set_password_flags_sync_failure_without_raising(
    db: OrmSession, agent: AgentClient, state: AgentState
) -> None:
    user = await users_service.create_user(
        db, agent, CTX, username="carol", password="x", description=""
    )
    assert user.smb_password_synced is True

    users = cast(FakePosixUsers, state.users)

    async def broken(username: str, password: str) -> None:  # noqa: ARG001
        raise SystemUserError("smbpasswd unreachable")

    users.smb_set_password = broken  # type: ignore[method-assign]

    updated = await users_service.set_password(db, agent, CTX, user, password="new")

    assert updated.smb_password_synced is False
    assert users.unix_passwords["carol"] == "new"  # unix side still succeeded
