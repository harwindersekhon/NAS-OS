"""Spawns, tracks, and reaps per-user nasos-fileworker child processes
(PLAN.md §1's "fileworker lifecycle: spawn/reap/reconnect", Milestone 3).

Lives entirely in the root agent process — never imported by the worker
itself or by dev mode's direct-dispatch shortcut (services/files.py calls
files.* straight through the shared dev dispatcher, no real child process
or socket involved there). Only ever constructed for real in build_state(),
same as every other adapter.

The agent binds and owns the socket file; the child only ever sees an
already-listening fd 3 (see agent/fileworker.py's module docstring for why
that means there's no readiness race to wait out here).
"""

from __future__ import annotations

import logging
import os
import pwd
import socket
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

FILEWORKER_BINARY = "/usr/libexec/nasos/nasos-fileworker"


@dataclass
class _Worker:
    pid: int
    socket_path: str


class FileWorkerSupervisor:
    def __init__(self, run_dir: str, *, binary: str = FILEWORKER_BINARY) -> None:
        self._run_dir = run_dir
        self._binary = binary
        self._workers: dict[int, _Worker] = {}
        self._pid_to_uid: dict[int, int] = {}

    def _socket_path(self, uid: int) -> str:
        return f"{self._run_dir}/workers/{uid}.sock"

    async def ensure(self, uid: int, username: str) -> str:
        existing = self._workers.get(uid)
        if existing is not None and _process_alive(existing.pid):
            return existing.socket_path

        socket_path = self._socket_path(uid)
        sock = _bind_worker_socket(socket_path)
        try:
            pid = _spawn_worker(self._binary, uid, sock)
        finally:
            # The child's fd 3 is an independent dup(); our copy can close.
            sock.close()

        self._workers[uid] = _Worker(pid=pid, socket_path=socket_path)
        self._pid_to_uid[pid] = uid
        logger.info("spawned nasos-fileworker uid=%d (%s) pid=%d", uid, username, pid)
        return socket_path

    def reap(self) -> None:
        """Call from a SIGCHLD handler. Reaps every exited child (not just
        fileworkers, mirroring a shell reaping any of its children) and
        drops dead workers from tracking, so the next ensure() respawns
        instead of handing back a stale socket path nothing is listening
        on any more.
        """
        while True:
            try:
                pid, _status = os.waitpid(-1, os.WNOHANG)
            except ChildProcessError:
                break
            if pid == 0:
                break
            uid = self._pid_to_uid.pop(pid, None)
            if uid is None:
                continue
            worker = self._workers.get(uid)
            if worker is not None and worker.pid == pid:
                del self._workers[uid]
                logger.info("reaped nasos-fileworker uid=%d pid=%d", uid, pid)


def _process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _bind_worker_socket(path: str) -> socket.socket:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        p.unlink()
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.bind(path)
    nasos = pwd.getpwnam("nasos")
    os.chown(path, nasos.pw_uid, nasos.pw_gid)
    os.chmod(path, 0o600)
    sock.listen(16)
    return sock


def _spawn_worker(binary: str, uid: int, sock: socket.socket) -> int:
    argv = [binary, "--uid", str(uid), "--listen-fd", "3"]
    return os.posix_spawn(
        binary,
        argv,
        dict(os.environ),
        file_actions=[(os.POSIX_SPAWN_DUP2, sock.fileno(), 3)],
    )
