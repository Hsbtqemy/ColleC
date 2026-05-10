"""Tests d'intégration du dashboard et des routes placeholders."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from archives_tool.api.main import app
from archives_tool.api.services.fonds import FormulaireFonds, creer_fonds
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.demo import peupler_base
from archives_tool.models import Base, CollaborateurFonds, Collection, Fonds, Item, ItemCollection
from sqlalchemy import select as sa_select

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
def db_demo_factory(base_demo_path: Path):
    """Factory de sessions sur la base demo (lecture/écriture).

    Utile pour les tests qui ont besoin de lire la DB avant et/ou après
    un appel HTTP : `with db_demo_factory() as s: ...`."""
    engine = creer_engine(base_demo_path)
    try:
        yield creer_session_factory(engine)
    finally:
        engine.dispose()


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


def test_fonds_lecture_composants_riches(client_demo: TestClient) -> None:
    """V0.9.2-alpha : la page Fonds rend tableau_collections + avancement
    + cellule_modifie. Vérification par marqueurs HTML."""
    response = client_demo.get("/fonds/HK")
    assert response.status_code == 200
    # Bandeau : section avancement + nb fichiers.
    assert "Avancement du catalogage" in response.text
    # tableau_collections injecte un id `collections-fonds-<cote>`.
    assert 'id="collections-fonds-HK"' in response.text
    # Header de tableau (l'une des colonnes attendues).
    assert "Avancement" in response.text


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
    client_demo: TestClient, db_demo_factory
) -> None:
    """Supprime un collaborateur seedé : redirige et la page ne le
    montre plus."""
    with db_demo_factory() as s:
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
    client_demo: TestClient, db_demo_factory
) -> None:
    """Un collaborateur de FA ne peut pas être supprimé via /fonds/HK/."""
    with db_demo_factory() as s:
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


# ---------------------------------------------------------------------------
# Édition collection (V0.9.0-beta.2.1)
# ---------------------------------------------------------------------------


def test_modifier_collection_libre_charge(client_demo: TestClient) -> None:
    response = client_demo.get(
        "/collection/FA-OEUVRES/modifier?fonds=FA"
    )
    assert response.status_code == 200
    assert "Œuvres" in response.text
    assert 'value="FA-OEUVRES"' in response.text  # cote pré-affichée


def test_modifier_collection_miroir_403(client_demo: TestClient) -> None:
    response = client_demo.get("/collection/HK/modifier?fonds=HK")
    assert response.status_code == 403


def test_modifier_collection_transversale_charge(
    client_demo: TestClient,
) -> None:
    response = client_demo.get("/collection/TEMOIG/modifier")
    assert response.status_code == 200
    assert "Témoignages" in response.text


def test_modifier_collection_post_succes(client_demo: TestClient) -> None:
    response = client_demo.post(
        "/collection/FA-OEUVRES/modifier?fonds=FA",
        data={
            "cote": "FA-OEUVRES",
            "titre": "Œuvres (modifié)",
            "phase": "catalogage",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/collection/FA-OEUVRES?fonds=FA"
    relue = client_demo.get("/collection/FA-OEUVRES?fonds=FA")
    assert "Œuvres (modifié)" in relue.text


def test_modifier_collection_titre_vide_re_render(
    client_demo: TestClient,
) -> None:
    response = client_demo.post(
        "/collection/FA-OEUVRES/modifier?fonds=FA",
        data={"cote": "FA-OEUVRES", "titre": "", "phase": "catalogage"},
        follow_redirects=False,
    )
    assert response.status_code == 400


def test_modifier_collection_post_miroir_403(client_demo: TestClient) -> None:
    response = client_demo.post(
        "/collection/HK/modifier?fonds=HK",
        data={"cote": "HK", "titre": "X", "phase": "catalogage"},
        follow_redirects=False,
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Tableau d'items + pagination + filtre état
# ---------------------------------------------------------------------------


def test_collection_lecture_affiche_tableau_items(
    client_demo: TestClient,
) -> None:
    response = client_demo.get("/collection/FA-OEUVRES?fonds=FA")
    assert response.status_code == 200
    # Au moins une ligne d'item visible.
    assert "FA-OEUVRES-001" in response.text


def test_collection_libre_a_bouton_ajouter(client_demo: TestClient) -> None:
    response = client_demo.get("/collection/FA-OEUVRES?fonds=FA")
    assert "items/picker" in response.text


def test_collection_miroir_pas_de_bouton_ajouter(
    client_demo: TestClient,
) -> None:
    response = client_demo.get("/collection/HK?fonds=HK")
    # La miroir : pas de bouton picker.
    assert "items/picker" not in response.text


def test_collection_lecture_composants_riches(client_demo: TestClient) -> None:
    """V0.9.2-beta : la page Collection rend bandeau enrichi
    (avancement_detaille + traçabilité + compteurs) + tableau_items
    avec pagination intégrée."""
    response = client_demo.get("/collection/HK?fonds=HK")
    assert response.status_code == 200
    # Bandeau enrichi.
    assert "Avancement du catalogage" in response.text
    # tableau_items inclut la barre d'actions Filtrer / Colonnes /
    # Exporter, et son id de wrapper.
    assert "Filtrer" in response.text
    assert "Colonnes" in response.text
    assert 'id="tableau-items"' in response.text
    # Pagination intégrée par tableau_items.
    assert "1–40 sur 40" in response.text or "1-40 sur 40" in response.text


def test_collection_pagination(client_demo: TestClient) -> None:
    response = client_demo.get(
        "/collection/FA?fonds=FA&par_page=50&page=1"
    )
    assert response.status_code == 200
    # FA a 167 items dans sa miroir → pagination active. Le composant
    # `pagination.html` rend « 1–50 sur 167 ».
    texte = _texte_visible(response.text)
    assert "1–50 sur 167" in texte or "1-50 sur 167" in texte


def test_collection_filtre_etat(client_demo: TestClient) -> None:
    response = client_demo.get(
        "/collection/FA-OEUVRES?fonds=FA&etat=brouillon"
    )
    assert response.status_code == 200


def test_collection_filtre_etat_multi_csv(client_demo: TestClient) -> None:
    """V0.9.2-beta.2 : le filtre état accepte des valeurs multiples
    en CSV (cumul OR), et les pastilles s'affichent."""
    response = client_demo.get(
        "/collection/FA?fonds=FA&etat=brouillon,a_verifier"
    )
    assert response.status_code == 200
    # Pastilles présentes : « État: Brouillon ✕ » + « État: À vérifier ✕ »
    assert "Filtres actifs" in response.text
    # Compteur dans le bouton « Filtrer · 1 »
    assert "Filtrer" in response.text


def test_collection_filtre_etat_multi_cles_repetees(
    client_demo: TestClient,
) -> None:
    """Régression V0.9.2-beta.2 : les `<select multiple>` envoient
    `?etat=A&etat=B` (clés répétées) ; la route doit conserver les
    deux états (auparavant FastAPI ne gardait que la dernière)."""
    response = client_demo.get(
        "/collection/FA",
        params=[
            ("fonds", "FA"),
            ("etat", "brouillon"),
            ("etat", "a_verifier"),
        ],
    )
    assert response.status_code == 200
    assert "Filtres actifs" in response.text
    # Les deux pastilles d'état sont présentes.
    assert "Brouillon" in response.text
    assert "À vérifier" in response.text or "vérifier" in response.text


def test_collection_filtre_etat_invalide_ignore(client_demo: TestClient) -> None:
    """Un état hors enum est silencieusement ignoré (pas de 400)."""
    response = client_demo.get(
        "/collection/FA?fonds=FA&etat=inexistant"
    )
    assert response.status_code == 200
    # Aucune pastille rendue puisque le filtre est invalide.
    assert "Filtres actifs" not in response.text


def test_collection_filtre_periode(client_demo: TestClient) -> None:
    """Filtre par plage d'années."""
    response = client_demo.get(
        "/collection/HK?fonds=HK&annee_de=1969&annee_a=1972"
    )
    assert response.status_code == 200
    assert "Filtres actifs" in response.text
    assert "Période" in response.text


def test_collection_transversale_montre_colonne_fonds(
    client_demo: TestClient,
) -> None:
    response = client_demo.get("/collection/TEMOIG")
    assert response.status_code == 200
    # Header Fonds présent dans la table car transversale.
    texte = _texte_visible(response.text)
    assert "Fonds" in texte


# ---------------------------------------------------------------------------
# Item picker
# ---------------------------------------------------------------------------


def test_picker_charge(client_demo: TestClient) -> None:
    response = client_demo.get(
        "/collection/FA-OEUVRES/items/picker?fonds=FA"
    )
    assert response.status_code == 200
    assert "Ajouter" in response.text


def test_picker_miroir_403(client_demo: TestClient) -> None:
    response = client_demo.get(
        "/collection/HK/items/picker?fonds=HK"
    )
    assert response.status_code == 403


def test_picker_transversale_filtre_fonds(client_demo: TestClient) -> None:
    response = client_demo.get(
        "/collection/TEMOIG/items/picker?fonds_filter=HK"
    )
    assert response.status_code == 200
    # Au moins un item HK proposé.
    assert "HK-" in response.text


def test_picker_recherche(client_demo: TestClient) -> None:
    response = client_demo.get(
        "/collection/FA-OEUVRES/items/picker?fonds=FA&recherche=manuscrit"
    )
    assert response.status_code == 200


def test_ajouter_items_a_collection(
    client_demo: TestClient, db_demo_factory
) -> None:
    """Ajout multi-id idempotent vers une transversale."""
    with db_demo_factory() as s:
        fonds_hk = s.scalar(sa_select(Fonds).where(Fonds.cote == "HK"))
        item_ids = list(
            s.scalars(
                sa_select(Item.id)
                .where(Item.fonds_id == fonds_hk.id)
                .order_by(Item.cote)
                .limit(2)
            ).all()
        )
        transv = s.scalar(sa_select(Collection).where(Collection.cote == "TEMOIG"))
        coll_id = transv.id

    response = client_demo.post(
        "/collection/TEMOIG/items",
        data={"item_ids": item_ids},
        follow_redirects=False,
    )
    assert response.status_code == 303

    # Vérifier la persistance directement en DB plutôt que via le
    # rendu HTML (la pagination peut placer HK-XXX hors page 1).
    with db_demo_factory() as s:
        for iid in item_ids:
            assert s.get(ItemCollection, (iid, coll_id)) is not None


def test_ajouter_items_idempotent(
    client_demo: TestClient, db_demo_factory
) -> None:
    """Le second submit ne crée pas de doublon."""
    with db_demo_factory() as s:
        fonds_fa = s.scalar(sa_select(Fonds).where(Fonds.cote == "FA"))
        un_item = s.scalar(
            sa_select(Item).where(Item.fonds_id == fonds_fa.id).limit(1)
        )
        iid = un_item.id

    # Premier ajout (l'item est déjà dans la miroir, mais on l'ajoute
    # à TEMOIG : il y est en demo avec d'autres items déjà).
    r1 = client_demo.post(
        "/collection/TEMOIG/items",
        data={"item_ids": str(iid)},
        follow_redirects=False,
    )
    # Second ajout du même : idempotent → 303 sans erreur.
    r2 = client_demo.post(
        "/collection/TEMOIG/items",
        data={"item_ids": str(iid)},
        follow_redirects=False,
    )
    assert r1.status_code == 303
    assert r2.status_code == 303


def test_ajouter_items_a_miroir_403(client_demo: TestClient) -> None:
    response = client_demo.post(
        "/collection/HK/items?fonds=HK",
        data={"item_ids": "1"},
        follow_redirects=False,
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Retrait d'item
# ---------------------------------------------------------------------------


def test_retirer_item_de_libre(
    client_demo: TestClient, db_demo_factory
) -> None:
    with db_demo_factory() as s:
        oeuvres = s.scalar(
            sa_select(Collection).where(Collection.cote == "FA-OEUVRES")
        )
        liaison = s.scalar(
            sa_select(ItemCollection)
            .where(ItemCollection.collection_id == oeuvres.id)
            .limit(1)
        )
        iid = liaison.item_id
        coll_id = oeuvres.id

    response = client_demo.post(
        f"/collection/FA-OEUVRES/items/{iid}/retirer?fonds=FA",
        follow_redirects=False,
    )
    assert response.status_code == 303

    # Vérifier la suppression de la liaison.
    with db_demo_factory() as s:
        relue = s.get(ItemCollection, (iid, coll_id))
        assert relue is None


def test_retirer_item_de_miroir_garde_dans_fonds(
    client_demo: TestClient, db_demo_factory
) -> None:
    """Invariant 7 : retirer un item de la miroir ne le supprime pas
    du fonds."""
    with db_demo_factory() as s:
        fonds_hk = s.scalar(sa_select(Fonds).where(Fonds.cote == "HK"))
        fonds_hk_id = fonds_hk.id
        un_item = s.scalar(
            sa_select(Item).where(Item.fonds_id == fonds_hk_id).limit(1)
        )
        iid = un_item.id

    response = client_demo.post(
        f"/collection/HK/items/{iid}/retirer?fonds=HK",
        follow_redirects=False,
    )
    assert response.status_code == 303

    # L'item existe toujours dans son fonds.
    with db_demo_factory() as s:
        item = s.get(Item, iid)
        assert item is not None
        assert item.fonds_id == fonds_hk_id


def test_retirer_item_idempotent(
    client_demo: TestClient, db_demo_factory
) -> None:
    """Retirer un item déjà absent : pas d'erreur."""
    with db_demo_factory() as s:
        un_item = s.scalar(sa_select(Item).limit(1))
        iid = un_item.id

    # FA-OEUVRES ne contient probablement pas un HK item.
    response = client_demo.post(
        f"/collection/FA-OEUVRES/items/{iid}/retirer?fonds=FA",
        follow_redirects=False,
    )
    assert response.status_code == 303


# ---------------------------------------------------------------------------
# Page item — lecture, visionneuse, service de fichier (V0.9.0-beta.3)
# ---------------------------------------------------------------------------


def test_page_item_lecture_charge(client_demo: TestClient) -> None:
    response = client_demo.get("/item/HK-001?fonds=HK")
    assert response.status_code == 200
    assert "HK-001" in response.text
    # Bandeau : titre du fonds + breadcrumb cliquable.
    assert "Hara-Kiri" in response.text
    assert 'href="/"' in response.text
    assert 'href="/fonds/HK"' in response.text


def test_page_item_lecture_collections_appartenance(
    client_demo: TestClient, db_demo_factory
) -> None:
    """Tout item nouvellement créé est dans sa miroir → badge `miroir`.

    On évite HK-001 car d'autres tests retirent le premier item HK de
    sa miroir (invariant 7) ; on prend une cote d'un fonds non muté."""
    with db_demo_factory() as s:
        # Premier item d'un fonds que les autres tests ne touchent pas.
        row = s.execute(
            sa_select(Item.cote, Fonds.cote.label("fonds_cote"))
            .join(Fonds, Fonds.id == Item.fonds_id)
            .where(Fonds.cote.in_(("MAR", "RDM", "CONC-1789")))
            .order_by(Fonds.cote, Item.cote)
            .limit(1)
        ).first()
    assert row is not None
    response = client_demo.get(f"/item/{row.cote}?fonds={row.fonds_cote}")
    assert response.status_code == 200
    assert "Présent dans les collections" in response.text
    assert "miroir" in response.text


def test_page_item_lecture_visionneuse_premier_fichier(
    client_demo: TestClient,
) -> None:
    """Le premier fichier (ordre=1) est affiché par défaut."""
    response = client_demo.get("/item/HK-001?fonds=HK")
    assert response.status_code == 200
    # Le seeder crée des fichiers nommés `{cote}-{ordre:02d}.tif`.
    assert "HK-001-01.tif" in response.text
    # Position 1 / N affichée dans le contrôle de navigation.
    assert "1 /" in response.text


def test_page_item_lecture_visionneuse_navigation(
    client_demo: TestClient,
) -> None:
    """?fichier_courant=2 affiche le 2e fichier."""
    response = client_demo.get("/item/HK-001?fonds=HK&fichier_courant=2")
    assert response.status_code == 200
    assert "HK-001-02.tif" in response.text


def test_page_item_lecture_visionneuse_format_non_natif(
    client_demo: TestClient,
) -> None:
    """Format TIFF (non supporté) : message + lien de téléchargement."""
    response = client_demo.get("/item/HK-001?fonds=HK")
    assert response.status_code == 200
    assert "non supporté nativement" in response.text
    assert "Télécharger le fichier" in response.text


def test_page_item_lecture_clamp_position_si_depasse(
    client_demo: TestClient,
) -> None:
    """?fichier_courant trop grand est clampé sur le dernier fichier."""
    response = client_demo.get("/item/HK-001?fonds=HK&fichier_courant=999")
    assert response.status_code == 200
    # La position effective <= nb_fichiers : pas de crash.


def test_servir_fichier_404_si_disque_absent(client_demo: TestClient) -> None:
    """Sur la base demo, les chemins sont fictifs : la racine n'est pas
    configurée → 404."""
    # Récupérer l'id d'un fichier de HK-001 — par convention seeder
    # ordre=1 existe.
    response = client_demo.get("/item/HK-001?fonds=HK")
    assert response.status_code == 200
    # On utilise l'API directement plutôt que parser le HTML.
    # L'id le plus bas existe en demo.
    response = client_demo.get("/item/HK-001/fichiers/1?fonds=HK")
    assert response.status_code == 404


def test_servir_fichier_anti_confused_deputy(
    client_demo: TestClient, db_demo_factory
) -> None:
    """Demander un fichier d'un autre item via /item/X/fichiers/{id} → 404."""
    with db_demo_factory() as s:
        # Récupère un fichier rattaché à HK-001.
        fonds_hk = s.scalar(sa_select(Fonds).where(Fonds.cote == "HK"))
        item_hk1 = s.scalar(
            sa_select(Item).where(
                Item.fonds_id == fonds_hk.id, Item.cote == "HK-001"
            )
        )
        from archives_tool.models import Fichier as FichierModel

        f_id = s.scalar(
            sa_select(FichierModel.id)
            .where(FichierModel.item_id == item_hk1.id)
            .order_by(FichierModel.ordre)
            .limit(1)
        )

    # Demander ce fichier via un autre item du même fonds → 404.
    response = client_demo.get(f"/item/HK-002/fichiers/{f_id}?fonds=HK")
    assert response.status_code == 404


def test_servir_fichier_inexistant_404(client_demo: TestClient) -> None:
    response = client_demo.get("/item/HK-001/fichiers/9999999?fonds=HK")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Page item — édition (V0.9.0-beta.3)
# ---------------------------------------------------------------------------


def test_modifier_item_charge(client_demo: TestClient) -> None:
    response = client_demo.get("/item/HK-001/modifier?fonds=HK")
    assert response.status_code == 200
    assert "HK-001" in response.text
    # La cote est verrouillée (input disabled), le fonds aussi.
    assert "ne peut pas être modifiée" in response.text
    assert "immuable" in response.text


def test_modifier_item_inexistant_404(client_demo: TestClient) -> None:
    response = client_demo.get("/item/N_EXISTE_PAS/modifier?fonds=HK")
    assert response.status_code == 404


def test_modifier_item_sans_fonds_422(client_demo: TestClient) -> None:
    response = client_demo.get("/item/HK-001/modifier")
    assert response.status_code == 422


def test_post_modifier_item_succes(
    client_demo: TestClient, db_demo_factory
) -> None:
    response = client_demo.post(
        "/item/HK-001/modifier?fonds=HK",
        data={
            "cote": "HK-001",
            "titre": "Numéro 1 (modifié par test)",
            "fonds_id": "999",  # ignoré silencieusement (immuable)
            "etat_catalogage": "valide",
            "annee": "1969",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "/item/HK-001" in response.headers["location"]

    # Vérifier la persistance en DB.
    with db_demo_factory() as s:
        fonds_hk = s.scalar(sa_select(Fonds).where(Fonds.cote == "HK"))
        item = s.scalar(
            sa_select(Item).where(
                Item.fonds_id == fonds_hk.id, Item.cote == "HK-001"
            )
        )
        assert item.titre == "Numéro 1 (modifié par test)"
        assert item.etat_catalogage == "valide"
        assert item.annee == 1969
        # fonds_id immuable : silent override.
        assert item.fonds_id == fonds_hk.id


def test_post_modifier_item_titre_vide(client_demo: TestClient) -> None:
    response = client_demo.post(
        "/item/HK-002/modifier?fonds=HK",
        data={
            "cote": "HK-002",
            "titre": "",
            "fonds_id": "1",
            "etat_catalogage": "brouillon",
        },
    )
    assert response.status_code == 400
    # Le formulaire est ré-rendu avec le message d'erreur.
    assert "titre" in response.text.lower()
