"""Dépendances FastAPI : session DB, identité utilisateur, base courante.

`ARCHIVES_DB` (variable d'environnement) prime sur `data/archives.db` :
permet de basculer sur une base de démonstration sans toucher à la
config locale (ex. `ARCHIVES_DB=data/demo.db uvicorn ...`).
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import ValidationError
from sqlalchemy.orm import Session, sessionmaker

from archives_tool.config import ConfigLocale, charger_config
from archives_tool.db import creer_engine, creer_session_factory

CHEMIN_DB_DEFAUT = Path("data/archives.db")
CHEMIN_CONFIG_DEFAUT = Path("config_local.yaml")


def chemin_base_courant() -> Path:
    valeur_env = os.environ.get("ARCHIVES_DB")
    return Path(valeur_env) if valeur_env else CHEMIN_DB_DEFAUT


@lru_cache(maxsize=4)
def _factory_pour(chemin: Path) -> sessionmaker[Session]:
    """Engine + session factory mis en cache par chemin de base.

    Recréer l'engine à chaque requête défait le pool de connexions et
    relance l'introspection du dialecte. Le cache, borné à 4 entrées,
    couvre largement le besoin (quelques bases distinctes au plus).
    """
    return creer_session_factory(creer_engine(chemin))


def get_db() -> Iterator[Session]:
    """Session SQLAlchemy par requête (engine partagé via cache)."""
    factory = _factory_pour(chemin_base_courant())
    with factory() as session:
        yield session


def _charger_config() -> ConfigLocale | None:
    chemin = Path(os.environ.get("ARCHIVES_CONFIG", CHEMIN_CONFIG_DEFAUT))
    try:
        return charger_config(chemin)
    except (FileNotFoundError, yaml.YAMLError, ValidationError, ValueError):
        return None


def get_utilisateur_courant() -> str:
    config = _charger_config()
    return config.utilisateur if config else "anonyme"


def get_racines() -> dict[str, Path]:
    config = _charger_config()
    return dict(config.racines) if config else {}


def get_nom_base() -> str:
    return chemin_base_courant().name
