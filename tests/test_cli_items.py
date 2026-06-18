"""Tests des commandes `archives-tool items ...` (V0.9.7)."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import func, select
from typer.testing import CliRunner

from archives_tool.api.services.fonds import FormulaireFonds, creer_fonds
from archives_tool.cli import app
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.models import Base, Item

runner = CliRunner()


def _base_avec_fonds(tmp_path: Path, cote: str = "ZX") -> Path:
    """Base SQLite avec un fonds frais (miroir auto-créée)."""
    db = tmp_path / "test.db"
    engine = creer_engine(db)
    Base.metadata.create_all(engine)
    factory = creer_session_factory(engine)
    with factory() as s:
        creer_fonds(s, FormulaireFonds(cote=cote, titre=f"Test {cote}"))
    engine.dispose()
    return db


# ---------------------------------------------------------------------------
# creer-serie : cas nominal + erreurs
# ---------------------------------------------------------------------------


def test_creer_serie_succes(tmp_path: Path) -> None:
    """Cas nominal : 5 items créés via la CLI dans la miroir."""
    db = _base_avec_fonds(tmp_path)
    result = runner.invoke(
        app,
        [
            "items",
            "creer-serie",
            "--fonds",
            "ZX",
            "--pattern",
            "ZX-{n:03d}",
            "--de",
            "1",
            "--a",
            "5",
            "--titre",
            "Numéro {n}",
            "--db-path",
            str(db),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "5 item(s) créé" in result.output
    assert "ZX-001 → ZX-005" in result.output

    # Vérifie en base : 5 items existent
    engine = creer_engine(db)
    factory = creer_session_factory(engine)
    with factory() as s:
        n = s.scalar(select(func.count(Item.id)))
        assert n == 5
        # Titres formatés correctement
        items = list(s.scalars(select(Item).order_by(Item.cote)).all())
        assert items[0].titre == "Numéro 1"
        assert items[4].titre == "Numéro 5"
    engine.dispose()


def test_creer_serie_pattern_invalide_exit_1(tmp_path: Path) -> None:
    """Pattern sans `{n}` (produit cotes en doublon) → exit 1 +
    message d'erreur explicite, rien créé en base."""
    db = _base_avec_fonds(tmp_path)
    result = runner.invoke(
        app,
        [
            "items",
            "creer-serie",
            "--fonds",
            "ZX",
            "--pattern",
            "ZX-fixe",  # pas de {n}
            "--de",
            "1",
            "--a",
            "3",
            "--db-path",
            str(db),
        ],
    )
    assert result.exit_code == 1
    assert "pattern_cote" in result.output or "doublon" in result.output

    engine = creer_engine(db)
    factory = creer_session_factory(engine)
    with factory() as s:
        n = s.scalar(select(func.count(Item.id)))
        assert n == 0
    engine.dispose()


def test_creer_serie_fonds_inexistant_exit_1(tmp_path: Path) -> None:
    """Fonds inconnu → exit 1 du resolveur (pas du service)."""
    db = _base_avec_fonds(tmp_path)
    result = runner.invoke(
        app,
        [
            "items",
            "creer-serie",
            "--fonds",
            "INCONNU",
            "--pattern",
            "X-{n}",
            "--de",
            "1",
            "--a",
            "3",
            "--db-path",
            str(db),
        ],
    )
    assert result.exit_code == 1


def test_creer_serie_ignorer_existants_relancable(tmp_path: Path) -> None:
    """Avec --ignorer-existants, lancer 2 fois la même commande crée la
    1ère fois, ignore la 2ème (idempotent)."""
    db = _base_avec_fonds(tmp_path)
    # 1er appel
    r1 = runner.invoke(
        app,
        [
            "items",
            "creer-serie",
            "--fonds",
            "ZX",
            "--pattern",
            "ZX-{n:02d}",
            "--de",
            "1",
            "--a",
            "3",
            "--db-path",
            str(db),
        ],
    )
    assert r1.exit_code == 0
    # 2e appel : ignorer
    r2 = runner.invoke(
        app,
        [
            "items",
            "creer-serie",
            "--fonds",
            "ZX",
            "--pattern",
            "ZX-{n:02d}",
            "--de",
            "1",
            "--a",
            "3",
            "--ignorer-existants",
            "--db-path",
            str(db),
        ],
    )
    assert r2.exit_code == 0
    assert "0 item(s) créé" in r2.output
    assert "3 cote(s) ignorée" in r2.output

    # Toujours 3 items en base, pas plus
    engine = creer_engine(db)
    factory = creer_session_factory(engine)
    with factory() as s:
        n = s.scalar(select(func.count(Item.id)))
        assert n == 3
    engine.dispose()


def test_creer_serie_avec_collection_libre(tmp_path: Path) -> None:
    """--collection pointe sur une libre rattachée. Items rattachés à
    la libre ET à la miroir (invariant 6)."""
    from archives_tool.api.services.collections import (
        FormulaireCollection,
        creer_collection_libre,
    )

    db = _base_avec_fonds(tmp_path)
    engine = creer_engine(db)
    factory = creer_session_factory(engine)
    with factory() as s:
        from archives_tool.api.services.fonds import lire_fonds_par_cote

        fonds = lire_fonds_par_cote(s, "ZX")
        creer_collection_libre(
            s,
            FormulaireCollection(
                cote="ZX-FAV",
                titre="Favoris",
                fonds_id=fonds.id,
            ),
        )
    engine.dispose()

    result = runner.invoke(
        app,
        [
            "items",
            "creer-serie",
            "--fonds",
            "ZX",
            "--collection",
            "ZX-FAV",
            "--pattern",
            "ZX-{n}",
            "--de",
            "1",
            "--a",
            "2",
            "--db-path",
            str(db),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "2 item(s) créé" in result.output


def test_creer_serie_help_affiche_exemple(tmp_path: Path) -> None:
    """`--help` montre l'exemple d'usage pour démarrage rapide."""
    result = runner.invoke(app, ["items", "creer-serie", "--help"])
    assert result.exit_code == 0
    assert "creer-serie" in result.output
    assert "--pattern" in result.output
