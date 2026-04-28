"""Tests des commandes `archives-tool montrer ...`."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

import archives_tool.affichage.console as console_module
from archives_tool.affichage.console import silencer_pour_tests
from archives_tool.config import ConfigLocale
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.importers.ecrivain import importer as importer_profil
from archives_tool.models import Base, Collection
from archives_tool.profils import charger_profil

FIXTURES = Path(__file__).parent / "fixtures" / "profils"
runner = CliRunner()


@pytest.fixture(autouse=True)
def _silencer_console() -> None:
    """Forcer la console en mode déterministe pour tous les tests."""
    silencer_pour_tests()


@pytest.fixture
def base_avec_items(tmp_path: Path) -> Path:
    """DB de test peuplée avec les fixtures cas_item_simple et
    cas_hierarchie_cote (pour avoir une hiérarchie réelle)."""
    db = tmp_path / "test.db"
    engine = creer_engine(db)
    Base.metadata.create_all(engine)

    factory = creer_session_factory(engine)
    for cas in ("cas_item_simple", "cas_hierarchie_cote"):
        dossier = tmp_path / "profils" / cas
        shutil.copytree(FIXTURES / cas, dossier)
        config = ConfigLocale(
            utilisateur="T",
            racines={
                "scans_revues": dossier / "arbre",
                "scans_archives": dossier / "arbre",
            },
        )
        with factory() as session:
            profil = charger_profil(dossier / "profil.yaml")
            importer_profil(
                profil, dossier / "profil.yaml", session, config, dry_run=False
            )

    # Ajouter une sous-collection vide pour tester l'arbre.
    with factory() as session:
        from sqlalchemy import select

        fa = session.scalar(
            select(Collection).where(Collection.cote_collection == "FA")
        )
        sous = Collection(cote_collection="FA-SOUS", titre="Sous-fonds A", parent=fa)
        session.add(sous)
        session.commit()

    engine.dispose()
    return db


@pytest.fixture
def base_vide(tmp_path: Path) -> Path:
    db = tmp_path / "vide.db"
    engine = creer_engine(db)
    Base.metadata.create_all(engine)
    engine.dispose()
    return db


def _invoquer(args: list[str]) -> tuple[int, str]:
    # Importe le module CLI à chaud pour qu'il prenne la console
    # silencée *après* l'autouse fixture (évite un cache d'instance).
    from archives_tool.cli import app

    with console_module.console.capture() as cap:
        result = runner.invoke(app, args, catch_exceptions=False)
    return result.exit_code, cap.get()


def test_montrer_collections_plat(base_avec_items: Path) -> None:
    code, sortie = _invoquer(
        ["montrer", "collections", "--db-path", str(base_avec_items)]
    )
    assert code == 0
    assert "HK" in sortie
    assert "FA" in sortie
    assert "Hara-Kiri" in sortie
    # Les compteurs apparaissent.
    assert "5" in sortie  # 5 items HK
    assert "4" in sortie  # 4 items FA


def test_montrer_collections_arbre(base_avec_items: Path) -> None:
    code, sortie = _invoquer(
        [
            "montrer",
            "collections",
            "--recursif",
            "--db-path",
            str(base_avec_items),
        ]
    )
    assert code == 0
    # Le parent et l'enfant doivent tous deux apparaître dans l'arbre.
    assert "FA" in sortie
    assert "FA-SOUS" in sortie


def test_montrer_collections_avec_items_seulement(base_avec_items: Path) -> None:
    # FA-SOUS est vide : avec --avec-items elle ne doit pas apparaître
    # en mode plat.
    code, sortie = _invoquer(
        [
            "montrer",
            "collections",
            "--avec-items",
            "--db-path",
            str(base_avec_items),
        ]
    )
    assert code == 0
    assert "FA-SOUS" not in sortie
    assert "HK" in sortie
    assert "FA" in sortie


def test_montrer_collections_base_vide(base_vide: Path) -> None:
    code, sortie = _invoquer(["montrer", "collections", "--db-path", str(base_vide)])
    assert code == 0
    assert "Aucune collection" in sortie
