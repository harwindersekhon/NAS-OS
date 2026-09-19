"""Integration-style tests for the files.* RPC surface (Milestone 3):
request -> Dispatcher -> handler -> real filesystem under tmp_path. No
FakeRunner needed here — unlike setfacl/smbpasswd/systemd, "list a
directory" and "rename a file" are direct os.* calls with nothing to fake,
same as M2's managedfile.py render/validate logic was tested directly.
"""

from __future__ import annotations

import asyncio
import os
import zipfile
from pathlib import Path

import pytest

from nasos.agent.dispatcher import Dispatcher
from nasos.agent.handlers import files as _files_handlers  # noqa: F401
from nasos.agent.handlers import uploads as _upload_handlers  # noqa: F401
from nasos.agent.jobs import JobRunner
from nasos.agent.workerstate import WorkerState
from nasos.rpc.schemas import RpcRequest
from nasos.system.acl import FakeAcl


@pytest.fixture
def state(tmp_path: Path) -> WorkerState:
    jobs = JobRunner(str(tmp_path / "jobs.jsonl"), on_event=lambda *_a: None)
    return WorkerState(uid=os.getuid(), username="tester", jobs=jobs, acl=FakeAcl(), uploads={})


@pytest.fixture
def dispatcher(state: WorkerState) -> Dispatcher:
    return Dispatcher(state)


async def call(dispatcher: Dispatcher, method: str, **params: object) -> dict[str, object]:
    resp = await dispatcher.handle(RpcRequest(id="1", method=method, params=params))
    assert resp.ok, resp.error
    assert resp.result is not None
    return resp.result


async def call_error(dispatcher: Dispatcher, method: str, **params: object) -> str:
    resp = await dispatcher.handle(RpcRequest(id="1", method=method, params=params))
    assert not resp.ok
    assert resp.error is not None
    return resp.error.code


async def wait_for_job(state: WorkerState, job_id: str) -> dict[str, object]:
    for _ in range(200):
        (record,) = [j for j in state.jobs.list() if j["id"] == job_id]
        if record["status"] in ("done", "failed", "cancelled"):
            return record
        await asyncio.sleep(0.01)
    raise AssertionError(f"job {job_id} never finished")


# --- list / search -----------------------------------------------------


async def test_list_sorts_dirs_first_then_alpha(dispatcher: Dispatcher, tmp_path: Path) -> None:
    (tmp_path / "zebra.txt").write_text("z")
    (tmp_path / "apple.txt").write_text("a")
    (tmp_path / "beta_dir").mkdir()

    result = await call(dispatcher, "files.list", path=str(tmp_path))
    names = [e["name"] for e in result["entries"]]  # type: ignore[attr-defined]
    assert names == ["beta_dir", "apple.txt", "zebra.txt"]


async def test_list_skips_entries_that_vanish(dispatcher: Dispatcher, tmp_path: Path) -> None:
    (tmp_path / "keep.txt").write_text("x")
    result = await call(dispatcher, "files.list", path=str(tmp_path))
    assert len(result["entries"]) == 1  # type: ignore[arg-type]


async def test_list_missing_dir_is_not_found(dispatcher: Dispatcher, tmp_path: Path) -> None:
    code = await call_error(dispatcher, "files.list", path=str(tmp_path / "nope"))
    assert code == "not_found"


async def test_search_matches_substring_case_insensitive(
    dispatcher: Dispatcher, tmp_path: Path
) -> None:
    (tmp_path / "Report.PDF").write_text("x")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "report_final.txt").write_text("x")
    (tmp_path / "other.doc").write_text("x")

    result = await call(dispatcher, "files.search", path=str(tmp_path), query="report")
    names = {e["name"] for e in result["entries"]}  # type: ignore[attr-defined]
    assert names == {"Report.PDF", "report_final.txt"}


# --- mkdir / rename ------------------------------------------------------


async def test_mkdir_creates_directory(dispatcher: Dispatcher, tmp_path: Path) -> None:
    target = tmp_path / "new_folder"
    await call(dispatcher, "files.mkdir", path=str(target))
    assert target.is_dir()


async def test_mkdir_existing_fails(dispatcher: Dispatcher, tmp_path: Path) -> None:
    target = tmp_path / "dup"
    target.mkdir()
    code = await call_error(dispatcher, "files.mkdir", path=str(target))
    assert code == "already_exists"


async def test_rename_moves_within_same_dir(dispatcher: Dispatcher, tmp_path: Path) -> None:
    src = tmp_path / "old.txt"
    src.write_text("hi")
    await call(dispatcher, "files.rename", path=str(src), new_name="new.txt")
    assert not src.exists()
    assert (tmp_path / "new.txt").read_text() == "hi"


async def test_rename_onto_existing_fails(dispatcher: Dispatcher, tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "b.txt").write_text("b")
    code = await call_error(
        dispatcher, "files.rename", path=str(tmp_path / "a.txt"), new_name="b.txt"
    )
    assert code == "already_exists"


async def test_rename_rejects_path_separator_in_new_name(
    dispatcher: Dispatcher, tmp_path: Path
) -> None:
    src = tmp_path / "a.txt"
    src.write_text("a")
    code = await call_error(dispatcher, "files.rename", path=str(src), new_name="sub/evil.txt")
    assert code == "invalid_params"


# --- delete / copy / move (jobs) -----------------------------------------


async def test_delete_job_removes_file_and_dir(
    dispatcher: Dispatcher, state: WorkerState, tmp_path: Path
) -> None:
    f = tmp_path / "f.txt"
    f.write_text("x")
    d = tmp_path / "d"
    (d / "nested").mkdir(parents=True)

    result = await call(dispatcher, "files.delete", paths=[str(f), str(d)])
    record = await wait_for_job(state, result["job_id"])  # type: ignore[arg-type]
    assert record["status"] == "done"
    assert not f.exists()
    assert not d.exists()


async def test_copy_job_preserves_source(
    dispatcher: Dispatcher, state: WorkerState, tmp_path: Path
) -> None:
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    f = src_dir / "f.txt"
    f.write_text("hello")
    dest_dir = tmp_path / "dest"
    dest_dir.mkdir()

    result = await call(dispatcher, "files.copy", sources=[str(f)], dest_dir=str(dest_dir))
    record = await wait_for_job(state, result["job_id"])  # type: ignore[arg-type]
    assert record["status"] == "done"
    assert f.read_text() == "hello"
    assert (dest_dir / "f.txt").read_text() == "hello"


async def test_move_job_removes_source(
    dispatcher: Dispatcher, state: WorkerState, tmp_path: Path
) -> None:
    f = tmp_path / "f.txt"
    f.write_text("hello")
    dest_dir = tmp_path / "dest"
    dest_dir.mkdir()

    result = await call(dispatcher, "files.move", sources=[str(f)], dest_dir=str(dest_dir))
    record = await wait_for_job(state, result["job_id"])  # type: ignore[arg-type]
    assert record["status"] == "done"
    assert not f.exists()
    assert (dest_dir / "f.txt").read_text() == "hello"


async def test_copy_job_fails_on_existing_dest(
    dispatcher: Dispatcher, state: WorkerState, tmp_path: Path
) -> None:
    f = tmp_path / "f.txt"
    f.write_text("hello")
    dest_dir = tmp_path / "dest"
    dest_dir.mkdir()
    (dest_dir / "f.txt").write_text("already here")

    result = await call(dispatcher, "files.copy", sources=[str(f)], dest_dir=str(dest_dir))
    record = await wait_for_job(state, result["job_id"])  # type: ignore[arg-type]
    assert record["status"] == "failed"
    assert (dest_dir / "f.txt").read_text() == "already here"


# --- zip -------------------------------------------------------------


async def test_zip_job_archives_directory_tree(
    dispatcher: Dispatcher, state: WorkerState, tmp_path: Path
) -> None:
    src = tmp_path / "photos"
    (src / "sub").mkdir(parents=True)
    (src / "a.jpg").write_text("aaa")
    (src / "sub" / "b.jpg").write_text("bbb")
    dest_zip = tmp_path / "out.zip"

    result = await call(dispatcher, "files.zip", sources=[str(src)], dest_path=str(dest_zip))
    record = await wait_for_job(state, result["job_id"])  # type: ignore[arg-type]
    assert record["status"] == "done"

    with zipfile.ZipFile(dest_zip) as zf:
        names = set(zf.namelist())
        assert names == {"photos/a.jpg", "photos/sub/b.jpg"}
        assert zf.read("photos/a.jpg") == b"aaa"
        # store-only, per PLAN.md §5
        for info in zf.infolist():
            assert info.compress_type == zipfile.ZIP_STORED


# --- properties -----------------------------------------------------


async def test_properties_reports_file_stat(dispatcher: Dispatcher, tmp_path: Path) -> None:
    f = tmp_path / "f.txt"
    f.write_text("hello world")
    result = await call(dispatcher, "files.properties", path=str(f))
    assert result["is_dir"] is False
    assert result["size"] == 11
    assert result["owner_uid"] == os.getuid()
    assert result["item_count"] is None
    assert len(result["mode"]) == 9  # type: ignore[arg-type]


async def test_properties_reports_dir_item_count(dispatcher: Dispatcher, tmp_path: Path) -> None:
    d = tmp_path / "d"
    d.mkdir()
    (d / "a").write_text("a")
    (d / "b").write_text("b")
    result = await call(dispatcher, "files.properties", path=str(d))
    assert result["is_dir"] is True
    assert result["item_count"] == 2


# --- ACL ---------------------------------------------------------------


async def test_acl_round_trips_through_replace_all(
    dispatcher: Dispatcher, state: WorkerState, tmp_path: Path
) -> None:
    target = str(tmp_path / "shared")
    os.mkdir(target)

    await call(
        dispatcher,
        "files.set_acl",
        path=target,
        entries=[{"kind": "user", "numeric_id": 5001, "level": "rw"}],
        recursive=False,
    )
    result = await call(dispatcher, "files.get_acl", path=target)
    assert result["entries"] == [{"kind": "user", "numeric_id": 5001, "level": "rw"}]


async def test_acl_recursive_runs_as_job(
    dispatcher: Dispatcher, state: WorkerState, tmp_path: Path
) -> None:
    target = str(tmp_path / "shared")
    os.mkdir(target)

    result = await call(
        dispatcher,
        "files.set_acl",
        path=target,
        entries=[{"kind": "group", "numeric_id": 6001, "level": "ro"}],
        recursive=True,
    )
    assert result["job_id"] is not None
    record = await wait_for_job(state, result["job_id"])  # type: ignore[arg-type]
    assert record["status"] == "done"


# --- uploads -------------------------------------------------------------


async def test_upload_lifecycle_begin_write_complete(
    dispatcher: Dispatcher, state: WorkerState, tmp_path: Path
) -> None:
    dest = tmp_path / "photo.jpg"
    await call(dispatcher, "files.upload_begin", upload_id="u1", dest_path=str(dest), size=5)

    part_path = tmp_path / ".nasos-upload-u1.part"
    assert part_path.exists()

    from nasos.agent import filedata

    offset = await filedata.write_chunk(str(part_path), 0, b"hello")
    assert offset == 5

    result = await call(dispatcher, "files.upload_offset", upload_id="u1")
    assert result["offset"] == 5

    await call(dispatcher, "files.upload_complete", upload_id="u1")
    assert not part_path.exists()
    assert dest.read_bytes() == b"hello"
    assert "u1" not in state.uploads


async def test_upload_begin_fails_if_dest_exists(dispatcher: Dispatcher, tmp_path: Path) -> None:
    dest = tmp_path / "existing.txt"
    dest.write_text("already there")
    code = await call_error(
        dispatcher, "files.upload_begin", upload_id="u2", dest_path=str(dest), size=1
    )
    assert code == "already_exists"


async def test_upload_abort_removes_part_file(
    dispatcher: Dispatcher, state: WorkerState, tmp_path: Path
) -> None:
    dest = tmp_path / "abandoned.bin"
    await call(dispatcher, "files.upload_begin", upload_id="u3", dest_path=str(dest), size=100)
    part_path = tmp_path / ".nasos-upload-u3.part"
    assert part_path.exists()

    await call(dispatcher, "files.upload_abort", upload_id="u3")
    assert not part_path.exists()
    assert not dest.exists()
    assert "u3" not in state.uploads


async def test_upload_offset_unknown_id_is_not_found(dispatcher: Dispatcher) -> None:
    code = await call_error(dispatcher, "files.upload_offset", upload_id="ghost")
    assert code == "not_found"
