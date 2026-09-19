"""Generic systemd unit control via dasbus (PLAN.md §4): start/stop/restart/
reload/enable/disable, plus polling ActiveState until a unit settles. Every
service adapter that needs to touch a unit (samba, nfs-server, vsftpd, a
generated volumeN.mount, ...) goes through this rather than shelling out to
`systemctl`.

dasbus is a synchronous D-Bus binding (GDBus underneath), so every call here
runs off the event loop (PLAN.md §4: "Blocking libs (pam, dasbus, firewall,
psutil scans) via asyncio.to_thread"). Method names/signatures below were
verified against the live systemd1 D-Bus interface on the target OS
(`busctl introspect org.freedesktop.systemd1 /org/freedesktop/systemd1`),
not guessed from documentation.
"""

from __future__ import annotations

import asyncio
import time
from typing import Protocol

_MODE = "replace"
_POLL_INTERVAL_SECONDS = 0.2
_SYSTEMD_BUS_NAME = "org.freedesktop.systemd1"
_SYSTEMD_OBJECT_PATH = "/org/freedesktop/systemd1"
_UNIT_INTERFACE = "org.freedesktop.systemd1.Unit"


class SystemdError(Exception):
    pass


class UnitTimeoutError(SystemdError):
    """The unit didn't reach (or left) 'active' within the timeout."""


class Systemd(Protocol):
    async def start(self, unit: str) -> None: ...
    async def stop(self, unit: str) -> None: ...
    async def restart(self, unit: str) -> None: ...
    async def reload(self, unit: str) -> None: ...
    async def enable(self, unit: str) -> None: ...
    async def disable(self, unit: str) -> None: ...
    async def daemon_reload(self) -> None: ...
    async def active_state(self, unit: str) -> str: ...
    async def is_enabled(self, unit: str) -> bool: ...
    async def wait_active(self, unit: str, *, timeout: float = 10.0) -> None: ...


class DBusSystemd:
    def _manager(self):  # type: ignore[no-untyped-def]
        from dasbus.connection import SystemMessageBus

        bus = SystemMessageBus()
        return bus, bus.get_proxy(_SYSTEMD_BUS_NAME, _SYSTEMD_OBJECT_PATH)

    async def start(self, unit: str) -> None:
        await asyncio.to_thread(self._call, "StartUnit", unit, _MODE)

    async def stop(self, unit: str) -> None:
        await asyncio.to_thread(self._call, "StopUnit", unit, _MODE)

    async def restart(self, unit: str) -> None:
        await asyncio.to_thread(self._call, "RestartUnit", unit, _MODE)

    async def reload(self, unit: str) -> None:
        await asyncio.to_thread(self._call, "ReloadUnit", unit, _MODE)

    def _call(self, method: str, *args: str) -> None:
        _, manager = self._manager()
        getattr(manager, method)(*args)

    async def enable(self, unit: str) -> None:
        await asyncio.to_thread(self._enable_sync, unit)

    def _enable_sync(self, unit: str) -> None:
        _, manager = self._manager()
        manager.EnableUnitFiles([unit], False, False)

    async def disable(self, unit: str) -> None:
        await asyncio.to_thread(self._disable_sync, unit)

    def _disable_sync(self, unit: str) -> None:
        _, manager = self._manager()
        manager.DisableUnitFiles([unit], False)

    async def daemon_reload(self) -> None:
        await asyncio.to_thread(self._daemon_reload_sync)

    def _daemon_reload_sync(self) -> None:
        _, manager = self._manager()
        manager.Reload()

    async def active_state(self, unit: str) -> str:
        return await asyncio.to_thread(self._active_state_sync, unit)

    def _active_state_sync(self, unit: str) -> str:
        bus, manager = self._manager()
        try:
            unit_path = manager.GetUnit(unit)
        except Exception:
            unit_path = manager.LoadUnit(unit)
        unit_proxy = bus.get_proxy(_SYSTEMD_BUS_NAME, unit_path, interface_name=_UNIT_INTERFACE)
        return str(unit_proxy.ActiveState)

    async def is_enabled(self, unit: str) -> bool:
        return await asyncio.to_thread(self._is_enabled_sync, unit)

    def _is_enabled_sync(self, unit: str) -> bool:
        _, manager = self._manager()
        return str(manager.GetUnitFileState(unit)) == "enabled"

    async def wait_active(self, unit: str, *, timeout: float = 10.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = await self.active_state(unit)
            if state == "active":
                return
            if state == "failed":
                raise UnitTimeoutError(f"{unit} entered state 'failed'")
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)
        raise UnitTimeoutError(f"{unit} did not become active within {timeout}s")


class FakeSystemd:
    """In-memory state machine for dev mode / unit tests."""

    def __init__(self) -> None:
        self.states: dict[str, str] = {}
        self.enabled: set[str] = set()
        self.calls: list[tuple[str, str]] = []
        self.fail_units: set[str] = set()
        """Units that `start`/`restart` should land in state 'failed' for."""

    async def start(self, unit: str) -> None:
        self.calls.append(("start", unit))
        self.states[unit] = "failed" if unit in self.fail_units else "active"

    async def stop(self, unit: str) -> None:
        self.calls.append(("stop", unit))
        self.states[unit] = "inactive"

    async def restart(self, unit: str) -> None:
        self.calls.append(("restart", unit))
        self.states[unit] = "failed" if unit in self.fail_units else "active"

    async def reload(self, unit: str) -> None:
        self.calls.append(("reload", unit))

    async def enable(self, unit: str) -> None:
        self.calls.append(("enable", unit))
        self.enabled.add(unit)

    async def disable(self, unit: str) -> None:
        self.calls.append(("disable", unit))
        self.enabled.discard(unit)

    async def daemon_reload(self) -> None:
        self.calls.append(("daemon-reload", ""))

    async def active_state(self, unit: str) -> str:
        return self.states.get(unit, "inactive")

    async def is_enabled(self, unit: str) -> bool:
        return unit in self.enabled

    async def wait_active(self, unit: str, *, timeout: float = 10.0) -> None:  # noqa: ARG002
        state = self.states.get(unit, "inactive")
        if state != "active":
            raise UnitTimeoutError(f"{unit} did not become active (fake state={state!r})")
