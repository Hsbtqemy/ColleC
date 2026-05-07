"""Tests de la commande `archives-tool demo init` et du seeder."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select
from typer.testing import CliRunner

import archives_tool.affichage.console as console_module
from archives_tool.affichage.console import silencer_pour_tests
from archives_tool.cli import app
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.demo import peupler_base
from archives_tool.models import Collection, Fichier, Item

runner = CliRunner()


@pytest.fixture(autouse=True)
def _silencer_console() -> None:
    silencer_pour_tests()


def test_peupler_base_cree_collections_attendues(tmp_path: Path) -> None:
    db = tmp_path / "demo.db"
    rapport = peupler_base(db)
    assert db.exists()
    assert rapport.nb_collections_racines == 5
    assert rapport.nb_items > 100

    engine = creer_engine(db)
    factory = creer_session_factory(engine)
    with factory() as s:
        cotes = set(
            s.scalars(
                select(Collection.cote_collection).where(Collection.parent_id.is_(None))
            ).all()
        )
        assert cotes == {"FA", "HK", "PF", "RDM", "LE"}
        # FA a quatre sous-collections.
        fa = s.scalar(select(Collection).where(Collection.cote_collection == "FA"))
        assert len(fa.enfants) == 4
        # Au moins un item sans fichier (anomalie injectée).
        items_vides = s.scalars(
            select(Item).where(~Item.id.in_(select(Fichier.item_id)))
        ).all()
        assert any(it.cote == "HK-VIDE" for it in items_vides)
    engine.dispose()


def test_demo_init_cli_refuse_si_existe_sans_force(tmp_path: Path) -> None:
    db = tmp_path / "demo.db"
    db.write_bytes(b"existant")
    result = runner.invoke(
        app, ["demo", "init", "--sortie", str(db)], catch_exceptions=False
    )
    assert result.exit_code == 1


def test_demo_init_cli_force_ecrase(tmp_path: Path) -> None:
    db = tmp_path / "demo.db"
    db.write_bytes(b"existant")
    with console_module.console.capture():
        result = runner.invoke(
            app,
            ["demo", "init", "--sortie", str(db), "--force"],
            catch_exceptions=False,
        )
    assert result.exit_code == 0
    assert db.stat().st_size > 1000  # base sqlite réelle, pas le placeholder
