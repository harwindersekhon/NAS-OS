"""Mountpoint introspection (PLAN.md §4), used by `volumes.register` (M2)
and later Storage Manager mount-unit management (Milestone 4). Pure
`/proc/mounts` + `os.path.ismount` — no subprocess needed, so unlike most
adapters here there's nothing for a `Runner` to wrap.
"""

from __future__ import annotations

import os
from typing import Protocol


class MountInfo(Protocol):
    async def is_mountpoint(self, path: str) -> bool: ...
    async def filesystem_type(self, path: str) -> str | None: ...


class ProcMounts:
    async def is_mountpoint(self, path: str) -> bool:
        return os.path.ismount(path)

    async def filesystem_type(self, path: str) -> str | None:
        with open("/proc/mounts") as fh:
            for line in fh:
                fields = line.split()
                if len(fields) >= 3 and fields[1] == path:
                    return fields[2]
        return None


class FakeMounts:
    """In-memory {path: filesystem type} for dev mode / unit tests."""

    def __init__(self) -> None:
        self.mounts: dict[str, str] = {}

    async def is_mountpoint(self, path: str) -> bool:
        return path in self.mounts

    async def filesystem_type(self, path: str) -> str | None:
        return self.mounts.get(path)
