"""Dépendances FastAPI : session DB, identité utilisateur, base courante.

`ARCHIVES_DB` (variable d'environnement) prime sur `data/archives.db` :
permet de basculer sur une base de démonstration sans toucher à la
config locale (ex. `ARCHIVES_DB=data/demo.db uvicorn ...`).
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

from sqlalchemy.orm import Session

from archives_tool.config import ConfigLocale, charger_config
from archives_tool.db import creer_engine, creer_session_factory

CHEMIN_DB_DEFAUT = Path("data/archives.db")
CHEMIN_CONFIG_DEFAUT = Path("config_local.yaml")


def chemin_base_courant() -> Path:
    valeur_env = os.environ.get("ARCHIVES_DB")
    return Path(valeur_env) if valeur_env else CHEMIN_DB_DEFAUT


def get_db() -> Iterator[Session]:
    """Session SQLAlchemy par requête."""
    engine = creer_engine(chemin_base_courant())
    factory = creer_session_factory(engine)
    with factory() as session:
        yield session


def _charger_config() -> ConfigLocale | None:
    chemin = Path(os.environ.get("ARCHIVES_CONFIG", CHEMIN_CONFIG_DEFAUT))
    try:
        return charger_config(chemin)
    except (FileNotFoundError, Exception):
        return None


def get_utilisateur_courant() -> str:
    config = _charger_config()
    return config.utilisateur if config else "anonyme"


def get_racines() -> dict[str, Path]:
    config = _charger_config()
    return dict(config.racines) if config else {}


def get_nom_base() -> str:
    return chemin_base_courant().name
