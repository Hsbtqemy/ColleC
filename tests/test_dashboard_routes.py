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


def test_fonds_lecture(client_demo: TestClient) -> None:
    response = client_demo.get("/fonds/HK")
    assert response.status_code == 200
    assert "Hara-Kiri" in response.text
    # Bandeau métadonnées affiche le responsable Archives.
    assert "Cavanna" in response.text
    # Au moins un item récent visible.
    assert "HK-040" in response.text


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


# ---------------------------------------------------------------------------
# Page fonds : modification
# ---------------------------------------------------------------------------


def test_fonds_modifier_charge(client_demo: TestClient) -> None:
    response = client_demo.get("/fonds/HK/modifier")
    assert response.status_code == 200
    # La cote est verrouillée et pré-affichée.
    assert 'value="HK"' in response.text
    assert "Hara-Kiri" in response.text


def test_fonds_modifier_post_redirect(client_demo: TestClient) -> None:
    response = client_demo.post(
        "/fonds/HK/modifier",
        data={
            "cote": "HK",
            "titre": "Hara-Kiri (modifié)",
            "responsable_archives": "Cavanna",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/fonds/HK"
    # Vérifier la persistance.
    relue = client_demo.get("/fonds/HK")
    assert "Hara-Kiri (modifié)" in relue.text


def test_fonds_modifier_titre_vide_re_render(client_demo: TestClient) -> None:
    response = client_demo.post(
        "/fonds/HK/modifier",
        data={"cote": "HK", "titre": ""},
        follow_redirects=False,
    )
    assert response.status_code == 400
    assert "obligatoire" in response.text.lower()


def test_fonds_modifier_inexistant_404(client_demo: TestClient) -> None:
    response = client_demo.get("/fonds/INCONNU/modifier")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Page collection : 3 variantes
# ---------------------------------------------------------------------------


def test_collection_lecture_miroir(client_demo: TestClient) -> None:
    response = client_demo.get("/collection/HK?fonds=HK")
    assert response.status_code == 200
    assert "Collection miroir" in response.text
    # Lien retour vers le fonds parent.
    assert 'href="/fonds/HK"' in response.text
    # Pas de bouton « Modifier » sur une miroir : le lien d'édition
    # n'est pas généré.
    assert "/collection/HK/modifier" not in response.text


def test_collection_lecture_libre_rattachee(client_demo: TestClient) -> None:
    response = client_demo.get("/collection/FA-OEUVRES?fonds=FA")
    assert response.status_code == 200
    assert "Œuvres" in response.text
    assert "Fonds Aínsa" in response.text
    # Bouton modifier disponible pour une libre.
    assert "/collection/FA-OEUVRES/modifier" in response.text


def test_collection_lecture_transversale(client_demo: TestClient) -> None:
    response = client_demo.get("/collection/TEMOIG")
    assert response.status_code == 200
    texte = _texte_visible(response.text)
    assert "transversale" in texte.lower()
    assert "Pioche dans" in texte
    # Au moins 2 fonds représentés.
    assert "Fonds Aínsa" in response.text
    assert "Concorde 1789" in response.text


# ---------------------------------------------------------------------------
# Collaborateurs d'un fonds
# ---------------------------------------------------------------------------


def test_collaborateurs_fonds_listes_sur_page_fonds(
    client_demo: TestClient,
) -> None:
    """Les collaborateurs seedés sur HK sont visibles."""
    response = client_demo.get("/fonds/HK")
    assert response.status_code == 200
    assert "Marie Dupont" in response.text
    assert "Hugo Martin" in response.text
    # Groupé par rôle : la libellé du rôle apparaît.
    assert "Numérisation" in response.text


def test_ajouter_collaborateur_fonds(client_demo: TestClient) -> None:
    response = client_demo.post(
        "/fonds/RDM/collaborateurs",
        data={"nom": "Lucas Bernard", "roles": ["catalogage"]},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/fonds/RDM"
    # Vérifier la présence sur la page.
    page = client_demo.get("/fonds/RDM")
    assert "Lucas Bernard" in page.text


def test_ajouter_collaborateur_nom_vide_400(client_demo: TestClient) -> None:
    response = client_demo.post(
        "/fonds/HK/collaborateurs",
        data={"nom": "", "roles": ["numerisation"]},
        follow_redirects=False,
    )
    assert response.status_code == 400
    assert "nom" in response.text.lower()


def test_ajouter_collaborateur_roles_vides_400(client_demo: TestClient) -> None:
    response = client_demo.post(
        "/fonds/HK/collaborateurs",
        data={"nom": "Test"},  # pas de roles
        follow_redirects=False,
    )
    assert response.status_code == 400


def test_ajouter_collaborateur_fonds_inexistant_404(
    client_demo: TestClient,
) -> None:
    response = client_demo.post(
        "/fonds/N_EXISTE_PAS/collaborateurs",
        data={"nom": "X", "roles": ["numerisation"]},
        follow_redirects=False,
    )
    assert response.status_code == 404


def test_supprimer_collaborateur_fonds(
    client_demo: TestClient, base_demo_path: Path
) -> None:
    """Supprime un collaborateur seedé : redirige et la page ne le
    montre plus."""
    # Récupérer l'id d'un collaborateur HK directement en DB.
    from archives_tool.models import CollaborateurFonds, Fonds
    from sqlalchemy import select as sa_select

    engine = creer_engine(base_demo_path)
    factory = creer_session_factory(engine)
    with factory() as s:
        fonds = s.scalar(sa_select(Fonds).where(Fonds.cote == "RDM"))
        # Ajouter d'abord un collaborateur dédié pour pouvoir le retirer
        # sans toucher aux fixtures partagées.
        nouveau = CollaborateurFonds(
            fonds_id=fonds.id, nom="ÀSupprimer", roles=["numerisation"]
        )
        s.add(nouveau)
        s.commit()
        s.refresh(nouveau)
        cid = nouveau.id

    response = client_demo.post(
        f"/fonds/RDM/collaborateurs/{cid}/supprimer",
        follow_redirects=False,
    )
    assert response.status_code == 303

    page = client_demo.get("/fonds/RDM")
    assert "ÀSupprimer" not in page.text


def test_collaborateur_fonds_anti_confused_deputy(
    client_demo: TestClient, base_demo_path: Path
) -> None:
    """Un collaborateur de FA ne peut pas être supprimé via /fonds/HK/."""
    from archives_tool.models import CollaborateurFonds, Fonds
    from sqlalchemy import select as sa_select

    engine = creer_engine(base_demo_path)
    factory = creer_session_factory(engine)
    with factory() as s:
        fonds_fa = s.scalar(sa_select(Fonds).where(Fonds.cote == "FA"))
        cid = s.scalar(
            sa_select(CollaborateurFonds.id).where(
                CollaborateurFonds.fonds_id == fonds_fa.id
            )
        )

    response = client_demo.post(
        f"/fonds/HK/collaborateurs/{cid}/supprimer",
        follow_redirects=False,
    )
    assert response.status_code == 404
