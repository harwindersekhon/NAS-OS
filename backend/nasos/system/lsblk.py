"""Block device inventory via `lsblk -J -O -b` (PLAN.md §4 decision: CLI
JSON adapters rather than blivet/udisks2). Generic over `Runner`, no
bespoke Fake (see system/samba.py's docstring for the rationale) — dev mode
gets useful behaviour for free via `FakeRunner`.

lsblk's own `-J` output is already a nested tree (`blockdevices` ->
`children` -> `children` -> ...) that walks disk -> partition -> md member
-> PV -> LV -> filesystem exactly the way the guard needs to (system/
storage_guard... see services/storage/guard.py), so this adapter just
types that shape rather than flattening and re-nesting it.
"""

from __future__ import annotations

import json

from nasos.rpc.schemas import DiskNode
from nasos.system.runner import Runner

# -O (all columns) is what actually includes SERIAL/WWN/TRAN; the base set
# omits them. -b reports sizes in bytes, not "1.8T" strings.
LSBLK_ARGV = ["lsblk", "-J", "-O", "-b"]


class LsblkError(Exception):
    pass


async def list_block_devices(runner: Runner) -> list[DiskNode]:
    """Returns only top-level TYPE=disk entries (each with its full nested
    children tree) — lsblk's `blockdevices` array can also contain loop/rom
    devices at the top level, which NAS-OS's storage inventory has no use
    for and would otherwise show up as bogus "disks" with no serial.
    """
    result = await runner.run(LSBLK_ARGV)
    if not result.ok:
        raise LsblkError(result.stderr.strip() or f"lsblk exited {result.returncode}")

    try:
        parsed = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise LsblkError(f"lsblk produced invalid JSON: {exc}") from exc

    return [
        _to_node(entry) for entry in parsed.get("blockdevices", []) if entry.get("type") == "disk"
    ]


def _to_node(entry: dict[str, object]) -> DiskNode:
    children_raw = entry.get("children") or []
    assert isinstance(children_raw, list)
    size_raw = entry.get("size")
    return DiskNode(
        name=str(entry.get("name", "")),
        path=str(entry.get("path", "")),
        type=str(entry.get("type", "")),
        serial=_str_or_none(entry.get("serial")),
        model=_str_or_none(entry.get("model")),
        wwn=_str_or_none(entry.get("wwn")),
        size=int(str(size_raw)) if size_raw is not None else 0,
        rota=bool(entry.get("rota", False)),
        transport=_str_or_none(entry.get("tran")) or "unknown",
        fstype=_str_or_none(entry.get("fstype")),
        mountpoint=_str_or_none(entry.get("mountpoint")),
        uuid=_str_or_none(entry.get("uuid")),
        children=[_to_node(child) for child in children_raw],
    )


def _str_or_none(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
