"""Tests de `archives-tool reindexer` (V0.9.3)."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from archives_tool.api.services.fonds import FormulaireFonds, creer_fonds
from archives_tool.api.services.items import FormulaireItem, creer_item
from archives_tool.cli import app
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.models import Base

runner = CliRunner()


def _base_petite(tmp_path: Path, avec_fts: bool = True) -> Path:
    """1 fonds + 2 items, sans fichier physique. Si `avec_fts=False`,
    crée la base sans appeler `assurer_tables_fts` — simule une base
    ancienne pré-V0.9.3."""
    db = tmp_path / "test.db"
    engine = creer_engine(db)
    Base.metadata.create_all(engine)
    if avec_fts:
        from archives_tool.db import assurer_tables_fts

        assurer_tables_fts(engine)
    factory = creer_session_factory(engine)
    with factory() as s:
        creer_fonds(s, FormulaireFonds(cote="HK", titre="Hara-Kiri"))
        from archives_tool.api.services.fonds import lire_fonds_par_cote

        fonds = lire_fonds_par_cote(s, "HK")
        creer_item(s, FormulaireItem(cote="HK-001", titre="N1", fonds_id=fonds.id))
        creer_item(s, FormulaireItem(cote="HK-002", titre="N2", fonds_id=fonds.id))
    engine.dispose()
    return db


def test_cli_reindexer_base_existante(tmp_path: Path) -> None:
    """Reindex sur une base avec FTS existantes : exit 0, sortie
    indique le compte de chaque table FTS."""
    db = _base_petite(tmp_path, avec_fts=True)
    result = runner.invoke(app, ["reindexer", "--db-path", str(db)])
    assert result.exit_code == 0
    assert "2 items" in result.stdout
    assert "1 fonds" in result.stdout
    assert "1 collections" in result.stdout  # miroir auto-créée


def test_cli_reindexer_base_pre_v093(tmp_path: Path) -> None:
    """Cas typique : base ancienne sans tables FTS. La commande les
    crée puis les peuple — pas de plantage, exit 0."""
    db = _base_petite(tmp_path, avec_fts=False)
    result = runner.invoke(app, ["reindexer", "--db-path", str(db)])
    assert result.exit_code == 0
    assert "2 items" in result.stdout

    # Vérifie qu'on peut maintenant rechercher
    from archives_tool.api.services.recherche import rechercher

    engine = creer_engine(db)
    factory = creer_session_factory(engine)
    with factory() as s:
        res = rechercher(s, "HK")
    engine.dispose()
    # Au moins les 2 items (cote HK-001 / HK-002) + le fonds HK
    assert res.total >= 3


def test_cli_reindexer_base_introuvable(tmp_path: Path) -> None:
    """Si la base n'existe pas : exit 2 + message d'erreur."""
    result = runner.invoke(
        app, ["reindexer", "--db-path", str(tmp_path / "inexistante.db")]
    )
    assert result.exit_code == 2
    assert "introuvable" in result.stdout or "introuvable" in (result.stderr or "")


def test_cli_reindexer_idempotent(tmp_path: Path) -> None:
    """Appeler reindexer plusieurs fois ne dédouble pas l'index
    (vide puis repeuple à chaque appel)."""
    db = _base_petite(tmp_path)
    r1 = runner.invoke(app, ["reindexer", "--db-path", str(db)])
    r2 = runner.invoke(app, ["reindexer", "--db-path", str(db)])
    assert r1.exit_code == 0
    assert r2.exit_code == 0
    # Mêmes comptes à chaque appel
    assert r1.stdout == r2.stdout
