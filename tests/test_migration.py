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


# ---------------------------------------------------------------------------
# Passe 26 — Dette signalee : tester `alembic downgrade` en CI
# ---------------------------------------------------------------------------


# Borne de descente : la refonte V0.9.0-alpha (`g7l8m9n0o1p2`) leve
# explicitement `NotImplementedError` au downgrade (decision documentee :
# le modele n'est pas reversible). On valide donc le cycle sur les
# **migrations posterieures a la refonte** : downgrade jusqu'a la
# refonte elle-meme (qui reste appliquee), pas plus bas.
#
# Semantique Alembic : `downgrade <rev>` defait jusqu'a ce que le DB
# soit a `<rev>` (la revision <rev> reste appliquee). Donc pour
# preserver la refonte appliquee tout en defaisant les migrations
# posterieures, on pointe sur `g7l8m9n0o1p2`.
#
# Toute nouvelle migration ajoutee apres cette borne DOIT avoir une
# `downgrade()` fonctionnelle — sinon ce test rouge la signale.
_BORNE_DOWNGRADE = "g7l8m9n0o1p2"


def test_migration_downgrade_apres_refonte_v090_puis_upgrade_head_est_idempotent(
    tmp_path: Path,
) -> None:
    """Cycle upgrade head → downgrade jusqu'avant la refonte V0.9.0-alpha
    → upgrade head. Valide que toutes les `downgrade()` des migrations
    POST-refonte sont écrites correctement et que le cycle est idempotent.

    Sans ce test, un bug dans une `downgrade()` ne se découvre qu'au
    moment d'un rollback en prod (panic mode). Critique pour la sûreté
    des releases V0.9.x+.

    La migration de refonte (`g7l8m9n0o1p2`) refuse explicitement le
    downgrade — c'est une borne dure documentee : on ne descend pas
    sous V0.9.0-alpha, on restaure depuis sauvegarde si besoin.
    """
    db_path = tmp_path / "alembic.db"
    cfg = Config(str(RACINE / "alembic.ini"))
    cfg.set_main_option("script_location", str(RACINE / "alembic"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")

    # 1. upgrade head : creee toutes les tables
    command.upgrade(cfg, "head")
    engine = creer_engine(db_path)
    tables_apres_upgrade = _noms_tables(engine)
    assert tables_apres_upgrade, "Aucune table creee — migrations vides ?"
    engine.dispose()

    # 2. downgrade jusqu'au predecessor de la refonte : doit reussir
    # sans NotImplementedError sur toutes les migrations posterieures.
    command.downgrade(cfg, _BORNE_DOWNGRADE)

    # 3. upgrade head a nouveau : doit re-creer les memes tables que
    # le premier upgrade (idempotence du cycle post-refonte)
    command.upgrade(cfg, "head")
    engine = creer_engine(db_path)
    tables_apres_re_upgrade = _noms_tables(engine)
    assert tables_apres_re_upgrade == tables_apres_upgrade, (
        "Tables apres re-upgrade differentes du 1er upgrade — "
        "downgrade() incomplet ou non symetrique sur une migration "
        "posterieure a la refonte V0.9.0-alpha."
    )
    engine.dispose()


def test_migration_downgrade_traverse_refonte_v090_leve_explicitement(
    tmp_path: Path,
) -> None:
    """Garde-fou : downgrade jusqu'a `base` DOIT lever
    `NotImplementedError` (refonte V0.9.0-alpha non reversible).

    Si quelqu'un implemente un jour la downgrade() de la refonte
    (en V2+ ?), ce test echoue et signale qu'il faut mettre a jour
    `_BORNE_DOWNGRADE` au-dessus.
    """
    db_path = tmp_path / "alembic.db"
    cfg = Config(str(RACINE / "alembic.ini"))
    cfg.set_main_option("script_location", str(RACINE / "alembic"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")

    command.upgrade(cfg, "head")
    with pytest.raises(NotImplementedError, match="refonte V0.9.0-alpha"):
        command.downgrade(cfg, "base")
