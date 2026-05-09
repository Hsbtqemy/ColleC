"""Tests des commandes `archives-tool collections ...` (V0.9.0-gamma.1)."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from typer.testing import CliRunner

from archives_tool.api.services.fonds import (
    FormulaireFonds,
    creer_fonds,
    lire_fonds_par_cote,
)
from archives_tool.cli import app
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.models import Base, Collection

runner = CliRunner()


def _base_avec_fonds(tmp_path: Path) -> Path:
    """Crée une base SQLite avec un fonds HK + un fonds FA."""
    db = tmp_path / "test.db"
    engine = creer_engine(db)
    Base.metadata.create_all(engine)
    factory = creer_session_factory(engine)
    with factory() as s:
        creer_fonds(s, FormulaireFonds(cote="HK", titre="Hara-Kiri"))
        creer_fonds(s, FormulaireFonds(cote="FA", titre="Fonds Aínsa"))
    engine.dispose()
    return db


# ---------------------------------------------------------------------------
# creer-libre
# ---------------------------------------------------------------------------


def test_creer_libre_rattachee(tmp_path: Path) -> None:
    db = _base_avec_fonds(tmp_path)
    result = runner.invoke(
        app,
        [
            "collections",
            "creer-libre",
            "HK-OEUVRES",
            "Œuvres complètes",
            "--fonds",
            "HK",
            "--db-path",
            str(db),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "HK-OEUVRES" in result.output
    assert "rattachée au fonds HK" in result.output


def test_creer_libre_transversale(tmp_path: Path) -> None:
    db = _base_avec_fonds(tmp_path)
    result = runner.invoke(
        app,
        [
            "collections",
            "creer-libre",
            "TRANSV",
            "Collection transversale",
            "--db-path",
            str(db),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "transversale" in result.output


def test_creer_libre_fonds_inexistant(tmp_path: Path) -> None:
    db = _base_avec_fonds(tmp_path)
    result = runner.invoke(
        app,
        [
            "collections",
            "creer-libre",
            "X",
            "Test",
            "--fonds",
            "INEXISTANT",
            "--db-path",
            str(db),
        ],
    )
    assert result.exit_code == 1
    assert "introuvable" in result.output.lower()


def test_creer_libre_phase_invalide(tmp_path: Path) -> None:
    """Une phase hors enum est rejetée par Typer (exit 2 = bad usage)
    avec le message d'aide énumérant les valeurs acceptées."""
    db = _base_avec_fonds(tmp_path)
    result = runner.invoke(
        app,
        [
            "collections",
            "creer-libre",
            "X",
            "Test",
            "--fonds",
            "HK",
            "--phase",
            "phase_inconnue",
            "--db-path",
            str(db),
        ],
    )
    assert result.exit_code == 2
    assert "phase" in result.output.lower()


# ---------------------------------------------------------------------------
# lister
# ---------------------------------------------------------------------------


def test_lister_par_fonds(tmp_path: Path) -> None:
    db = _base_avec_fonds(tmp_path)
    # Ajoute une libre à HK.
    runner.invoke(
        app,
        [
            "collections",
            "creer-libre",
            "HK-OEUVRES",
            "Œuvres",
            "--fonds",
            "HK",
            "--db-path",
            str(db),
        ],
    )
    result = runner.invoke(
        app, ["collections", "lister", "--fonds", "HK", "--db-path", str(db)]
    )
    assert result.exit_code == 0, result.output
    # Miroir HK + libre HK-OEUVRES.
    assert "HK-OEUVRES" in result.output
    assert "[miroir]" in result.output
    assert "[libre]" in result.output


def test_lister_transversales(tmp_path: Path) -> None:
    db = _base_avec_fonds(tmp_path)
    runner.invoke(
        app,
        [
            "collections",
            "creer-libre",
            "TRANSV",
            "Transversale",
            "--db-path",
            str(db),
        ],
    )
    result = runner.invoke(
        app, ["collections", "lister", "--transversales", "--db-path", str(db)]
    )
    assert result.exit_code == 0, result.output
    assert "TRANSV" in result.output
    # Pas de miroir dans les transversales.
    assert "[miroir]" not in result.output


def test_lister_aucune(tmp_path: Path) -> None:
    db = tmp_path / "vide.db"
    engine = creer_engine(db)
    Base.metadata.create_all(engine)
    engine.dispose()
    result = runner.invoke(app, ["collections", "lister", "--db-path", str(db)])
    assert result.exit_code == 0
    assert "Aucune collection" in result.output


# ---------------------------------------------------------------------------
# supprimer
# ---------------------------------------------------------------------------


def test_supprimer_libre_avec_yes(tmp_path: Path) -> None:
    db = _base_avec_fonds(tmp_path)
    runner.invoke(
        app,
        [
            "collections",
            "creer-libre",
            "HK-OEUVRES",
            "Œuvres",
            "--fonds",
            "HK",
            "--db-path",
            str(db),
        ],
    )
    result = runner.invoke(
        app,
        [
            "collections",
            "supprimer",
            "HK-OEUVRES",
            "--fonds",
            "HK",
            "--yes",
            "--db-path",
            str(db),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "supprimée" in result.output

    # Vérifier en base.
    engine = creer_engine(db)
    factory = creer_session_factory(engine)
    with factory() as s:
        col = s.scalar(select(Collection).where(Collection.cote == "HK-OEUVRES"))
        assert col is None


def test_supprimer_miroir_refuse(tmp_path: Path) -> None:
    db = _base_avec_fonds(tmp_path)
    result = runner.invoke(
        app,
        [
            "collections",
            "supprimer",
            "HK",
            "--fonds",
            "HK",
            "--yes",
            "--db-path",
            str(db),
        ],
    )
    assert result.exit_code == 1
    assert "miroir" in result.output.lower()

    # La miroir existe toujours.
    engine = creer_engine(db)
    factory = creer_session_factory(engine)
    with factory() as s:
        fonds = lire_fonds_par_cote(s, "HK")
        assert fonds is not None


def test_supprimer_inexistante(tmp_path: Path) -> None:
    db = _base_avec_fonds(tmp_path)
    result = runner.invoke(
        app,
        [
            "collections",
            "supprimer",
            "INEXISTANT",
            "--yes",
            "--db-path",
            str(db),
        ],
    )
    assert result.exit_code == 1


def test_db_path_inexistant(tmp_path: Path) -> None:
    """L'erreur d'ouverture de base est claire (pas crash)."""
    result = runner.invoke(
        app,
        [
            "collections",
            "lister",
            "--db-path",
            str(tmp_path / "inexistante.db"),
        ],
    )
    assert result.exit_code == 2
    assert "introuvable" in result.output.lower()
