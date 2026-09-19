"""SMART health poll (PLAN.md §6: "SMART every 30 min + on demand with
threshold notifications") — a Notification only fires on a health
*transition*, not on every poll of an already-known state.
"""

from __future__ import annotations

from sqlalchemy import select

from nasos.db.models import Base, DiskSeen, Notification
from nasos.db.session import make_engine, make_session_factory
from nasos.rpc.schemas import DiskNode, DiskSmart
from nasos.services.storage.health import SmartHealthPoller


def _session_factory():  # type: ignore[no-untyped-def]
    engine = make_engine(":memory:")
    Base.metadata.create_all(engine)
    return make_session_factory(engine)


def _disk(serial: str, health: str) -> DiskNode:
    return DiskNode(
        name="sda",
        path="/dev/sda",
        type="disk",
        serial=serial,
        model="Model X",
        size=1000,
        smart=DiskSmart(health=health),  # type: ignore[arg-type]
    )


def test_first_observation_of_a_critical_disk_notifies() -> None:
    session_factory = _session_factory()
    poller = SmartHealthPoller(agent=None, session_factory=session_factory)  # type: ignore[arg-type]

    with session_factory() as db:
        poller._update(db, _disk("S1", "critical"))  # noqa: SLF001
        db.commit()

    with session_factory() as db:
        row = db.get(DiskSeen, "S1")
        assert row is not None
        assert row.last_health == "critical"
        assert db.execute(select(Notification)).scalar_one().level == "critical"


def test_repeated_poll_at_the_same_health_does_not_renotify() -> None:
    session_factory = _session_factory()
    poller = SmartHealthPoller(agent=None, session_factory=session_factory)  # type: ignore[arg-type]

    with session_factory() as db:
        poller._update(db, _disk("S1", "warning"))  # noqa: SLF001
        db.commit()
    with session_factory() as db:
        poller._update(db, _disk("S1", "warning"))  # noqa: SLF001
        db.commit()

    with session_factory() as db:
        assert len(db.execute(select(Notification)).all()) == 1


def test_transition_from_ok_to_warning_notifies_once() -> None:
    session_factory = _session_factory()
    poller = SmartHealthPoller(agent=None, session_factory=session_factory)  # type: ignore[arg-type]

    with session_factory() as db:
        poller._update(db, _disk("S1", "ok"))  # noqa: SLF001
        db.commit()
    with session_factory() as db:
        poller._update(db, _disk("S1", "warning"))  # noqa: SLF001
        db.commit()

    with session_factory() as db:
        notifications = db.execute(select(Notification)).all()
        assert len(notifications) == 1
        assert notifications[0][0].level == "warning"
