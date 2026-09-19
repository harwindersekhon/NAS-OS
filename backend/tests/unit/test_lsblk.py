from __future__ import annotations

import json

from nasos.system.lsblk import LSBLK_ARGV, list_block_devices
from nasos.system.runner import FakeRunner


async def test_parses_top_level_disks_only() -> None:
    runner = FakeRunner()
    runner.expect(
        LSBLK_ARGV,
        stdout=json.dumps(
            {
                "blockdevices": [
                    {
                        "name": "sda",
                        "path": "/dev/sda",
                        "type": "disk",
                        "serial": "S123",
                        "model": "Model X",
                        "wwn": "0x5000",
                        "size": 4000787030016,
                        "rota": True,
                        "tran": "sata",
                        "fstype": None,
                        "mountpoint": None,
                        "uuid": None,
                        "children": [],
                    },
                    {
                        "name": "loop0",
                        "path": "/dev/loop0",
                        "type": "loop",
                        "size": 1024,
                        "children": [],
                    },
                ]
            }
        ),
    )

    disks = await list_block_devices(runner)

    assert len(disks) == 1
    assert disks[0].name == "sda"
    assert disks[0].serial == "S123"
    assert disks[0].size == 4000787030016
    assert disks[0].rota is True
    assert disks[0].transport == "sata"


async def test_parses_nested_children_tree() -> None:
    runner = FakeRunner()
    runner.expect(
        LSBLK_ARGV,
        stdout=json.dumps(
            {
                "blockdevices": [
                    {
                        "name": "sdc",
                        "path": "/dev/sdc",
                        "type": "disk",
                        "serial": "S456",
                        "size": 500107862016,
                        "children": [
                            {
                                "name": "sdc1",
                                "path": "/dev/sdc1",
                                "type": "part",
                                "fstype": "xfs",
                                "mountpoint": "/",
                                "uuid": "1111-2222",
                                "size": 499034120192,
                                "children": [],
                            }
                        ],
                    }
                ]
            }
        ),
    )

    disks = await list_block_devices(runner)

    assert len(disks[0].children) == 1
    child = disks[0].children[0]
    assert child.name == "sdc1"
    assert child.fstype == "xfs"
    assert child.mountpoint == "/"
    assert child.uuid == "1111-2222"


async def test_empty_string_fields_normalize_to_none() -> None:
    runner = FakeRunner()
    runner.expect(
        LSBLK_ARGV,
        stdout=json.dumps(
            {
                "blockdevices": [
                    {
                        "name": "sda",
                        "path": "/dev/sda",
                        "type": "disk",
                        "serial": "",
                        "model": "",
                        "size": 0,
                        "children": [],
                    }
                ]
            }
        ),
    )

    disks = await list_block_devices(runner)

    assert disks[0].serial is None
    assert disks[0].model is None
