"""Tests des commandes `archives-tool renommer ...`."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from sqlalchemy import select
from typer.testing import CliRunner

import archives_tool.affichage.console as console_module
from archives_tool.affichage.console import silencer_pour_tests
from archives_tool.cli import app
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.models import Base, Collection, Fichier, Item, OperationFichier

runner = CliRunner()


@pytest.fixture(autouse=True)
def _silencer_console() -> None:
    silencer_pour_tests()


def _peupler(db: Path, racine: Path) -> None:
    racine.mkdir(parents=True, exist_ok=True)
    (racine / "a.png").write_bytes(b"x")
    (racine / "b.png").write_bytes(b"y")
    engine = creer_engine(db)
    Base.metadata.create_all(engine)
    factory = creer_session_factory(engine)
    with factory() as s:
        col = Collection(cote_collection="C", titre="T")
        s.add(col)
        s.flush()
        i1 = Item(collection_id=col.id, cote="ALPHA")
        i2 = Item(collection_id=col.id, cote="BETA")
        s.add_all([i1, i2])
        s.flush()
        s.add_all(
            [
                Fichier(
                    item_id=i1.id,
                    racine="s",
                    chemin_relatif="a.png",
                    nom_fichier="a.png",
                    ordre=1,
                ),
                Fichier(
                    item_id=i2.id,
                    racine="s",
                    chemin_relatif="b.png",
                    nom_fichier="b.png",
                    ordre=1,
                ),
            ]
        )
        s.commit()
    engine.dispose()


def _ecrire_config(chemin: Path, racine: Path) -> None:
    chemin.write_text(
        yaml.safe_dump({"utilisateur": "T", "racines": {"s": str(racine)}}),
        encoding="utf-8",
    )


def _invoquer(args: list[str]) -> tuple[int, str]:
    with console_module.console.capture() as cap:
        result = runner.invoke(app, args, catch_exceptions=False)
    return result.exit_code, cap.get()


def test_renommer_dry_run_affiche_plan_sans_toucher_disque(tmp_path: Path) -> None:
    db = tmp_path / "t.db"
    racine = tmp_path / "scans"
    cfg = tmp_path / "config.yaml"
    _peupler(db, racine)
    _ecrire_config(cfg, racine)

    code, sortie = _invoquer(
        [
            "renommer",
            "appliquer",
            "--template",
            "{cote}.{ext}",
            "--collection",
            "C",
            "--db-path",
            str(db),
            "--config",
            str(cfg),
        ]
    )
    assert code == 0
    assert "DRY-RUN" in sortie
    # Plan affiche les cibles ALPHA.png et BETA.png.
    assert "ALPHA.png" in sortie
    assert "BETA.png" in sortie
    # Disque inchangé.
    assert (racine / "a.png").exists()
    assert not (racine / "ALPHA.png").exists()


def test_renommer_no_dry_run_applique(tmp_path: Path) -> None:
    db = tmp_path / "t.db"
    racine = tmp_path / "scans"
    cfg = tmp_path / "config.yaml"
    _peupler(db, racine)
    _ecrire_config(cfg, racine)

    code, sortie = _invoquer(
        [
            "renommer",
            "appliquer",
            "--template",
            "{cote}.{ext}",
            "--collection",
            "C",
            "--no-dry-run",
            "--db-path",
            str(db),
            "--config",
            str(cfg),
        ]
    )
    assert code == 0
    assert (racine / "ALPHA.png").exists()
    assert (racine / "BETA.png").exists()


def test_renommer_plan_non_applicable_exit_1(tmp_path: Path) -> None:
    db = tmp_path / "t.db"
    racine = tmp_path / "scans"
    cfg = tmp_path / "config.yaml"
    _peupler(db, racine)
    _ecrire_config(cfg, racine)
    # Squatter ALPHA.png pour fabriquer une collision externe.
    (racine / "ALPHA.png").write_bytes(b"squat")

    code, sortie = _invoquer(
        [
            "renommer",
            "appliquer",
            "--template",
            "{cote}.{ext}",
            "--collection",
            "C",
            "--db-path",
            str(db),
            "--config",
            str(cfg),
        ]
    )
    assert code == 1
    assert "collision" in sortie.lower() or "applicable" in sortie.lower()


def test_renommer_annuler_inverse(tmp_path: Path) -> None:
    db = tmp_path / "t.db"
    racine = tmp_path / "scans"
    cfg = tmp_path / "config.yaml"
    _peupler(db, racine)
    _ecrire_config(cfg, racine)

    code, _ = _invoquer(
        [
            "renommer",
            "appliquer",
            "--template",
            "{cote}.{ext}",
            "--collection",
            "C",
            "--no-dry-run",
            "--db-path",
            str(db),
            "--config",
            str(cfg),
        ]
    )
    assert code == 0

    # Récupère le batch_id depuis le journal.
    engine = creer_engine(db)
    factory = creer_session_factory(engine)
    with factory() as s:
        op = s.scalar(select(OperationFichier))
        batch = op.batch_id
    engine.dispose()

    code, sortie = _invoquer(
        [
            "renommer",
            "annuler",
            "--batch-id",
            batch,
            "--no-dry-run",
            "--db-path",
            str(db),
            "--config",
            str(cfg),
        ]
    )
    assert code == 0
    assert (racine / "a.png").exists()
    assert not (racine / "ALPHA.png").exists()


def test_renommer_historique_liste_les_batchs(tmp_path: Path) -> None:
    db = tmp_path / "t.db"
    racine = tmp_path / "scans"
    cfg = tmp_path / "config.yaml"
    _peupler(db, racine)
    _ecrire_config(cfg, racine)

    _invoquer(
        [
            "renommer",
            "appliquer",
            "--template",
            "{cote}.{ext}",
            "--collection",
            "C",
            "--no-dry-run",
            "--db-path",
            str(db),
            "--config",
            str(cfg),
        ]
    )

    code, sortie = _invoquer(["renommer", "historique", "--db-path", str(db)])
    assert code == 0
    assert "rename" in sortie
