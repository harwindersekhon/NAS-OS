"""API-level tests for storage/* (Milestone 4): the two-phase plan/execute
flow, the confirm-token/typed-confirmation checks, and the guard blocking
a protected disk at plan-creation time.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from nasos.agent.state import AgentState

from ..conftest import CSRF_HEADERS, login

SPARE_DISK_SERIAL = "NASOS-SIM-0001"
BOOT_DISK_SERIAL = "NASOS-SIM-0003"


def test_get_inventory_returns_seeded_disks(client: TestClient) -> None:
    login(client)
    resp = client.get("/api/v1/storage/inventory")
    assert resp.status_code == 200, resp.text
    serials = {d["serial"] for d in resp.json()["disks"]}
    assert serials == {"NASOS-SIM-0001", "NASOS-SIM-0002", "NASOS-SIM-0003"}


def test_create_plan_renders_exact_argv_and_single_disk_confirm_text(
    client: TestClient,
    dev_agent_state: AgentState,  # noqa: ARG001
) -> None:
    login(client)
    resp = client.post(
        "/api/v1/storage/plans",
        json={
            "volume_name": "volume1",
            "level": "basic",
            "filesystem": "xfs",
            "disk_serials": [SPARE_DISK_SERIAL],
        },
        headers=CSRF_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["confirm_text"] == SPARE_DISK_SERIAL
    run_steps = [s for s in body["steps"] if s["op"] == "run"]
    assert run_steps[0]["argv"] == ["wipefs", "-a", "/dev/sda"]
    assert run_steps[-1]["argv"] == ["mkfs.xfs", "-L", "volume1", "/dev/nasos_volume1/volume1"]
    assert "ERASE ALL DATA" in body["data_loss_summary"]


def test_create_plan_with_two_disks_requires_typing_erase(client: TestClient) -> None:
    login(client)
    resp = client.post(
        "/api/v1/storage/plans",
        json={
            "volume_name": "pool1",
            "level": "1",
            "filesystem": "xfs",
            "disk_serials": [SPARE_DISK_SERIAL, "NASOS-SIM-0002"],
        },
        headers=CSRF_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["confirm_text"] == "ERASE"


def test_create_plan_rejects_a_protected_disk(client: TestClient) -> None:
    login(client)
    resp = client.post(
        "/api/v1/storage/plans",
        json={
            "volume_name": "volume1",
            "level": "basic",
            "filesystem": "xfs",
            "disk_serials": [BOOT_DISK_SERIAL],
        },
        headers=CSRF_HEADERS,
    )
    assert resp.status_code == 400
    assert "protected" in resp.json()["detail"]


def test_create_plan_rejects_too_few_disks_for_raid_level(client: TestClient) -> None:
    login(client)
    resp = client.post(
        "/api/v1/storage/plans",
        json={
            "volume_name": "pool1",
            "level": "5",
            "filesystem": "xfs",
            "disk_serials": [SPARE_DISK_SERIAL, "NASOS-SIM-0002"],
        },
        headers=CSRF_HEADERS,
    )
    assert resp.status_code == 400
    assert "not_enough_disks" in resp.json()["detail"] or "level 5" in resp.json()["detail"]


def test_execute_plan_rejects_wrong_confirm_token(client: TestClient) -> None:
    login(client)
    plan = client.post(
        "/api/v1/storage/plans",
        json={
            "volume_name": "volume1",
            "level": "basic",
            "filesystem": "xfs",
            "disk_serials": [SPARE_DISK_SERIAL],
        },
        headers=CSRF_HEADERS,
    ).json()

    resp = client.post(
        f"/api/v1/storage/plans/{plan['id']}/execute",
        json={"confirm_token": "not-the-real-token", "typed_confirmation": plan["confirm_text"]},
        headers=CSRF_HEADERS,
    )
    assert resp.status_code == 400
    assert "confirm" in resp.json()["detail"]


def test_execute_plan_rejects_wrong_typed_confirmation(client: TestClient) -> None:
    login(client)
    plan = client.post(
        "/api/v1/storage/plans",
        json={
            "volume_name": "volume1",
            "level": "basic",
            "filesystem": "xfs",
            "disk_serials": [SPARE_DISK_SERIAL],
        },
        headers=CSRF_HEADERS,
    ).json()

    resp = client.post(
        f"/api/v1/storage/plans/{plan['id']}/execute",
        json={"confirm_token": plan["confirm_token"], "typed_confirmation": "not the right text"},
        headers=CSRF_HEADERS,
    )
    assert resp.status_code == 400
    assert "type" in resp.json()["detail"]


def test_execute_plan_rejects_unknown_plan_id(client: TestClient) -> None:
    login(client)
    resp = client.post(
        "/api/v1/storage/plans/does-not-exist/execute",
        json={"confirm_token": "x", "typed_confirmation": "ERASE"},
        headers=CSRF_HEADERS,
    )
    assert resp.status_code == 400
    assert "not found" in resp.json()["detail"]


def test_execute_plan_with_correct_confirmation_starts_a_job(client: TestClient) -> None:
    login(client)
    plan = client.post(
        "/api/v1/storage/plans",
        json={
            "volume_name": "volume1",
            "level": "basic",
            "filesystem": "xfs",
            "disk_serials": [SPARE_DISK_SERIAL],
        },
        headers=CSRF_HEADERS,
    ).json()

    resp = client.post(
        f"/api/v1/storage/plans/{plan['id']}/execute",
        json={"confirm_token": plan["confirm_token"], "typed_confirmation": plan["confirm_text"]},
        headers=CSRF_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["job_id"]


def test_non_admin_cannot_create_plans(client: TestClient) -> None:
    login(client, username="alice", password="alicepass123")
    resp = client.post(
        "/api/v1/storage/plans",
        json={
            "volume_name": "volume1",
            "level": "basic",
            "filesystem": "xfs",
            "disk_serials": [SPARE_DISK_SERIAL],
        },
        headers=CSRF_HEADERS,
    )
    assert resp.status_code == 403
