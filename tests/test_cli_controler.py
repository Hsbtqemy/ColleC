"""Tests de `archives-tool controler` (V0.9.0-gamma.3)."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from archives_tool.api.services.fonds import FormulaireFonds, creer_fonds
from archives_tool.api.services.items import FormulaireItem, creer_item
from archives_tool.cli import app
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.models import Base

runner = CliRunner()


def _base_petite(tmp_path: Path) -> Path:
    """Petite base : 1 fonds + 2 items, sans fichier physique."""
    db = tmp_path / "test.db"
    engine = creer_engine(db)
    Base.metadata.create_all(engine)
    factory = creer_session_factory(engine)
    with factory() as s:
        creer_fonds(s, FormulaireFonds(cote="HK", titre="Hara-Kiri"))
        from archives_tool.api.services.fonds import lire_fonds_par_cote

        fonds = lire_fonds_par_cote(s, "HK")
        creer_item(s, FormulaireItem(cote="HK-001", titre="N°1", fonds_id=fonds.id))
        creer_item(s, FormulaireItem(cote="HK-002", titre="N°2", fonds_id=fonds.id))
    engine.dispose()
    return db


def test_cli_controler_base_saine(tmp_path: Path) -> None:
    """Sortie text par défaut, exit 0 sur une base saine."""
    db = _base_petite(tmp_path)
    result = runner.invoke(
        app,
        [
            "controler",
            "--db-path",
            str(db),
            "--config",
            str(tmp_path / "absent.yaml"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Bilan" in result.output
    assert "INV1" in result.output


def test_cli_controler_format_json(tmp_path: Path) -> None:
    """`--format json` produit un JSON valide avec la structure attendue."""
    db = _base_petite(tmp_path)
    result = runner.invoke(
        app,
        [
            "controler",
            "--db-path",
            str(db),
            "--format",
            "json",
            "--config",
            str(tmp_path / "absent.yaml"),
        ],
    )
    assert result.exit_code == 0, result.output
    rapport = json.loads(result.output)
    assert rapport["version_qa"] == "0.9.0"
    assert "controles" in rapport
    assert "bilan" in rapport
    assert rapport["bilan"]["erreurs"] == 0
    # 14 contrôles.
    assert len(rapport["controles"]) == 14


def test_cli_controler_filtre_par_fonds(tmp_path: Path) -> None:
    db = _base_petite(tmp_path)
    result = runner.invoke(
        app,
        [
            "controler",
            "--fonds",
            "HK",
            "--db-path",
            str(db),
            "--format",
            "json",
            "--config",
            str(tmp_path / "absent.yaml"),
        ],
    )
    assert result.exit_code == 0, result.output
    rapport = json.loads(result.output)
    assert rapport["perimetre"]["type"] == "fonds"


def test_cli_controler_fonds_inexistant(tmp_path: Path) -> None:
    db = _base_petite(tmp_path)
    result = runner.invoke(
        app,
        [
            "controler",
            "--fonds",
            "INEXISTANT",
            "--db-path",
            str(db),
            "--config",
            str(tmp_path / "absent.yaml"),
        ],
    )
    assert result.exit_code == 1
    assert "introuvable" in result.output.lower()


def test_cli_controler_fonds_et_collection_exclusifs(tmp_path: Path) -> None:
    db = _base_petite(tmp_path)
    result = runner.invoke(
        app,
        [
            "controler",
            "--fonds",
            "HK",
            "--collection",
            "HK",
            "--db-path",
            str(db),
            "--config",
            str(tmp_path / "absent.yaml"),
        ],
    )
    assert result.exit_code == 2
    assert "exclusifs" in result.output.lower()


def test_cli_controler_format_invalide(tmp_path: Path) -> None:
    db = _base_petite(tmp_path)
    result = runner.invoke(
        app,
        [
            "controler",
            "--format",
            "html",
            "--db-path",
            str(db),
            "--config",
            str(tmp_path / "absent.yaml"),
        ],
    )
    assert result.exit_code == 2


def test_cli_controler_strict_avec_avertissements(tmp_path: Path) -> None:
    """`--strict` fait échouer dès qu'un avertissement remonte.
    Sur une base sans config locale, FILE-MISSING signale les racines
    non configurées en avertissement."""
    db = _base_petite(tmp_path)
    # Forcer un fichier en base pour avoir un avertissement.
    factory = creer_session_factory(creer_engine(db))
    with factory() as s:
        from archives_tool.models import Fichier, Item
        from sqlalchemy import select as sa_select

        item = s.scalar(sa_select(Item).where(Item.cote == "HK-001"))
        s.add(
            Fichier(
                item_id=item.id,
                racine="s",
                chemin_relatif="x.tif",
                nom_fichier="x.tif",
                ordre=1,
            )
        )
        s.commit()

    result = runner.invoke(
        app,
        [
            "controler",
            "--strict",
            "--db-path",
            str(db),
            "--config",
            str(tmp_path / "absent.yaml"),
        ],
    )
    assert result.exit_code == 1


def test_cli_controler_db_inexistante(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "controler",
            "--db-path",
            str(tmp_path / "absente.db"),
            "--config",
            str(tmp_path / "absent.yaml"),
        ],
    )
    assert result.exit_code == 2
    assert "introuvable" in result.output.lower()
