"""Guards against drift between the hand-written Alembic migrations and the
SQLAlchemy models they're supposed to produce. Dev/test mode always uses
Base.metadata.create_all() (models.py) directly and never runs the
migrations, so nothing else would catch the two diverging.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, inspect

from nasos.db.models import Base
from nasos.db.session import make_engine

BACKEND_ROOT = Path(__file__).parent.parent.parent


def _schema_snapshot(engine: Engine) -> dict[str, set[str]]:
    inspector = inspect(engine)
    return {
        table: {col["name"] for col in inspector.get_columns(table)}
        for table in inspector.get_table_names()
        if table != "alembic_version"  # Alembic's own bookkeeping, not one of our models
    }


def test_migrations_produce_the_same_schema_as_the_models(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    models_db = tmp_path / "models.db"
    migrated_db = tmp_path / "migrated.db"

    models_engine = make_engine(str(models_db))
    Base.metadata.create_all(models_engine)

    monkeypatch.setenv("NASOS_DB_PATH", str(migrated_db))
    alembic_cfg: Any = Config(str(BACKEND_ROOT / "alembic.ini"))
    command.upgrade(alembic_cfg, "head")
    migrated_engine = make_engine(str(migrated_db))

    assert _schema_snapshot(models_engine) == _schema_snapshot(migrated_engine)


def test_migrations_downgrade_cleanly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "roundtrip.db"
    monkeypatch.setenv("NASOS_DB_PATH", str(db_path))
    alembic_cfg: Any = Config(str(BACKEND_ROOT / "alembic.ini"))

    command.upgrade(alembic_cfg, "head")
    command.downgrade(alembic_cfg, "base")

    engine = make_engine(str(db_path))
    assert inspect(engine).get_table_names() == ["alembic_version"]
