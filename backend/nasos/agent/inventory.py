"""Gathers and merges the storage inventory (PLAN.md §6) from lsblk (the
device tree), smartctl (per physical disk health), mdadm (per-array detail
+ /proc/mdstat resync), and lvm (vg/lv reports) into one
`StorageInventoryResult`. Runs in the agent (privileged) process — the web
process only ever sees the result, over the `storage.inventory` RPC call.

`merge` itself takes already-gathered pieces and does no I/O, so it's
independently unit-testable against hand-built fixture data without a
Runner at all (PLAN.md §12's M4 gate: "fixture tests for inventory
merge").
"""

from __future__ import annotations

from nasos.rpc.schemas import ArrayInfo, DiskNode, LvInfo, StorageInventoryResult, VgInfo
from nasos.system import mdadm as mdadm_adapter
from nasos.system import smart as smart_adapter
from nasos.system.lsblk import list_block_devices
from nasos.system.lvm import report_lvs, report_vgs
from nasos.system.mdstat import MdstatReader
from nasos.system.runner import Runner


async def gather(runner: Runner, mdstat: MdstatReader) -> StorageInventoryResult:
    disks = await list_block_devices(runner)
    vgs = await report_vgs(runner)
    lvs = await report_lvs(runner)
    mdstat_text = await mdstat.read()

    array_details: dict[str, dict[str, str]] = {}
    for disk in disks:
        for md_node in _find_type_prefix(disk, "raid"):
            array_details[md_node.name] = await mdadm_adapter.detail(runner, md_node.path)

    for disk in disks:
        for target in _find_with_serial(disk):
            target.smart = await smart_adapter.read(runner, target.path)

    return merge(
        disks=disks, vgs=vgs, lvs=lvs, mdstat_text=mdstat_text, array_details=array_details
    )


def merge(
    *,
    disks: list[DiskNode],
    vgs: list[VgInfo],
    lvs: list[LvInfo],
    mdstat_text: str,
    array_details: dict[str, dict[str, str]],
) -> StorageInventoryResult:
    """`disks` already carries SMART data attached per-node (the gather
    step above does that in place, since a DiskNode is the natural home for
    "this one device's health") — this function's own job is just turning
    the md arrays found in the device tree into flat `ArrayInfo` summaries
    for display, cross-referencing `array_details`/`mdstat_text`.
    """
    arrays: list[ArrayInfo] = []
    for disk in disks:
        for md_node in _find_type_prefix(disk, "raid"):
            detail = array_details.get(md_node.name, {})
            arrays.append(
                ArrayInfo(
                    path=md_node.path,
                    name=md_node.name,
                    level=detail.get("MD_LEVEL", md_node.type),
                    devices=mdadm_adapter.member_devices(detail),
                    state=detail.get("MD_METADATA", "unknown"),
                    resync_percent=mdadm_adapter.resync_percent(mdstat_text, md_node.name),
                )
            )

    return StorageInventoryResult(disks=disks, arrays=arrays, vgs=vgs, lvs=lvs)


def _find_type_prefix(node: DiskNode, prefix: str) -> list[DiskNode]:
    found = [node] if node.type.startswith(prefix) else []
    for child in node.children:
        found.extend(_find_type_prefix(child, prefix))
    return found


def _find_with_serial(node: DiskNode) -> list[DiskNode]:
    found = [node] if node.serial else []
    for child in node.children:
        found.extend(_find_with_serial(child))
    return found
