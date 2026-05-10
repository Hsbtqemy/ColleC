"""Tests des commandes `archives-tool deriver appliquer / nettoyer`.

Modèle V0.9.0+ : périmètres alignés sur `renommer` (--fonds, --collection,
--item, --fichier-id), Perimetre validé à l'appel.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from PIL import Image
from typer.testing import CliRunner

import archives_tool.affichage.console as console_module
from archives_tool.affichage.console import silencer_pour_tests
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


@pytest.fixture(autouse=True)
def _silencer_console() -> None:
    silencer_pour_tests()


def _peupler(db: Path, src: Path) -> None:
    """Fonds HK + miroir auto + 1 item HK-001 + 1 fichier image PNG réel."""
    src.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (800, 600), (10, 20, 30)).save(src / "01.png")

    engine = creer_engine(db)
    Base.metadata.create_all(engine)
    factory = creer_session_factory(engine)
    with factory() as s:
        creer_fonds(s, FormulaireFonds(cote="HK", titre="Hara-Kiri"))
        fonds = lire_fonds_par_cote(s, "HK")
        item = creer_item(
            s, FormulaireItem(cote="HK-001", titre="N°1", fonds_id=fonds.id)
        )
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


def _env(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    db = tmp_path / "t.db"
    src = tmp_path / "scans"
    cible = tmp_path / "miniatures"
    cfg = tmp_path / "config.yaml"
    _peupler(db, src)
    _ecrire_config(cfg, src, cible)
    return db, src, cible, cfg


def test_deriver_appliquer_par_fonds(tmp_path: Path) -> None:
    db, _, cible, cfg = _env(tmp_path)
    code, sortie = _invoquer(
        [
            "deriver",
            "appliquer",
            "--fonds",
            "HK",
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


def test_deriver_appliquer_par_collection_miroir(tmp_path: Path) -> None:
    """La miroir auto HK contient l'unique item ; --collection HK la cible."""
    db, _, cible, cfg = _env(tmp_path)
    code, _ = _invoquer(
        [
            "deriver",
            "appliquer",
            "--collection",
            "HK",
            "--fonds",
            "HK",
            "--db-path",
            str(db),
            "--config",
            str(cfg),
        ]
    )
    assert code == 0
    assert (cible / "vignette" / "01.jpg").exists()


def test_deriver_appliquer_par_item(tmp_path: Path) -> None:
    db, _, cible, cfg = _env(tmp_path)
    code, _ = _invoquer(
        [
            "deriver",
            "appliquer",
            "--item",
            "HK-001",
            "--fonds",
            "HK",
            "--db-path",
            str(db),
            "--config",
            str(cfg),
        ]
    )
    assert code == 0
    assert (cible / "vignette" / "01.jpg").exists()


def test_deriver_perimetre_manquant_exit_2(tmp_path: Path) -> None:
    db, _, _, cfg = _env(tmp_path)
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


def test_deriver_perimetres_multiples_exit_2(tmp_path: Path) -> None:
    """--collection et --item ensemble : Perimetre rejette à la construction."""
    db, _, _, cfg = _env(tmp_path)
    code, _ = _invoquer(
        [
            "deriver",
            "appliquer",
            "--collection",
            "HK",
            "--item",
            "HK-001",
            "--fonds",
            "HK",
            "--db-path",
            str(db),
            "--config",
            str(cfg),
        ]
    )
    assert code == 2


def test_deriver_collection_inconnue_exit_1(tmp_path: Path) -> None:
    db, _, _, cfg = _env(tmp_path)
    code, _ = _invoquer(
        [
            "deriver",
            "appliquer",
            "--collection",
            "INCONNUE",
            "--fonds",
            "HK",
            "--db-path",
            str(db),
            "--config",
            str(cfg),
        ]
    )
    assert code == 1


def test_deriver_nettoyer_supprime(tmp_path: Path) -> None:
    db, _, cible, cfg = _env(tmp_path)
    _invoquer(
        [
            "deriver",
            "appliquer",
            "--fonds",
            "HK",
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
            "--fonds",
            "HK",
            "--db-path",
            str(db),
            "--config",
            str(cfg),
        ]
    )
    assert code == 0
    assert not (cible / "vignette" / "01.jpg").exists()
