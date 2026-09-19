"""samba.* RPC methods (PLAN.md §2's Samba row)."""

from __future__ import annotations

from pathlib import Path

from nasos.agent.dispatcher import handler
from nasos.agent.state import AgentState
from nasos.rpc.schemas import (
    OkResult,
    RpcContext,
    RpcException,
    SambaApplyConfigParams,
    SambaApplyConfigResult,
    SambaEnsureEnabledParams,
)
from nasos.system.managedfile import ConfigApplyError, ConfigValidationError, ManagedFile
from nasos.system.samba import NASOS_CONF, SMB_CONF, ensure_include_block, validate


@handler("samba.apply_config")
async def apply_config(
    params: SambaApplyConfigParams,
    ctx: RpcContext,  # noqa: ARG001
    state: AgentState,
) -> SambaApplyConfigResult:
    apply_fn = state.samba.restart if params.restart else state.samba.reload_or_start
    managed = ManagedFile(
        path=state.settings.system_path(NASOS_CONF),
        render=lambda: params.content,
        runner=state.runner,
        validate=lambda target: validate(state.runner, target),
        apply=apply_fn,
        backup_dir=f"{state.settings.state_dir}/config-backups",
    )
    try:
        sha256 = await managed.write_and_apply()
    except ConfigValidationError as exc:
        raise RpcException("config_invalid", exc.detail) from exc
    except ConfigApplyError as exc:
        raise RpcException("apply_failed", exc.detail) from exc
    return SambaApplyConfigResult(sha256=sha256)


@handler("samba.ensure_enabled")
async def ensure_enabled(
    params: SambaEnsureEnabledParams,  # noqa: ARG001
    ctx: RpcContext,  # noqa: ARG001
    state: AgentState,
) -> OkResult:
    """Idempotently wires smb.conf's include (PLAN.md §2 marker block) and
    starts+enables smb/nmb. Safe to call every time SMB is (re-)enabled —
    the marker-block edit is a no-op once present.
    """
    smb_conf = Path(state.settings.system_path(SMB_CONF))
    original = smb_conf.read_text() if smb_conf.exists() else ""
    updated = ensure_include_block(original)
    if updated != original:
        try:
            smb_conf.parent.mkdir(parents=True, exist_ok=True)
            smb_conf.write_text(updated)
            await state.runner.run(["restorecon", str(smb_conf)])
        except OSError as exc:
            raise RpcException("system_error", str(exc)) from exc

    try:
        await state.systemd.enable("smb.service")
        await state.systemd.enable("nmb.service")
        await state.samba.restart()
    except Exception as exc:
        raise RpcException("apply_failed", str(exc)) from exc
    return OkResult()
