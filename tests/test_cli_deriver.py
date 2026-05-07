"""Tests des commandes `archives-tool deriver ...`."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from PIL import Image
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


def _peupler(db: Path, src: Path) -> None:
    src.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (800, 600), (10, 20, 30)).save(src / "01.png")

    engine = creer_engine(db)
    Base.metadata.create_all(engine)
    factory = creer_session_factory(engine)
    with factory() as s:
        col = Collection(cote_collection="C", titre="T")
        s.add(col)
        s.flush()
        item = Item(collection_id=col.id, cote="C-001")
        s.add(item)
        s.flush()
        s.add(
            Fichier(
                item_id=item.id,
                racine="src",
                chemin_relatif="01.png",
                nom_fichier="01.png",
                ordre=1,
            )
        )
        s.commit()
    engine.dispose()


def _ecrire_config(chemin: Path, src: Path, cible: Path) -> None:
    cible.mkdir(parents=True, exist_ok=True)
    chemin.write_text(
        yaml.safe_dump(
            {
                "utilisateur": "T",
                "racines": {"src": str(src), "miniatures": str(cible)},
            }
        ),
        encoding="utf-8",
    )


def _invoquer(args: list[str]) -> tuple[int, str]:
    with console_module.console.capture() as cap:
        result = runner.invoke(app, args, catch_exceptions=False)
    return result.exit_code, cap.get()


def test_deriver_appliquer_genere_les_derives(tmp_path: Path) -> None:
    db = tmp_path / "t.db"
    src = tmp_path / "scans"
    cible = tmp_path / "miniatures"
    cfg = tmp_path / "config.yaml"
    _peupler(db, src)
    _ecrire_config(cfg, src, cible)

    code, sortie = _invoquer(
        [
            "deriver",
            "appliquer",
            "--collection",
            "C",
            "--db-path",
            str(db),
            "--config",
            str(cfg),
        ]
    )
    assert code == 0
    assert (cible / "vignette" / "01.jpg").exists()
    assert (cible / "apercu" / "01.jpg").exists()
    assert "Générés" in sortie


def test_deriver_perimetre_manquant_exit_2(tmp_path: Path) -> None:
    db = tmp_path / "t.db"
    src = tmp_path / "scans"
    cible = tmp_path / "miniatures"
    cfg = tmp_path / "config.yaml"
    _peupler(db, src)
    _ecrire_config(cfg, src, cible)

    code, _ = _invoquer(
        [
            "deriver",
            "appliquer",
            "--db-path",
            str(db),
            "--config",
            str(cfg),
        ]
    )
    assert code == 2


def test_deriver_nettoyer_supprime(tmp_path: Path) -> None:
    db = tmp_path / "t.db"
    src = tmp_path / "scans"
    cible = tmp_path / "miniatures"
    cfg = tmp_path / "config.yaml"
    _peupler(db, src)
    _ecrire_config(cfg, src, cible)

    _invoquer(
        [
            "deriver",
            "appliquer",
            "--collection",
            "C",
            "--db-path",
            str(db),
            "--config",
            str(cfg),
        ]
    )
    assert (cible / "vignette" / "01.jpg").exists()

    code, _ = _invoquer(
        [
            "deriver",
            "nettoyer",
            "--collection",
            "C",
            "--db-path",
            str(db),
            "--config",
            str(cfg),
        ]
    )
    assert code == 0
    assert not (cible / "vignette" / "01.jpg").exists()
