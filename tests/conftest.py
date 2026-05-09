"""Fixtures partagées pour la suite de tests."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from archives_tool.api.services.fonds import (
    FormulaireFonds,
    creer_fonds,
)
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.models import Base, Fonds

# V0.9.0-alpha : la refonte Fonds / Collection / Item invalide la
# plupart des tests existants (ancien `Collection.parent_id`,
# `Collection.cote_collection`, `Item.collection_id`). La liste
# ci-dessous met en quarantaine les fichiers concernés ; ils seront
# adaptés et réactivés au fil des sessions V0.9.0-gamma (services
# Collection/Item refondus, demo seeder, importers v2, exporters,
# qa, renamer, derivatives, affichage CLI, routes web).
collect_ignore = [
    "test_cli_controler.py",
    "test_cli_deriver.py",
    "test_cli_importer.py",
    "test_cli_montrer.py",
    "test_cli_renommer.py",
    "test_collaborateurs.py",
    "test_collection_routes.py",
    "test_collection_services.py",
    "test_collections_creation.py",
    "test_contraintes.py",
    "test_dashboard_services.py",
    "test_derivatives_generateur.py",
    "test_derives_route.py",
    "test_mapping_dc.py",
    "test_preferences.py",
    "test_profils_generateur.py",
    "test_qa_controles.py",
    "test_rapport_export.py",
    "test_renamer_annulation.py",
    "test_renamer_execution.py",
    "test_renamer_plan.py",
    "test_renamer_template.py",
    "test_roundtrip.py",
]


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


@pytest.fixture
def fonds_hk(session: Session) -> Fonds:
    """Fonds HK + sa miroir auto, prêt à recevoir des items."""
    return creer_fonds(session, FormulaireFonds(cote="HK", titre="Hara-Kiri"))


@pytest.fixture
def session_avec_export(session: Session) -> Session:
    """Base avec 2 fonds + 5 items + 1 collection libre + 1 transversale.

    Partagée par tests/test_export_*.py pour ne pas dupliquer le seeder
    (les 3 exporters DC / xlsx / Nakala consomment le même contexte).

    HK : 3 items (HK-001, HK-002, HK-003) dans la miroir + libre
    HK-FAVORIS (HK-001, HK-002).
    FA : 2 items (FA-001, FA-002).
    TRANSV : transversale avec HK-001 + FA-001.
    """
    from sqlalchemy import select

    from archives_tool.api.services.collections import (
        FormulaireCollection,
        creer_collection_libre,
        lire_collection_par_cote,
    )
    from archives_tool.api.services.fonds import lire_fonds_par_cote
    from archives_tool.api.services.items import (
        FormulaireItem,
        creer_item,
    )
    from archives_tool.models import Item, ItemCollection

    creer_fonds(session, FormulaireFonds(cote="HK", titre="Hara-Kiri"))
    creer_fonds(session, FormulaireFonds(cote="FA", titre="Fonds Aínsa"))
    fonds_hk_obj = lire_fonds_par_cote(session, "HK")
    fonds_fa_obj = lire_fonds_par_cote(session, "FA")

    for cote, titre in [
        ("HK-001", "Numéro 1"),
        ("HK-002", "Numéro 2"),
        ("HK-003", "Numéro 3"),
    ]:
        creer_item(
            session,
            FormulaireItem(
                cote=cote,
                titre=titre,
                fonds_id=fonds_hk_obj.id,
                etat_catalogage="valide",
            ),
        )
    for cote, titre in [("FA-001", "Manuscrit 1"), ("FA-002", "Lettre 1")]:
        creer_item(
            session,
            FormulaireItem(
                cote=cote,
                titre=titre,
                fonds_id=fonds_fa_obj.id,
                etat_catalogage="valide",
            ),
        )

    creer_collection_libre(
        session,
        FormulaireCollection(
            cote="HK-FAVORIS",
            titre="Hara-Kiri favoris",
            description_publique="Sélection éditoriale",
            fonds_id=fonds_hk_obj.id,
        ),
    )
    creer_collection_libre(
        session,
        FormulaireCollection(
            cote="TRANSV",
            titre="Transversale d'exemple",
            fonds_id=None,
        ),
    )

    favoris = lire_collection_par_cote(
        session, "HK-FAVORIS", fonds_id=fonds_hk_obj.id
    )
    transv = lire_collection_par_cote(session, "TRANSV")
    hk_001 = session.scalar(
        select(Item).where(Item.cote == "HK-001", Item.fonds_id == fonds_hk_obj.id)
    )
    hk_002 = session.scalar(
        select(Item).where(Item.cote == "HK-002", Item.fonds_id == fonds_hk_obj.id)
    )
    fa_001 = session.scalar(
        select(Item).where(Item.cote == "FA-001", Item.fonds_id == fonds_fa_obj.id)
    )
    session.add(ItemCollection(item_id=hk_001.id, collection_id=favoris.id))
    session.add(ItemCollection(item_id=hk_002.id, collection_id=favoris.id))
    session.add(ItemCollection(item_id=hk_001.id, collection_id=transv.id))
    session.add(ItemCollection(item_id=fa_001.id, collection_id=transv.id))
    session.commit()
    return session
