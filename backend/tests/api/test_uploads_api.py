"""tus upload endpoint tests (PLAN.md §5), API level: the milestone gate is
"upload/download 1 GiB file in dev mode with progress; resumable after
refresh; ownership correct" — the resumability test here is the one that
matters most: it deliberately throws away the client's in-memory offset
between two PATCHes and re-discovers it via a fresh HEAD, exactly like a
real browser refresh would force tus-js-client to do.
"""

from __future__ import annotations

import base64
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nasos.agent.state import AgentState
from tests.conftest import CSRF_HEADERS, login


def _metadata(**kv: str) -> str:
    return ",".join(f"{k} {base64.b64encode(v.encode()).decode()}" for k, v in kv.items())


def test_tus_options_advertises_creation_and_termination(client: TestClient) -> None:
    resp = client.options("/api/v1/uploads")
    assert resp.status_code == 204
    assert resp.headers["Tus-Resumable"] == "1.0.0"
    assert "creation" in resp.headers["Tus-Extension"]
    assert "termination" in resp.headers["Tus-Extension"]


def test_create_upload_requires_login(client: TestClient, tmp_path: Path) -> None:
    resp = client.post(
        "/api/v1/uploads",
        headers={
            **CSRF_HEADERS,
            "Upload-Length": "5",
            "Upload-Metadata": _metadata(filename="a.txt", dir=str(tmp_path)),
        },
    )
    assert resp.status_code == 401


def test_create_upload_returns_location(client: TestClient, tmp_path: Path) -> None:
    login(client, "alice", "alicepass123")
    resp = client.post(
        "/api/v1/uploads",
        headers={
            **CSRF_HEADERS,
            "Upload-Length": "5",
            "Upload-Metadata": _metadata(filename="a.txt", dir=str(tmp_path)),
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.headers["Tus-Resumable"] == "1.0.0"
    assert resp.headers["Location"].startswith("/api/v1/uploads/")


def test_create_upload_requires_length_header(client: TestClient, tmp_path: Path) -> None:
    login(client, "alice", "alicepass123")
    resp = client.post(
        "/api/v1/uploads",
        headers={**CSRF_HEADERS, "Upload-Metadata": _metadata(filename="a.txt", dir=str(tmp_path))},
    )
    assert resp.status_code == 400


def test_create_upload_requires_filename_and_dir_metadata(
    client: TestClient, tmp_path: Path
) -> None:
    login(client, "alice", "alicepass123")
    resp = client.post(
        "/api/v1/uploads",
        headers={
            **CSRF_HEADERS,
            "Upload-Length": "5",
            "Upload-Metadata": _metadata(filename="a.txt"),
        },
    )
    assert resp.status_code == 400


def _begin(client: TestClient, tmp_path: Path, *, filename: str, size: int) -> str:
    resp = client.post(
        "/api/v1/uploads",
        headers={
            **CSRF_HEADERS,
            "Upload-Length": str(size),
            "Upload-Metadata": _metadata(filename=filename, dir=str(tmp_path)),
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.headers["Location"].removeprefix("/api/v1/uploads/")


def test_full_upload_single_patch_completes_and_renames(client: TestClient, tmp_path: Path) -> None:
    login(client, "alice", "alicepass123")
    upload_id = _begin(client, tmp_path, filename="whole.bin", size=11)

    resp = client.patch(
        f"/api/v1/uploads/{upload_id}",
        headers={
            **CSRF_HEADERS,
            "Upload-Offset": "0",
            "Content-Type": "application/offset+octet-stream",
        },
        content=b"hello world",
    )
    assert resp.status_code == 204, resp.text
    assert resp.headers["Upload-Offset"] == "11"

    dest = tmp_path / "whole.bin"
    assert dest.read_bytes() == b"hello world"
    assert not (tmp_path / f".nasos-upload-{upload_id}.part").exists()


def test_upload_resumable_after_simulated_refresh(client: TestClient, tmp_path: Path) -> None:
    login(client, "alice", "alicepass123")
    payload = b"0123456789" * 100  # 1000 bytes
    upload_id = _begin(client, tmp_path, filename="resumed.bin", size=len(payload))

    first_half = payload[:400]
    resp = client.patch(
        f"/api/v1/uploads/{upload_id}",
        headers={
            **CSRF_HEADERS,
            "Upload-Offset": "0",
            "Content-Type": "application/offset+octet-stream",
        },
        content=first_half,
    )
    assert resp.status_code == 204
    assert resp.headers["Upload-Offset"] == "400"

    # "Refresh": the test forgets the offset it just got back and asks the
    # server fresh, exactly like tus-js-client does on resume.
    head = client.head(f"/api/v1/uploads/{upload_id}", headers=CSRF_HEADERS)
    assert head.status_code == 200
    assert head.headers["Upload-Offset"] == "400"
    assert head.headers["Upload-Length"] == str(len(payload))
    resumed_offset = int(head.headers["Upload-Offset"])

    second_half = payload[resumed_offset:]
    resp = client.patch(
        f"/api/v1/uploads/{upload_id}",
        headers={
            **CSRF_HEADERS,
            "Upload-Offset": str(resumed_offset),
            "Content-Type": "application/offset+octet-stream",
        },
        content=second_half,
    )
    assert resp.status_code == 204
    assert resp.headers["Upload-Offset"] == str(len(payload))

    dest = tmp_path / "resumed.bin"
    assert dest.read_bytes() == payload
    assert not (tmp_path / f".nasos-upload-{upload_id}.part").exists()


def test_patch_across_multiple_internal_buffer_flushes(client: TestClient, tmp_path: Path) -> None:
    """A single PATCH larger than the server's internal 1 MiB forwarding
    buffer (api/uploads.py's PATCH_BUFFER_SIZE) — exercises the chunking
    loop crossing several write_chunk calls within one request, the same
    code path a real multi-megabyte tus PATCH takes."""
    login(client, "alice", "alicepass123")
    size = 1024 * 1024 + 12345  # a bit over one internal buffer's worth
    payload = bytes((i % 251) for i in range(size))
    upload_id = _begin(client, tmp_path, filename="big.bin", size=size)

    resp = client.patch(
        f"/api/v1/uploads/{upload_id}",
        headers={
            **CSRF_HEADERS,
            "Upload-Offset": "0",
            "Content-Type": "application/offset+octet-stream",
        },
        content=payload,
    )
    assert resp.status_code == 204
    assert resp.headers["Upload-Offset"] == str(size)
    assert (tmp_path / "big.bin").read_bytes() == payload


def test_patch_with_mismatched_offset_returns_409(client: TestClient, tmp_path: Path) -> None:
    login(client, "alice", "alicepass123")
    upload_id = _begin(client, tmp_path, filename="a.bin", size=10)

    resp = client.patch(
        f"/api/v1/uploads/{upload_id}",
        headers={
            **CSRF_HEADERS,
            "Upload-Offset": "5",  # wrong: nothing written yet, server expects 0
            "Content-Type": "application/offset+octet-stream",
        },
        content=b"xxxxx",
    )
    assert resp.status_code == 409


def test_patch_requires_correct_content_type(client: TestClient, tmp_path: Path) -> None:
    login(client, "alice", "alicepass123")
    upload_id = _begin(client, tmp_path, filename="a.bin", size=5)

    resp = client.patch(
        f"/api/v1/uploads/{upload_id}",
        headers={**CSRF_HEADERS, "Upload-Offset": "0", "Content-Type": "text/plain"},
        content=b"hello",
    )
    assert resp.status_code == 415


def test_head_unknown_upload_404(client: TestClient) -> None:
    login(client, "alice", "alicepass123")
    resp = client.head("/api/v1/uploads/does-not-exist", headers=CSRF_HEADERS)
    assert resp.status_code == 404


def test_upload_isolated_per_user(client: TestClient, tmp_path: Path) -> None:
    """alice can't HEAD/PATCH an upload she didn't create."""
    login(client, "alice", "alicepass123")
    upload_id = _begin(client, tmp_path, filename="alices.bin", size=5)
    client.post("/api/v1/auth/logout", headers=CSRF_HEADERS)

    login(client, "admin", "adminpass123")
    resp = client.head(f"/api/v1/uploads/{upload_id}", headers=CSRF_HEADERS)
    assert resp.status_code == 404


def test_delete_upload_aborts_and_removes_part_file(client: TestClient, tmp_path: Path) -> None:
    login(client, "alice", "alicepass123")
    upload_id = _begin(client, tmp_path, filename="abandoned.bin", size=100)
    part_path = tmp_path / f".nasos-upload-{upload_id}.part"
    assert part_path.exists()

    resp = client.delete(f"/api/v1/uploads/{upload_id}", headers=CSRF_HEADERS)
    assert resp.status_code == 204
    assert not part_path.exists()

    assert client.head(f"/api/v1/uploads/{upload_id}", headers=CSRF_HEADERS).status_code == 404


def test_upload_rejected_when_declared_size_exceeds_free_space(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    dev_agent_state: AgentState,
) -> None:
    login(client, "admin", "adminpass123")
    volume_dir = tmp_path / "volume1"
    volume_dir.mkdir()
    dev_agent_state.mounts.mounts[str(volume_dir)] = "xfs"  # type: ignore[attr-defined]
    resp = client.post(
        "/api/v1/volumes",
        json={"name": "volume1", "mountpoint": str(volume_dir)},
        headers=CSRF_HEADERS,
    )
    assert resp.status_code == 200, resp.text

    from types import SimpleNamespace

    monkeypatch.setattr(
        "nasos.services.uploads.shutil.disk_usage",
        lambda _path: SimpleNamespace(free=10),
    )

    resp = client.post(
        "/api/v1/uploads",
        headers={
            **CSRF_HEADERS,
            "Upload-Length": "1000000",
            "Upload-Metadata": _metadata(filename="huge.bin", dir=str(volume_dir)),
        },
    )
    assert resp.status_code == 400
    assert "insufficient_space" in resp.text or "free" in resp.text
