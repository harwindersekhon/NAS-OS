from __future__ import annotations

from pathlib import Path

import pytest

from nasos.system.managedfile import ConfigApplyError, ConfigValidationError
from nasos.system.runner import FakeRunner
from nasos.system.samba import NASOS_CONF, Samba, ensure_include_block, validate
from nasos.system.systemd import FakeSystemd

# --- ensure_include_block ---------------------------------------------------


def test_inserts_block_at_end_of_global_when_global_is_only_section() -> None:
    original = "[global]\nworkgroup = WORKGROUP\nserver string = NAS\n"
    result = ensure_include_block(original)
    assert result == (
        "[global]\nworkgroup = WORKGROUP\nserver string = NAS\n"
        f"# BEGIN NASOS MANAGED\ninclude = {NASOS_CONF}\n# END NASOS MANAGED\n"
    )


def test_inserts_block_before_next_section_not_at_eof() -> None:
    original = "[global]\nworkgroup = WORKGROUP\n[homes]\nbrowseable = no\n"
    result = ensure_include_block(original)
    assert result == (
        "[global]\nworkgroup = WORKGROUP\n"
        f"# BEGIN NASOS MANAGED\ninclude = {NASOS_CONF}\n# END NASOS MANAGED\n"
        "[homes]\nbrowseable = no\n"
    )


def test_preserves_existing_usershares_include() -> None:
    original = "[global]\nworkgroup = WORKGROUP\ninclude = /etc/samba/usershares.conf\n[printers]\n"
    result = ensure_include_block(original)
    assert "include = /etc/samba/usershares.conf" in result
    assert f"include = {NASOS_CONF}" in result
    # Ours goes after the admin's existing include, still inside [global].
    assert result.index("usershares.conf") < result.index(NASOS_CONF)


def test_idempotent_when_block_already_present() -> None:
    once = ensure_include_block("[global]\nworkgroup = WORKGROUP\n")
    twice = ensure_include_block(once)
    assert once == twice


def test_noop_when_no_global_section() -> None:
    original = "[homes]\nbrowseable = no\n"
    result = ensure_include_block(original)
    assert (
        result == original + f"# BEGIN NASOS MANAGED\ninclude = {NASOS_CONF}\n# END NASOS MANAGED\n"
    )


# --- validate ----------------------------------------------------------------


async def test_validate_passes_on_clean_config() -> None:
    runner = FakeRunner()
    runner.expect(
        ["testparm", "-s", "--suppress-prompt", "/etc/samba/smb.conf"],
        stdout="Load smb config files from /etc/samba/smb.conf\nLoaded services file OK.\n",
    )
    await validate(runner, Path("/etc/samba/nasos.conf"))  # must not raise


async def test_validate_raises_on_bad_boolean_value() -> None:
    runner = FakeRunner()
    runner.expect(
        ["testparm", "-s", "--suppress-prompt", "/etc/samba/smb.conf"],
        returncode=1,
        stderr=(
            "params.c: set_variable_helper(notabool): value is not boolean!\n"
            "Error loading services.\n"
        ),
    )
    with pytest.raises(ConfigValidationError, match="Error loading services"):
        await validate(runner, Path("/etc/samba/nasos.conf"))


async def test_validate_treats_error_string_as_failure_even_with_exit_0() -> None:
    """Belt-and-suspenders: testparm has been seen to print the failure
    banner on stdout while still returning a misleading exit code on some
    versions — check the text, not just returncode.
    """
    runner = FakeRunner()
    runner.expect(
        ["testparm", "-s", "--suppress-prompt", "/etc/samba/smb.conf"],
        returncode=0,
        stdout="Error loading services.\n",
    )
    with pytest.raises(ConfigValidationError):
        await validate(runner, Path("/etc/samba/nasos.conf"))


# --- Samba.reload_or_start / restart ------------------------------------------


@pytest.fixture
def runner() -> FakeRunner:
    return FakeRunner()


@pytest.fixture
def systemd() -> FakeSystemd:
    return FakeSystemd()


async def test_reload_or_start_reloads_when_already_active(
    runner: FakeRunner, systemd: FakeSystemd
) -> None:
    systemd.states["smb.service"] = "active"
    runner.expect(["smbcontrol", "all", "reload-config"])

    samba = Samba(runner, systemd)
    await samba.reload_or_start()

    assert runner.calls == [["smbcontrol", "all", "reload-config"]]
    assert ("restart", "smb.service") not in systemd.calls


async def test_reload_or_start_starts_when_not_active(
    runner: FakeRunner, systemd: FakeSystemd
) -> None:
    samba = Samba(runner, systemd)
    await samba.reload_or_start()

    assert await systemd.active_state("smb.service") == "active"
    assert await systemd.active_state("nmb.service") == "active"
    assert runner.calls == []  # never even tried smbcontrol


async def test_reload_or_start_falls_back_to_start_when_smbcontrol_fails(
    runner: FakeRunner, systemd: FakeSystemd
) -> None:
    systemd.states["smb.service"] = "active"
    runner.expect(
        ["smbcontrol", "all", "reload-config"],
        returncode=1,
        stderr="Could not init messaging context, not root?\n",
    )

    samba = Samba(runner, systemd)
    await samba.reload_or_start()

    assert ("restart", "smb.service") in systemd.calls
    assert ("restart", "nmb.service") in systemd.calls


async def test_restart_always_restarts_both_units(runner: FakeRunner, systemd: FakeSystemd) -> None:
    samba = Samba(runner, systemd)
    await samba.restart()

    assert ("restart", "smb.service") in systemd.calls
    assert ("restart", "nmb.service") in systemd.calls


async def test_apply_error_when_unit_never_becomes_active(
    runner: FakeRunner, systemd: FakeSystemd
) -> None:
    systemd.fail_units.add("smb.service")
    samba = Samba(runner, systemd)
    with pytest.raises(ConfigApplyError):
        await samba.restart()
