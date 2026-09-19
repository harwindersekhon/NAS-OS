from __future__ import annotations

import json

from nasos.system.lvm import (
    lvcreate_full_free,
    lvcreate_full_free_argv,
    pvcreate,
    pvcreate_argv,
    report_lvs,
    report_vgs,
    vgcreate,
    vgcreate_argv,
)
from nasos.system.runner import FakeRunner


def test_argv_helpers_match_plan_md_exact_shape() -> None:
    assert pvcreate_argv("/dev/md/pool1") == ["pvcreate", "/dev/md/pool1"]
    assert vgcreate_argv("nasos_pool1", "/dev/md/pool1") == [
        "vgcreate",
        "nasos_pool1",
        "/dev/md/pool1",
    ]
    assert lvcreate_full_free_argv("nasos_pool1", "volume1") == [
        "lvcreate",
        "-l",
        "100%FREE",
        "-n",
        "volume1",
        "nasos_pool1",
    ]


async def test_pvcreate_vgcreate_lvcreate_run_expected_argv() -> None:
    runner = FakeRunner()
    runner.expect(["pvcreate", "/dev/md/pool1"])
    runner.expect(["vgcreate", "nasos_pool1", "/dev/md/pool1"])
    runner.expect(["lvcreate", "-l", "100%FREE", "-n", "volume1", "nasos_pool1"])

    await pvcreate(runner, "/dev/md/pool1")
    await vgcreate(runner, "nasos_pool1", "/dev/md/pool1")
    await lvcreate_full_free(runner, "nasos_pool1", "volume1")

    assert runner.calls == [
        ["pvcreate", "/dev/md/pool1"],
        ["vgcreate", "nasos_pool1", "/dev/md/pool1"],
        ["lvcreate", "-l", "100%FREE", "-n", "volume1", "nasos_pool1"],
    ]


async def test_report_vgs_groups_multiple_pvs_under_one_vg() -> None:
    runner = FakeRunner()
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
        stdout=json.dumps(
            {
                "report": [
                    {
                        "vg": [
                            {
                                "vg_name": "nasos_pool1",
                                "pv_name": "/dev/md/pool1",
                                "vg_size": "4000000000",
                                "vg_free": "0",
                            }
                        ]
                    }
                ]
            }
        ),
    )

    vgs = await report_vgs(runner)

    assert len(vgs) == 1
    assert vgs[0].name == "nasos_pool1"
    assert vgs[0].pvs == ["/dev/md/pool1"]
    assert vgs[0].size == 4000000000
    assert vgs[0].free == 0


async def test_report_lvs_parses_rows() -> None:
    runner = FakeRunner()
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
        stdout=json.dumps(
            {
                "report": [
                    {
                        "lv": [
                            {
                                "lv_name": "volume1",
                                "vg_name": "nasos_pool1",
                                "lv_path": "/dev/nasos_pool1/volume1",
                                "lv_size": "4000000000",
                            }
                        ]
                    }
                ]
            }
        ),
    )

    lvs = await report_lvs(runner)

    assert len(lvs) == 1
    assert lvs[0].name == "volume1"
    assert lvs[0].vg == "nasos_pool1"
    assert lvs[0].path == "/dev/nasos_pool1/volume1"
    assert lvs[0].size == 4000000000
