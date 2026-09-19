"""storage.* RPC methods (PLAN.md §6, Milestone 4).

`storage.execute_plan` re-derives everything safety-critical from scratch
on this (privileged) side rather than trusting the web's plan preview:
fresh inventory, a fresh guard check, and current device paths resolved by
serial (paths can shift between plan-preview and execute, e.g. after a
hotplug event) — the web's `expected_sizes` is only an extra tripwire on
top of that, not the primary check.
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

from nasos.agent import inventory
from nasos.agent.dispatcher import handler
from nasos.agent.state import AgentState
from nasos.rpc.schemas import (
    DiskNode,
    JobStartedResult,
    RpcContext,
    RpcException,
    StorageExecutePlanParams,
    StorageInventoryParams,
    StorageInventoryResult,
    StoragePlanSpec,
)
from nasos.services.storage.guard import compute_protected
from nasos.system.managedfile import ManagedFile
from nasos.system.mount_units import (
    VOLUMES_TARGET_UNIT_PATH,
    mount_unit_name,
    mount_unit_path,
    render_mount_unit,
    render_service_dropin,
    render_volumes_target,
    service_dropin_path,
)
from nasos.system.storage_plan import (
    DaemonReload,
    EnableStartUnit,
    Restorecon,
    Run,
    WriteDropins,
    WriteTarget,
    WriteUnit,
    build_steps,
    lv_device,
)

if TYPE_CHECKING:
    from nasos.agent.jobs import JobHandle

# The one thing NAS-OS's own unit files should ever wire into — kept fixed
# rather than reading them from any elsewhere-defined constant table, since
# these three service units are the whole set PLAN.md §6 names.
_DROPIN_SERVICES = ("smb.service", "nfs-server.service", "vsftpd.service")


@handler("storage.inventory")
async def get_inventory(
    params: StorageInventoryParams,  # noqa: ARG001
    ctx: RpcContext,  # noqa: ARG001
    state: AgentState,
) -> StorageInventoryResult:
    result = await inventory.gather(state.runner, state.mdstat)
    compute_protected(result)
    return result


@handler("storage.execute_plan")
async def execute_plan(
    params: StorageExecutePlanParams,
    ctx: RpcContext,
    state: AgentState,
) -> JobStartedResult:
    spec = params.spec

    async def body(handle: JobHandle) -> None:
        handle.progress(0.0, "Re-checking device safety")
        fresh = await inventory.gather(state.runner, state.mdstat)
        protected_serials = compute_protected(fresh)
        resolved = _resolve_spec(spec, fresh, protected_serials, params.expected_sizes)

        steps = build_steps(resolved)
        total_steps = len(steps)
        unit_name: str | None = None
        fs_uuid = ""
        backup_dir = f"{state.settings.state_dir}/config-backups"

        for index, step in enumerate(steps):
            handle.progress(index / total_steps, step.description)

            if step.op == Run:
                result = await state.runner.run(step.argv)
                if not result.ok:
                    raise RuntimeError(f"{step.description} failed: {result.stderr.strip()}")

            elif step.op == WriteUnit:
                blkid_result = await state.runner.run(
                    ["blkid", "-o", "value", "-s", "UUID", lv_device(resolved)]
                )
                fs_uuid = blkid_result.stdout.strip()
                unit_name = await mount_unit_name(state.runner, resolved.mountpoint)

                def _render_unit(
                    uuid: str = fs_uuid,
                    where: str = resolved.mountpoint,
                    fs: str = resolved.filesystem,
                ) -> str:
                    return render_mount_unit(uuid=uuid, where=where, fstype=fs)

                await ManagedFile(
                    path=state.settings.system_path(mount_unit_path(unit_name)),
                    render=_render_unit,
                    runner=state.runner,
                    backup_dir=backup_dir,
                ).write_and_apply()

            elif step.op == WriteTarget:
                await ManagedFile(
                    path=state.settings.system_path(VOLUMES_TARGET_UNIT_PATH),
                    render=render_volumes_target,
                    runner=state.runner,
                    backup_dir=backup_dir,
                ).write_and_apply()

            elif step.op == WriteDropins:

                def _render_dropin(mp: list[str] = params.managed_mountpoints) -> str:
                    return render_service_dropin(mountpoints=mp)

                for service_unit in _DROPIN_SERVICES:
                    await ManagedFile(
                        path=state.settings.system_path(service_dropin_path(service_unit)),
                        render=_render_dropin,
                        runner=state.runner,
                        backup_dir=backup_dir,
                    ).write_and_apply()

            elif step.op == DaemonReload:
                await state.systemd.daemon_reload()

            elif step.op == EnableStartUnit:
                assert unit_name is not None
                await state.systemd.enable(unit_name)
                await state.systemd.start(unit_name)
                await state.systemd.wait_active(unit_name, timeout=30)

            elif step.op == Restorecon:
                await state.runner.run(["restorecon", "-R", resolved.mountpoint])

        os.makedirs(os.path.join(resolved.mountpoint, "@nasos", "tmp"), exist_ok=True)

        handle.progress(
            1.0,
            json.dumps(
                {
                    "name": resolved.volume_name,
                    "mountpoint": resolved.mountpoint,
                    "filesystem": resolved.filesystem,
                    "device": lv_device(resolved),
                    "uuid": fs_uuid,
                    "raid_level": resolved.level,
                    "array_name": resolved.array_name if resolved.level != "basic" else None,
                    "disk_serials": resolved.disk_serials,
                }
            ),
        )

    job_id = state.jobs.submit(
        "storage.execute_plan",
        body,
        # A single global lock rather than one per disk: two storage
        # orchestrations should never run concurrently at all (PLAN.md §6's
        # "never cancel mid-mkfs" carefulness extends to "never race two of
        # these"), even if they'd otherwise touch disjoint disks.
        resource="storage",
        created_by=ctx.user,
    )
    return JobStartedResult(job_id=job_id)


def _resolve_spec(
    spec: StoragePlanSpec,
    fresh: StorageInventoryResult,
    protected_serials: set[str],
    expected_sizes: dict[str, int],
) -> StoragePlanSpec:
    by_serial = {node.serial: node for node in _flatten(fresh.disks) if node.serial}

    resolved_paths: list[str] = []
    for serial in spec.disk_serials:
        node = by_serial.get(serial)
        if node is None:
            raise RpcException("device_missing", f"disk {serial} is no longer present")
        if serial in protected_serials:
            raise RpcException(
                "device_protected", f"disk {serial} is now protected: {node.protected_reason}"
            )
        expected = expected_sizes.get(serial)
        if expected is not None and node.size != expected:
            raise RpcException(
                "size_mismatch",
                f"disk {serial} is now {node.size} bytes, was {expected} when the plan was made",
            )
        resolved_paths.append(node.path)

    return spec.model_copy(update={"disk_paths": resolved_paths})


def _flatten(nodes: list[DiskNode]) -> list[DiskNode]:
    found: list[DiskNode] = []
    for node in nodes:
        found.append(node)
        found.extend(_flatten(node.children))
    return found
