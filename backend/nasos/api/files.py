"""files REST API (PLAN.md §5): browse/search/sort, mkdir/rename,
delete/copy/move/zip jobs, properties, ACL editor, content (download +
preview share one endpoint — they differ only in Content-Disposition and
both need Range support for video/audio seeking, so there is no separate
"preview" route).

No services/files.py: unlike shares/users, there is no DB table mirroring
file content — the filesystem itself, through the acting user's own POSIX
permissions, is the only source of truth (PLAN.md §3) — so this layer is a
thin, direct FileWorkerClient pass-through with one shared error mapping.
"""

from __future__ import annotations

import mimetypes
import os
import tempfile
from collections.abc import AsyncIterator
from typing import cast

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session as OrmSession
from starlette.responses import Response, StreamingResponse

from nasos.db.models import Session as DbSession
from nasos.rpc.client import FileWorkerClient
from nasos.rpc.schemas import (
    FilesGetAclResult,
    FilesListResult,
    FilesPropertiesResult,
    FilesSearchResult,
    JobListResult,
    JobStartedResult,
    RpcContext,
    RpcModel,
)
from nasos.rpc.transport import RpcCallError
from nasos.services import shares as shares_service
from nasos.web.deps import get_current_session, get_db, get_file_worker_client

router = APIRouter(prefix="/api/v1/files", tags=["files"])

_ERROR_STATUS = {
    "not_found": 404,
    "already_exists": 409,
    "permission_denied": 403,
    "is_a_directory": 400,
    "not_a_directory": 400,
    "invalid_params": 400,
}


def _ctx(session: DbSession) -> RpcContext:
    return RpcContext(user=session.username, role=session.role)


async def _call(
    client: FileWorkerClient, ctx: RpcContext, method: str, **params: object
) -> RpcModel:
    try:
        return await client.metadata.call(method, ctx, **params)
    except RpcCallError as exc:
        raise HTTPException(
            status_code=_ERROR_STATUS.get(exc.code, 400), detail=exc.message
        ) from exc


class RootOut(BaseModel):
    id: int
    name: str
    path: str


@router.get("/roots", response_model=list[RootOut])
def list_roots(
    db: OrmSession = Depends(get_db),
    session: DbSession = Depends(get_current_session),  # noqa: ARG001
) -> list[RootOut]:
    return [
        RootOut(id=share.id, name=share.name, path=share.path)
        for share in shares_service.list_shares(db)
    ]


@router.get("/jobs", response_model=JobListResult)
async def list_jobs(
    client: FileWorkerClient = Depends(get_file_worker_client),
    session: DbSession = Depends(get_current_session),
) -> RpcModel:
    """Polled by the frontend for delete/copy/move/zip/set_acl(recursive)
    progress — these jobs run in this user's own fileworker, a separate
    JobRunner from the root agent's (see files.jobs.list's docstring)."""
    return await _call(client, _ctx(session), "files.jobs.list")


@router.get("/list", response_model=FilesListResult)
async def list_dir(
    path: str,
    client: FileWorkerClient = Depends(get_file_worker_client),
    session: DbSession = Depends(get_current_session),
) -> RpcModel:
    return await _call(client, _ctx(session), "files.list", path=path)


@router.get("/search", response_model=FilesSearchResult)
async def search(
    path: str,
    query: str,
    client: FileWorkerClient = Depends(get_file_worker_client),
    session: DbSession = Depends(get_current_session),
) -> RpcModel:
    return await _call(client, _ctx(session), "files.search", path=path, query=query)


class PathBody(BaseModel):
    path: str


@router.post("/mkdir")
async def mkdir(
    body: PathBody,
    client: FileWorkerClient = Depends(get_file_worker_client),
    session: DbSession = Depends(get_current_session),
) -> dict[str, bool]:
    await _call(client, _ctx(session), "files.mkdir", path=body.path)
    return {"ok": True}


class RenameBody(BaseModel):
    path: str
    new_name: str


@router.post("/rename")
async def rename(
    body: RenameBody,
    client: FileWorkerClient = Depends(get_file_worker_client),
    session: DbSession = Depends(get_current_session),
) -> dict[str, bool]:
    await _call(client, _ctx(session), "files.rename", path=body.path, new_name=body.new_name)
    return {"ok": True}


class PathsBody(BaseModel):
    paths: list[str]


class JobStartedOut(BaseModel):
    job_id: str | None


@router.post("/delete", response_model=JobStartedOut)
async def delete(
    body: PathsBody,
    client: FileWorkerClient = Depends(get_file_worker_client),
    session: DbSession = Depends(get_current_session),
) -> JobStartedOut:
    result = cast(
        JobStartedResult, await _call(client, _ctx(session), "files.delete", paths=body.paths)
    )
    return JobStartedOut(job_id=result.job_id)


class SourcesDestBody(BaseModel):
    sources: list[str]
    dest_dir: str


@router.post("/copy", response_model=JobStartedOut)
async def copy(
    body: SourcesDestBody,
    client: FileWorkerClient = Depends(get_file_worker_client),
    session: DbSession = Depends(get_current_session),
) -> JobStartedOut:
    result = cast(
        JobStartedResult,
        await _call(
            client, _ctx(session), "files.copy", sources=body.sources, dest_dir=body.dest_dir
        ),
    )
    return JobStartedOut(job_id=result.job_id)


@router.post("/move", response_model=JobStartedOut)
async def move(
    body: SourcesDestBody,
    client: FileWorkerClient = Depends(get_file_worker_client),
    session: DbSession = Depends(get_current_session),
) -> JobStartedOut:
    result = cast(
        JobStartedResult,
        await _call(
            client, _ctx(session), "files.move", sources=body.sources, dest_dir=body.dest_dir
        ),
    )
    return JobStartedOut(job_id=result.job_id)


class ZipBody(BaseModel):
    sources: list[str]


class ZipStartedOut(BaseModel):
    job_id: str | None
    dest_path: str


@router.post("/zip", response_model=ZipStartedOut)
async def zip_paths(
    body: ZipBody,
    client: FileWorkerClient = Depends(get_file_worker_client),
    session: DbSession = Depends(get_current_session),
) -> ZipStartedOut:
    fd, dest_path = tempfile.mkstemp(prefix="nasos-zip-", suffix=".zip")
    os.close(fd)
    os.remove(dest_path)  # files.zip creates it; we only wanted a unique name
    result = cast(
        JobStartedResult,
        await _call(client, _ctx(session), "files.zip", sources=body.sources, dest_path=dest_path),
    )
    return ZipStartedOut(job_id=result.job_id, dest_path=dest_path)


@router.get("/properties", response_model=FilesPropertiesResult)
async def properties(
    path: str,
    client: FileWorkerClient = Depends(get_file_worker_client),
    session: DbSession = Depends(get_current_session),
) -> RpcModel:
    return await _call(client, _ctx(session), "files.properties", path=path)


class AclEntryBody(BaseModel):
    kind: str
    numeric_id: int
    level: str


@router.get("/acl", response_model=FilesGetAclResult)
async def get_acl(
    path: str,
    client: FileWorkerClient = Depends(get_file_worker_client),
    session: DbSession = Depends(get_current_session),
) -> RpcModel:
    return await _call(client, _ctx(session), "files.get_acl", path=path)


class SetAclBody(BaseModel):
    path: str
    entries: list[AclEntryBody]
    recursive: bool = False


@router.put("/acl", response_model=JobStartedOut)
async def set_acl(
    body: SetAclBody,
    client: FileWorkerClient = Depends(get_file_worker_client),
    session: DbSession = Depends(get_current_session),
) -> JobStartedOut:
    result = cast(
        JobStartedResult,
        await _call(
            client,
            _ctx(session),
            "files.set_acl",
            path=body.path,
            entries=[e.model_dump() for e in body.entries],
            recursive=body.recursive,
        ),
    )
    return JobStartedOut(job_id=result.job_id)


@router.get("/content")
async def content(
    path: str,
    request: Request,
    disposition: str = "inline",
    client: FileWorkerClient = Depends(get_file_worker_client),
    session: DbSession = Depends(get_current_session),
) -> Response:
    props = cast(
        FilesPropertiesResult, await _call(client, _ctx(session), "files.properties", path=path)
    )
    total = props.size
    name = props.name

    range_header = request.headers.get("range")
    offset, length, status_code = 0, total, 200
    extra_headers = {}
    if range_header and range_header.startswith("bytes="):
        start_str, _, end_str = range_header.removeprefix("bytes=").partition("-")
        start = int(start_str) if start_str else 0
        end = int(end_str) if end_str else total - 1
        offset, length, status_code = start, end - start + 1, 206
        extra_headers["Content-Range"] = f"bytes {start}-{end}/{total}"

    content_type = mimetypes.guess_type(name)[0] or "application/octet-stream"

    async def body() -> AsyncIterator[bytes]:
        try:
            async for chunk in client.data.read_range(path, offset, length):
                yield chunk
        except RpcCallError as exc:
            raise HTTPException(
                status_code=_ERROR_STATUS.get(exc.code, 400), detail=exc.message
            ) from exc

    return StreamingResponse(
        body(),
        status_code=status_code,
        media_type=content_type,
        headers={
            "Content-Length": str(length),
            "Content-Disposition": f'{disposition}; filename="{name}"',
            "Accept-Ranges": "bytes",
            **extra_headers,
        },
    )
