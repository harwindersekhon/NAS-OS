"""Samba integration (PLAN.md §2 table): renders /etc/samba/nasos.conf
(globals + one [share] section per share), validates with testparm against
the real resolved smb.conf, and reloads/restarts smbd+nmbd. Owns only
nasos.conf; smb.conf itself is the admin's file — NAS-OS's one edit to it
is an idempotent marker block at the end of [global] pointing at
nasos.conf (`ensure_include_block`), mirroring the distro's own
`include = /etc/samba/usershares.conf` convention already there.

`Samba` is generic over `Runner`/`Systemd` rather than having its own
Real/Fake split: dev mode gets the same behaviour for free by constructing
it with `FakeRunner`/`FakeSystemd` (PLAN.md §4's adapter pattern, without
duplicating this class).
"""

from __future__ import annotations

from pathlib import Path

from nasos.system.managedfile import ConfigApplyError, ConfigValidationError
from nasos.system.runner import Runner
from nasos.system.systemd import Systemd

SMB_CONF = "/etc/samba/smb.conf"
NASOS_CONF = "/etc/samba/nasos.conf"

_MARKER_BEGIN = "# BEGIN NASOS MANAGED"
_MARKER_END = "# END NASOS MANAGED"
_MARKER_BLOCK = f"{_MARKER_BEGIN}\ninclude = {NASOS_CONF}\n{_MARKER_END}\n"


def ensure_include_block(smb_conf_text: str) -> str:
    """Idempotently ensures the marker block is present as the last lines
    of [global]. The block's content never varies, so there's nothing to
    update once present — only insert-if-absent.
    """
    if _MARKER_BEGIN in smb_conf_text:
        return smb_conf_text
    lines = smb_conf_text.splitlines(keepends=True)
    insert_at = _end_of_global_section(lines)
    return "".join(lines[:insert_at]) + _MARKER_BLOCK + "".join(lines[insert_at:])


def _end_of_global_section(lines: list[str]) -> int:
    """Index to insert at: just before the next [section] after [global],
    or end of file if [global] is the last (or only) section. If there's
    no [global] at all (unusual, but not our job to fix an admin's file),
    appends at the end.
    """
    in_global = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.lower() == "[global]":
            in_global = True
            continue
        if in_global and stripped.startswith("[") and stripped.endswith("]"):
            return i
    return len(lines)


async def validate(runner: Runner, _target: Path) -> None:
    """testparm's only generic failure signal (verified during M2 research):
    a bad *value* fails with this exact line and exit 1. An unknown
    directive *name* and a missing include target are both silently exit-0
    — testparm success is not proof the rendered content is semantically
    complete, just that nothing testparm checks is actively wrong.
    """
    result = await runner.run(["testparm", "-s", "--suppress-prompt", SMB_CONF])
    output = result.stdout + result.stderr
    if not result.ok or "Error loading services." in output:
        raise ConfigValidationError(output.strip())


class Samba:
    def __init__(self, runner: Runner, systemd: Systemd) -> None:
        self._runner = runner
        self._systemd = systemd

    async def reload_or_start(self) -> None:
        """For a share-only change (PLAN.md §2: "smbcontrol all
        reload-config"). `smbcontrol` needs a live messaging context and
        fails outright without one — verified: "Could not init messaging
        context, not root?" even as root, when smbd was never started —
        so this falls back to starting the service rather than treating
        that as fatal on first-ever activation.
        """
        if await self._systemd.active_state("smb.service") != "active":
            await self._start()
            return
        result = await self._runner.run(["smbcontrol", "all", "reload-config"])
        if not result.ok:
            await self._start()

    async def restart(self) -> None:
        """For a global-parameter change (PLAN.md §2: "restart smb nmb
        only when global network params change")."""
        await self._start()

    async def _start(self) -> None:
        try:
            await self._systemd.restart("smb.service")
            await self._systemd.restart("nmb.service")
            await self._systemd.wait_active("smb.service", timeout=15)
        except Exception as exc:
            raise ConfigApplyError(str(exc)) from exc
