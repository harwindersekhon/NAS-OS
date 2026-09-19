"""FileWorkerSupervisor (PLAN.md §1 "fileworker lifecycle: spawn/reap/
reconnect"). _bind_worker_socket's chown-to-"nasos" and _spawn_worker's
posix_spawn are real root-only/production-only operations, so this test
process (not root, no "nasos" system user) can't exercise ensure() fully
end to end — instead: _spawn_worker's exact posix_spawn call shape is
tested directly (by capturing the call, not letting it actually spawn);
ensure()'s reuse/respawn/track orchestration is tested with
_bind_worker_socket/_spawn_worker swapped for test-friendly equivalents;
_process_alive and reap() are tested against real (but harmless, this
process's own) subprocesses.
"""

from __future__ import annotations

import asyncio
import os
import socket
import subprocess
from pathlib import Path

import pytest

from nasos.agent import fileworker_supervisor as fws
from nasos.agent.fileworker_supervisor import FileWorkerSupervisor, _process_alive


def test_process_alive_true_for_running_process() -> None:
    proc = subprocess.Popen(["sleep", "5"])
    try:
        assert _process_alive(proc.pid) is True
    finally:
        proc.kill()
        proc.wait()


def test_process_alive_false_after_exit() -> None:
    proc = subprocess.Popen(["true"])
    proc.wait()
    assert _process_alive(proc.pid) is False


def test_spawn_worker_dup2s_socket_onto_fd_3(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_posix_spawn(path, argv, env, *, file_actions):  # noqa: ANN001
        captured["path"] = path
        captured["argv"] = argv
        captured["file_actions"] = file_actions
        return 12345

    monkeypatch.setattr(os, "posix_spawn", fake_posix_spawn)
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    expected_fd = sock.fileno()
    try:
        pid = fws._spawn_worker("/usr/libexec/nasos/nasos-fileworker", 6001, sock)

        assert pid == 12345
        assert captured["path"] == "/usr/libexec/nasos/nasos-fileworker"
        assert captured["argv"] == [
            "/usr/libexec/nasos/nasos-fileworker",
            "--uid",
            "6001",
            "--listen-fd",
            "3",
        ]
        assert captured["file_actions"] == [(os.POSIX_SPAWN_DUP2, expected_fd, 3)]
    finally:
        sock.close()


@pytest.fixture
def supervisor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FileWorkerSupervisor:
    """A supervisor whose socket-binding doesn't require root or a "nasos"
    system account, and whose "spawn" starts a real, harmless, easily
    reaped subprocess instead of the real nasos-fileworker binary — testing
    ensure()/reap()'s own orchestration logic, not the privileged bits."""

    def fake_bind(path: str) -> socket.socket:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.exists():
            p.unlink()
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.bind(path)
        sock.listen(1)
        return sock

    def fake_spawn(binary: str, uid: int, sock: socket.socket) -> int:  # noqa: ARG001
        proc = subprocess.Popen(["sleep", "5"])
        return proc.pid

    monkeypatch.setattr(fws, "_bind_worker_socket", fake_bind)
    monkeypatch.setattr(fws, "_spawn_worker", fake_spawn)
    return FileWorkerSupervisor(str(tmp_path / "run"))


async def test_ensure_spawns_then_reuses_alive_worker(supervisor: FileWorkerSupervisor) -> None:
    path1 = await supervisor.ensure(6001, "alice")
    path2 = await supervisor.ensure(6001, "alice")
    assert path1 == path2 == str(Path(supervisor._run_dir) / "workers" / "6001.sock")  # noqa: SLF001
    assert len(supervisor._workers) == 1  # noqa: SLF001


async def test_ensure_respawns_after_worker_dies(
    supervisor: FileWorkerSupervisor, monkeypatch: pytest.MonkeyPatch
) -> None:
    await supervisor.ensure(6001, "alice")
    first_pid = supervisor._workers[6001].pid  # noqa: SLF001

    monkeypatch.setattr(fws, "_process_alive", lambda pid: False)  # noqa: ARG005
    await supervisor.ensure(6001, "alice")
    second_pid = supervisor._workers[6001].pid  # noqa: SLF001
    assert second_pid != first_pid


async def test_reap_drops_dead_worker_from_tracking(supervisor: FileWorkerSupervisor) -> None:
    await supervisor.ensure(6001, "alice")
    pid = supervisor._workers[6001].pid  # noqa: SLF001
    os.kill(pid, 9)

    # No os.waitpid faking: reap() calls the real syscall against our own
    # real (now-dead) child, exactly like it would for a real fileworker.
    for _ in range(200):
        if 6001 not in supervisor._workers:  # noqa: SLF001
            break
        supervisor.reap()
        await asyncio.sleep(0.01)

    assert 6001 not in supervisor._workers  # noqa: SLF001
    assert pid not in supervisor._pid_to_uid  # noqa: SLF001
