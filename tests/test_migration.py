"""Parité entre migrations Alembic et métadonnées SQLAlchemy.

Garde-fou contre la dérive : si un modèle change sans qu'une nouvelle
migration soit générée, ces tests échouent.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, inspect, text

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


def test_migration_fichier_item_id_a_on_delete_cascade(
    engine_alembic: Engine, engine
) -> None:
    """R5 (revue generale) : la FK `fichier.item_id` doit porter
    `ON DELETE CASCADE`, en parite avec ses soeurs (item.fonds_id,
    item_collection, annotation_region.fichier_id) — defense en profondeur
    SQL contre un futur delete() Core/bulk qui orphelinerait les fichiers.

    Verifie a la fois sur la base montee par Alembic (migration
    `v0z1a2b3c4d5`) et celle montee par `Base.metadata.create_all` (modele),
    donc parite migration <-> modele.
    """
    for libelle, eng in (("alembic", engine_alembic), ("metadata", engine)):
        fks = inspect(eng).get_foreign_keys("fichier")
        item_fk = next(
            (fk for fk in fks if fk["constrained_columns"] == ["item_id"]), None
        )
        assert item_fk is not None, f"{libelle}: FK fichier.item_id absente"
        ondelete = (item_fk.get("options") or {}).get("ondelete")
        assert (ondelete or "").upper() == "CASCADE", (
            f"{libelle}: fichier.item_id sans ON DELETE CASCADE (got {ondelete!r})"
        )


def test_fichier_cascade_sql_au_delete_item_bulk(engine) -> None:
    """R5 — but reel de l'ON DELETE CASCADE : un `DELETE` bulk SQL sur `item`
    (qui CONTOURNE la cascade ORM `Item.fichiers`) doit cascader jusqu'aux
    `fichier` ET transitivement leurs `annotation_region` (elles-memes en
    CASCADE sur fichier). C'est le scenario que R5 protege : sans la cascade
    SQL, un bulk delete orphelinerait les fichiers.

    `engine` (fixture) applique `foreign_keys=ON` via `creer_engine`.
    """
    from sqlalchemy.orm import Session

    from archives_tool.api.services.fonds import (
        FormulaireFonds,
        creer_fonds,
        lire_fonds_par_cote,
    )
    from archives_tool.api.services.items import FormulaireItem, creer_item
    from archives_tool.models import AnnotationRegion, Fichier

    with Session(engine) as s:
        creer_fonds(s, FormulaireFonds(cote="RC", titre="RC"))
        fonds = lire_fonds_par_cote(s, "RC")
        item = creer_item(s, FormulaireItem(cote="RC-1", titre="N", fonds_id=fonds.id))
        fichier = Fichier(
            item_id=item.id,
            racine="r",
            chemin_relatif="a.tif",
            nom_fichier="a.tif",
            ordre=1,
            type_page="page",
        )
        s.add(fichier)
        s.flush()
        s.add(
            AnnotationRegion(fichier_id=fichier.id, selecteur="xywh=0,0,1,1", corps=[])
        )
        s.commit()
        item_id, fichier_id = item.id, fichier.id

    # DELETE bulk SQL : ne passe PAS par l'ORM (donc pas de delete-orphan).
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM item WHERE id = :i"), {"i": item_id})

    with engine.connect() as conn:
        nf = conn.execute(
            text("SELECT count(*) FROM fichier WHERE id = :i"), {"i": fichier_id}
        ).scalar()
        na = conn.execute(
            text("SELECT count(*) FROM annotation_region WHERE fichier_id = :i"),
            {"i": fichier_id},
        ).scalar()
    assert nf == 0, "fichier non cascade-supprime au DELETE bulk de l'item (R5)"
    assert na == 0, "annotation_region non cascade-supprimee transitivement (R5)"


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
