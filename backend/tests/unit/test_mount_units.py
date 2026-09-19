"""Golden-file tests for the systemd units Storage Manager renders
(PLAN.md §12's M4 gate: "golden .mount/target/drop-ins").
"""

from __future__ import annotations

from pathlib import Path

from nasos.system.mount_units import (
    mount_unit_name,
    mount_unit_path,
    render_mount_unit,
    render_service_dropin,
    render_volumes_target,
    service_dropin_path,
)
from nasos.system.runner import FakeRunner

GOLDEN_DIR = Path(__file__).parent.parent / "fixtures" / "golden"


def test_render_mount_unit_matches_golden_file() -> None:
    rendered = render_mount_unit(
        uuid="11111111-2222-3333-4444-555555555555", where="/volume1", fstype="xfs"
    )

    assert rendered == (GOLDEN_DIR / "volume1.mount").read_text()


def test_render_volumes_target_matches_golden_file() -> None:
    rendered = render_volumes_target()

    assert rendered == (GOLDEN_DIR / "nasos-volumes.target").read_text()


def test_render_service_dropin_matches_golden_file() -> None:
    rendered = render_service_dropin(mountpoints=["/volume1", "/volume2"])

    assert rendered == (GOLDEN_DIR / "50-nasos-volumes.conf").read_text()


async def test_mount_unit_name_uses_systemd_escape() -> None:
    runner = FakeRunner()
    runner.expect(["systemd-escape", "-p", "--suffix=mount", "/volume1"], stdout="volume1.mount\n")

    name = await mount_unit_name(runner, "/volume1")

    assert name == "volume1.mount"


def test_mount_unit_path() -> None:
    assert mount_unit_path("volume1.mount") == "/etc/systemd/system/volume1.mount"


def test_service_dropin_path() -> None:
    assert (
        service_dropin_path("smb.service")
        == "/etc/systemd/system/smb.service.d/50-nasos-volumes.conf"
    )
