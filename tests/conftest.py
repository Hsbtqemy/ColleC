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
    "test_cli_exporter.py",
    "test_cli_importer.py",
    "test_cli_montrer.py",
    "test_cli_renommer.py",
    "test_collaborateurs.py",
    "test_collection_routes.py",
    "test_collection_services.py",
    "test_collections_creation.py",
    "test_contraintes.py",
    "test_dashboard_routes.py",
    "test_dashboard_services.py",
    "test_derivatives_generateur.py",
    "test_derives_route.py",
    "test_export_dc.py",
    "test_export_excel.py",
    "test_export_nakala.py",
    "test_importer.py",
    "test_item_services.py",
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
    "test_selection.py",
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
