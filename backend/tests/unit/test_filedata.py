"""Unit tests for agent/filedata.py's write_chunk/read_range — the shared
byte-level I/O both the real fileworker's socket handler and dev mode's
DirectFileDataClient call (see that module's docstring)."""

from __future__ import annotations

from pathlib import Path

from nasos.agent import filedata


async def test_write_chunk_at_offset_zero(tmp_path: Path) -> None:
    part = tmp_path / "f.part"
    part.write_bytes(b"")
    new_offset = await filedata.write_chunk(str(part), 0, b"hello")
    assert new_offset == 5
    assert part.read_bytes() == b"hello"


async def test_write_chunk_appends_at_nonzero_offset(tmp_path: Path) -> None:
    part = tmp_path / "f.part"
    part.write_bytes(b"hello")
    new_offset = await filedata.write_chunk(str(part), 5, b" world")
    assert new_offset == 11
    assert part.read_bytes() == b"hello world"


async def test_read_range_full_file(tmp_path: Path) -> None:
    f = tmp_path / "f.bin"
    f.write_bytes(b"0123456789")
    chunks = [c async for c in filedata.read_range(str(f), 0, None)]
    assert b"".join(chunks) == b"0123456789"


async def test_read_range_partial(tmp_path: Path) -> None:
    f = tmp_path / "f.bin"
    f.write_bytes(b"0123456789")
    chunks = [c async for c in filedata.read_range(str(f), 2, 4)]
    assert b"".join(chunks) == b"2345"


async def test_read_range_respects_frame_size(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(filedata, "DOWNLOAD_FRAME_SIZE", 3)
    f = tmp_path / "f.bin"
    f.write_bytes(b"0123456789")
    chunks = [c async for c in filedata.read_range(str(f), 0, None)]
    assert chunks == [b"012", b"345", b"678", b"9"]
    assert b"".join(chunks) == b"0123456789"
