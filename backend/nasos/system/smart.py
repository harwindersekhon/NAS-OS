"""SMART health via `smartctl --json=c` (PLAN.md §4/§6). Generic over
`Runner`, no bespoke Fake — see system/samba.py's docstring.

smartctl's own exit code is a bitmask of unrelated conditions (bit 0:
command-line parse error, bit 2: SMART command failed, bit 3: disk failing
now, bit 4: prefail attributes below threshold, ...), so unlike every other
adapter here a nonzero exit is *not* itself a failure — the JSON payload's
own `smart_status.passed` is the actual health signal, and it's present
even when smartctl's exit code is nonzero for an unrelated bit.
"""

from __future__ import annotations

import json

from nasos.rpc.schemas import DiskSmart, SmartAttribute, StorageHealth
from nasos.system.runner import Runner

SMARTCTL_ARGV = ["smartctl", "--json=c", "-a"]

# Reallocated_Sector_Ct, Current_Pending_Sector, Offline_Uncorrectable: any
# nonzero raw value on these three is the standard early-warning signal
# (a disk that still passes the overall SMART self-check but has started
# relocating sectors), distinct from `smart_status.passed == False`, which
# only fires once the drive's own firmware has given up on it entirely.
_WARNING_ATTRIBUTE_IDS = {5, 197, 198}


class SmartError(Exception):
    pass


async def read(runner: Runner, device: str) -> DiskSmart | None:
    """None for a device smartctl can't get a SMART report from at all
    (USB bridges without SAT passthrough, virtual/loop devices in dev
    mode's loopdisks, ...) — absence of SMART data isn't itself an error
    NAS-OS should surface, just a disk the health column shows as
    "unknown" for.
    """
    result = await runner.run([*SMARTCTL_ARGV, device])
    try:
        parsed = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None

    if "smart_status" not in parsed and "ata_smart_attributes" not in parsed:
        return None

    return DiskSmart(
        health=_health(parsed),
        temperature_c=_temperature(parsed),
        power_on_hours=_power_on_hours(parsed),
        attributes=_attributes(parsed),
    )


def _health(parsed: dict[str, object]) -> StorageHealth:
    status = parsed.get("smart_status")
    passed = status.get("passed") if isinstance(status, dict) else None
    if passed is False:
        return "critical"
    if passed is True:
        return "warning" if _has_warning_attributes(parsed) else "ok"
    return "unknown"


def _has_warning_attributes(parsed: dict[str, object]) -> bool:
    table = parsed.get("ata_smart_attributes")
    entries = table.get("table") if isinstance(table, dict) else None
    if not isinstance(entries, list):
        return False
    for entry in entries:
        if not isinstance(entry, dict) or int(entry.get("id", 0)) not in _WARNING_ATTRIBUTE_IDS:
            continue
        raw = entry.get("raw")
        raw_value = raw.get("value") if isinstance(raw, dict) else None
        if isinstance(raw_value, int | float) and raw_value > 0:
            return True
    return False


def _temperature(parsed: dict[str, object]) -> float | None:
    temp = parsed.get("temperature")
    if isinstance(temp, dict):
        current = temp.get("current")
        if isinstance(current, int | float):
            return float(current)
    return None


def _power_on_hours(parsed: dict[str, object]) -> int | None:
    power = parsed.get("power_on_time")
    if isinstance(power, dict):
        hours = power.get("hours")
        if isinstance(hours, int | float):
            return int(hours)
    return None


def _attributes(parsed: dict[str, object]) -> list[SmartAttribute]:
    table = parsed.get("ata_smart_attributes")
    if not isinstance(table, dict):
        return []
    entries = table.get("table")
    if not isinstance(entries, list):
        return []

    attributes: list[SmartAttribute] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        raw = entry.get("raw")
        raw_string = raw.get("string", "") if isinstance(raw, dict) else ""
        attributes.append(
            SmartAttribute(
                id=int(entry.get("id", 0)),
                name=str(entry.get("name", "")),
                value=int(entry.get("value", 0)),
                worst=int(entry.get("worst", 0)),
                threshold=int(entry.get("thresh", 0)),
                raw=str(raw_string),
            )
        )
    return attributes
