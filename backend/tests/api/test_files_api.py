"""files REST API tests (PLAN.md §5), API level: browse/mutate/download
through the real HTTP routes, dev mode's in-process WorkerState/FakeAcl
underneath (same wiring `make dev` uses)."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from fastapi.testclient import TestClient

from nasos.agent.state import AgentState
from nasos.system.runner import FakeRunner
from nasos.system.samba import NASOS_CONF, SMB_CONF
from tests.conftest import CSRF_HEADERS, login


def test_files_routes_require_login(client: TestClient, tmp_path: Path) -> None:
    resp = client.get("/api/v1/files/list", params={"path": str(tmp_path)})
    assert resp.status_code == 401


def test_roots_is_empty_with_no_shares(client: TestClient) -> None:
    login(client, "alice", "alicepass123")
    resp = client.get("/api/v1/files/roots", headers=CSRF_HEADERS)
    assert resp.status_code == 200
    assert resp.json() == []


def test_roots_lists_registered_shares(
    client: TestClient, tmp_path: Path, dev_agent_state: AgentState
) -> None:
    login(client, "admin", "adminpass123")
    mountpoint = str(tmp_path / "vol1")
    dev_agent_state.mounts.mounts[mountpoint] = "xfs"  # type: ignore[attr-defined]
    resp = client.post(
        "/api/v1/volumes", json={"name": "volume1", "mountpoint": mountpoint}, headers=CSRF_HEADERS
    )
    assert resp.status_code == 200, resp.text
    volume_id = resp.json()["id"]

    runner = cast(FakeRunner, dev_agent_state.runner)
    runner.expect(
        ["testparm", "-s", "--suppress-prompt", "/etc/samba/smb.conf"],
        stdout="Loaded services file OK.\n",
    )
    nasos_conf_path = str(Path(dev_agent_state.settings.system_path(NASOS_CONF)))
    runner.expect(["restorecon", nasos_conf_path])
    smb_conf_path = str(Path(dev_agent_state.settings.system_path(SMB_CONF)))
    runner.expect(["restorecon", smb_conf_path])

    resp = client.post(
        "/api/v1/shares",
        json={"name": "media", "volume_id": volume_id, "description": "Media"},
        headers=CSRF_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    share = resp.json()

    resp = client.get("/api/v1/files/roots", headers=CSRF_HEADERS)
    assert resp.status_code == 200
    assert resp.json() == [{"id": share["id"], "name": "media", "path": share["path"]}]


def test_list_mkdir_rename_delete_roundtrip(client: TestClient, tmp_path: Path) -> None:
    login(client, "alice", "alicepass123")
    # A fresh subdirectory, not tmp_path itself: dev-mode's build_state()
    # seeds tmp_path/devdata/{volume1,volume2} as a side effect of app
    # startup (conftest.py's settings fixture points devdata_dir there),
    # which would otherwise show up alongside "photos" in the listing.
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    resp = client.post(
        "/api/v1/files/mkdir", json={"path": str(workspace / "photos")}, headers=CSRF_HEADERS
    )
    assert resp.status_code == 200, resp.text

    resp = client.get("/api/v1/files/list", params={"path": str(workspace)}, headers=CSRF_HEADERS)
    assert resp.status_code == 200
    names = [e["name"] for e in resp.json()["entries"]]
    assert names == ["photos"]

    resp = client.post(
        "/api/v1/files/rename",
        json={"path": str(workspace / "photos"), "new_name": "pictures"},
        headers=CSRF_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    assert (workspace / "pictures").is_dir()

    resp = client.post(
        "/api/v1/files/delete", json={"paths": [str(workspace / "pictures")]}, headers=CSRF_HEADERS
    )
    assert resp.status_code == 200, resp.text
    job_id = resp.json()["job_id"]
    assert job_id is not None
    _wait_for_job_done(client, job_id)
    assert not (workspace / "pictures").exists()


def _wait_for_job_done(client: TestClient, job_id: str) -> None:
    import time

    for _ in range(200):
        resp = client.get("/api/v1/files/jobs", headers=CSRF_HEADERS)
        (job,) = [j for j in resp.json()["jobs"] if j["id"] == job_id]
        if job["status"] in ("done", "failed", "cancelled"):
            assert job["status"] == "done", job
            return
        time.sleep(0.01)
    raise AssertionError("job never finished")


def test_copy_then_move_job(client: TestClient, tmp_path: Path) -> None:
    login(client, "alice", "alicepass123")
    src = tmp_path / "a.txt"
    src.write_text("hello")
    dest1 = tmp_path / "dest1"
    dest1.mkdir()
    dest2 = tmp_path / "dest2"
    dest2.mkdir()

    resp = client.post(
        "/api/v1/files/copy",
        json={"sources": [str(src)], "dest_dir": str(dest1)},
        headers=CSRF_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    _wait_for_job_done(client, resp.json()["job_id"])
    assert src.exists()
    assert (dest1 / "a.txt").read_text() == "hello"

    resp = client.post(
        "/api/v1/files/move",
        json={"sources": [str(dest1 / "a.txt")], "dest_dir": str(dest2)},
        headers=CSRF_HEADERS,
    )
    assert resp.status_code == 200, resp.text
    _wait_for_job_done(client, resp.json()["job_id"])
    assert not (dest1 / "a.txt").exists()
    assert (dest2 / "a.txt").read_text() == "hello"


def test_properties_reports_size_and_owner(client: TestClient, tmp_path: Path) -> None:
    login(client, "alice", "alicepass123")
    f = tmp_path / "notes.txt"
    f.write_text("hello world")

    resp = client.get("/api/v1/files/properties", params={"path": str(f)}, headers=CSRF_HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["size"] == 11
    assert body["is_dir"] is False
    assert body["name"] == "notes.txt"


def test_properties_missing_path_404(client: TestClient, tmp_path: Path) -> None:
    login(client, "alice", "alicepass123")
    resp = client.get(
        "/api/v1/files/properties", params={"path": str(tmp_path / "nope")}, headers=CSRF_HEADERS
    )
    assert resp.status_code == 404


def test_acl_get_set_roundtrip(client: TestClient, tmp_path: Path) -> None:
    login(client, "alice", "alicepass123")
    target = tmp_path / "shared"
    target.mkdir()

    resp = client.put(
        "/api/v1/files/acl",
        json={
            "path": str(target),
            "entries": [{"kind": "user", "numeric_id": 5001, "level": "rw"}],
            "recursive": False,
        },
        headers=CSRF_HEADERS,
    )
    assert resp.status_code == 200, resp.text

    resp = client.get("/api/v1/files/acl", params={"path": str(target)}, headers=CSRF_HEADERS)
    assert resp.status_code == 200
    assert resp.json()["entries"] == [{"kind": "user", "numeric_id": 5001, "level": "rw"}]


def test_content_downloads_full_file(client: TestClient, tmp_path: Path) -> None:
    login(client, "alice", "alicepass123")
    f = tmp_path / "report.txt"
    f.write_text("the quick brown fox")

    resp = client.get("/api/v1/files/content", params={"path": str(f)}, headers=CSRF_HEADERS)
    assert resp.status_code == 200
    assert resp.content == b"the quick brown fox"
    assert resp.headers["Content-Length"] == "19"
    assert 'filename="report.txt"' in resp.headers["Content-Disposition"]


def test_content_supports_range_requests(client: TestClient, tmp_path: Path) -> None:
    login(client, "alice", "alicepass123")
    f = tmp_path / "data.bin"
    f.write_bytes(b"0123456789")

    resp = client.get(
        "/api/v1/files/content",
        params={"path": str(f)},
        headers={**CSRF_HEADERS, "Range": "bytes=2-5"},
    )
    assert resp.status_code == 206
    assert resp.content == b"2345"
    assert resp.headers["Content-Range"] == "bytes 2-5/10"


def test_zip_then_download(client: TestClient, tmp_path: Path) -> None:
    login(client, "alice", "alicepass123")
    src = tmp_path / "album"
    src.mkdir()
    (src / "1.jpg").write_bytes(b"aaa")
    (src / "2.jpg").write_bytes(b"bbb")

    resp = client.post("/api/v1/files/zip", json={"sources": [str(src)]}, headers=CSRF_HEADERS)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    _wait_for_job_done(client, body["job_id"])

    resp = client.get(
        "/api/v1/files/content",
        params={"path": body["dest_path"], "disposition": "attachment"},
        headers=CSRF_HEADERS,
    )
    assert resp.status_code == 200
    assert resp.headers["Content-Disposition"].startswith("attachment")

    import io
    import zipfile

    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        assert set(zf.namelist()) == {"album/1.jpg", "album/2.jpg"}
