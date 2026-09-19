"""Reads `/proc/mdstat` for resync progress (PLAN.md §6: "resync progress
from /proc/mdstat"). Pure `/proc` read, no subprocess needed — same shape
as system/mounts.py's ProcMounts/FakeMounts.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

MDSTAT_PATH = "/proc/mdstat"


class MdstatReader(Protocol):
    async def read(self) -> str: ...


class ProcMdstat:
    async def read(self) -> str:
        path = Path(MDSTAT_PATH)
        return path.read_text() if path.exists() else ""


class FakeMdstat:
    def __init__(self) -> None:
        self.text = ""

    async def read(self) -> str:
        return self.text
