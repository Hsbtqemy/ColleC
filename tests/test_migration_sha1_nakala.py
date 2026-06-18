"""Test du backfill `Fichier.sha1_nakala` depuis `metadonnees["sha1"]`
(migration s7w8x9y0z1, palier P3+a du versioning fichiers Nakala).

Vérifie que les fichiers déjà matérialisés via `rapatrier` (qui rangeait
le sha1 Nakala en `metadonnees["sha1"]`) voient leur sha1 promu en
colonne dédiée. Pattern aligné sur `test_migration_remap_coar.py`.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from archives_tool.api.services.items import FormulaireItem, creer_item
from archives_tool.models import Fichier, Fonds, Item


_MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "s7w8x9y0z1a2_fichier_sha1_nakala.py"
)


def _charger_migration():
    spec = importlib.util.spec_from_file_location("_mig_sha1", _MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _seed_fichier(s: Session, item: Item, ordre: int, *, metadonnees, sha1_nakala=None):
    s.add(
        Fichier(
            item_id=item.id,
            nom_fichier=f"f{ordre}.jpg",
            racine="scans",
            chemin_relatif=f"f{ordre}.jpg",
            ordre=ordre,
            metadonnees=metadonnees,
            sha1_nakala=sha1_nakala,
        )
    )


def test_backfill_promeut_sha1_metadonnees_vers_colonne(
    session: Session,
    fonds_hk: Fonds,
) -> None:
    """Cas typique : fichier matérialisé via `rapatrier` avant la migration
    P3+a — sha1 stocké en `metadonnees["sha1"]`, colonne `sha1_nakala`
    encore NULL. Le backfill doit promouvoir."""
    mig = _charger_migration()
    item = creer_item(
        session,
        FormulaireItem(cote="HK-001", titre="X", fonds_id=fonds_hk.id),
    )
    _seed_fichier(
        session,
        item,
        ordre=1,
        metadonnees={"sha1": "deadbeef", "mime_type": "image/jpeg"},
    )
    session.commit()

    mig.appliquer_backfill(session.connection())
    session.commit()
    session.expire_all()

    fichier = session.scalar(select(Fichier).join(Item).where(Item.cote == "HK-001"))
    assert fichier.sha1_nakala == "deadbeef"
    # metadonnees préservés (compat retro pour les consommateurs qui les
    # lisaient là — exports, scripts ad-hoc).
    assert fichier.metadonnees["sha1"] == "deadbeef"


def test_backfill_ne_touche_pas_si_sha1_nakala_deja_pose(
    session: Session,
    fonds_hk: Fonds,
) -> None:
    """Si `sha1_nakala` est déjà rempli (cas d'un Fichier déposé après
    la migration, ou d'un rejouage), le backfill ne le modifie pas."""
    mig = _charger_migration()
    item = creer_item(
        session,
        FormulaireItem(cote="HK-002", titre="X", fonds_id=fonds_hk.id),
    )
    _seed_fichier(
        session,
        item,
        ordre=1,
        metadonnees={"sha1": "ancien_metadonnees"},
        sha1_nakala="deja_correct",
    )
    session.commit()

    mig.appliquer_backfill(session.connection())
    session.commit()
    session.expire_all()

    fichier = session.scalar(select(Fichier).join(Item).where(Item.cote == "HK-002"))
    # `sha1_nakala` préservé (priorité à la colonne dédiée).
    assert fichier.sha1_nakala == "deja_correct"


def test_backfill_idempotent(session: Session, fonds_hk: Fonds) -> None:
    """Rejouer le backfill ne change rien : la condition WHERE filtre les
    lignes déjà migrées (`sha1_nakala IS NULL`)."""
    mig = _charger_migration()
    item = creer_item(
        session,
        FormulaireItem(cote="HK-003", titre="X", fonds_id=fonds_hk.id),
    )
    _seed_fichier(session, item, ordre=1, metadonnees={"sha1": "abc"})
    session.commit()

    mig.appliquer_backfill(session.connection())
    session.commit()
    mig.appliquer_backfill(session.connection())  # 2e passe
    session.commit()
    session.expire_all()

    fichier = session.scalar(select(Fichier).join(Item).where(Item.cote == "HK-003"))
    assert fichier.sha1_nakala == "abc"


def test_backfill_skip_fichiers_sans_sha1_en_metadonnees(
    session: Session,
    fonds_hk: Fonds,
) -> None:
    """Fichiers locaux purs (jamais déposés ni pullés) : metadonnees ne
    contient pas de sha1 — le backfill ne touche pas, `sha1_nakala`
    reste NULL."""
    mig = _charger_migration()
    item = creer_item(
        session,
        FormulaireItem(cote="HK-004", titre="X", fonds_id=fonds_hk.id),
    )
    _seed_fichier(session, item, ordre=1, metadonnees=None)
    _seed_fichier(session, item, ordre=2, metadonnees={"autre_cle": "v"})
    session.commit()

    mig.appliquer_backfill(session.connection())
    session.commit()
    session.expire_all()

    fichiers = session.scalars(
        select(Fichier).join(Item).where(Item.cote == "HK-004").order_by(Fichier.ordre)
    ).all()
    assert all(f.sha1_nakala is None for f in fichiers)
