"""The only place NAS-OS shells out from. Every system adapter (samba.py,
nfs.py, acl.py, ...) calls through a `Runner` — never subprocess directly,
never a shell string (PLAN.md §1: "The agent never receives shell strings:
all adapters use asyncio.create_subprocess_exec with argv lists").
`FakeRunner` replays canned results for dev mode and unit tests (PLAN.md §4:
"each adapter = Protocol + real impl + Fake* (fixture replay) for dev/test").
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol


@dataclass
class CommandResult:
    argv: list[str]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


class Runner(Protocol):
    async def run(self, argv: list[str], *, input: str | None = None) -> CommandResult: ...


class SubprocessRunner:
    async def run(self, argv: list[str], *, input: str | None = None) -> CommandResult:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE if input is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await proc.communicate(
            input.encode() if input is not None else None
        )
        assert proc.returncode is not None
        return CommandResult(
            argv=argv,
            returncode=proc.returncode,
            stdout=stdout_bytes.decode(errors="replace"),
            stderr=stderr_bytes.decode(errors="replace"),
        )


class FakeRunner:
    """Replays a canned CommandResult per expected argv.

    In strict mode (the default, used by unit tests) an unexpected command
    raises rather than silently no-op'ing, so a test doesn't pass by
    accident because a call it should have asserted on never happened. In
    non-strict mode (used for the interactive `make dev` server, which has
    no test asserting exact expectations) an unexpected command just
    returns a canned success, since crashing on the first not-yet-stubbed
    command would make interactive dev unusable as new features land.
    """

    def __init__(self, *, strict: bool = True) -> None:
        self._expectations: dict[tuple[str, ...], CommandResult] = {}
        self._responders: list[tuple[tuple[str, ...], Callable[[list[str]], CommandResult]]] = []
        self._strict = strict
        self.calls: list[list[str]] = []
        self.inputs: list[str | None] = []
        """Parallel to `calls`: the `input` each call was made with."""

    def expect(
        self, argv: list[str], *, returncode: int = 0, stdout: str = "", stderr: str = ""
    ) -> None:
        self._expectations[tuple(argv)] = CommandResult(
            argv=argv, returncode=returncode, stdout=stdout, stderr=stderr
        )

    def respond(self, prefix: list[str], fn: Callable[[list[str]], CommandResult]) -> None:
        """Like `expect`, but for argv that can't be predicted exactly ahead
        of time (e.g. `systemd-escape ... <a dynamically-chosen mountpoint>`)
        — `fn` computes the `CommandResult` from the actual argv at call
        time. Checked after exact `expect` matches, before the non-strict
        fallback.
        """
        self._responders.append((tuple(prefix), fn))

    async def run(self, argv: list[str], *, input: str | None = None) -> CommandResult:
        self.calls.append(argv)
        self.inputs.append(input)
        result = self._expectations.get(tuple(argv))
        if result is not None:
            return result
        for prefix, fn in self._responders:
            if tuple(argv[: len(prefix)]) == prefix:
                return fn(argv)
        if not self._strict:
            return CommandResult(argv=argv, returncode=0, stdout="", stderr="")
        raise AssertionError(f"FakeRunner: no expectation set for {argv!r}")
