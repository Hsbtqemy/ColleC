"""Tests de la commande `archives-tool demo init`.

Tests d'intégrité de la base produite vivent dans
`test_demo_seeder.py` ; ce fichier ne couvre que la CLI elle-même
(refus / force / sortie console)."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

import archives_tool.affichage.console as console_module
from archives_tool.affichage.console import silencer_pour_tests
from archives_tool.cli import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def _silencer_console() -> None:
    silencer_pour_tests()


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
    # Base SQLite réelle, plus le placeholder de 8 octets.
    assert db.stat().st_size > 1000
