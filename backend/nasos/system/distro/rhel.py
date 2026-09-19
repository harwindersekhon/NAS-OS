"""Rocky/Alma/RHEL/Fedora adapter — the only target for v1 (PLAN.md "Target OS
v1"). Nothing overridden yet: package/unit/path names match BaseDistroAdapter
until a second distro needs to diverge.
"""

from __future__ import annotations

from nasos.system.distro.base import BaseDistroAdapter


class RhelDistroAdapter(BaseDistroAdapter):
    pass
