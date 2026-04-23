"""Tests du chargement de `config_local.yaml`."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from archives_tool.config import ConfigLocale, charger_config


def _ecrire_yaml(chemin: Path, contenu: str) -> Path:
    chemin.write_text(contenu, encoding="utf-8")
    return chemin


def test_config_valide(tmp_path: Path) -> None:
    racine_scans = tmp_path / "scans"
    racine_scans.mkdir()
    cfg_path = _ecrire_yaml(
        tmp_path / "config.yaml",
        f"""
utilisateur: "Marie Dupont"
racines:
  scans: {racine_scans}
""",
    )
    cfg = charger_config(cfg_path)
    assert isinstance(cfg, ConfigLocale)
    assert cfg.utilisateur == "Marie Dupont"
    assert cfg.racines["scans"] == racine_scans


def test_racine_inexistante_rejetee(tmp_path: Path) -> None:
    cfg_path = _ecrire_yaml(
        tmp_path / "config.yaml",
        f"""
utilisateur: "Marie"
racines:
  scans: {tmp_path / "n_existe_pas"}
""",
    )
    with pytest.raises(ValidationError):
        charger_config(cfg_path)


def test_racine_pointant_sur_fichier_rejetee(tmp_path: Path) -> None:
    faux = tmp_path / "faux.txt"
    faux.write_text("x", encoding="utf-8")
    cfg_path = _ecrire_yaml(
        tmp_path / "config.yaml",
        f"""
utilisateur: "Marie"
racines:
  scans: {faux}
""",
    )
    with pytest.raises(ValidationError):
        charger_config(cfg_path)


def test_utilisateur_vide_rejete(tmp_path: Path) -> None:
    cfg_path = _ecrire_yaml(
        tmp_path / "config.yaml",
        """
utilisateur: ""
racines: {}
""",
    )
    with pytest.raises(ValidationError):
        charger_config(cfg_path)


def test_yaml_non_mapping_rejete(tmp_path: Path) -> None:
    cfg_path = _ecrire_yaml(tmp_path / "config.yaml", "- une\n- liste\n")
    with pytest.raises(ValueError):
        charger_config(cfg_path)


def test_config_sans_racines_ok(tmp_path: Path) -> None:
    cfg_path = _ecrire_yaml(tmp_path / "config.yaml", 'utilisateur: "Jean"\n')
    cfg = charger_config(cfg_path)
    assert cfg.racines == {}
