"""Parité entre migrations Alembic et métadonnées SQLAlchemy.

Garde-fou contre la dérive : si un modèle change sans qu'une nouvelle
migration soit générée, ces tests échouent.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, inspect

from archives_tool.db import creer_engine
from archives_tool.models import Base

RACINE = Path(__file__).resolve().parent.parent


@pytest.fixture
def engine_alembic(tmp_path: Path) -> Engine:
    """Applique `alembic upgrade head` sur une base neuve."""
    db_path = tmp_path / "alembic.db"
    cfg = Config(str(RACINE / "alembic.ini"))
    cfg.set_main_option("script_location", str(RACINE / "alembic"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    command.upgrade(cfg, "head")
    return creer_engine(db_path)


def _noms_tables(engine: Engine) -> set[str]:
    return {
        nom
        for nom in inspect(engine).get_table_names()
        if not nom.startswith("alembic_")
    }


def test_migration_cree_les_memes_tables_que_metadata(
    engine_alembic: Engine, engine
) -> None:
    assert _noms_tables(engine_alembic) == _noms_tables(engine)


def test_migration_cree_les_memes_colonnes(engine_alembic: Engine, engine) -> None:
    insp_alembic = inspect(engine_alembic)
    insp_meta = inspect(engine)
    for nom in _noms_tables(engine_alembic):
        cols_a = {c["name"] for c in insp_alembic.get_columns(nom)}
        cols_m = {c["name"] for c in insp_meta.get_columns(nom)}
        assert cols_a == cols_m, f"divergence colonnes sur {nom}: {cols_a ^ cols_m}"


def test_migration_cree_les_memes_contraintes_uniques(
    engine_alembic: Engine, engine
) -> None:
    insp_a = inspect(engine_alembic)
    insp_m = inspect(engine)
    for nom in _noms_tables(engine_alembic):
        uq_a = {
            tuple(sorted(u["column_names"])) for u in insp_a.get_unique_constraints(nom)
        }
        uq_m = {
            tuple(sorted(u["column_names"])) for u in insp_m.get_unique_constraints(nom)
        }
        assert uq_a == uq_m, f"divergence UNIQUE sur {nom}: {uq_a ^ uq_m}"
