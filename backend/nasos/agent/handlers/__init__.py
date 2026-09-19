"""Importing this package registers every RPC handler with the dispatcher."""

from nasos.agent.handlers import (  # noqa: F401
    auth,
    fileworker,
    firewall,
    groups,
    jobs,
    samba,
    shares,
    storage,
    system,
    users,
    volumes,
)
