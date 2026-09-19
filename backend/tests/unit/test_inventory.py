"""Fixture tests for the storage inventory merge (PLAN.md §12's M4 gate:
"fixture tests for inventory merge + guard"). `merge` is pure — no Runner
needed — so these build the lsblk/vgs/lvs/mdstat pieces by hand rather than
going through FakeRunner, and a separate end-to-end test exercises the full
`gather()` path with a FakeRunner to prove the pieces are wired correctly.
"""

from __future__ import annotations

import json

from nasos.agent.inventory import gather, merge
from nasos.rpc.schemas import DiskNode, LvInfo, VgInfo
from nasos.system.mdstat import FakeMdstat
from nasos.system.runner import FakeRunner


def _disk(
    name: str, *, serial: str | None = None, children: list[DiskNode] | None = None
) -> DiskNode:
    return DiskNode(
        name=name,
        path=f"/dev/{name}",
        type="disk",
        serial=serial,
        size=1000,
        children=children or [],
    )


def test_merge_attaches_array_summary_for_a_raid_node_found_in_the_tree() -> None:
    md_node = DiskNode(name="md127", path="/dev/md127", type="raid1", size=1000)
    part = DiskNode(name="sda1", path="/dev/sda1", type="part", size=1000, children=[md_node])
    disk = _disk("sda", serial="S1", children=[part])

    result = merge(
        disks=[disk],
        vgs=[],
        lvs=[],
        mdstat_text="md127 : active raid1 sda1[0] sdb1[1]\n      1000 blocks [2/2] [UU]\n",
        array_details={"md127": {"MD_LEVEL": "raid1", "MD_METADATA": "1.2"}},
    )

    assert len(result.arrays) == 1
    array = result.arrays[0]
    assert array.name == "md127"
    assert array.level == "raid1"
    assert array.state == "1.2"
    assert array.resync_percent is None  # not in the "resync = " state in this mdstat fixture


def test_merge_reports_resync_percent_from_mdstat() -> None:
    md_node = DiskNode(name="md127", path="/dev/md127", type="raid1", size=1000)
    disk = _disk("sda", serial="S1", children=[md_node])
    mdstat = (
        "md127 : active raid1 sda1[0] sdb1[1]\n"
        "      1000 blocks [2/2] [UU]\n"
        "      [====>...]  resync = 40.0% (400/1000) finish=1.0min speed=1000K/sec\n"
    )

    result = merge(disks=[disk], vgs=[], lvs=[], mdstat_text=mdstat, array_details={"md127": {}})

    assert result.arrays[0].resync_percent == 40.0


def test_merge_passes_through_disks_vgs_and_lvs_unchanged() -> None:
    disk = _disk("sda", serial="S1")
    vg = VgInfo(name="nasos_pool1", pvs=["/dev/md127"], size=1000, free=0)
    lv = LvInfo(name="volume1", vg="nasos_pool1", path="/dev/nasos_pool1/volume1", size=1000)

    result = merge(disks=[disk], vgs=[vg], lvs=[lv], mdstat_text="", array_details={})

    assert result.disks == [disk]
    assert result.vgs == [vg]
    assert result.lvs == [lv]
    assert result.arrays == []


async def test_gather_wires_lsblk_smart_mdadm_lvm_and_mdstat_together() -> None:
    runner = FakeRunner()
    mdstat = FakeMdstat()
    mdstat.text = "md127 : active raid1 sda1[0]\n      1000 blocks [1/1] [U]\n"

    runner.expect(
        ["lsblk", "-J", "-O", "-b"],
        stdout=json.dumps(
            {
                "blockdevices": [
                    {
                        "name": "sda",
                        "path": "/dev/sda",
                        "type": "disk",
                        "serial": "S1",
                        "size": 4000,
                        "children": [
                            {
                                "name": "sda1",
                                "path": "/dev/sda1",
                                "type": "part",
                                "size": 4000,
                                "children": [
                                    {
                                        "name": "md127",
                                        "path": "/dev/md127",
                                        "type": "raid1",
                                        "size": 4000,
                                        "children": [],
                                    }
                                ],
                            }
                        ],
                    }
                ]
            }
        ),
    )
    runner.expect(
        [
            "vgs",
            "--reportformat",
            "json",
            "--units",
            "b",
            "--nosuffix",
            "-o",
            "vg_name,pv_name,vg_size,vg_free",
        ],
        stdout=json.dumps({"report": [{"vg": []}]}),
    )
    runner.expect(
        [
            "lvs",
            "--reportformat",
            "json",
            "--units",
            "b",
            "--nosuffix",
            "-o",
            "lv_name,vg_name,lv_path,lv_size",
        ],
        stdout=json.dumps({"report": [{"lv": []}]}),
    )
    runner.expect(
        ["mdadm", "--detail", "--export", "/dev/md127"],
        stdout="MD_LEVEL=raid1\nMD_METADATA=1.2\n",
    )
    runner.expect(
        ["smartctl", "--json=c", "-a", "/dev/sda"],
        stdout=json.dumps(
            {"smart_status": {"passed": True}, "ata_smart_attributes": {"table": []}}
        ),
    )

    result = await gather(runner, mdstat)

    assert result.disks[0].serial == "S1"
    assert result.disks[0].smart is not None
    assert result.disks[0].smart.health == "ok"
    assert len(result.arrays) == 1
    assert result.arrays[0].name == "md127"
    assert result.arrays[0].resync_percent is None
