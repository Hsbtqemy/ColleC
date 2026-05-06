"""Tests de la commande `archives-tool controler`."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

import archives_tool.affichage.console as console_module
from archives_tool.affichage.console import silencer_pour_tests
from archives_tool.cli import app
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.models import Base, Collection, Fichier, Item

runner = CliRunner()


@pytest.fixture(autouse=True)
def _silencer_console() -> None:
    silencer_pour_tests()


def _peupler(db: Path, racine: Path) -> None:
    racine.mkdir(parents=True, exist_ok=True)
    (racine / "ref.png").write_bytes(b"x")
    (racine / "orph.png").write_bytes(b"y")

    engine = creer_engine(db)
    Base.metadata.create_all(engine)
    factory = creer_session_factory(engine)
    with factory() as s:
        col = Collection(cote_collection="C", titre="T")
        s.add(col)
        s.flush()
        i_avec = Item(collection_id=col.id, cote="AVEC")
        i_vide = Item(collection_id=col.id, cote="VIDE")
        s.add_all([i_avec, i_vide])
        s.flush()
        s.add(
            Fichier(
                item_id=i_avec.id,
                racine="s",
                chemin_relatif="ref.png",
                nom_fichier="ref.png",
                ordre=1,
            )
        )
        s.add(
            Fichier(
                item_id=i_avec.id,
                racine="s",
                chemin_relatif="manquant.png",
                nom_fichier="manquant.png",
                ordre=2,
            )
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


def test_controler_remonte_les_quatre_categories(tmp_path: Path) -> None:
    db = tmp_path / "t.db"
    racine = tmp_path / "scans"
    cfg = tmp_path / "config.yaml"
    _peupler(db, racine)
    _ecrire_config(cfg, racine)

    code, sortie = _invoquer(["controler", "--db-path", str(db), "--config", str(cfg)])
    # Anomalies présentes (manquant + orphelin + item vide) → exit 1.
    assert code == 1
    # Les quatre titres apparaissent dans le rapport.
    assert "absents du disque" in sortie
    assert "non référencés" in sortie
    assert "sans fichier" in sortie
    assert "Doublons" in sortie
    # Détails clés visibles.
    assert "manquant.png" in sortie
    assert "orph.png" in sortie
    assert "VIDE" in sortie


def test_controler_subset_via_check(tmp_path: Path) -> None:
    db = tmp_path / "t.db"
    racine = tmp_path / "scans"
    cfg = tmp_path / "config.yaml"
    _peupler(db, racine)
    _ecrire_config(cfg, racine)

    code, sortie = _invoquer(
        [
            "controler",
            "--db-path",
            str(db),
            "--config",
            str(cfg),
            "--check",
            "items-vides",
        ]
    )
    assert code == 1
    assert "sans fichier" in sortie
    assert "absents du disque" not in sortie


def test_controler_collection_introuvable_exit_2(tmp_path: Path) -> None:
    db = tmp_path / "t.db"
    racine = tmp_path / "scans"
    cfg = tmp_path / "config.yaml"
    _peupler(db, racine)
    _ecrire_config(cfg, racine)

    code, sortie = _invoquer(
        [
            "controler",
            "--db-path",
            str(db),
            "--config",
            str(cfg),
            "--collection",
            "N_EXISTE_PAS",
        ]
    )
    assert code == 2


def test_controler_sans_config_avertit_mais_continue(tmp_path: Path) -> None:
    db = tmp_path / "t.db"
    racine = tmp_path / "scans"
    _peupler(db, racine)

    # Pas de config locale fournie : le contrôle items-vides reste utile.
    code, sortie = _invoquer(
        [
            "controler",
            "--db-path",
            str(db),
            "--config",
            str(tmp_path / "absente.yaml"),
            "--check",
            "items-vides",
        ]
    )
    assert code == 1
    assert "VIDE" in sortie


def test_controler_aucune_anomalie_exit_0(tmp_path: Path) -> None:
    db = tmp_path / "t.db"
    engine = creer_engine(db)
    Base.metadata.create_all(engine)
    engine.dispose()

    code, sortie = _invoquer(
        [
            "controler",
            "--db-path",
            str(db),
            "--config",
            str(tmp_path / "absente.yaml"),
        ]
    )
    assert code == 0
