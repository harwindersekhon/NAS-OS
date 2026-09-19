"""Disk wiping and partitioning: `wipefs -a`, `parted -s ... mklabel gpt
mkpart ... set 1 raid on`, `parted -s -j ... print` for inventory (PLAN.md
§4/§6 decision). Generic over `Runner`, no bespoke Fake — see
system/samba.py's docstring.
"""

from __future__ import annotations

import json

from nasos.system.runner import Runner

PARTITION_LABEL = "nasos"


class PartedError(Exception):
    pass


def wipefs_argv(device: str) -> list[str]:
    return ["wipefs", "-a", device]


def mkpart_argv(device: str) -> list[str]:
    """Single whole-disk GPT partition flagged for RAID membership (the
    `raid on` flag is what makes it show up correctly in `parted print`
    and is what udev/mdadm conventionally expect on a RAID member, even
    though mdadm itself doesn't require it)."""
    return [
        "parted",
        "-s",
        device,
        "mklabel",
        "gpt",
        "mkpart",
        PARTITION_LABEL,
        "1MiB",
        "100%",
        "set",
        "1",
        "raid",
        "on",
    ]


async def wipe(runner: Runner, device: str) -> None:
    result = await runner.run(wipefs_argv(device))
    if not result.ok:
        raise PartedError(result.stderr.strip() or f"wipefs exited {result.returncode}")


async def make_single_partition(runner: Runner, device: str) -> None:
    result = await runner.run(mkpart_argv(device))
    if not result.ok:
        raise PartedError(result.stderr.strip() or f"parted exited {result.returncode}")


async def json_report(runner: Runner, device: str) -> dict[str, object]:
    result = await runner.run(["parted", "-s", "-j", device, "unit", "b", "print"])
    if not result.ok:
        raise PartedError(result.stderr.strip() or f"parted exited {result.returncode}")
    try:
        parsed: dict[str, object] = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise PartedError(f"parted produced invalid JSON: {exc}") from exc
    return parsed
