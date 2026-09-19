"""Pure, deterministic plan-step builder (PLAN.md §6's default
orchestration: md + LVM + XFS/ext4, single-disk "basic" skips md).

Called identically by the web process (to render a plan preview) and,
unchanged, by the agent (to actually execute) — same `StoragePlanSpec` in,
the same ordered steps out, so "plan preview renders exact argv" is a real
guarantee rather than two hand-synced implementations that could drift.

No I/O happens here: each `PlanStep` is `{description, op, argv}`; the
agent's executor (agent/handlers/storage.py) is what actually runs `argv`
through a `Runner` (for `op == "run"`) or calls the matching system/
adapter directly (for the unit-file/systemd ops) — this module only
decides *what* runs and in *what order*, never *how*.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from nasos.rpc.schemas import StoragePlanSpec
from nasos.system.lvm import lvcreate_full_free_argv, pvcreate_argv, vgcreate_argv
from nasos.system.mdadm import create_argv as mdadm_create_argv
from nasos.system.mkfs import argv as mkfs_argv
from nasos.system.parted import mkpart_argv, wipefs_argv

WriteUnit = "write_mount_unit"
WriteTarget = "write_target"
WriteDropins = "write_dropins"
DaemonReload = "daemon_reload"
EnableStartUnit = "enable_start_unit"
Restorecon = "restorecon"
Run = "run"


@dataclass
class PlanStep:
    description: str
    op: str
    argv: list[str] = field(default_factory=list)


def partition_path(disk: str, number: int) -> str:
    """/dev/sda -> /dev/sda1, but /dev/nvme0n1 -> /dev/nvme0n1p1 (and
    similarly for any other disk name that itself ends in a digit, e.g.
    loop devices used by `make loopdisks`)."""
    if disk and disk[-1].isdigit():
        return f"{disk}p{number}"
    return f"{disk}{number}"


def array_device(spec: StoragePlanSpec) -> str:
    return f"/dev/md/{spec.array_name}"


def lv_device(spec: StoragePlanSpec) -> str:
    return f"/dev/{spec.vg_name}/{spec.lv_name}"


def build_steps(spec: StoragePlanSpec) -> list[PlanStep]:
    steps: list[PlanStep] = []

    for disk in spec.disk_paths:
        steps.append(PlanStep(f"Wipe existing signatures on {disk}", Run, wipefs_argv(disk)))
        steps.append(PlanStep(f"Create partition table on {disk}", Run, mkpart_argv(disk)))

    partitions = [partition_path(disk, 1) for disk in spec.disk_paths]

    if spec.level == "basic":
        pv_device = partitions[0]
    else:
        steps.append(
            PlanStep(
                f"Create RAID {spec.level} array {spec.array_name}",
                Run,
                mdadm_create_argv(array_name=spec.array_name, level=spec.level, devices=partitions),
            )
        )
        pv_device = array_device(spec)

    steps.append(
        PlanStep(f"Initialize physical volume on {pv_device}", Run, pvcreate_argv(pv_device))
    )
    steps.append(
        PlanStep(f"Create volume group {spec.vg_name}", Run, vgcreate_argv(spec.vg_name, pv_device))
    )
    steps.append(
        PlanStep(
            f"Create logical volume {spec.lv_name}",
            Run,
            lvcreate_full_free_argv(spec.vg_name, spec.lv_name),
        )
    )
    steps.append(
        PlanStep(
            f"Create {spec.filesystem} filesystem",
            Run,
            mkfs_argv(spec.filesystem, spec.lv_name, lv_device(spec)),
        )
    )
    steps.append(PlanStep(f"Create mount unit for {spec.mountpoint}", WriteUnit))
    steps.append(PlanStep("Ensure nasos-volumes.target exists", WriteTarget))
    steps.append(PlanStep("Update service drop-ins (RequiresMountsFor)", WriteDropins))
    steps.append(PlanStep("Reload systemd", DaemonReload))
    steps.append(PlanStep(f"Enable and start mount for {spec.mountpoint}", EnableStartUnit))
    steps.append(PlanStep(f"Apply SELinux context to {spec.mountpoint}", Restorecon))
    return steps
