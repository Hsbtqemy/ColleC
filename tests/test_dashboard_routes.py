"""Tests d'intégration de la route du dashboard."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from archives_tool.api.main import app
from archives_tool.demo import peupler_base


@pytest.fixture
def base_demo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "demo.db"
    peupler_base(db)
    monkeypatch.setenv("ARCHIVES_DB", str(db))
    return db


@pytest.fixture
def base_vide(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "vide.db"
    from archives_tool.db import creer_engine
    from archives_tool.models import Base

    engine = creer_engine(db)
    Base.metadata.create_all(engine)
    engine.dispose()
    monkeypatch.setenv("ARCHIVES_DB", str(db))
    return db


def test_dashboard_repond_200(base_demo: Path) -> None:
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200


def test_dashboard_contient_titre(base_demo: Path) -> None:
    client = TestClient(app)
    resp = client.get("/")
    assert "Tableau de bord" in resp.text


def test_dashboard_contient_collections_demo(base_demo: Path) -> None:
    client = TestClient(app)
    resp = client.get("/")
    # Les cinq collections racines doivent apparaître dans le tableau.
    for cote in ("FA", "HK", "PF", "RDM", "LE"):
        assert cote in resp.text


def test_dashboard_base_vide_ne_plante_pas(base_vide: Path) -> None:
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Aucune collection" in resp.text


def test_dashboard_affiche_nom_base(base_demo: Path) -> None:
    client = TestClient(app)
    resp = client.get("/")
    assert "demo.db" in resp.text
