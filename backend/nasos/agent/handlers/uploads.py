"""files.upload_* handlers: the metadata side of a tus upload (PLAN.md §1/§5)
— begin/offset/complete/abort. The actual bytes never come through here;
they arrive as binary frames handled directly in agent/fileworker.py's
connection loop (`_op_upload_chunk`), which looks up the .part path this
module's `upload_begin` records on `state.uploads`.

Partial uploads live at `<dest>/.nasos-upload-<id>.part` (PLAN.md §1,
literal naming) and are rename()'d onto `dest_path` on completion — so the
file is created by the correct user from the first byte (setgid dir +
default ACLs apply to the .part file directly) and never briefly visible
under its final name half-written.
"""

from __future__ import annotations

import os

from nasos.agent.dispatcher import handler
from nasos.agent.workerstate import UploadHandle, WorkerState
from nasos.rpc.schemas import (
    FilesUploadAbortParams,
    FilesUploadBeginParams,
    FilesUploadCompleteParams,
    FilesUploadOffsetParams,
    FilesUploadOffsetResult,
    OkResult,
    RpcContext,
    RpcException,
)


def part_path_for(dest_path: str, upload_id: str) -> str:
    directory = os.path.dirname(dest_path)
    return os.path.join(directory, f".nasos-upload-{upload_id}.part")


@handler("files.upload_begin")
async def upload_begin(
    params: FilesUploadBeginParams,
    ctx: RpcContext,
    state: WorkerState,  # noqa: ARG001
) -> OkResult:
    if os.path.exists(params.dest_path):
        raise RpcException("already_exists", f"{params.dest_path} already exists")
    part_path = part_path_for(params.dest_path, params.upload_id)
    try:
        fd = os.open(part_path, os.O_CREAT | os.O_WRONLY, 0o600)
        os.close(fd)
    except OSError as exc:
        raise RpcException("io_error", str(exc)) from exc
    state.uploads[params.upload_id] = UploadHandle(dest_path=params.dest_path, part_path=part_path)
    return OkResult()


def _handle_or_raise(state: WorkerState, upload_id: str) -> UploadHandle:
    handle = state.uploads.get(upload_id)
    if handle is None:
        raise RpcException("not_found", f"unknown upload_id: {upload_id}")
    return handle


@handler("files.upload_offset")
async def upload_offset(
    params: FilesUploadOffsetParams,
    ctx: RpcContext,
    state: WorkerState,  # noqa: ARG001
) -> FilesUploadOffsetResult:
    handle = _handle_or_raise(state, params.upload_id)
    try:
        size = os.path.getsize(handle.part_path)
    except OSError as exc:
        raise RpcException("not_found", str(exc)) from exc
    return FilesUploadOffsetResult(offset=size)


@handler("files.upload_complete")
async def upload_complete(
    params: FilesUploadCompleteParams,
    ctx: RpcContext,
    state: WorkerState,  # noqa: ARG001
) -> OkResult:
    handle = _handle_or_raise(state, params.upload_id)
    try:
        os.rename(handle.part_path, handle.dest_path)
    except OSError as exc:
        raise RpcException("io_error", str(exc)) from exc
    state.uploads.pop(params.upload_id, None)
    return OkResult()


@handler("files.upload_abort")
async def upload_abort(
    params: FilesUploadAbortParams,
    ctx: RpcContext,
    state: WorkerState,  # noqa: ARG001
) -> OkResult:
    handle = state.uploads.pop(params.upload_id, None)
    if handle is not None:
        try:
            os.remove(handle.part_path)
        except FileNotFoundError:
            pass
    return OkResult()
