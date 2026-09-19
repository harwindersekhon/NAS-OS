"""firewalld integration via python3-firewall's `FirewallClient` (PLAN.md
§4, §9). `FirewallClient` is a synchronous D-Bus binding, so every call
here runs in a thread (PLAN.md §4: "Blocking libs ... firewall ... via
asyncio.to_thread").

One long-lived client plus a lock serializes every call: M2 research found
firewalld's D-Bus interface can stop responding under rapid/concurrent
calls from multiple short-lived connections, and there's no recovery short
of `systemctl restart firewalld` (which needs root the agent always has,
but a wedged call still needs a hard timeout rather than hanging forever).

Idempotency (verified by reading the installed `firewall/client.py` and
`firewall/core/fw_zone.py`, and confirmed live against the real daemon):
re-adding an already-present service or removing an absent one raises
`dbus.exceptions.DBusException`, not the local `FirewallError` class — that
one's only raised by pure-Python client-side objects, never anything that
actually crosses D-Bus, because `FirewallClient` only translates exceptions
through a callback registered via `setExceptionHandler`, which this class
never registers. The exception's string is formatted `"<CODE>: <message>"`;
`ALREADY_ENABLED` / `NOT_ENABLED` are treated as success, everything else
propagates as `FirewallError`.
"""

from __future__ import annotations

import asyncio
from typing import Any, Protocol

_CALL_TIMEOUT_SECONDS = 10.0


class FirewallError(Exception):
    pass


class Firewall(Protocol):
    async def default_zone(self) -> str: ...
    async def ensure_service(self, zone: str, service: str) -> None: ...
    async def remove_service(self, zone: str, service: str) -> None: ...
    async def has_service(self, zone: str, service: str) -> bool: ...


def _error_code(exc: Exception) -> str:
    return str(exc).split(":", 1)[0].strip()


class DBusFirewall:
    def __init__(self) -> None:
        self._client: Any = None
        self._lock = asyncio.Lock()

    def _get_client(self) -> Any:
        if self._client is None:
            from firewall.client import FirewallClient

            self._client = FirewallClient()
        return self._client

    async def default_zone(self) -> str:
        async with self._lock:
            return await asyncio.wait_for(
                asyncio.to_thread(self._default_zone_sync), timeout=_CALL_TIMEOUT_SECONDS
            )

    def _default_zone_sync(self) -> str:
        return str(self._get_client().getDefaultZone())

    async def ensure_service(self, zone: str, service: str) -> None:
        async with self._lock:
            await asyncio.wait_for(
                asyncio.to_thread(self._ensure_service_sync, zone, service),
                timeout=_CALL_TIMEOUT_SECONDS,
            )

    def _ensure_service_sync(self, zone: str, service: str) -> None:
        import dbus

        client = self._get_client()
        try:
            client.addService(zone, service, 0)  # runtime, timeout=0 == until removed/reload
        except dbus.exceptions.DBusException as exc:
            if _error_code(exc) != "ALREADY_ENABLED":
                raise FirewallError(str(exc)) from exc
        try:
            client.config().getZoneByName(zone).addService(service)  # permanent
        except dbus.exceptions.DBusException as exc:
            if _error_code(exc) != "ALREADY_ENABLED":
                raise FirewallError(str(exc)) from exc

    async def remove_service(self, zone: str, service: str) -> None:
        async with self._lock:
            await asyncio.wait_for(
                asyncio.to_thread(self._remove_service_sync, zone, service),
                timeout=_CALL_TIMEOUT_SECONDS,
            )

    def _remove_service_sync(self, zone: str, service: str) -> None:
        import dbus

        client = self._get_client()
        try:
            client.removeService(zone, service)
        except dbus.exceptions.DBusException as exc:
            if _error_code(exc) != "NOT_ENABLED":
                raise FirewallError(str(exc)) from exc
        try:
            client.config().getZoneByName(zone).removeService(service)
        except dbus.exceptions.DBusException as exc:
            if _error_code(exc) != "NOT_ENABLED":
                raise FirewallError(str(exc)) from exc

    async def has_service(self, zone: str, service: str) -> bool:
        async with self._lock:
            return await asyncio.wait_for(
                asyncio.to_thread(self._has_service_sync, zone, service),
                timeout=_CALL_TIMEOUT_SECONDS,
            )

    def _has_service_sync(self, zone: str, service: str) -> bool:
        return bool(self._get_client().queryService(zone, service))


class FakeFirewall:
    """In-memory {zone: {service}} for dev mode / unit tests."""

    def __init__(self, default: str = "public") -> None:
        self._default = default
        self.services: dict[str, set[str]] = {}

    async def default_zone(self) -> str:
        return self._default

    async def ensure_service(self, zone: str, service: str) -> None:
        self.services.setdefault(zone, set()).add(service)

    async def remove_service(self, zone: str, service: str) -> None:
        self.services.get(zone, set()).discard(service)

    async def has_service(self, zone: str, service: str) -> bool:
        return service in self.services.get(zone, set())
