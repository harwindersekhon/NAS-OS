"""Integration-style tests for storage.* RPC methods: request -> Dispatcher
-> handler -> Fake adapters, mirroring test_m2_handlers.py's shape.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import cast

import pytest

from nasos.agent import handlers  # noqa: F401  (populates the dispatcher registry)
from nasos.agent.dispatcher import Dispatcher
from nasos.agent.state import AgentState, build_state
from nasos.config import Mode, Settings
from nasos.rpc.schemas import RpcRequest
from nasos.system.runner import FakeRunner

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"

SPARE_DISK_SERIAL = "NASOS-SIM-0001"
SPARE_DISK_PATH = "/dev/sda"
BOOT_DISK_SERIAL = "NASOS-SIM-0003"


@pytest.fixture
def state(tmp_path: Path) -> AgentState:
    settings = Settings(
        mode=Mode.test,
        devusers_file=str(FIXTURES_DIR / "devusers.toml"),
        state_dir=str(tmp_path / "state"),
        devdata_dir=str(tmp_path / "devdata"),
        volumes_root="/volume",
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


# --- storage.inventory -----------------------------------------------------


async def test_inventory_returns_seeded_dev_disks(dispatcher: Dispatcher) -> None:
    result = await call(dispatcher, "storage.inventory")

    disks = result["disks"]
    assert isinstance(disks, list)
    serials = {d["serial"] for d in disks}  # type: ignore[union-attr]
    assert serials == {"NASOS-SIM-0001", "NASOS-SIM-0002", "NASOS-SIM-0003"}


async def test_inventory_marks_boot_disk_protected(dispatcher: Dispatcher) -> None:
    result = await call(dispatcher, "storage.inventory")

    disks = cast("list[dict[str, object]]", result["disks"])
    by_serial = {d["serial"]: d for d in disks}
    assert by_serial["NASOS-SIM-0003"]["protected"] is True  # type: ignore[index]
    assert by_serial["NASOS-SIM-0001"]["protected"] is False  # type: ignore[index]


# --- storage.execute_plan ---------------------------------------------------


def _spec(mountpoint: str) -> dict[str, object]:
    return {
        "volume_name": "volume1",
        "level": "basic",
        "filesystem": "xfs",
        "disk_paths": [SPARE_DISK_PATH],
        "disk_serials": [SPARE_DISK_SERIAL],
        "array_name": "volume1",
        "vg_name": "nasos_volume1",
        "lv_name": "volume1",
        "mountpoint": mountpoint,
    }


def _seed_execute_expectations(runner: FakeRunner, *, mountpoint: str, unit_dir: str) -> None:
    runner.expect(["wipefs", "-a", SPARE_DISK_PATH])
    runner.expect(
        [
            "parted",
            "-s",
            SPARE_DISK_PATH,
            "mklabel",
            "gpt",
            "mkpart",
            "nasos",
            "1MiB",
            "100%",
            "set",
            "1",
            "raid",
            "on",
        ]
    )
    runner.expect(["pvcreate", f"{SPARE_DISK_PATH}1"])
    runner.expect(["vgcreate", "nasos_volume1", f"{SPARE_DISK_PATH}1"])
    runner.expect(["lvcreate", "-l", "100%FREE", "-n", "volume1", "nasos_volume1"])
    runner.expect(["mkfs.xfs", "-L", "volume1", "/dev/nasos_volume1/volume1"])
    runner.expect(
        ["blkid", "-o", "value", "-s", "UUID", "/dev/nasos_volume1/volume1"],
        stdout="11111111-2222-3333-4444-555555555555\n",
    )
    runner.expect(["systemd-escape", "-p", "--suffix=mount", mountpoint], stdout="volume1.mount\n")
    runner.expect(["restorecon", f"{unit_dir}/volume1.mount"])
    runner.expect(["restorecon", f"{unit_dir}/nasos-volumes.target"])
    for service in ("smb.service", "nfs-server.service", "vsftpd.service"):
        runner.expect(["restorecon", f"{unit_dir}/{service}.d/50-nasos-volumes.conf"])
    runner.expect(["restorecon", "-R", mountpoint])


async def test_execute_plan_runs_every_step_and_reports_the_new_volume(
    state: AgentState, dispatcher: Dispatcher, tmp_path: Path
) -> None:
    mountpoint = str(tmp_path / "devdata" / "volume" / "volume1")
    unit_dir = str(tmp_path / "devdata" / "etc" / "systemd" / "system")
    runner = cast(FakeRunner, state.runner)
    _seed_execute_expectations(runner, mountpoint=mountpoint, unit_dir=unit_dir)

    result = await call(
        dispatcher,
        "storage.execute_plan",
        spec=_spec(mountpoint),
        expected_sizes={SPARE_DISK_SERIAL: 4_000_787_030_016},
        managed_mountpoints=[mountpoint],
    )
    job_id = result["job_id"]
    assert job_id

    # The job runs as a fire-and-forget asyncio task; give the event loop a
    # turn to let it actually finish before asserting on its final state.
    for _ in range(50):
        await asyncio.sleep(0)
    jobs = {j["id"]: j for j in state.jobs.list()}
    assert jobs[job_id]["status"] == "done"

    info = json.loads(jobs[job_id]["message"])  # type: ignore[arg-type]
    assert info["name"] == "volume1"
    assert info["mountpoint"] == mountpoint
    assert info["device"] == "/dev/nasos_volume1/volume1"
    assert info["uuid"] == "11111111-2222-3333-4444-555555555555"
    assert info["raid_level"] == "basic"
    assert info["array_name"] is None
    assert info["disk_serials"] == [SPARE_DISK_SERIAL]

    # PLAN.md §6: "/volumeN/@nasos/tmp"
    assert (Path(mountpoint) / "@nasos" / "tmp").is_dir()


async def test_execute_plan_aborts_on_now_protected_disk(
    state: AgentState, dispatcher: Dispatcher, tmp_path: Path
) -> None:
    mountpoint = str(tmp_path / "devdata" / "volume" / "boot-attempt")
    spec = _spec(mountpoint)
    spec["disk_paths"] = ["/dev/sdc"]
    spec["disk_serials"] = [BOOT_DISK_SERIAL]

    result = await call(
        dispatcher,
        "storage.execute_plan",
        spec=spec,
        expected_sizes={BOOT_DISK_SERIAL: 500_107_862_016},
        managed_mountpoints=[mountpoint],
    )
    job_id = result["job_id"]

    for _ in range(50):
        await asyncio.sleep(0)
    jobs = {j["id"]: j for j in state.jobs.list()}
    assert jobs[job_id]["status"] == "failed"
    assert "protected" in jobs[job_id]["message"]  # type: ignore[operator]


async def test_execute_plan_aborts_on_size_mismatch(
    state: AgentState, dispatcher: Dispatcher, tmp_path: Path
) -> None:
    mountpoint = str(tmp_path / "devdata" / "volume" / "volume1")
    result = await call(
        dispatcher,
        "storage.execute_plan",
        spec=_spec(mountpoint),
        expected_sizes={SPARE_DISK_SERIAL: 1},  # doesn't match the seeded 4 TB disk
        managed_mountpoints=[mountpoint],
    )
    job_id = result["job_id"]

    for _ in range(50):
        await asyncio.sleep(0)
    jobs = {j["id"]: j for j in state.jobs.list()}
    assert jobs[job_id]["status"] == "failed"
    assert "bytes" in jobs[job_id]["message"]  # type: ignore[operator]
