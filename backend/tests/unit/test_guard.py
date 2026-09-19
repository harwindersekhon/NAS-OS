"""Fixture tests for the protected-device guard (PLAN.md §12's M4 gate:
"fixture tests for inventory merge + guard"; §6: "any device transitively
hosting a mounted FS, swap, /, /boot*, /var/lib/nasos, an active md member,
or a PV in a VG with active LVs").
"""

from __future__ import annotations

from nasos.rpc.schemas import DiskNode, LvInfo, StorageInventoryResult, VgInfo
from nasos.services.storage.guard import compute_protected


def _inventory(
    disks: list[DiskNode], *, vgs: list[VgInfo] | None = None, lvs: list[LvInfo] | None = None
) -> StorageInventoryResult:
    return StorageInventoryResult(disks=disks, arrays=[], vgs=vgs or [], lvs=lvs or [])


def test_spare_unpartitioned_disk_is_unprotected() -> None:
    disk = DiskNode(name="sda", path="/dev/sda", type="disk", serial="S1", size=1000)

    protected = compute_protected(_inventory([disk]))

    assert protected == set()
    assert disk.protected is False


def test_disk_with_mounted_root_partition_is_protected() -> None:
    root_part = DiskNode(
        name="sdc2", path="/dev/sdc2", type="part", size=1000, fstype="xfs", mountpoint="/"
    )
    disk = DiskNode(
        name="sdc", path="/dev/sdc", type="disk", serial="S3", size=2000, children=[root_part]
    )

    protected = compute_protected(_inventory([disk]))

    assert protected == {"S3"}
    assert disk.protected is True
    assert "mounted at /" in (disk.protected_reason or "")
    assert root_part.protected is True


def test_disk_with_active_swap_partition_is_protected() -> None:
    swap_part = DiskNode(name="sdd1", path="/dev/sdd1", type="part", size=1000, fstype="swap")
    disk = DiskNode(
        name="sdd", path="/dev/sdd", type="disk", serial="S4", size=1000, children=[swap_part]
    )

    protected = compute_protected(_inventory([disk]))

    assert protected == {"S4"}
    assert "swap" in (disk.protected_reason or "")


def test_disk_that_is_an_active_md_member_is_protected_even_without_a_mount() -> None:
    md_node = DiskNode(name="md127", path="/dev/md127", type="raid1", size=1000)
    part = DiskNode(name="sda1", path="/dev/sda1", type="part", size=1000, children=[md_node])
    disk = DiskNode(
        name="sda", path="/dev/sda", type="disk", serial="S1", size=1000, children=[part]
    )

    protected = compute_protected(_inventory([disk]))

    assert protected == {"S1"}
    assert "RAID" in (disk.protected_reason or "")


def test_disk_backing_a_pv_in_a_vg_with_an_active_lv_is_protected() -> None:
    disk = DiskNode(name="sda", path="/dev/sda", type="disk", serial="S1", size=1000)
    vg = VgInfo(name="nasos_pool1", pvs=["/dev/sda"], size=1000, free=0)
    lv = LvInfo(name="volume1", vg="nasos_pool1", path="/dev/nasos_pool1/volume1", size=1000)

    protected = compute_protected(_inventory([disk], vgs=[vg], lvs=[lv]))

    assert protected == {"S1"}
    assert "physical volume" in (disk.protected_reason or "")


def test_pv_in_a_vg_with_no_lvs_is_not_protected() -> None:
    disk = DiskNode(name="sda", path="/dev/sda", type="disk", serial="S1", size=1000)
    vg = VgInfo(name="nasos_pool1", pvs=["/dev/sda"], size=1000, free=1000)

    protected = compute_protected(_inventory([disk], vgs=[vg]))

    assert protected == set()


def test_two_disks_only_the_mounted_one_is_protected() -> None:
    mounted_part = DiskNode(
        name="sdc1", path="/dev/sdc1", type="part", size=1000, fstype="xfs", mountpoint="/"
    )
    mounted_disk = DiskNode(
        name="sdc",
        path="/dev/sdc",
        type="disk",
        serial="S_MOUNTED",
        size=1000,
        children=[mounted_part],
    )
    spare_disk = DiskNode(name="sda", path="/dev/sda", type="disk", serial="S_SPARE", size=1000)

    protected = compute_protected(_inventory([mounted_disk, spare_disk]))

    assert protected == {"S_MOUNTED"}
    assert spare_disk.protected is False
