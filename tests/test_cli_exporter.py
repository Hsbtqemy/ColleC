"""Tests de la commande CLI `archives-tool exporter`."""

from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd
import pytest
from typer.testing import CliRunner

from archives_tool.cli import app
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.importers.ecrivain import importer as importer_profil
from archives_tool.models import Base
from archives_tool.profils import charger_profil

FIXTURES = Path(__file__).parent / "fixtures" / "profils"
runner = CliRunner()


@pytest.fixture
def base(tmp_path: Path) -> Path:
    """Base temporaire avec cas_item_simple importé."""
    db = tmp_path / "test.db"
    engine = creer_engine(db)
    Base.metadata.create_all(engine)

    dossier = tmp_path / "profils" / "cas_item_simple"
    shutil.copytree(FIXTURES / "cas_item_simple", dossier)

    from archives_tool.config import ConfigLocale

    config = ConfigLocale(
        utilisateur="T",
        racines={"scans_revues": dossier / "arbre"},
    )
    factory = creer_session_factory(engine)
    with factory() as session:
        profil = charger_profil(dossier / "profil.yaml")
        importer_profil(profil, dossier / "profil.yaml", session, config, dry_run=False)
    engine.dispose()
    return db


def test_cli_export_xlsx(base: Path, tmp_path: Path) -> None:
    sortie = tmp_path / "out.xlsx"
    result = runner.invoke(
        app,
        [
            "exporter",
            "xlsx",
            "--collection",
            "HK",
            "--sortie",
            str(sortie),
            "--db-path",
            str(base),
        ],
    )
    assert result.exit_code == 0, result.output
    assert sortie.is_file()
    df = pd.read_excel(sortie)
    assert len(df) == 5


def test_cli_export_dc_xml(base: Path, tmp_path: Path) -> None:
    sortie = tmp_path / "out.xml"
    result = runner.invoke(
        app,
        [
            "exporter",
            "dc-xml",
            "--collection",
            "HK",
            "--sortie",
            str(sortie),
            "--db-path",
            str(base),
        ],
    )
    assert result.exit_code == 0, result.output
    assert sortie.is_file()
    assert sortie.read_text(encoding="utf-8").startswith("<?xml")


def test_cli_export_nakala_csv(base: Path, tmp_path: Path) -> None:
    sortie = tmp_path / "out.csv"
    result = runner.invoke(
        app,
        [
            "exporter",
            "nakala-csv",
            "--collection",
            "HK",
            "--sortie",
            str(sortie),
            "--db-path",
            str(base),
            "--licence",
            "CC-BY-4.0",
        ],
    )
    assert result.exit_code == 0, result.output
    assert sortie.is_file()
    df = pd.read_csv(sortie, sep=";", encoding="utf-8-sig")
    assert (df["http://nakala.fr/terms#license"] == "CC-BY-4.0").all()


def test_cli_dry_run_ne_cree_pas_le_fichier(base: Path, tmp_path: Path) -> None:
    sortie = tmp_path / "dry.xlsx"
    result = runner.invoke(
        app,
        [
            "exporter",
            "xlsx",
            "--collection",
            "HK",
            "--sortie",
            str(sortie),
            "--db-path",
            str(base),
            "--dry-run",
        ],
    )
    assert result.exit_code == 0, result.output
    assert not sortie.exists()


def test_cli_collection_inexistante(base: Path, tmp_path: Path) -> None:
    sortie = tmp_path / "out.xlsx"
    result = runner.invoke(
        app,
        [
            "exporter",
            "xlsx",
            "--collection",
            "N_EXISTE_PAS",
            "--sortie",
            str(sortie),
            "--db-path",
            str(base),
        ],
    )
    assert result.exit_code == 2
    assert "introuvable" in (result.output + (result.stderr or "")).lower()


def test_cli_format_inconnu(base: Path, tmp_path: Path) -> None:
    sortie = tmp_path / "out.zzz"
    result = runner.invoke(
        app,
        [
            "exporter",
            "xml-custom",
            "--collection",
            "HK",
            "--sortie",
            str(sortie),
            "--db-path",
            str(base),
        ],
    )
    assert result.exit_code == 2


def test_cli_strict_remonte_items_incomplets(base: Path, tmp_path: Path) -> None:
    # Ajout d'un item incomplet pour DC (sans titre).
    from sqlalchemy import select
    from archives_tool.models import Collection, Item

    engine = creer_engine(base)
    factory = creer_session_factory(engine)
    with factory() as s:
        col = s.scalar(select(Collection).where(Collection.cote_collection == "HK"))
        s.add(Item(collection_id=col.id, cote="HK-sans-titre"))
        s.commit()
    engine.dispose()

    sortie = tmp_path / "out.xml"
    result = runner.invoke(
        app,
        [
            "exporter",
            "dc-xml",
            "--collection",
            "HK",
            "--sortie",
            str(sortie),
            "--db-path",
            str(base),
            "--strict",
        ],
    )
    assert result.exit_code == 1
