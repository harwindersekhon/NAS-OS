"""Filesystem creation on a fresh LV (PLAN.md §6: "mkfs.xfs -L volume1
(ext4 selectable)"). Generic over `Runner`, no bespoke Fake — see
system/samba.py's docstring.
"""

from __future__ import annotations

from nasos.system.runner import Runner

FS_LABEL_MAX_XFS = 12
FS_LABEL_MAX_EXT4 = 16


class MkfsError(Exception):
    pass


def argv(filesystem: str, label: str, device: str) -> list[str]:
    if filesystem == "xfs":
        return ["mkfs.xfs", "-L", label, device]
    if filesystem == "ext4":
        return ["mkfs.ext4", "-L", label, device]
    raise MkfsError(f"unsupported filesystem: {filesystem}")


async def create(runner: Runner, filesystem: str, label: str, device: str) -> None:
    result = await runner.run(argv(filesystem, label, device))
    if not result.ok:
        raise MkfsError(result.stderr.strip() or f"mkfs.{filesystem} exited {result.returncode}")
