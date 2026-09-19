"""users.* business logic: composes the `users` DB table (the "NAS-managed"
marker, PLAN.md §3) with the agent's privileged RPC calls. Runs in the web
process.
"""

from __future__ import annotations

from typing import cast

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from nasos.db.models import Notification, User
from nasos.rpc.client import AgentClient
from nasos.rpc.schemas import RpcContext, UserInfo
from nasos.rpc.transport import RpcCallError


class UserServiceError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def list_users(db: OrmSession) -> list[User]:
    return list(db.execute(select(User)).scalars())


def get_user(db: OrmSession, uid: int) -> User | None:
    return db.get(User, uid)


async def create_user(
    db: OrmSession,
    agent: AgentClient,
    ctx: RpcContext,
    *,
    username: str,
    password: str,
    description: str,
) -> User:
    try:
        info = cast(
            UserInfo,
            await agent.call(
                "users.create",
                ctx,
                username=username,
                password=password,
                description=description,
            ),
        )
    except RpcCallError as exc:
        raise UserServiceError(exc.code, exc.message) from exc

    user = User(
        uid=info.uid,
        username=info.username,
        description=description,
        smb_enabled=True,
        ftp_enabled=False,
        created_by_nasos=True,
        smb_password_synced=True,
    )
    db.add(user)
    db.commit()
    return user


async def import_user(
    db: OrmSession, agent: AgentClient, ctx: RpcContext, *, username: str, description: str
) -> User:
    try:
        info = cast(UserInfo, await agent.call("users.import_existing", ctx, username=username))
    except RpcCallError as exc:
        raise UserServiceError(exc.code, exc.message) from exc

    user = User(
        uid=info.uid,
        username=info.username,
        description=description,
        smb_enabled=False,
        ftp_enabled=False,
        created_by_nasos=False,
        smb_password_synced=False,
    )
    db.add(user)
    db.commit()
    return user


async def set_smb_enabled(
    db: OrmSession, agent: AgentClient, ctx: RpcContext, user: User, *, enabled: bool
) -> User:
    try:
        await agent.call("users.set_smb_enabled", ctx, username=user.username, enabled=enabled)
    except RpcCallError as exc:
        raise UserServiceError(exc.code, exc.message) from exc
    user.smb_enabled = enabled
    db.commit()
    return user


async def set_password(
    db: OrmSession, agent: AgentClient, ctx: RpcContext, user: User, *, password: str
) -> User:
    try:
        await agent.call("users.set_password", ctx, username=user.username, password=password)
        user.smb_password_synced = True
    except RpcCallError as exc:
        if exc.code != "smb_password_sync_failed":
            raise UserServiceError(exc.code, exc.message) from exc
        # Unix password changed; Samba's didn't (PLAN.md §3) — not a hard
        # failure, just a drift flag + notification for the resync badge.
        user.smb_password_synced = False
        db.add(
            Notification(
                level="warning",
                title="Samba password out of sync",
                message=f"{user.username}'s SMB password wasn't updated: {exc.message}",
                source="users",
            )
        )
    db.commit()
    return user


async def delete_user(
    db: OrmSession, agent: AgentClient, ctx: RpcContext, user: User, *, delete_home: bool
) -> None:
    try:
        await agent.call("users.delete", ctx, username=user.username, delete_home=delete_home)
    except RpcCallError as exc:
        raise UserServiceError(exc.code, exc.message) from exc
    db.delete(user)
    db.commit()


def update_description(db: OrmSession, user: User, *, description: str) -> User:
    """Pure DB — PLAN.md §3: description is NAS-OS's own bookkeeping, no RPC."""
    user.description = description
    db.commit()
    return user
