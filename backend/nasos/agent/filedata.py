"""Byte-level I/O primitives for uploads/downloads (PLAN.md §1): the actual
read()/write() logic behind both the real fileworker's raw-socket binary
frame ops (agent/fileworker.py's `_op_upload_chunk`/`_op_download_range`)
and dev mode's in-process DirectFileDataClient (rpc/client.py) — one
implementation of "write N bytes at this offset" / "read this byte range"
regardless of which path is driving it, so the two can never drift.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator

DOWNLOAD_FRAME_SIZE = 1024 * 1024


async def write_chunk(part_path: str, offset: int, data: bytes) -> int:
    """Writes `data` at `offset` into the .part file, fsync'd, returning the
    file's new total size (used to report the tus Upload-Offset back)."""

    def _write() -> int:
        with open(part_path, "r+b") as fh:
            fh.seek(offset)
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
            return fh.tell()

    return await asyncio.to_thread(_write)


async def read_range(path: str, offset: int, length: int | None) -> AsyncIterator[bytes]:
    """Yields `path`'s bytes from `offset`, in DOWNLOAD_FRAME_SIZE pieces,
    for `length` bytes or to EOF if `length` is None (whole-file / open-
    ended Range download)."""
    size = await asyncio.to_thread(os.path.getsize, path)
    remaining = size - offset if length is None else length
    if remaining < 0:
        remaining = 0

    fh = await asyncio.to_thread(open, path, "rb")
    try:
        await asyncio.to_thread(fh.seek, offset)
        while remaining > 0:
            chunk = await asyncio.to_thread(fh.read, min(DOWNLOAD_FRAME_SIZE, remaining))
            if not chunk:
                break
            yield chunk
            remaining -= len(chunk)
    finally:
        await asyncio.to_thread(fh.close)
