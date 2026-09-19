"""DistroAdapter: the seam between NAS-OS and distro-specific package names,
paths and security hooks (PLAN.md §13 "Distro drift"). v1 targets RHEL-family
only (rhel.py); a Debian adapter can subclass BaseDistroAdapter later without
touching call sites.
"""

from __future__ import annotations

import platform
import socket
from pathlib import Path
from typing import Protocol


class DistroAdapter(Protocol):
    def hostname(self) -> str: ...
    def os_pretty_name(self) -> str: ...


class BaseDistroAdapter:
    """Behaviour common to every distro; subclasses override where tools differ."""

    def hostname(self) -> str:
        return socket.gethostname()

    def os_pretty_name(self) -> str:
        return _read_os_release().get("PRETTY_NAME", platform.platform())


def _read_os_release() -> dict[str, str]:
    path = Path("/etc/os-release")
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        if "=" not in line or line.startswith("#"):
            continue
        key, _, raw_value = line.partition("=")
        values[key] = raw_value.strip().strip('"')
    return values
