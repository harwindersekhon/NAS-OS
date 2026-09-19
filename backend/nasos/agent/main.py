"""nasos-agent: the root daemon. Socket-activated on /run/nasos/agent.sock
(PLAN.md §1), it validates every request's peer credentials, dispatches to
the handlers registered in `nasos.agent.handlers`, and journals the result.

`--dev` (used by packaging/dev/nasos-agent-dev.service) trusts the invoking
uid instead of the `nasos` service account, since a developer's dev-mode web
process runs as themselves, not as `nasos`.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import socket
import struct
from pathlib import Path

from nasos.agent import handlers  # noqa: F401  (populates the dispatcher registry)
from nasos.agent.broadcaster import EventBroadcaster
from nasos.agent.dispatcher import Dispatcher
from nasos.agent.state import build_state
from nasos.config import Settings, get_settings
from nasos.rpc.schemas import RpcRequest

logger = logging.getLogger(__name__)

_LISTEN_FDS_START = 3
_SO_PEERCRED_STRUCT = "3i"  # pid_t, uid_t, gid_t


def _listen_socket_from_systemd() -> socket.socket | None:
    """LISTEN_FDS/LISTEN_PID per sd_listen_fds(3); None if not socket-activated."""
    listen_fds = os.environ.get("LISTEN_FDS")
    listen_pid = os.environ.get("LISTEN_PID")
    if not listen_fds or (listen_pid and int(listen_pid) != os.getpid()):
        return None
    if int(listen_fds) < 1:
        return None
    sock = socket.socket(fileno=_LISTEN_FDS_START)
    sock.setblocking(False)
    return sock


def _bind_socket(path: str) -> socket.socket:
    """Fallback for running outside systemd (manual dev invocation)."""
    sock_path = Path(path)
    sock_path.parent.mkdir(parents=True, exist_ok=True)
    if sock_path.exists():
        sock_path.unlink()
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.bind(str(sock_path))
    os.chmod(sock_path, 0o660)
    sock.setblocking(False)
    sock.listen(128)
    return sock


def _sd_notify(message: str) -> None:
    addr = os.environ.get("NOTIFY_SOCKET")
    if not addr:
        return
    if addr.startswith("@"):
        addr = "\0" + addr[1:]
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as sock:
        sock.connect(addr)
        sock.sendall(message.encode())


def _peercred_uid(sock: socket.socket) -> int:
    size = struct.calcsize(_SO_PEERCRED_STRUCT)
    raw = sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, size)
    _pid, uid, _gid = struct.unpack(_SO_PEERCRED_STRUCT, raw)
    return uid


def _trusted_uid(dev: bool) -> int:
    if dev:
        return os.getuid()
    import pwd

    return pwd.getpwnam("nasos").pw_uid


async def _handle_connection(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    dispatcher: Dispatcher,
    trusted_uid: int,
    broadcaster: EventBroadcaster | None = None,
) -> None:
    sock = writer.get_extra_info("socket")
    if sock is not None:
        peer_uid = _peercred_uid(sock)
        if peer_uid != 0 and peer_uid != trusted_uid:
            logger.warning("rejecting agent connection from untrusted uid=%d", peer_uid)
            writer.close()
            return
    if broadcaster is not None:
        broadcaster.register(writer)
    try:
        while True:
            line = await reader.readline()
            if not line:
                break
            asyncio.create_task(_handle_line(line, writer, dispatcher))
    finally:
        if broadcaster is not None:
            broadcaster.unregister(writer)
        writer.close()


async def _handle_line(line: bytes, writer: asyncio.StreamWriter, dispatcher: Dispatcher) -> None:
    try:
        request = RpcRequest.model_validate_json(line)
    except Exception:
        logger.warning("dropping malformed rpc frame")
        return
    response = await dispatcher.handle(request)
    writer.write(response.model_dump_json().encode() + b"\n")
    await writer.drain()


async def run(settings: Settings, *, dev: bool = False) -> None:
    broadcaster = EventBroadcaster()
    state = build_state(settings, broadcaster.publish, dev=dev)
    dispatcher = Dispatcher(state)
    trusted_uid = _trusted_uid(dev or settings.is_dev)

    # Reap fileworker children (and any other child process) as they exit,
    # so FileWorkerSupervisor.ensure() notices and respawns instead of
    # handing back a socket path nothing is listening on (PLAN.md §1
    # "fileworker lifecycle: spawn/reap/reconnect").
    asyncio.get_running_loop().add_signal_handler(signal.SIGCHLD, state.fileworkers.reap)

    sock = _listen_socket_from_systemd() or _bind_socket(settings.agent_socket)
    server = await asyncio.start_unix_server(
        lambda r, w: _handle_connection(r, w, dispatcher, trusted_uid, broadcaster),
        sock=sock,
    )
    _sd_notify(f"READY=1\nMAINPID={os.getpid()}")
    logger.info("nasos-agent listening on %s", settings.agent_socket)
    async with server:
        await server.serve_forever()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(prog="nasos-agent")
    parser.add_argument(
        "--dev",
        action="store_true",
        help="trust the invoking uid instead of the nasos service account",
    )
    args = parser.parse_args()
    asyncio.run(run(get_settings(), dev=args.dev))


if __name__ == "__main__":
    main()
