from __future__ import annotations

import json

import pytest

from nasos.system.parted import (
    PartedError,
    json_report,
    make_single_partition,
    mkpart_argv,
    wipe,
    wipefs_argv,
)
from nasos.system.runner import FakeRunner


def test_wipefs_argv() -> None:
    assert wipefs_argv("/dev/sda") == ["wipefs", "-a", "/dev/sda"]


def test_mkpart_argv_matches_plan_md_exact_shape() -> None:
    assert mkpart_argv("/dev/sda") == [
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


async def test_wipe_runs_and_raises_on_failure() -> None:
    runner = FakeRunner()
    runner.expect(["wipefs", "-a", "/dev/sda"], returncode=1, stderr="permission denied")

    with pytest.raises(PartedError, match="permission denied"):
        await wipe(runner, "/dev/sda")


async def test_make_single_partition_runs_expected_argv() -> None:
    runner = FakeRunner()
    runner.expect(mkpart_argv("/dev/sda"))

    await make_single_partition(runner, "/dev/sda")

    assert runner.calls == [mkpart_argv("/dev/sda")]


async def test_json_report_parses_output() -> None:
    runner = FakeRunner()
    runner.expect(
        ["parted", "-s", "-j", "/dev/sda", "unit", "b", "print"],
        stdout=json.dumps({"disk": {"path": "/dev/sda", "size": "4000787030016B"}}),
    )

    report = await json_report(runner, "/dev/sda")

    assert report["disk"]["path"] == "/dev/sda"  # type: ignore[index]
