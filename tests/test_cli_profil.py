"""Tests des commandes `archives-tool profil ...`."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from archives_tool.cli import app
from archives_tool.profils import charger_profil

FIXTURES = Path(__file__).parent / "fixtures" / "profils"
runner = CliRunner()


def test_profil_init_cree_fichier(tmp_path: Path) -> None:
    sortie = tmp_path / "p.yaml"
    result = runner.invoke(
        app,
        [
            "profil",
            "init",
            "--cote",
            "HK",
            "--titre",
            "Hara-Kiri",
            "--tableur",
            "tableur.csv",
            "--sortie",
            str(sortie),
        ],
    )
    assert result.exit_code == 0, result.output
    assert sortie.is_file()
    contenu = sortie.read_text(encoding="utf-8")
    assert '  cote: "HK"' in contenu
    assert "TODO" in contenu
    assert "✓ Profil créé" in result.output


def test_profil_init_refus_sans_force(tmp_path: Path) -> None:
    sortie = tmp_path / "p.yaml"
    sortie.write_text("preexistant", encoding="utf-8")
    result = runner.invoke(
        app,
        [
            "profil",
            "init",
            "--cote",
            "HK",
            "--titre",
            "X",
            "--tableur",
            "x.csv",
            "--sortie",
            str(sortie),
        ],
    )
    assert result.exit_code == 1
    # Le contenu original n'a pas été touché.
    assert sortie.read_text(encoding="utf-8") == "preexistant"


def test_profil_init_force_ecrase(tmp_path: Path) -> None:
    sortie = tmp_path / "p.yaml"
    sortie.write_text("preexistant", encoding="utf-8")
    result = runner.invoke(
        app,
        [
            "profil",
            "init",
            "--cote",
            "HK",
            "--titre",
            "X",
            "--tableur",
            "x.csv",
            "--sortie",
            str(sortie),
            "--force",
        ],
    )
    assert result.exit_code == 0
    assert sortie.read_text(encoding="utf-8") != "preexistant"


def test_profil_init_stdout(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "profil",
            "init",
            "--cote",
            "HK",
            "--titre",
            "X",
            "--tableur",
            "x.csv",
            "--stdout",
        ],
    )
    assert result.exit_code == 0
    assert "version_profil: 2" in result.output
    # Pas de fichier créé.
    assert not (tmp_path / "profil.yaml").exists()


def test_profil_init_granularite_invalide(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "profil",
            "init",
            "--cote",
            "HK",
            "--titre",
            "X",
            "--tableur",
            "x.csv",
            "--granularite",
            "n_importe_quoi",
            "--sortie",
            str(tmp_path / "p.yaml"),
        ],
    )
    assert result.exit_code == 2


def test_profil_analyser_cree_fichier(tmp_path: Path) -> None:
    # Copier la fixture pour éviter de polluer son dossier.
    import shutil

    src = FIXTURES / "cas_item_simple" / "tableur.csv"
    tab = tmp_path / "tableur.csv"
    shutil.copy(src, tab)

    sortie = tmp_path / "p.yaml"
    result = runner.invoke(
        app,
        [
            "profil",
            "analyser",
            str(tab),
            "--cote",
            "HK",
            "--titre",
            "Hara-Kiri",
            "--sortie",
            str(sortie),
        ],
    )
    assert result.exit_code == 0, result.output
    assert sortie.is_file()
    # Résumé dans la sortie standard.
    assert "Tableur analysé" in result.output
    assert "colonnes détectées" in result.output
    assert "mappées automatiquement" in result.output
    # Le profil produit doit être chargeable (tableur co-localisé).
    profil = charger_profil(sortie)
    assert profil.fonds.cote == "HK"
    assert "cote" in profil.mapping.champs
    assert profil.mapping.champs["cote"].source == "Cote"


def test_profil_analyser_fichier_inexistant(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "profil",
            "analyser",
            str(tmp_path / "n_existe_pas.csv"),
            "--sortie",
            str(tmp_path / "p.yaml"),
        ],
    )
    # Typer rejette à la validation de l'argument (exists=True).
    assert result.exit_code != 0


def test_profil_analyser_extension_inconnue(tmp_path: Path) -> None:
    fichier = tmp_path / "x.txt"
    fichier.write_text("nope", encoding="utf-8")
    result = runner.invoke(
        app,
        [
            "profil",
            "analyser",
            str(fichier),
            "--sortie",
            str(tmp_path / "p.yaml"),
        ],
    )
    assert result.exit_code == 2
    assert "Extension" in result.output
