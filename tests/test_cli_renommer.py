"""Tests de `archives-tool renommer`."""

from __future__ import annotations

from pathlib import Path

import yaml
from typer.testing import CliRunner

from archives_tool.api.services.fonds import (
    FormulaireFonds,
    creer_fonds,
    lire_fonds_par_cote,
)
from archives_tool.api.services.items import FormulaireItem, creer_item
from archives_tool.cli import app
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.models import Base, Fichier

runner = CliRunner()


def _base_avec_fichiers(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Crée une mini base + fichiers physiques + config locale.

    Renvoie `(db_path, config_path, racine_scans)`.
    """
    db = tmp_path / "test.db"
    racine_scans = tmp_path / "scans"
    racine_scans.mkdir()
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "utilisateur": "Test",
                "racines": {"scans": str(racine_scans)},
            }
        ),
        encoding="utf-8",
    )

    engine = creer_engine(db)
    Base.metadata.create_all(engine)
    factory = creer_session_factory(engine)
    with factory() as s:
        creer_fonds(s, FormulaireFonds(cote="HK", titre="Hara-Kiri"))
        fonds = lire_fonds_par_cote(s, "HK")
        item = creer_item(
            s, FormulaireItem(cote="HK-001", titre="N°1", fonds_id=fonds.id)
        )
        for ordre in range(1, 4):
            nom = f"HK-001-{ordre:03d}.tif"
            (racine_scans / nom).write_bytes(b"data")
            s.add(
                Fichier(
                    item_id=item.id,
                    racine="scans",
                    chemin_relatif=nom,
                    nom_fichier=nom,
                    ordre=ordre,
                    format="tif",
                    type_page="page",
                )
            )
        s.commit()
    engine.dispose()
    return db, config_path, racine_scans


def test_cli_renommer_dry_run_par_defaut(tmp_path: Path) -> None:
    """Sans --no-dry-run, c'est un dry-run (rien ne bouge sur disque)."""
    db, conf, scans = _base_avec_fichiers(tmp_path)
    result = runner.invoke(
        app,
        [
            "renommer",
            "appliquer",
            "--template",
            "renomme/{cote}-{ordre:03d}.{ext}",
            "--fonds",
            "HK",
            "--db-path",
            str(db),
            "--config",
            str(conf),
        ],
    )
    assert result.exit_code == 0, result.output
    # Disque inchangé.
    assert (scans / "HK-001-001.tif").exists()
    assert not (scans / "renomme").exists()


def test_cli_renommer_appliquer_modifie_disque(tmp_path: Path) -> None:
    """Avec --no-dry-run, les fichiers sont effectivement déplacés."""
    db, conf, scans = _base_avec_fichiers(tmp_path)
    result = runner.invoke(
        app,
        [
            "renommer",
            "appliquer",
            "--template",
            "renomme/{cote}-{ordre:03d}.{ext}",
            "--fonds",
            "HK",
            "--no-dry-run",
            "--db-path",
            str(db),
            "--config",
            str(conf),
        ],
    )
    assert result.exit_code == 0, result.output
    assert (scans / "renomme" / "HK-001-001.tif").exists()
    assert not (scans / "HK-001-001.tif").exists()


def test_cli_renommer_collision_intra_batch(tmp_path: Path) -> None:
    """Pattern non-discriminant : conflit détecté, exit 1."""
    db, conf, scans = _base_avec_fichiers(tmp_path)
    result = runner.invoke(
        app,
        [
            "renommer",
            "appliquer",
            "--template",
            "{cote}.{ext}",  # produit la même cible pour 3 fichiers
            "--fonds",
            "HK",
            "--db-path",
            str(db),
            "--config",
            str(conf),
        ],
    )
    assert result.exit_code == 1


def test_cli_renommer_perimetre_obligatoire(tmp_path: Path) -> None:
    """Au moins un de --fonds/--collection/--item/--fichier-id requis."""
    db, conf, _ = _base_avec_fichiers(tmp_path)
    result = runner.invoke(
        app,
        [
            "renommer",
            "appliquer",
            "--template",
            "{cote}-{ordre:03d}.{ext}",
            "--db-path",
            str(db),
            "--config",
            str(conf),
        ],
    )
    assert result.exit_code == 2
    assert "exactement un" in result.output.lower()


def test_cli_renommer_template_inconnu(tmp_path: Path) -> None:
    """Template avec variable inconnue : plan rendu, exit 1."""
    db, conf, _ = _base_avec_fichiers(tmp_path)
    result = runner.invoke(
        app,
        [
            "renommer",
            "appliquer",
            "--template",
            "{xxx}.tif",
            "--fonds",
            "HK",
            "--db-path",
            str(db),
            "--config",
            str(conf),
        ],
    )
    assert result.exit_code == 1


def test_cli_renommer_historique(tmp_path: Path) -> None:
    """Après applique, `renommer historique` liste le batch."""
    db, conf, _ = _base_avec_fichiers(tmp_path)
    runner.invoke(
        app,
        [
            "renommer",
            "appliquer",
            "--template",
            "renomme/{cote}-{ordre:03d}.{ext}",
            "--fonds",
            "HK",
            "--no-dry-run",
            "--db-path",
            str(db),
            "--config",
            str(conf),
        ],
    )
    result = runner.invoke(
        app, ["renommer", "historique", "--db-path", str(db)]
    )
    assert result.exit_code == 0, result.output
    assert "Batch" in result.output  # entête du tableau
