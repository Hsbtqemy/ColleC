"""Tests d'intégration des routes /collection/... et /item/..."""

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


def test_collection_root_redirige_vers_items(base_demo: Path) -> None:
    client = TestClient(app)
    resp = client.get("/collection/HK", follow_redirects=False)
    assert resp.status_code == 307
    assert resp.headers["location"] == "/collection/HK/items"


def test_collection_inexistante_404(base_demo: Path) -> None:
    client = TestClient(app)
    resp = client.get("/collection/N_EXISTE_PAS/items")
    assert resp.status_code == 404


def test_onglet_items_full_html(base_demo: Path) -> None:
    client = TestClient(app)
    resp = client.get("/collection/HK/items")
    assert resp.status_code == 200
    # Page complète : header + tabs + table.
    assert "<header" in resp.text
    assert "Hara-Kiri" in resp.text
    assert "<table" in resp.text


def test_onglet_items_partial_via_htmx(base_demo: Path) -> None:
    client = TestClient(app)
    resp = client.get("/collection/HK/items", headers={"HX-Request": "true"})
    assert resp.status_code == 200
    # Partiel : table sans le header de page (qui contiendrait <h1>).
    assert "<table" in resp.text
    assert "<h1" not in resp.text


def test_onglet_sous_collections(base_demo: Path) -> None:
    client = TestClient(app)
    # FA a 4 sous-collections dans la démo.
    resp = client.get("/collection/FA/sous-collections")
    assert resp.status_code == 200
    for sub in ("FA-AA", "FA-AB", "FA-AC", "FA-AD"):
        assert sub in resp.text


def test_onglet_fichiers(base_demo: Path) -> None:
    client = TestClient(app)
    resp = client.get("/collection/HK/fichiers")
    assert resp.status_code == 200
    # Au moins une ligne avec un nom de fichier généré par la démo.
    assert "HK-001" in resp.text


def test_vue_item(base_demo: Path) -> None:
    client = TestClient(app)
    resp = client.get("/item/HK-001")
    assert resp.status_code == 200
    assert 'id="visionneuse"' in resp.text
    assert "sources-fichiers" in resp.text
    assert "openseadragon" in resp.text


def test_vue_item_inexistant(base_demo: Path) -> None:
    client = TestClient(app)
    resp = client.get("/item/N_EXISTE_PAS")
    assert resp.status_code == 404


def test_vue_item_avec_fichier_initial(base_demo: Path) -> None:
    client = TestClient(app)
    resp = client.get("/item/HK-001?fichier=42")
    assert resp.status_code == 200
    assert "FICHIER_INITIAL_ID = 42" in resp.text


def test_breadcrumb_collection_racine(base_demo: Path) -> None:
    client = TestClient(app)
    resp = client.get("/collection/HK/items")
    assert resp.status_code == 200
    # Tableau de bord (lien) + HK (page courante).
    assert ">Tableau de bord</a>" in resp.text
    assert ">HK</span>" in resp.text


def test_breadcrumb_sous_collection_inclut_parent(base_demo: Path) -> None:
    """Pour FA-AB, le fil d'ariane doit inclure FA (parent)."""
    client = TestClient(app)
    resp = client.get("/collection/FA-AB/items")
    assert resp.status_code == 200
    # FA en tant que lien parent dans le fil d'ariane.
    assert 'href="/collection/FA"' in resp.text


def test_empty_state_collection_vide(base_demo: Path, tmp_path: Path) -> None:
    """Collection sans items et sans sous-collections → empty state."""
    # On crée une collection vide via le POST.
    client = TestClient(app)
    client.post(
        "/collections", data={"cote": "VIDE", "titre": "Vide"}, follow_redirects=False
    )
    resp = client.get("/collection/VIDE/items")
    assert resp.status_code == 200
    assert "Cette collection ne contient aucun item" in resp.text
    assert "Importer un tableur" in resp.text
    assert "/import?collection=VIDE" in resp.text
    # Lien "Ajouter un item manuellement" désactivé.
    assert 'aria-disabled="true"' in resp.text


def test_empty_state_pas_si_des_sous_collections(base_demo: Path) -> None:
    """FA a 4 sous-collections — pas d'empty state items prononcé."""
    client = TestClient(app)
    resp = client.get("/collection/FA/items")
    assert resp.status_code == 200
    # FA n'a pas d'items mais a des sous-collections : message court,
    # pas la grosse boîte d'empty state.
    assert "Cette collection ne contient aucun item" not in resp.text


def test_empty_state_sous_collections_avec_lien_parent(base_demo: Path) -> None:
    """HK n'a pas de sous-collections : empty state avec lien parent."""
    client = TestClient(app)
    resp = client.get("/collection/HK/sous-collections")
    assert resp.status_code == 200
    assert "Créer une sous-collection" in resp.text
    assert "/collections/nouvelle?parent=HK" in resp.text


def test_bandeau_collection_a_les_boutons_modifier_et_importer(
    base_demo: Path,
) -> None:
    client = TestClient(app)
    resp = client.get("/collection/HK/items")
    assert resp.status_code == 200
    # Boutons d'action sur le bandeau (V0.7.x).
    assert 'href="/collection/HK/modifier"' in resp.text
    assert "Modifier la collection" in resp.text
    assert 'href="/import?collection=HK"' in resp.text
    assert "Importer dans cette collection" in resp.text
