"""DBusFirewall's exception-handling is tested against a fake client object
that raises real dbus.exceptions.DBusException instances (constructible
without an actual bus connection), so the ALREADY_ENABLED/NOT_ENABLED
idempotency logic is exercised against the real exception type it will
actually see in production, not a stand-in.
"""

from __future__ import annotations

import dbus.exceptions
import pytest

from nasos.system.firewall import DBusFirewall, FakeFirewall, FirewallError, _error_code


class _FakeZoneConfig:
    def __init__(self, raise_on_add: Exception | None, raise_on_remove: Exception | None) -> None:
        self._raise_on_add = raise_on_add
        self._raise_on_remove = raise_on_remove
        self.added: list[str] = []
        self.removed: list[str] = []

    def addService(self, service: str) -> None:
        if self._raise_on_add:
            raise self._raise_on_add
        self.added.append(service)

    def removeService(self, service: str) -> None:
        if self._raise_on_remove:
            raise self._raise_on_remove
        self.removed.append(service)


class _FakeConfig:
    def __init__(self, zone_config: _FakeZoneConfig) -> None:
        self._zone_config = zone_config

    def getZoneByName(self, zone: str) -> _FakeZoneConfig:  # noqa: ARG002
        return self._zone_config


class _FakeDbusClient:
    """Stands in for firewall.client.FirewallClient."""

    def __init__(
        self,
        *,
        raise_on_runtime_add: Exception | None = None,
        raise_on_runtime_remove: Exception | None = None,
        raise_on_permanent_add: Exception | None = None,
        raise_on_permanent_remove: Exception | None = None,
        default_zone: str = "public",
    ) -> None:
        self._raise_on_runtime_add = raise_on_runtime_add
        self._raise_on_runtime_remove = raise_on_runtime_remove
        self._default_zone = default_zone
        self.runtime_added: list[str] = []
        self.runtime_removed: list[str] = []
        self._zone_config = _FakeZoneConfig(raise_on_permanent_add, raise_on_permanent_remove)

    def getDefaultZone(self) -> str:
        return self._default_zone

    def addService(self, zone: str, service: str, timeout: int) -> None:  # noqa: ARG002
        if self._raise_on_runtime_add:
            raise self._raise_on_runtime_add
        self.runtime_added.append(service)

    def removeService(self, zone: str, service: str) -> None:  # noqa: ARG002
        if self._raise_on_runtime_remove:
            raise self._raise_on_runtime_remove
        self.runtime_removed.append(service)

    def queryService(self, zone: str, service: str) -> bool:  # noqa: ARG002
        return service in self.runtime_added

    def config(self) -> _FakeConfig:
        return _FakeConfig(self._zone_config)


def _already_enabled(name: str) -> dbus.exceptions.DBusException:
    return dbus.exceptions.DBusException(f"ALREADY_ENABLED: '{name}' already in 'public'")


def _not_enabled(name: str) -> dbus.exceptions.DBusException:
    return dbus.exceptions.DBusException(f"NOT_ENABLED: '{name}' not in 'public'")


def _invalid_service(name: str) -> dbus.exceptions.DBusException:
    return dbus.exceptions.DBusException(f"INVALID_SERVICE: '{name}'")


def test_error_code_parses_the_leading_token() -> None:
    assert _error_code(_already_enabled("samba")) == "ALREADY_ENABLED"
    assert _error_code(_invalid_service("bogus")) == "INVALID_SERVICE"


async def test_ensure_service_succeeds_on_clean_add() -> None:
    fw = DBusFirewall()
    fw._client = _FakeDbusClient()
    await fw.ensure_service("public", "samba")
    assert fw._client.runtime_added == ["samba"]


async def test_ensure_service_is_idempotent_on_already_enabled() -> None:
    fw = DBusFirewall()
    fw._client = _FakeDbusClient(
        raise_on_runtime_add=_already_enabled("samba"),
        raise_on_permanent_add=_already_enabled("samba"),
    )
    await fw.ensure_service("public", "samba")  # must not raise


async def test_ensure_service_raises_firewall_error_for_other_codes() -> None:
    fw = DBusFirewall()
    fw._client = _FakeDbusClient(raise_on_runtime_add=_invalid_service("bogus"))
    with pytest.raises(FirewallError, match="INVALID_SERVICE"):
        await fw.ensure_service("public", "bogus")


async def test_remove_service_is_idempotent_on_not_enabled() -> None:
    fw = DBusFirewall()
    fw._client = _FakeDbusClient(
        raise_on_runtime_remove=_not_enabled("samba"),
        raise_on_permanent_remove=_not_enabled("samba"),
    )
    await fw.remove_service("public", "samba")  # must not raise


async def test_default_zone_reads_through_client() -> None:
    fw = DBusFirewall()
    fw._client = _FakeDbusClient(default_zone="internal")
    assert await fw.default_zone() == "internal"


# --- FakeFirewall ------------------------------------------------------------


async def test_fake_firewall_roundtrip() -> None:
    fw = FakeFirewall()
    assert await fw.has_service("public", "samba") is False
    await fw.ensure_service("public", "samba")
    assert await fw.has_service("public", "samba") is True
    await fw.remove_service("public", "samba")
    assert await fw.has_service("public", "samba") is False


async def test_fake_firewall_default_zone() -> None:
    fw = FakeFirewall(default="internal")
    assert await fw.default_zone() == "internal"
