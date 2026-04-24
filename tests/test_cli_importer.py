"""Tests de la commande CLI `archives-tool importer`."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from archives_tool.cli import app
from archives_tool.db import creer_engine
from archives_tool.models import Base

FIXTURES = Path(__file__).parent / "fixtures" / "profils"
runner = CliRunner()


@pytest.fixture
def env(tmp_path: Path) -> dict[str, Path]:
    """Prépare un environnement complet : DB vide migrée, config locale,
    copie du profil et de son tableur/arbre dans un dossier isolé."""
    db = tmp_path / "test.db"
    engine = creer_engine(db)
    Base.metadata.create_all(engine)
    engine.dispose()

    # Copie du profil cas_item_simple + arbre PNG.
    dossier_profil = tmp_path / "profils" / "cas_item_simple"
    shutil.copytree(FIXTURES / "cas_item_simple", dossier_profil)

    config = tmp_path / "config.yaml"
    config.write_text(
        f"""
utilisateur: "Test-CLI"
racines:
  scans_revues: {dossier_profil / "arbre"}
""",
        encoding="utf-8",
    )

    return {
        "db": db,
        "config": config,
        "profil": dossier_profil / "profil.yaml",
    }


def test_cli_dry_run(env: dict[str, Path]) -> None:
    result = runner.invoke(
        app,
        [
            "importer",
            str(env["profil"]),
            "--dry-run",
            "--db-path",
            str(env["db"]),
            "--config",
            str(env["config"]),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "DRY-RUN" in result.output
    assert "5 créés" in result.output


def test_cli_mode_reel_ecrit_en_base(env: dict[str, Path]) -> None:
    from sqlalchemy import select

    from archives_tool.db import creer_session_factory
    from archives_tool.models import Collection, OperationImport

    result = runner.invoke(
        app,
        [
            "importer",
            str(env["profil"]),
            "--no-dry-run",
            "--db-path",
            str(env["db"]),
            "--config",
            str(env["config"]),
            "--utilisateur",
            "Alice",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "RÉEL" in result.output

    engine = creer_engine(env["db"])
    factory = creer_session_factory(engine)
    with factory() as session:  # type: Session
        col = session.scalar(
            select(Collection).where(Collection.cote_collection == "HK")
        )
        assert col is not None
        assert col.cree_par == "Alice"
        journal = session.scalar(select(OperationImport))
        assert journal is not None
        assert journal.execute_par == "Alice"
    engine.dispose()


def test_cli_profil_invalide_code_sortie(tmp_path: Path, env: dict[str, Path]) -> None:
    # Un YAML sans version_profil doit remonter en ProfilInvalide et
    # faire sortir avec exit_code non-zéro.
    invalide = tmp_path / "mauvais.yaml"
    invalide.write_text(
        """
collection:
  cote: "X"
  titre: "Sans version"
tableur:
  chemin: "t.csv"
mapping:
  cote: "Cote"
""",
        encoding="utf-8",
    )
    result = runner.invoke(
        app,
        [
            "importer",
            str(invalide),
            "--db-path",
            str(env["db"]),
            "--config",
            str(env["config"]),
        ],
    )
    assert result.exit_code == 2
    assert "version_profil" in result.output or "version_profil" in (
        result.stderr or ""
    )


def test_cli_config_absente(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "importer",
            str(FIXTURES / "cas_item_simple" / "profil.yaml"),
            "--config",
            str(tmp_path / "n_existe_pas.yaml"),
        ],
    )
    assert result.exit_code == 2
