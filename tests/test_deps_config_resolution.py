"""Tests de la résolution du chemin de config (auto-détection adjacente)."""

from __future__ import annotations

from pathlib import Path

import pytest

from archives_tool.api.deps import _resoudre_chemin_config


def test_priorite_archives_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`ARCHIVES_CONFIG` prime sur tout le reste, même si une config
    sœur de `ARCHIVES_DB` existe."""
    cfg_explicite = tmp_path / "explicite.yaml"
    cfg_explicite.write_text("utilisateur: explicite\n", encoding="utf-8")
    db = tmp_path / "demo.db"
    db.touch()
    voisin = tmp_path / "demo_config.yaml"
    voisin.write_text("utilisateur: voisin\n", encoding="utf-8")
    monkeypatch.setenv("ARCHIVES_CONFIG", str(cfg_explicite))
    monkeypatch.setenv("ARCHIVES_DB", str(db))
    assert _resoudre_chemin_config() == cfg_explicite


def test_auto_detection_config_adjacente(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Sans `ARCHIVES_CONFIG`, on prend `<db>_config.yaml` adjacent si
    présent — évite la friction onboarding démo."""
    db = tmp_path / "demo.db"
    db.touch()
    voisin = tmp_path / "demo_config.yaml"
    voisin.write_text("utilisateur: démo\n", encoding="utf-8")
    monkeypatch.delenv("ARCHIVES_CONFIG", raising=False)
    monkeypatch.setenv("ARCHIVES_DB", str(db))
    assert _resoudre_chemin_config() == voisin


def test_fallback_config_local_si_pas_d_adjacent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Pas d'`ARCHIVES_CONFIG`, pas de config sœur → fallback sur
    `config_local.yaml` à la racine du projet."""
    db = tmp_path / "demo.db"
    db.touch()
    monkeypatch.delenv("ARCHIVES_CONFIG", raising=False)
    monkeypatch.setenv("ARCHIVES_DB", str(db))
    assert _resoudre_chemin_config() == Path("config_local.yaml")


def test_pas_d_archives_db_fallback_defaut(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Aucune variable d'env définie : fallback direct sur le défaut."""
    monkeypatch.delenv("ARCHIVES_CONFIG", raising=False)
    monkeypatch.delenv("ARCHIVES_DB", raising=False)
    assert _resoudre_chemin_config() == Path("config_local.yaml")
