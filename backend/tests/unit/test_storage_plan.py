"""PLAN.md §12's M4 gate: "plan preview renders exact argv". `build_steps`
is pure and deterministic (system/storage_plan.py's docstring: the web and
the agent both call it, unchanged, from the same `StoragePlanSpec`), so
these tests just assert the exact argv sequence for representative specs.
"""

from __future__ import annotations

from nasos.rpc.schemas import StoragePlanSpec
from nasos.system.storage_plan import (
    DaemonReload,
    EnableStartUnit,
    Restorecon,
    Run,
    WriteDropins,
    WriteTarget,
    WriteUnit,
    array_device,
    build_steps,
    lv_device,
    partition_path,
)


def test_partition_path_appends_digit_for_plain_disk_names() -> None:
    assert partition_path("/dev/sda", 1) == "/dev/sda1"


def test_partition_path_inserts_p_for_names_ending_in_a_digit() -> None:
    assert partition_path("/dev/nvme0n1", 1) == "/dev/nvme0n1p1"
    assert partition_path("/dev/loop0", 1) == "/dev/loop0p1"


def test_basic_single_disk_plan_skips_mdadm_and_uses_the_bare_partition_as_the_pv() -> None:
    spec = StoragePlanSpec(
        volume_name="volume1",
        level="basic",
        filesystem="xfs",
        disk_paths=["/dev/sda"],
        disk_serials=["S1"],
        array_name="volume1",
        vg_name="nasos_volume1",
        lv_name="volume1",
        mountpoint="/volume1",
    )

    steps = build_steps(spec)
    ops = [s.op for s in steps]

    assert ops == [
        Run,
        Run,  # wipe + mkpart for the one disk
        Run,  # pvcreate
        Run,  # vgcreate
        Run,  # lvcreate
        Run,  # mkfs
        WriteUnit,
        WriteTarget,
        WriteDropins,
        DaemonReload,
        EnableStartUnit,
        Restorecon,
    ]
    run_steps = [s for s in steps if s.op == Run]
    assert run_steps[0].argv == ["wipefs", "-a", "/dev/sda"]
    assert run_steps[1].argv == [
        "parted",
        "-s",
        "/dev/sda",
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
    assert run_steps[2].argv == ["pvcreate", "/dev/sda1"]  # no mdadm layer for "basic"
    assert run_steps[3].argv == ["vgcreate", "nasos_volume1", "/dev/sda1"]
    assert run_steps[4].argv == ["lvcreate", "-l", "100%FREE", "-n", "volume1", "nasos_volume1"]
    assert run_steps[5].argv == ["mkfs.xfs", "-L", "volume1", "/dev/nasos_volume1/volume1"]


def test_raid1_two_disk_plan_creates_the_array_before_the_pv() -> None:
    spec = StoragePlanSpec(
        volume_name="pool1",
        level="1",
        filesystem="ext4",
        disk_paths=["/dev/sda", "/dev/sdb"],
        disk_serials=["S1", "S2"],
        array_name="pool1",
        vg_name="nasos_pool1",
        lv_name="pool1",
        mountpoint="/volume3",
    )

    steps = build_steps(spec)
    run_steps = [s for s in steps if s.op == Run]

    # wipe+mkpart for each of 2 disks, then mdadm create, pvcreate, vgcreate,
    # lvcreate, mkfs = 4 + 5 = 9 "run" steps.
    assert len(run_steps) == 9
    assert run_steps[0].argv == ["wipefs", "-a", "/dev/sda"]
    assert run_steps[2].argv == ["wipefs", "-a", "/dev/sdb"]
    assert run_steps[4].argv == [
        "mdadm",
        "--create",
        "/dev/md/pool1",
        "--level=1",
        "--raid-devices=2",
        "--metadata=1.2",
        "--name=pool1",
        "--run",
        "/dev/sda1",
        "/dev/sdb1",
    ]
    assert run_steps[5].argv == ["pvcreate", "/dev/md/pool1"]
    assert run_steps[6].argv == ["vgcreate", "nasos_pool1", "/dev/md/pool1"]
    assert run_steps[7].argv == ["lvcreate", "-l", "100%FREE", "-n", "pool1", "nasos_pool1"]
    assert run_steps[8].argv == ["mkfs.ext4", "-L", "pool1", "/dev/nasos_pool1/pool1"]


def test_build_steps_is_deterministic_for_the_same_spec() -> None:
    spec = StoragePlanSpec(
        volume_name="volume1",
        level="basic",
        filesystem="xfs",
        disk_paths=["/dev/sda"],
        disk_serials=["S1"],
        array_name="volume1",
        vg_name="nasos_volume1",
        lv_name="volume1",
        mountpoint="/volume1",
    )

    first = build_steps(spec)
    second = build_steps(spec)

    assert [(s.op, s.argv) for s in first] == [(s.op, s.argv) for s in second]


def test_device_path_helpers() -> None:
    spec = StoragePlanSpec(
        volume_name="pool1",
        level="5",
        filesystem="xfs",
        disk_paths=["/dev/sda", "/dev/sdb", "/dev/sdc"],
        disk_serials=["S1", "S2", "S3"],
        array_name="pool1",
        vg_name="nasos_pool1",
        lv_name="pool1",
        mountpoint="/volume1",
    )

    assert array_device(spec) == "/dev/md/pool1"
    assert lv_device(spec) == "/dev/nasos_pool1/pool1"
