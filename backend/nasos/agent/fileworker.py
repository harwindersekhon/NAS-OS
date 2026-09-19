"""nasos-fileworker: per-user file I/O worker, spawned by the agent and
dropped to the logged-in user's uid/gid (PLAN.md §1 "File Station as the
logged-in user").

The agent creates and binds `/run/nasos/workers/<uid>.sock` (`nasos:nasos
0600`) *before* spawning this process, passing the already-listening socket
as fd 3 — so there is no readiness race: any connection the web process
makes queues in the kernel backlog even before this process calls accept(),
exactly like systemd socket activation (see agent/handlers/fileworker.py for
the spawn side). This process just drops privileges, opens the inherited
fd, and serves.

Wire protocol: newline-delimited JSON, same envelope as the agent socket
(RpcRequest/RpcResponse/RpcEvent, dispatched through the same
Dispatcher/REGISTRY/@handler machinery agent/handlers/files.py registers
into) for every metadata call. Bulk file bytes never go through that
machinery — PLAN.md §1's "optional binary frame (`{"bin": N}` header
followed by N bytes)" is a *separate*, hand-rolled framing used only by the
upload_chunk and download_range ops, handled by `_handle_op_line` before a
line is ever treated as an RpcRequest (a zip download is just a
download_range against the temp file files.zip already wrote — no separate
wire op needed). One request or op is processed fully (including reading
its binary frame, if any) before the next line is read — no pipelining on
this connection, unlike the agent socket — which is what makes an in-band
binary frame safe to read here without racing a concurrently-dispatched
neighbor request for the same bytes on the wire. A client that wants
concurrent file operations opens another connection; the socket is cheap
and local.
"""

from __future__ import annotations

import argparse
import asyncio
import ctypes
import json
import logging
import os
import pwd
import socket
import struct
import time
from typing import Any

from nasos.agent import filedata
from nasos.agent.broadcaster import EventBroadcaster
from nasos.agent.dispatcher import Dispatcher
from nasos.agent.jobs import JobRunner
from nasos.agent.workerstate import WorkerState
from nasos.config import Settings, get_settings
from nasos.rpc.schemas import RpcRequest

logger = logging.getLogger(__name__)

IDLE_TIMEOUT_SECONDS = 15 * 60
IDLE_CHECK_INTERVAL_SECONDS = 30
_SO_PEERCRED_STRUCT = "3i"  # pid_t, uid_t, gid_t
_PR_SET_NO_NEW_PRIVS = 38


def _drop_privileges(uid: int) -> str:
    """initgroups, setgid, setuid, prctl(NO_NEW_PRIVS), umask 002 — exact
    order from PLAN.md §1. Must run before anything else touches the
    filesystem or network on this process's behalf.
    """
    pw = pwd.getpwuid(uid)
    os.initgroups(pw.pw_name, pw.pw_gid)
    os.setgid(pw.pw_gid)
    os.setuid(uid)
    _set_no_new_privs()
    os.umask(0o002)
    return pw.pw_name


def _set_no_new_privs() -> None:
    libc = ctypes.CDLL("libc.so.6", use_errno=True)
    if libc.prctl(_PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
        errno = ctypes.get_errno()
        raise OSError(errno, os.strerror(errno), "prctl(PR_SET_NO_NEW_PRIVS)")


def _peercred_uid(sock: socket.socket) -> int:
    size = struct.calcsize(_SO_PEERCRED_STRUCT)
    raw = sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, size)
    _pid, uid, _gid = struct.unpack(_SO_PEERCRED_STRUCT, raw)
    return uid


def _trusted_uid() -> int:
    """Only the web process (User=nasos in nasos.service) or root may
    connect — matches the socket's own nasos:nasos 0600 ownership. Unlike
    agent/main.py's _trusted_uid, there's no --dev variant: this process
    never runs in dev mode at all (see module docstring)."""
    return pwd.getpwnam("nasos").pw_uid


class _IdleTracker:
    def __init__(self) -> None:
        self.last_activity = time.monotonic()

    def touch(self) -> None:
        self.last_activity = time.monotonic()

    async def watch(self, server: asyncio.Server) -> None:
        """Closing the server cancels serve_forever()'s internal future, so
        `run()`'s `await server.serve_forever()` raises CancelledError and
        the process exits cleanly — see run()'s try/except around it."""
        while True:
            await asyncio.sleep(IDLE_CHECK_INTERVAL_SECONDS)
            if time.monotonic() - self.last_activity >= IDLE_TIMEOUT_SECONDS:
                logger.info("fileworker idle for %ds, exiting", IDLE_TIMEOUT_SECONDS)
                server.close()
                return


async def _handle_op_line(
    op: dict[str, Any],
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    state: WorkerState,
) -> None:
    """The binary-frame ops: upload_chunk (reads a `{"bin": N}` frame off
    the wire and writes it to the upload's .part file) and download_range /
    download_zip (writes the requested bytes back as a sequence of `{"bin":
    N}` frames). Not RPC — see module docstring.
    """
    try:
        kind = op.get("op")
        if kind == "upload_chunk":
            await _op_upload_chunk(op, reader, writer, state)
        elif kind == "download_range":
            await _op_download_range(op, writer, state)
        else:
            await _write_json(writer, {"ok": False, "error": f"unknown op: {kind!r}"})
    except OSError as exc:
        await _write_json(writer, {"ok": False, "error": str(exc)})


async def _read_bin_frame(reader: asyncio.StreamReader) -> bytes:
    header_line = await reader.readline()
    if not header_line:
        raise OSError("connection closed before binary frame header")
    header = json.loads(header_line)
    length = int(header["bin"])
    return await reader.readexactly(length)


async def _write_json(writer: asyncio.StreamWriter, obj: dict[str, Any]) -> None:
    writer.write(json.dumps(obj).encode() + b"\n")
    await writer.drain()


async def _op_upload_chunk(
    op: dict[str, Any],
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    state: WorkerState,
) -> None:
    upload_id = op["upload_id"]
    offset = int(op["offset"])
    data = await _read_bin_frame(reader)

    handle = state.uploads.get(upload_id)
    if handle is None:
        await _write_json(writer, {"ok": False, "error": f"unknown upload_id: {upload_id}"})
        return

    new_offset = await filedata.write_chunk(handle.part_path, offset, data)
    await _write_json(writer, {"ok": True, "offset": new_offset})


async def _op_download_range(
    op: dict[str, Any],
    writer: asyncio.StreamWriter,
    state: WorkerState,  # noqa: ARG001
) -> None:
    path = op["path"]
    offset = int(op.get("offset", 0))
    length = op.get("length")
    length = int(length) if length is not None else None

    async for chunk in filedata.read_range(path, offset, length):
        writer.write(json.dumps({"bin": len(chunk)}).encode() + b"\n")
        writer.write(chunk)
        await writer.drain()
    await _write_json(writer, {"ok": True})


async def _handle_connection(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    dispatcher: Dispatcher,
    state: WorkerState,
    trusted_uid: int,
    broadcaster: EventBroadcaster,
    idle: _IdleTracker,
) -> None:
    sock = writer.get_extra_info("socket")
    if sock is not None:
        peer_uid = _peercred_uid(sock)
        if peer_uid != 0 and peer_uid != trusted_uid:
            logger.warning("rejecting fileworker connection from untrusted uid=%d", peer_uid)
            writer.close()
            return
    broadcaster.register(writer)
    try:
        while True:
            line = await reader.readline()
            if not line:
                break
            idle.touch()
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("dropping malformed fileworker frame")
                continue
            if raw.get("type") == "request":
                request = RpcRequest.model_validate(raw)
                response = await dispatcher.handle(request)
                writer.write(response.model_dump_json().encode() + b"\n")
                await writer.drain()
            elif "op" in raw:
                await _handle_op_line(raw, reader, writer, state)
            else:
                logger.warning("dropping unrecognised fileworker frame")
    finally:
        broadcaster.unregister(writer)
        writer.close()


def _socket_from_fd(fd: int) -> socket.socket:
    sock = socket.socket(fileno=fd)
    sock.setblocking(False)
    return sock


async def run(uid: int, listen_fd: int, settings: Settings) -> None:
    username = _drop_privileges(uid)

    from nasos.agent.handlers import files as _files_handlers  # noqa: F401  (populates REGISTRY)
    from nasos.agent.handlers import uploads as _upload_handlers  # noqa: F401
    from nasos.system.acl import SetfaclAcl
    from nasos.system.runner import SubprocessRunner

    broadcaster = EventBroadcaster()
    jobs = JobRunner(
        f"{settings.state_dir}/fileworker/{uid}/jobs.jsonl", on_event=broadcaster.publish
    )
    state = WorkerState(
        uid=uid, username=username, jobs=jobs, acl=SetfaclAcl(SubprocessRunner()), uploads={}
    )
    dispatcher = Dispatcher(state)
    trusted_uid = _trusted_uid()

    sock = _socket_from_fd(listen_fd)
    idle = _IdleTracker()

    server = await asyncio.start_unix_server(
        lambda r, w: _handle_connection(r, w, dispatcher, state, trusted_uid, broadcaster, idle),
        sock=sock,
    )
    logger.info("nasos-fileworker uid=%d (%s) listening", uid, username)
    watchdog = asyncio.create_task(idle.watch(server))
    try:
        async with server:
            await server.serve_forever()
    except asyncio.CancelledError:
        pass
    finally:
        watchdog.cancel()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s nasos-fileworker %(message)s"
    )
    parser = argparse.ArgumentParser(prog="nasos-fileworker")
    parser.add_argument("--uid", type=int, required=True)
    parser.add_argument("--listen-fd", type=int, default=3)
    args = parser.parse_args()
    asyncio.run(run(args.uid, args.listen_fd, get_settings()))


if __name__ == "__main__":
    main()
