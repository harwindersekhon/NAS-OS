from __future__ import annotations

from nasos.system.mdadm import create, create_argv, detail, member_devices, resync_percent
from nasos.system.runner import FakeRunner


def test_create_argv_matches_plan_md_exact_shape() -> None:
    argv = create_argv(array_name="pool1", level="1", devices=["/dev/sda1", "/dev/sdb1"])

    assert argv == [
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


async def test_create_runs_the_exact_argv() -> None:
    runner = FakeRunner()
    runner.expect(create_argv(array_name="pool1", level="1", devices=["/dev/sda1", "/dev/sdb1"]))

    await create(runner, array_name="pool1", level="1", devices=["/dev/sda1", "/dev/sdb1"])

    assert runner.calls == [
        create_argv(array_name="pool1", level="1", devices=["/dev/sda1", "/dev/sdb1"])
    ]


async def test_detail_parses_export_style_output() -> None:
    runner = FakeRunner()
    runner.expect(
        ["mdadm", "--detail", "--export", "/dev/md/pool1"],
        stdout=(
            "MD_LEVEL=raid1\n"
            "MD_DEVICES=2\n"
            "MD_METADATA=1.2\n"
            "MD_DEVICE_dev_sda1_DEV=/dev/sda1\n"
            "MD_DEVICE_dev_sda1_ROLE=active\n"
            "MD_DEVICE_dev_sdb1_DEV=/dev/sdb1\n"
            "MD_DEVICE_dev_sdb1_ROLE=active\n"
        ),
    )

    result = await detail(runner, "/dev/md/pool1")

    assert result["MD_LEVEL"] == "raid1"
    assert member_devices(result) == ["/dev/sda1", "/dev/sdb1"]


def test_resync_percent_extracts_the_active_array() -> None:
    mdstat = (
        "Personalities : [raid1]\n"
        "md127 : active raid1 sdb1[1] sda1[0]\n"
        "      4194304 blocks super 1.2 [2/2] [UU]\n"
        "      [==========>..........]  resync = 52.3% (2194304/4194304)"
        " finish=1.2min speed=12345K/sec\n"
        "\n"
        "unused devices: <none>\n"
    )

    assert resync_percent(mdstat, "md127") == 52.3


def test_resync_percent_none_when_not_resyncing() -> None:
    mdstat = "md127 : active raid1 sdb1[1] sda1[0]\n      4194304 blocks super 1.2 [2/2] [UU]\n"

    assert resync_percent(mdstat, "md127") is None


def test_resync_percent_none_for_unknown_array() -> None:
    assert resync_percent("", "md999") is None
