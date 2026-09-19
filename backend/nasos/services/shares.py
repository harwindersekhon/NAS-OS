"""shares.* business logic (PLAN.md §3): shares + share_permissions, and
driving their Samba config / ACL side effects. Runs in the web process.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import cast

from sqlalchemy import delete, select
from sqlalchemy.orm import Session as OrmSession

from nasos.db.models import GroupMeta, Share, SharePermission, User, Volume
from nasos.rpc.client import AgentClient
from nasos.rpc.schemas import JobStartedResult, RpcContext, SambaApplyConfigResult
from nasos.rpc.transport import RpcCallError
from nasos.services.samba_config import build_share_view, render_nasos_conf


class ShareServiceError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def list_shares(db: OrmSession) -> list[Share]:
    return list(db.execute(select(Share)).scalars())


def get_share(db: OrmSession, share_id: int) -> Share | None:
    return db.get(Share, share_id)


def list_permissions(db: OrmSession, share_id: int) -> list[SharePermission]:
    return list(
        db.execute(select(SharePermission).where(SharePermission.share_id == share_id)).scalars()
    )


async def create_share(
    db: OrmSession,
    agent: AgentClient,
    ctx: RpcContext,
    *,
    name: str,
    volume_id: int,
    description: str,
) -> Share:
    volume = db.get(Volume, volume_id)
    if volume is None:
        raise ShareServiceError("not_found", f"no such volume: {volume_id}")
    path = f"{volume.mountpoint}/{name}"

    try:
        await agent.call("shares.create", ctx, path=path)
    except RpcCallError as exc:
        raise ShareServiceError(exc.code, exc.message) from exc

    share = Share(
        name=name, volume_id=volume_id, path=path, description=description, smb_enabled=True
    )
    db.add(share)
    db.commit()

    await apply_samba_config(db, agent, ctx)
    return share


async def delete_share(
    db: OrmSession, agent: AgentClient, ctx: RpcContext, share: Share, *, delete_files: bool
) -> None:
    try:
        await agent.call("shares.delete", ctx, path=share.path, delete_files=delete_files)
    except RpcCallError as exc:
        raise ShareServiceError(exc.code, exc.message) from exc
    db.delete(share)
    db.commit()
    await apply_samba_config(db, agent, ctx)


def _resolve_numeric_id(db: OrmSession, principal_type: str, principal: str) -> int:
    if principal_type == "user":
        user = db.execute(select(User).where(User.username == principal)).scalar_one_or_none()
        if user is None:
            raise ShareServiceError("not_found", f"no such NAS-OS user: {principal}")
        return user.uid
    group = db.execute(select(GroupMeta).where(GroupMeta.name == principal)).scalar_one_or_none()
    if group is None:
        raise ShareServiceError("not_found", f"no such NAS-OS group: {principal}")
    return group.gid


async def set_share_permissions(
    db: OrmSession,
    agent: AgentClient,
    ctx: RpcContext,
    share: Share,
    *,
    permissions: Sequence[tuple[str, str, str]],  # (principal_type, principal, level)
    recursive: bool,
) -> str | None:
    entries = [
        {
            "kind": principal_type,
            "numeric_id": _resolve_numeric_id(db, principal_type, principal),
            "level": level,
        }
        for principal_type, principal, level in permissions
    ]

    try:
        result = cast(
            JobStartedResult,
            await agent.call(
                "shares.set_permissions", ctx, path=share.path, entries=entries, recursive=recursive
            ),
        )
    except RpcCallError as exc:
        raise ShareServiceError(exc.code, exc.message) from exc

    db.execute(delete(SharePermission).where(SharePermission.share_id == share.id))
    for principal_type, principal, level in permissions:
        db.add(
            SharePermission(
                share_id=share.id,
                principal_type=principal_type,
                principal=principal,
                level=level,
            )
        )
    db.commit()

    await apply_samba_config(db, agent, ctx)
    return result.job_id


async def apply_samba_config(
    db: OrmSession, agent: AgentClient, ctx: RpcContext, *, restart: bool = False
) -> str:
    shares = list_shares(db)
    views = [build_share_view(share, list_permissions(db, share.id)) for share in shares]
    content = render_nasos_conf(views)
    try:
        result = cast(
            SambaApplyConfigResult,
            await agent.call("samba.apply_config", ctx, content=content, restart=restart),
        )
    except RpcCallError as exc:
        raise ShareServiceError(exc.code, exc.message) from exc
    return result.sha256


async def ensure_samba_enabled(agent: AgentClient, ctx: RpcContext) -> None:
    try:
        await agent.call("samba.ensure_enabled", ctx)
        await agent.call("firewall.ensure_service", ctx, service="samba")
    except RpcCallError as exc:
        raise ShareServiceError(exc.code, exc.message) from exc
