from __future__ import annotations

import pytest

from nasos.system.mkfs import MkfsError, argv, create
from nasos.system.runner import FakeRunner


def test_xfs_argv() -> None:
    assert argv("xfs", "volume1", "/dev/nasos_pool1/volume1") == [
        "mkfs.xfs",
        "-L",
        "volume1",
        "/dev/nasos_pool1/volume1",
    ]


def test_ext4_argv() -> None:
    assert argv("ext4", "volume1", "/dev/nasos_pool1/volume1") == [
        "mkfs.ext4",
        "-L",
        "volume1",
        "/dev/nasos_pool1/volume1",
    ]


def test_unsupported_filesystem_raises() -> None:
    with pytest.raises(MkfsError):
        argv("btrfs", "volume1", "/dev/sda1")


async def test_create_runs_and_raises_on_failure() -> None:
    runner = FakeRunner()
    runner.expect(
        ["mkfs.xfs", "-L", "volume1", "/dev/nasos_pool1/volume1"],
        returncode=1,
        stderr="mkfs.xfs: specified blocksize too small",
    )

    with pytest.raises(MkfsError, match="blocksize"):
        await create(runner, "xfs", "volume1", "/dev/nasos_pool1/volume1")
