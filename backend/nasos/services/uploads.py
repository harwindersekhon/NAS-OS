"""tus upload business logic (PLAN.md §5): DB bookkeeping for in-flight
uploads plus the fileworker RPC calls that actually create/write/finish
them. The DB `uploads` row is *never* the resumability authority — that's
always the fileworker's own view of bytes on disk (see db/models.py's
Upload docstring) — it exists so a HEAD request can find the declared
dest_path/size for an upload_id without asking the worker every time, and
so free-space/GC logic has something to look at without a live connection.
"""

from __future__ import annotations

import os
import shutil
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from nasos.db.models import Upload, Volume
from nasos.rpc.client import FileWorkerClient
from nasos.rpc.schemas import RpcContext
from nasos.rpc.transport import RpcCallError


class UploadServiceError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _volume_for(db: OrmSession, path: str) -> Volume | None:
    for volume in db.execute(select(Volume)).scalars():
        if path == volume.mountpoint or path.startswith(volume.mountpoint.rstrip("/") + "/"):
            return volume
    return None


def _check_free_space(db: OrmSession, dest_dir: str, size: int) -> None:
    volume = _volume_for(db, dest_dir)
    if volume is None:
        return  # not under any registered volume — let the worker's real mkdir/open fail instead
    free = shutil.disk_usage(volume.mountpoint).free
    if size > free:
        raise UploadServiceError("insufficient_space", f"{size} bytes requested, {free} free")


async def begin_upload(
    db: OrmSession,
    client: FileWorkerClient,
    ctx: RpcContext,
    uid: int,
    *,
    dest_dir: str,
    filename: str,
    size: int,
) -> Upload:
    _check_free_space(db, dest_dir, size)
    dest_path = os.path.join(dest_dir, filename)
    upload_id = uuid.uuid4().hex
    try:
        await client.metadata.call(
            "files.upload_begin", ctx, upload_id=upload_id, dest_path=dest_path, size=size
        )
    except RpcCallError as exc:
        raise UploadServiceError(exc.code, exc.message) from exc
    upload = Upload(id=upload_id, uid=uid, dest_path=dest_path, size=size, offset=0)
    db.add(upload)
    db.commit()
    return upload


def get_upload(db: OrmSession, upload_id: str) -> Upload | None:
    return db.get(Upload, upload_id)


async def write_chunk(
    db: OrmSession, client: FileWorkerClient, upload: Upload, offset: int, data: bytes
) -> int:
    try:
        new_offset = await client.data.write_chunk(upload.id, offset, data)
    except RpcCallError as exc:
        raise UploadServiceError(exc.code, exc.message) from exc
    upload.offset = new_offset
    db.commit()
    return new_offset


async def current_offset(client: FileWorkerClient, ctx: RpcContext, upload_id: str) -> int:
    """The authority for resumability — always asks the worker (actual
    bytes on disk), never trusts the DB row's cached `offset` alone."""
    try:
        result = await client.metadata.call("files.upload_offset", ctx, upload_id=upload_id)
    except RpcCallError as exc:
        raise UploadServiceError(exc.code, exc.message) from exc
    return result.offset  # type: ignore[attr-defined]


async def complete_upload(
    db: OrmSession, client: FileWorkerClient, ctx: RpcContext, upload: Upload
) -> None:
    try:
        await client.metadata.call("files.upload_complete", ctx, upload_id=upload.id)
    except RpcCallError as exc:
        raise UploadServiceError(exc.code, exc.message) from exc
    db.delete(upload)
    db.commit()


async def abort_upload(
    db: OrmSession, client: FileWorkerClient, ctx: RpcContext, upload: Upload
) -> None:
    try:
        await client.metadata.call("files.upload_abort", ctx, upload_id=upload.id)
    except RpcCallError as exc:
        raise UploadServiceError(exc.code, exc.message) from exc
    db.delete(upload)
    db.commit()
