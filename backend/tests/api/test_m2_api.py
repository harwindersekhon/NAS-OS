"""API-level tests for M2: users/groups/volumes/shares REST endpoints,
including the share permission matrix end to end (PLAN.md M2 gate: "API
tests for the permission matrix").
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

from fastapi.testclient import TestClient

from nasos.agent.state import AgentState
from nasos.system.runner import FakeRunner
from nasos.system.samba import NASOS_CONF, SMB_CONF

from ..conftest import CSRF_HEADERS, login


def _expect_samba_apply(state: AgentState, *, already_active: bool = False) -> None:
    runner = cast(FakeRunner, state.runner)
    runner.expect(
        ["testparm", "-s", "--suppress-prompt", "/etc/samba/smb.conf"],
        stdout="Loaded services file OK.\n",
    )
    nasos_conf_path = str(Path(state.settings.system_path(NASOS_CONF)))
    runner.expect(["restorecon", nasos_conf_path])
    if already_active:
        runner.expect(["smbcontrol", "all", "reload-config"])


def _expect_ensure_enabled(state: AgentState) -> None:
    """create_share also calls samba.ensure_enabled, which edits smb.conf's
    include block the first time (a separate restorecon target from
    nasos.conf) and restarts smb/nmb directly (no smbcontrol involved).
    """
    runner = cast(FakeRunner, state.runner)
    smb_conf_path = str(Path(state.settings.system_path(SMB_CONF)))
    runner.expect(["restorecon", smb_conf_path])


def _register_volume(client: TestClient, tmp_path: Path, state: AgentState) -> int:
    mountpoint = str(tmp_path / "vol1")
    state.mounts.mounts[mountpoint] = "xfs"  # type: ignore[attr-defined]
    resp = client.post(
        "/api/v1/volumes",
        json={"name": "volume1", "mountpoint": mountpoint},
        headers=CSRF_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    return int(resp.json()["id"])


def test_users_require_authentication(client: TestClient) -> None:
    assert client.get("/api/v1/users").status_code == 401


def test_non_admin_cannot_create_user(client: TestClient) -> None:
    login(client, username="alice", password="alicepass123")
    resp = client.post(
        "/api/v1/users",
        json={"username": "bob", "password": "x", "description": ""},
        headers=CSRF_HEADERS,
    )
    assert resp.status_code == 403


def test_admin_can_create_list_and_delete_user(client: TestClient) -> None:
    login(client)
    create = client.post(
        "/api/v1/users",
        json={"username": "dave", "password": "x", "description": "Dave"},
        headers=CSRF_HEADERS,
    )
    assert create.status_code == 200, create.text
    uid = create.json()["uid"]

    listing = client.get("/api/v1/users")
    assert any(u["uid"] == uid for u in listing.json())

    delete = client.delete(f"/api/v1/users/{uid}", headers=CSRF_HEADERS)
    assert delete.status_code == 200
    assert not any(u["uid"] == uid for u in client.get("/api/v1/users").json())


def test_user_can_change_own_password_but_not_someone_elses(
    client: TestClient, dev_agent_state: AgentState
) -> None:
    login(client)
    other = client.post(
        "/api/v1/users",
        json={"username": "erin", "password": "x", "description": ""},
        headers=CSRF_HEADERS,
    )
    other_uid = other.json()["uid"]
    # "alice" can log in (she's a devusers.toml fixture) but starts with no
    # `users` row of her own, and — being a fixture, not a real POSIX
    # account — no entry in the fake POSIX user table either. Seed one, the
    # way a real pre-existing account would already exist on the box, then
    # import her as a managed user the same as an admin would (PLAN.md §3).
    dev_agent_state.users.users["alice"] = 5001  # type: ignore[attr-defined]
    imported = client.post("/api/v1/users/import", json={"username": "alice"}, headers=CSRF_HEADERS)
    assert imported.status_code == 200, imported.text
    client.post("/api/v1/auth/logout", headers=CSRF_HEADERS)

    login(client, username="alice", password="alicepass123")
    me = client.get("/api/v1/auth/me").json()

    forbidden = client.post(
        f"/api/v1/users/{other_uid}/password", json={"password": "new"}, headers=CSRF_HEADERS
    )
    assert forbidden.status_code == 403

    allowed = client.post(
        f"/api/v1/users/{me['uid']}/password", json={"password": "new"}, headers=CSRF_HEADERS
    )
    assert allowed.status_code == 200


def test_group_membership_roundtrip(client: TestClient) -> None:
    login(client)
    client.post("/api/v1/users", json={"username": "frank", "password": "x"}, headers=CSRF_HEADERS)
    group = client.post(
        "/api/v1/groups", json={"name": "family", "description": ""}, headers=CSRF_HEADERS
    )
    assert group.status_code == 200, group.text
    gid = group.json()["gid"]

    add = client.post(
        f"/api/v1/groups/{gid}/members", json={"username": "frank"}, headers=CSRF_HEADERS
    )
    assert add.status_code == 200

    remove = client.delete(f"/api/v1/groups/{gid}/members/frank", headers=CSRF_HEADERS)
    assert remove.status_code == 200


def test_volume_register_rejects_non_mountpoint(client: TestClient) -> None:
    login(client)
    resp = client.post(
        "/api/v1/volumes",
        json={"name": "bad", "mountpoint": "/not/a/mount"},
        headers=CSRF_HEADERS,
    )
    assert resp.status_code == 400


def test_share_permission_matrix_end_to_end(
    client: TestClient, dev_agent_state: AgentState, tmp_path: Path
) -> None:
    login(client)
    volume_id = _register_volume(client, tmp_path, dev_agent_state)

    alice = client.post(
        "/api/v1/users", json={"username": "gina", "password": "x"}, headers=CSRF_HEADERS
    ).json()
    group = client.post(
        "/api/v1/groups", json={"name": "staff", "description": ""}, headers=CSRF_HEADERS
    ).json()

    # First apply: smb.service starts (not yet active). ensure_samba_enabled
    # then restarts it again (still fine, FakeSystemd is idempotent).
    _expect_samba_apply(dev_agent_state)
    _expect_ensure_enabled(dev_agent_state)
    share = client.post(
        "/api/v1/shares",
        json={"name": "media", "volume_id": volume_id, "description": ""},
        headers=CSRF_HEADERS,
    )
    assert share.status_code == 200, share.text
    share_id = share.json()["id"]

    _expect_samba_apply(dev_agent_state, already_active=True)
    set_perms = client.put(
        f"/api/v1/shares/{share_id}/permissions",
        json={
            "permissions": [
                {"principal_type": "user", "principal": "gina", "level": "rw"},
                {"principal_type": "group", "principal": "staff", "level": "ro"},
            ],
            "recursive": False,
        },
        headers=CSRF_HEADERS,
    )
    assert set_perms.status_code == 200, set_perms.text
    assert set_perms.json()["job_id"] is None

    matrix = client.get(f"/api/v1/shares/{share_id}/permissions").json()
    assert {(p["principal_type"], p["principal"], p["level"]) for p in matrix} == {
        ("user", "gina", "rw"),
        ("group", "staff", "ro"),
    }

    nasos_conf = Path(dev_agent_state.settings.system_path(NASOS_CONF)).read_text()
    assert "valid users = gina, @staff" in nasos_conf
    assert "read list = @staff" in nasos_conf
    assert "write list = gina" in nasos_conf

    # Revoking one principal updates the matrix without touching the other.
    _expect_samba_apply(dev_agent_state, already_active=True)
    revoke = client.put(
        f"/api/v1/shares/{share_id}/permissions",
        json={
            "permissions": [{"principal_type": "user", "principal": "gina", "level": "rw"}],
            "recursive": False,
        },
        headers=CSRF_HEADERS,
    )
    assert revoke.status_code == 200
    matrix_after = client.get(f"/api/v1/shares/{share_id}/permissions").json()
    assert len(matrix_after) == 1
    assert matrix_after[0]["principal"] == "gina"

    assert alice["username"] == "gina"  # sanity: fixture data wired correctly
    assert group["name"] == "staff"
