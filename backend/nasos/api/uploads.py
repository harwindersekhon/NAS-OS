"""tus 1.0 resumable upload endpoints (PLAN.md §5: "tus 1.0 core
(creation/termination/expiration)"). Progress and resume are entirely a
tus-js-client concern client-side — it tracks bytes sent itself and resumes
from a HEAD-reported Upload-Offset after a refresh, so no server-sent
progress events are needed for uploads at all, unlike copy/move/delete/zip
jobs.
"""

from __future__ import annotations

import base64
import binascii

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session as OrmSession

from nasos.db.models import Session as DbSession
from nasos.rpc.client import FileWorkerClient
from nasos.rpc.schemas import RpcContext
from nasos.services import uploads as uploads_service
from nasos.services.uploads import UploadServiceError
from nasos.web.deps import get_current_session, get_db, get_file_worker_client

router = APIRouter(prefix="/api/v1/uploads", tags=["uploads"])

TUS_VERSION = "1.0.0"
PATCH_BUFFER_SIZE = 1024 * 1024


def _ctx(session: DbSession) -> RpcContext:
    return RpcContext(user=session.username, role=session.role)


def _tus_headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    headers = {"Tus-Resumable": TUS_VERSION}
    if extra:
        headers.update(extra)
    return headers


def _parse_metadata(header: str | None) -> dict[str, str]:
    """`key1 base64val1,key2 base64val2` per the tus Creation extension."""
    out: dict[str, str] = {}
    if not header:
        return out
    for pair in header.split(","):
        pair = pair.strip()
        if not pair:
            continue
        key, _, b64 = pair.partition(" ")
        try:
            out[key] = base64.b64decode(b64).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError):
            continue
    return out


@router.options("")
def tus_options() -> Response:
    return Response(
        status_code=204,
        headers=_tus_headers({"Tus-Version": TUS_VERSION, "Tus-Extension": "creation,termination"}),
    )


@router.post("", status_code=201)
async def create_upload(
    request: Request,
    db: OrmSession = Depends(get_db),
    client: FileWorkerClient = Depends(get_file_worker_client),
    session: DbSession = Depends(get_current_session),
) -> Response:
    length_header = request.headers.get("upload-length")
    if length_header is None:
        raise HTTPException(status_code=400, detail="Upload-Length header required")
    try:
        size = int(length_header)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid Upload-Length") from exc

    metadata = _parse_metadata(request.headers.get("upload-metadata"))
    filename = metadata.get("filename")
    dest_dir = metadata.get("dir")
    if not filename or not dest_dir:
        raise HTTPException(status_code=400, detail="Upload-Metadata must include filename and dir")

    try:
        upload = await uploads_service.begin_upload(
            db, client, _ctx(session), session.uid, dest_dir=dest_dir, filename=filename, size=size
        )
    except UploadServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return Response(
        status_code=201,
        headers=_tus_headers({"Location": f"/api/v1/uploads/{upload.id}"}),
    )


@router.head("/{upload_id}")
async def head_upload(
    upload_id: str,
    db: OrmSession = Depends(get_db),
    client: FileWorkerClient = Depends(get_file_worker_client),
    session: DbSession = Depends(get_current_session),
) -> Response:
    upload = uploads_service.get_upload(db, upload_id)
    if upload is None or upload.uid != session.uid:
        raise HTTPException(status_code=404, detail="no such upload")
    offset = await uploads_service.current_offset(client, _ctx(session), upload_id)
    return Response(
        status_code=200,
        headers=_tus_headers(
            {
                "Upload-Offset": str(offset),
                "Upload-Length": str(upload.size),
                "Cache-Control": "no-store",
            }
        ),
    )


@router.patch("/{upload_id}")
async def patch_upload(
    upload_id: str,
    request: Request,
    db: OrmSession = Depends(get_db),
    client: FileWorkerClient = Depends(get_file_worker_client),
    session: DbSession = Depends(get_current_session),
) -> Response:
    upload = uploads_service.get_upload(db, upload_id)
    if upload is None or upload.uid != session.uid:
        raise HTTPException(status_code=404, detail="no such upload")

    if request.headers.get("content-type") != "application/offset+octet-stream":
        raise HTTPException(status_code=415, detail="expected application/offset+octet-stream")

    client_offset_header = request.headers.get("upload-offset")
    if client_offset_header is None:
        raise HTTPException(status_code=400, detail="Upload-Offset header required")
    offset = int(client_offset_header)
    server_offset = await uploads_service.current_offset(client, _ctx(session), upload_id)
    if offset != server_offset:
        return Response(status_code=409, headers=_tus_headers())

    buf = bytearray()
    try:
        async for piece in request.stream():
            buf.extend(piece)
            while len(buf) >= PATCH_BUFFER_SIZE:
                chunk, buf = bytes(buf[:PATCH_BUFFER_SIZE]), buf[PATCH_BUFFER_SIZE:]
                offset = await uploads_service.write_chunk(db, client, upload, offset, chunk)
        if buf:
            offset = await uploads_service.write_chunk(db, client, upload, offset, bytes(buf))

        # tus has no explicit "finish" call: the upload is done the instant
        # the declared length is reached, and the server is expected to
        # notice and finalize on this same PATCH (PLAN.md §1: partial
        # uploads rename() onto dest_path on completion).
        if offset >= upload.size:
            await uploads_service.complete_upload(db, client, _ctx(session), upload)
    except UploadServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return Response(status_code=204, headers=_tus_headers({"Upload-Offset": str(offset)}))


@router.delete("/{upload_id}", status_code=204)
async def delete_upload(
    upload_id: str,
    db: OrmSession = Depends(get_db),
    client: FileWorkerClient = Depends(get_file_worker_client),
    session: DbSession = Depends(get_current_session),
) -> Response:
    upload = uploads_service.get_upload(db, upload_id)
    if upload is None or upload.uid != session.uid:
        raise HTTPException(status_code=404, detail="no such upload")
    try:
        await uploads_service.abort_upload(db, client, _ctx(session), upload)
    except UploadServiceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(status_code=204, headers=_tus_headers())
