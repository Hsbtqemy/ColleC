"""Fixtures partagées pour la suite de tests."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.models import Base


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    """Engine SQLite sur fichier temporaire, schéma créé via metadata."""
    engine = creer_engine(tmp_path / "test.db")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    factory = creer_session_factory(engine)
    with factory() as session:
        yield session
