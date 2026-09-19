"""Auto-registration (PLAN.md §6: "auto volume registration") once a
storage.execute_plan job reports done — see services/storage/completion.py's
docstring for why this has to be a background listener rather than the web
waiting on the job synchronously.
"""

from __future__ import annotations

import json

from sqlalchemy import select

from nasos.db.models import Base, Volume
from nasos.db.session import make_engine, make_session_factory
from nasos.events.bus import EventBus
from nasos.services.storage.completion import VolumeAutoRegistrar


def _session_factory():  # type: ignore[no-untyped-def]
    engine = make_engine(":memory:")
    Base.metadata.create_all(engine)
    return make_session_factory(engine)


def test_register_creates_a_managed_volume_row() -> None:
    session_factory = _session_factory()
    registrar = VolumeAutoRegistrar(EventBus(), session_factory)

    registrar._register(  # noqa: SLF001  (the interesting logic; the surrounding queue loop is plumbing)
        {
            "kind": "storage.execute_plan",
            "status": "done",
            "message": json.dumps(
                {
                    "name": "volume1",
                    "mountpoint": "/volume1",
                    "filesystem": "xfs",
                    "device": "/dev/nasos_volume1/volume1",
                    "uuid": "11111111-2222-3333-4444-555555555555",
                    "raid_level": "basic",
                    "array_name": None,
                    "disk_serials": ["S1"],
                }
            ),
        }
    )

    with session_factory() as db:
        volume = db.execute(select(Volume).where(Volume.name == "volume1")).scalar_one()
        assert volume.managed is True
        assert volume.mountpoint == "/volume1"
        assert volume.device == "/dev/nasos_volume1/volume1"
        assert volume.raid_level == "basic"
        assert volume.disk_serials == ["S1"]


def test_register_is_a_noop_on_unparseable_message() -> None:
    session_factory = _session_factory()
    registrar = VolumeAutoRegistrar(EventBus(), session_factory)

    registrar._register({"kind": "storage.execute_plan", "status": "done", "message": "not json"})  # noqa: SLF001

    with session_factory() as db:
        assert db.execute(select(Volume)).first() is None


def test_register_does_not_crash_on_duplicate_name() -> None:
    session_factory = _session_factory()
    registrar = VolumeAutoRegistrar(EventBus(), session_factory)
    event: dict[str, object] = {
        "kind": "storage.execute_plan",
        "status": "done",
        "message": json.dumps(
            {
                "name": "volume1",
                "mountpoint": "/volume1",
                "filesystem": "xfs",
                "device": "/dev/x",
                "uuid": "u",
                "raid_level": "basic",
                "array_name": None,
                "disk_serials": ["S1"],
            }
        ),
    }

    registrar._register(event)  # noqa: SLF001
    registrar._register(event)  # noqa: SLF001  (duplicate name -> logged, not raised)

    with session_factory() as db:
        assert db.execute(select(Volume)).all() != []
