"""files.* handlers (PLAN.md §1/§5): browse/search/sort, mkdir/rename,
delete/copy/move/zip jobs, properties, ACL get/set. Registered into the same
Dispatcher/REGISTRY machinery as every other handler module, but imported
only by the fileworker process (agent/fileworker.py) and by dev mode's
in-process wiring — never by the root agent, since these run real syscalls
against user file content and belong only in a process that has already
dropped to that user's uid/gid.

Mutating single-item ops (mkdir/rename) are synchronous, matching the sync
half of M2's ACL precedent (top-level apply is sync, recursive is a job).
delete/copy/move/zip run as jobs unconditionally: unlike a single setfacl
call, these can touch an unbounded number of files, and reusing one pattern
for all four is simpler than guessing a size threshold. Progress is reported
per top-level item (not per byte) — coarse but safe: `handle.progress()`
touches asyncio writer state, so it may only be called from the worker's own
event-loop thread, which per-item `await asyncio.to_thread(...)` naturally
guarantees (control returns to that thread between items) but a single
to_thread call spanning many files would not.
"""

from __future__ import annotations

import asyncio
import os
import pwd
import shutil
import stat
import zipfile

from nasos.agent.dispatcher import handler
from nasos.agent.jobs import JobHandle
from nasos.agent.workerstate import WorkerState
from nasos.rpc.schemas import (
    FileEntry,
    FilesAclEntry,
    FilesCopyParams,
    FilesDeleteParams,
    FilesGetAclParams,
    FilesGetAclResult,
    FilesJobListParams,
    FilesListParams,
    FilesListResult,
    FilesMkdirParams,
    FilesMoveParams,
    FilesPropertiesParams,
    FilesPropertiesResult,
    FilesRenameParams,
    FilesSearchParams,
    FilesSearchResult,
    FilesSetAclParams,
    FilesZipParams,
    JobListResult,
    JobRecordResult,
    JobStartedResult,
    OkResult,
    RpcContext,
    RpcException,
)

MAX_SEARCH_RESULTS = 500


def _wrap_os_error(exc: OSError) -> RpcException:
    if isinstance(exc, FileNotFoundError):
        return RpcException("not_found", str(exc))
    if isinstance(exc, FileExistsError):
        return RpcException("already_exists", str(exc))
    if isinstance(exc, PermissionError):
        return RpcException("permission_denied", str(exc))
    if isinstance(exc, IsADirectoryError):
        return RpcException("is_a_directory", str(exc))
    if isinstance(exc, NotADirectoryError):
        return RpcException("not_a_directory", str(exc))
    return RpcException("io_error", str(exc))


def _entry(path: str) -> FileEntry:
    try:
        st = os.stat(path)
    except OSError:
        st = os.lstat(path)  # broken symlink: fall back to the link's own metadata
    return FileEntry(
        name=os.path.basename(path),
        path=path,
        is_dir=stat.S_ISDIR(st.st_mode),
        size=st.st_size,
        mtime=st.st_mtime,
        owner_uid=st.st_uid,
    )


def _dest_for(source: str, dest_dir: str) -> str:
    dest = os.path.join(dest_dir, os.path.basename(source.rstrip("/")))
    if os.path.exists(dest):
        raise RpcException("already_exists", f"{dest} already exists")
    return dest


@handler("files.list")
async def list_dir(
    params: FilesListParams,
    ctx: RpcContext,
    state: WorkerState,  # noqa: ARG001
) -> FilesListResult:
    try:
        names = os.listdir(params.path)
    except OSError as exc:
        raise _wrap_os_error(exc) from exc
    entries: list[FileEntry] = []
    for name in names:
        try:
            entries.append(_entry(os.path.join(params.path, name)))
        except OSError:
            continue  # vanished mid-listing, or truly unreadable — skip, don't fail the page
    entries.sort(key=lambda e: (not e.is_dir, e.name.lower()))
    return FilesListResult(entries=entries)


@handler("files.search")
async def search(
    params: FilesSearchParams,
    ctx: RpcContext,
    state: WorkerState,  # noqa: ARG001
) -> FilesSearchResult:
    query = params.query.lower()
    matches: list[FileEntry] = []
    try:
        for root, dirnames, filenames in os.walk(params.path):
            for name in (*dirnames, *filenames):
                if query not in name.lower():
                    continue
                try:
                    matches.append(_entry(os.path.join(root, name)))
                except OSError:
                    continue
                if len(matches) >= MAX_SEARCH_RESULTS:
                    return FilesSearchResult(entries=matches)
    except OSError as exc:
        raise _wrap_os_error(exc) from exc
    return FilesSearchResult(entries=matches)


@handler("files.mkdir")
async def mkdir(
    params: FilesMkdirParams,
    ctx: RpcContext,
    state: WorkerState,  # noqa: ARG001
) -> OkResult:
    try:
        os.mkdir(params.path)
    except OSError as exc:
        raise _wrap_os_error(exc) from exc
    return OkResult()


@handler("files.rename")
async def rename(
    params: FilesRenameParams,
    ctx: RpcContext,
    state: WorkerState,  # noqa: ARG001
) -> OkResult:
    if "/" in params.new_name:
        raise RpcException("invalid_params", "new_name must not contain a path separator")
    dest = os.path.join(os.path.dirname(params.path), params.new_name)
    if os.path.exists(dest):
        raise RpcException("already_exists", f"{dest} already exists")
    try:
        os.rename(params.path, dest)
    except OSError as exc:
        raise _wrap_os_error(exc) from exc
    return OkResult()


@handler("files.delete")
async def delete(
    params: FilesDeleteParams, ctx: RpcContext, state: WorkerState
) -> JobStartedResult:
    async def body(handle: JobHandle) -> None:
        for i, path in enumerate(params.paths):
            if handle.cancel_requested:
                return
            try:
                if os.path.isdir(path) and not os.path.islink(path):
                    await asyncio.to_thread(shutil.rmtree, path)
                else:
                    await asyncio.to_thread(os.remove, path)
            except OSError as exc:
                raise _wrap_os_error(exc) from exc
            handle.progress((i + 1) / len(params.paths), path)

    job_id = state.jobs.submit("files.delete", body, created_by=ctx.user)
    return JobStartedResult(job_id=job_id)


@handler("files.copy")
async def copy(params: FilesCopyParams, ctx: RpcContext, state: WorkerState) -> JobStartedResult:
    async def body(handle: JobHandle) -> None:
        for i, source in enumerate(params.sources):
            if handle.cancel_requested:
                return
            dest = _dest_for(source, params.dest_dir)
            try:
                if os.path.isdir(source) and not os.path.islink(source):
                    await asyncio.to_thread(shutil.copytree, source, dest, symlinks=True)
                else:
                    await asyncio.to_thread(shutil.copy2, source, dest, follow_symlinks=False)
            except OSError as exc:
                raise _wrap_os_error(exc) from exc
            handle.progress((i + 1) / len(params.sources), dest)

    job_id = state.jobs.submit("files.copy", body, created_by=ctx.user)
    return JobStartedResult(job_id=job_id)


@handler("files.move")
async def move(params: FilesMoveParams, ctx: RpcContext, state: WorkerState) -> JobStartedResult:
    async def body(handle: JobHandle) -> None:
        for i, source in enumerate(params.sources):
            if handle.cancel_requested:
                return
            dest = _dest_for(source, params.dest_dir)
            try:
                await asyncio.to_thread(shutil.move, source, dest)
            except OSError as exc:
                raise _wrap_os_error(exc) from exc
            handle.progress((i + 1) / len(params.sources), dest)

    job_id = state.jobs.submit("files.move", body, created_by=ctx.user)
    return JobStartedResult(job_id=job_id)


def _files_under(sources: list[str]) -> list[tuple[str, str]]:
    """(absolute path, archive name) for every file under every source."""
    out: list[tuple[str, str]] = []
    for source in sources:
        base = os.path.basename(source.rstrip("/"))
        if os.path.isdir(source):
            for root, _dirs, filenames in os.walk(source):
                for name in filenames:
                    full = os.path.join(root, name)
                    arcname = os.path.join(base, os.path.relpath(full, source))
                    out.append((full, arcname))
        else:
            out.append((source, base))
    return out


@handler("files.zip")
async def zip_paths(
    params: FilesZipParams, ctx: RpcContext, state: WorkerState
) -> JobStartedResult:
    async def body(handle: JobHandle) -> None:
        files = await asyncio.to_thread(_files_under, params.sources)
        zf = await asyncio.to_thread(zipfile.ZipFile, params.dest_path, "w", zipfile.ZIP_STORED)
        try:
            for i, (full, arcname) in enumerate(files):
                if handle.cancel_requested:
                    return
                await asyncio.to_thread(zf.write, full, arcname)
                handle.progress((i + 1) / max(len(files), 1), arcname)
        finally:
            await asyncio.to_thread(zf.close)

    job_id = state.jobs.submit("files.zip", body, created_by=ctx.user)
    return JobStartedResult(job_id=job_id)


@handler("files.properties")
async def properties(
    params: FilesPropertiesParams,
    ctx: RpcContext,
    state: WorkerState,  # noqa: ARG001
) -> FilesPropertiesResult:
    try:
        st = os.stat(params.path)
    except OSError as exc:
        raise _wrap_os_error(exc) from exc
    is_dir = stat.S_ISDIR(st.st_mode)
    try:
        owner_name = pwd.getpwuid(st.st_uid).pw_name
    except KeyError:
        owner_name = str(st.st_uid)
    item_count = None
    if is_dir:
        try:
            item_count = len(os.listdir(params.path))
        except OSError:
            item_count = None
    return FilesPropertiesResult(
        name=os.path.basename(params.path.rstrip("/")) or params.path,
        path=params.path,
        is_dir=is_dir,
        size=st.st_size,
        mtime=st.st_mtime,
        owner_uid=st.st_uid,
        owner_name=owner_name,
        mode=stat.filemode(st.st_mode)[1:],
        item_count=item_count,
    )


@handler("files.get_acl")
async def get_acl(
    params: FilesGetAclParams,
    ctx: RpcContext,
    state: WorkerState,  # noqa: ARG001
) -> FilesGetAclResult:
    entries = await state.acl.read_acl(params.path)
    return FilesGetAclResult(
        entries=[FilesAclEntry(kind=k, numeric_id=i, level=lvl) for k, i, lvl in entries]
    )


@handler("files.set_acl")
async def set_acl(
    params: FilesSetAclParams, ctx: RpcContext, state: WorkerState
) -> JobStartedResult:
    entries = [(e.kind, e.numeric_id, e.level) for e in params.entries]

    if not params.recursive:
        await state.acl.replace_all(params.path, entries, recursive=False)
        return JobStartedResult(job_id=None)

    async def body(handle: JobHandle) -> None:
        handle.progress(0.0, params.path)
        await state.acl.replace_all(params.path, entries, recursive=True)

    job_id = state.jobs.submit("files.set_acl", body, created_by=ctx.user)
    return JobStartedResult(job_id=job_id)


@handler("files.jobs.list")
async def list_jobs(
    params: FilesJobListParams,  # noqa: ARG001
    ctx: RpcContext,  # noqa: ARG001
    state: WorkerState,
) -> JobListResult:
    """A distinct method from the root agent's own jobs.list (PLAN.md §4):
    _HANDLERS is one flat namespace keyed by method name, and delete/copy/
    move/zip/set_acl jobs run in this worker's own JobRunner, not the
    agent's — the web polls this one to show File Station job progress.
    """
    return JobListResult(
        jobs=[JobRecordResult.model_validate(record) for record in state.jobs.list()]
    )
