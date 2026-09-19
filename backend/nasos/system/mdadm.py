"""mdadm: array detail (`--detail --export`) and array creation (PLAN.md
§4/§6 decision: CLI adapters, `mdadm --create ... --metadata=1.2 --run`).
Generic over `Runner`, no bespoke Fake — see system/samba.py's docstring.
"""

from __future__ import annotations

import re

from nasos.system.runner import Runner

METADATA_VERSION = "1.2"

_RESYNC_RE = re.compile(r"resync\s*=\s*([\d.]+)%")


class MdadmError(Exception):
    pass


def create_argv(*, array_name: str, level: str, devices: list[str]) -> list[str]:
    """`array_name` is the bare name (e.g. "pool1"); the array node itself
    is created at the stable `/dev/md/<name>` path, not a numbered
    `/dev/mdN` that could collide with another array's number after a
    reboot re-scans in a different order.
    """
    return [
        "mdadm",
        "--create",
        f"/dev/md/{array_name}",
        f"--level={level}",
        f"--raid-devices={len(devices)}",
        f"--metadata={METADATA_VERSION}",
        f"--name={array_name}",
        "--run",
        *devices,
    ]


async def create(runner: Runner, *, array_name: str, level: str, devices: list[str]) -> None:
    result = await runner.run(create_argv(array_name=array_name, level=level, devices=devices))
    if not result.ok:
        raise MdadmError(result.stderr.strip() or f"mdadm --create exited {result.returncode}")


async def detail(runner: Runner, array_path: str) -> dict[str, str]:
    """Parses `--detail --export`'s `MD_KEY=value` lines (shell-assignment
    syntax, but never fed to a shell — split on the first `=` per line)."""
    result = await runner.run(["mdadm", "--detail", "--export", array_path])
    if not result.ok:
        raise MdadmError(result.stderr.strip() or f"mdadm --detail exited {result.returncode}")

    parsed: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        parsed[key.strip()] = value.strip()
    return parsed


def member_devices(detail: dict[str, str]) -> list[str]:
    """`mdadm --detail --export` emits one `MD_DEVICE_<name>_DEV=/dev/...`
    key per member (plus a matching `_ROLE` key this doesn't need)."""
    return sorted(v for k, v in detail.items() if k.startswith("MD_DEVICE_") and k.endswith("_DEV"))


def resync_percent(mdstat_text: str, array_name: str) -> float | None:
    """`array_name` is the bare name (e.g. "md127" or "pool1") as it
    appears at the start of its `/proc/mdstat` line."""
    in_array = False
    for line in mdstat_text.splitlines():
        if line.startswith(f"{array_name} ") or line.startswith(f"{array_name}:"):
            in_array = True
            continue
        if in_array:
            match = _RESYNC_RE.search(line)
            if match:
                return float(match.group(1))
            if line.strip() == "" or not line.startswith(" "):
                return None
    return None
