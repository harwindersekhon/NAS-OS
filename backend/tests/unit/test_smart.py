from __future__ import annotations

import json

from nasos.system.runner import FakeRunner
from nasos.system.smart import read

DEVICE = "/dev/sda"


async def test_healthy_disk_reports_ok() -> None:
    runner = FakeRunner()
    runner.expect(
        ["smartctl", "--json=c", "-a", DEVICE],
        stdout=json.dumps(
            {
                "smart_status": {"passed": True},
                "temperature": {"current": 34},
                "power_on_time": {"hours": 500},
                "ata_smart_attributes": {"table": []},
            }
        ),
    )

    smart = await read(runner, DEVICE)

    assert smart is not None
    assert smart.health == "ok"
    assert smart.temperature_c == 34
    assert smart.power_on_hours == 500


async def test_failed_self_check_is_critical_even_with_no_bad_attributes() -> None:
    runner = FakeRunner()
    runner.expect(
        ["smartctl", "--json=c", "-a", DEVICE],
        returncode=1,  # smartctl's exit bitmask is not itself the health signal
        stdout=json.dumps(
            {"smart_status": {"passed": False}, "ata_smart_attributes": {"table": []}}
        ),
    )

    smart = await read(runner, DEVICE)

    assert smart is not None
    assert smart.health == "critical"


async def test_passed_but_reallocated_sectors_present_is_warning() -> None:
    runner = FakeRunner()
    runner.expect(
        ["smartctl", "--json=c", "-a", DEVICE],
        stdout=json.dumps(
            {
                "smart_status": {"passed": True},
                "ata_smart_attributes": {
                    "table": [
                        {
                            "id": 5,
                            "name": "Reallocated_Sector_Ct",
                            "value": 100,
                            "worst": 100,
                            "thresh": 10,
                            "raw": {"value": 3, "string": "3"},
                        }
                    ]
                },
            }
        ),
    )

    smart = await read(runner, DEVICE)

    assert smart is not None
    assert smart.health == "warning"
    assert smart.attributes[0].id == 5
    assert smart.attributes[0].raw == "3"


async def test_zero_reallocated_sectors_stays_ok() -> None:
    runner = FakeRunner()
    runner.expect(
        ["smartctl", "--json=c", "-a", DEVICE],
        stdout=json.dumps(
            {
                "smart_status": {"passed": True},
                "ata_smart_attributes": {
                    "table": [
                        {
                            "id": 5,
                            "name": "Reallocated_Sector_Ct",
                            "value": 100,
                            "worst": 100,
                            "thresh": 10,
                            "raw": {"value": 0, "string": "0"},
                        }
                    ]
                },
            }
        ),
    )

    smart = await read(runner, DEVICE)

    assert smart is not None
    assert smart.health == "ok"


async def test_unparseable_output_returns_none() -> None:
    runner = FakeRunner()
    runner.expect(
        ["smartctl", "--json=c", "-a", DEVICE], returncode=2, stdout="", stderr="no such device"
    )

    smart = await read(runner, DEVICE)

    assert smart is None
