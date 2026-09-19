"""Protected-device guard (PLAN.md §6): "any device transitively hosting a
mounted FS, swap, /, /boot*, /var/lib/nasos, an active md member, or a PV
in a VG with active LVs -> 409 device_protected". Recomputed fresh from a
just-gathered inventory both before a plan is created and again right
before it executes (agent/handlers/storage.py) — never cached across that
gap, since a disk's protected status can change between the two.

Pure: no DB, no RPC, no imports outside rpc.schemas — the agent imports
this module directly (not over RPC) to redo the exact same check on its
own privileged side before anything destructive runs.

"/", "/boot*" and "/var/lib/nasos" aren't special-cased: they're always
*mounted* filesystems, so the general "transitively hosts a mounted FS"
rule already covers them without needing to know NAS-OS's own paths.
"""

from __future__ import annotations

from nasos.rpc.schemas import DiskNode, StorageInventoryResult


def compute_protected(inventory: StorageInventoryResult) -> set[str]:
    """Mutates `.protected`/`.protected_reason` on every node in
    `inventory.disks` in place (so the UI can show exactly which layer is
    protecting a disk) and returns the set of protected physical disks'
    serials for a quick plan-time membership check.
    """
    lv_vgs = {lv.vg for lv in inventory.lvs}
    protected_pv_paths: set[str] = set()
    for vg in inventory.vgs:
        if vg.name in lv_vgs:
            protected_pv_paths.update(vg.pvs)

    protected_serials: set[str] = set()
    for disk in inventory.disks:
        _walk(disk, protected_pv_paths)
        if disk.protected and disk.serial:
            protected_serials.add(disk.serial)
    return protected_serials


def _walk(node: DiskNode, protected_pv_paths: set[str]) -> str | None:
    """Recursively marks `node` and its whole subtree; returns the reason
    `node` itself ended up protected (its own condition, or the first
    protected descendant's), or None if nothing in this subtree is."""
    reason = _own_reason(node, protected_pv_paths)
    for child in node.children:
        child_reason = _walk(child, protected_pv_paths)
        if reason is None and child_reason is not None:
            reason = child_reason

    if reason is not None:
        node.protected = True
        node.protected_reason = reason
    return reason


def _own_reason(node: DiskNode, protected_pv_paths: set[str]) -> str | None:
    if node.mountpoint:
        return f"mounted at {node.mountpoint}"
    if node.fstype == "swap":
        return "active swap"
    if node.path in protected_pv_paths:
        return "LVM physical volume backing an active logical volume"
    if node.type.startswith("raid"):
        return f"active RAID member ({node.type})"
    return None
