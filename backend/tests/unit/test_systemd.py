from __future__ import annotations

import pytest

from nasos.system.systemd import FakeSystemd, UnitTimeoutError


@pytest.fixture
def systemd() -> FakeSystemd:
    return FakeSystemd()


async def test_start_makes_unit_active(systemd: FakeSystemd) -> None:
    await systemd.start("nasos.service")
    assert await systemd.active_state("nasos.service") == "active"


async def test_stop_makes_unit_inactive(systemd: FakeSystemd) -> None:
    await systemd.start("nasos.service")
    await systemd.stop("nasos.service")
    assert await systemd.active_state("nasos.service") == "inactive"


async def test_unknown_unit_defaults_inactive(systemd: FakeSystemd) -> None:
    assert await systemd.active_state("never-started.service") == "inactive"


async def test_enable_disable_tracked(systemd: FakeSystemd) -> None:
    assert await systemd.is_enabled("smb.service") is False
    await systemd.enable("smb.service")
    assert await systemd.is_enabled("smb.service") is True
    await systemd.disable("smb.service")
    assert await systemd.is_enabled("smb.service") is False


async def test_wait_active_succeeds_once_active(systemd: FakeSystemd) -> None:
    await systemd.start("smb.service")
    await systemd.wait_active("smb.service", timeout=1.0)  # must not raise


async def test_wait_active_raises_if_never_started(systemd: FakeSystemd) -> None:
    with pytest.raises(UnitTimeoutError):
        await systemd.wait_active("smb.service", timeout=0.01)


async def test_start_can_simulate_failure(systemd: FakeSystemd) -> None:
    systemd.fail_units.add("vsftpd.service")
    await systemd.start("vsftpd.service")
    assert await systemd.active_state("vsftpd.service") == "failed"
    with pytest.raises(UnitTimeoutError):
        await systemd.wait_active("vsftpd.service", timeout=0.01)


async def test_calls_are_recorded_in_order(systemd: FakeSystemd) -> None:
    await systemd.start("a.service")
    await systemd.enable("a.service")
    await systemd.restart("a.service")
    assert systemd.calls == [
        ("start", "a.service"),
        ("enable", "a.service"),
        ("restart", "a.service"),
    ]
