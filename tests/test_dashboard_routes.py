"""Tests d'intégration du dashboard et des routes placeholders."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from archives_tool.api.main import app
from archives_tool.api.services.fonds import FormulaireFonds, creer_fonds
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.demo import peupler_base
from archives_tool.models import Base
from _helpers import texte_visible as _texte_visible


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def base_demo_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    chemin = tmp_path_factory.mktemp("demo_routes") / "demo.db"
    peupler_base(chemin)
    return chemin


@pytest.fixture
def client_demo(
    base_demo_path: Path, monkeypatch: pytest.MonkeyPatch
) -> TestClient:
    monkeypatch.setenv("ARCHIVES_DB", str(base_demo_path))
    return TestClient(app)


@pytest.fixture
def client_vide(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Client sur une base existante mais sans aucun fonds (tables vides)."""
    db_path = tmp_path / "vide.db"
    engine = creer_engine(db_path)
    Base.metadata.create_all(engine)
    engine.dispose()
    monkeypatch.setenv("ARCHIVES_DB", str(db_path))
    return TestClient(app)


# ---------------------------------------------------------------------------
# Dashboard : composition
# ---------------------------------------------------------------------------


def test_dashboard_charge_sur_base_vide(client_vide: TestClient) -> None:
    response = client_vide.get("/")
    assert response.status_code == 200
    texte = _texte_visible(response.text)
    assert "Fonds (0)" in texte or "Aucun fonds" in texte
    assert "Collections transversales" not in texte


def test_dashboard_affiche_5_fonds_demo(client_demo: TestClient) -> None:
    response = client_demo.get("/")
    assert response.status_code == 200
    texte = _texte_visible(response.text)
    assert "Fonds (5)" in texte
    for cote in ("HK", "FA", "RDM", "MAR", "CONC-1789"):
        assert cote in response.text
    assert "Hara-Kiri" in response.text
    assert "Fonds Aínsa" in response.text


def test_dashboard_collections_libres_ainsa(client_demo: TestClient) -> None:
    response = client_demo.get("/")
    for titre in ("Œuvres", "Correspondance", "Documentation", "Photographies"):
        assert titre in response.text


def test_dashboard_section_transversale_visible(client_demo: TestClient) -> None:
    response = client_demo.get("/")
    texte = _texte_visible(response.text)
    assert "Collections transversales" in texte
    assert "Témoignages d'exil" in texte
    assert "Pioche dans" in texte


def test_dashboard_compteurs_corrects(client_demo: TestClient) -> None:
    response = client_demo.get("/")
    assert "40 items" in response.text
    assert "167 items" in response.text
    assert "39 items" in response.text
    assert "18 items" in response.text


def test_dashboard_lien_fonds(client_demo: TestClient) -> None:
    response = client_demo.get("/")
    assert 'href="/fonds/HK"' in response.text


def test_dashboard_lien_collection_libre_avec_query_fonds(
    client_demo: TestClient,
) -> None:
    response = client_demo.get("/")
    assert 'href="/collection/FA-OEUVRES?fonds=FA"' in response.text


def test_dashboard_lien_transversale_sans_query_fonds(
    client_demo: TestClient,
) -> None:
    response = client_demo.get("/")
    assert 'href="/collection/TEMOIG"' in response.text


def test_dashboard_n_affiche_pas_section_transversale_si_vide(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_path = tmp_path / "minimal.db"
    engine = creer_engine(db_path)
    Base.metadata.create_all(engine)
    factory = creer_session_factory(engine)
    with factory() as s:
        creer_fonds(s, FormulaireFonds(cote="MIN", titre="Minimal"))
    engine.dispose()
    monkeypatch.setenv("ARCHIVES_DB", str(db_path))
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    texte = _texte_visible(response.text)
    assert "Fonds (1)" in texte
    assert "Collections transversales" not in texte


# ---------------------------------------------------------------------------
# /fonds (liste)
# ---------------------------------------------------------------------------


def test_liste_fonds(client_demo: TestClient) -> None:
    response = client_demo.get("/fonds")
    assert response.status_code == 200
    texte = _texte_visible(response.text)
    assert "Fonds (5)" in texte
    assert "HK" in response.text


# ---------------------------------------------------------------------------
# Placeholders fonds / collection / item
# ---------------------------------------------------------------------------


def test_fonds_placeholder(client_demo: TestClient) -> None:
    response = client_demo.get("/fonds/HK")
    assert response.status_code == 200
    assert "Hara-Kiri" in response.text
    assert "à compléter" in response.text


def test_fonds_inexistant_404(client_demo: TestClient) -> None:
    response = client_demo.get("/fonds/INEXISTANT")
    assert response.status_code == 404


def test_collection_placeholder_avec_fonds(client_demo: TestClient) -> None:
    response = client_demo.get("/collection/FA-OEUVRES?fonds=FA")
    assert response.status_code == 200
    assert "Œuvres" in response.text


def test_collection_redirige_vers_fonds_si_meme_cote(
    client_demo: TestClient,
) -> None:
    response = client_demo.get("/collection/HK", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/fonds/HK"


def test_collection_meme_cote_avec_query_fonds_n_redirige_pas(
    client_demo: TestClient,
) -> None:
    response = client_demo.get(
        "/collection/HK?fonds=HK", follow_redirects=False
    )
    assert response.status_code == 200
    assert "miroir" in response.text


def test_collection_inexistante_404(client_demo: TestClient) -> None:
    response = client_demo.get("/collection/N_EXISTE_PAS?fonds=FA")
    assert response.status_code == 404


def test_collection_transversale_sans_fonds(client_demo: TestClient) -> None:
    response = client_demo.get("/collection/TEMOIG")
    assert response.status_code == 200
    assert "Témoignages" in response.text


def test_item_placeholder(client_demo: TestClient) -> None:
    response = client_demo.get("/item/HK-001?fonds=HK")
    assert response.status_code == 200
    assert "HK-001" in response.text


def test_item_sans_fonds_renvoie_422(client_demo: TestClient) -> None:
    response = client_demo.get("/item/HK-001")
    assert response.status_code == 422


def test_item_inexistant_404(client_demo: TestClient) -> None:
    response = client_demo.get("/item/N_EXISTE_PAS?fonds=HK")
    assert response.status_code == 404
