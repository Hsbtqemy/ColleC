"""Tests de la liseuse consultation (Lot 1 V0.9.x).

Couvre :
- Route `/lire/<fonds>/<cote>` : rendu HTML 200 + layout 3 colonnes
- Partial visionneuse `/lire/<fonds>/<cote>/visionneuse/<id>` : 200
- Bouton « Mode consultation » du header sur item/collection/fonds
- Sur la liseuse : chip « Mode consultation actif »
- Navigation pages (← Page / Page →) via boutons HTMX
- Navigation items (← Item / Item →) via liens reload
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from archives_tool.api.main import app
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.demo import peupler_base
from archives_tool.models import Fichier, Item


@pytest.fixture
def base_demo_path(tmp_path: Path) -> Path:
    chemin = tmp_path / "demo.db"
    peupler_base(chemin)
    return chemin


@pytest.fixture
def client_demo(base_demo_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("ARCHIVES_DB", str(base_demo_path))
    return TestClient(app)


@pytest.fixture
def db_demo_factory(base_demo_path: Path):
    engine = creer_engine(base_demo_path)
    try:
        yield creer_session_factory(engine)
    finally:
        engine.dispose()


def test_liseuse_route_rend_200(client_demo: TestClient) -> None:
    """GET /lire/<fonds>/<cote> renvoie 200 et le template liseuse
    avec les 3 zones reconnaissables."""
    response = client_demo.get("/lire/HK/HK-001")
    assert response.status_code == 200
    # Bandeau liseuse : chip Consultation distinctive
    assert "Consultation" in response.text
    # Layout 3 colonnes : meta gauche, visionneuse au centre, vignettes
    assert "zone-meta-liseuse" in response.text
    assert "zone-visionneuse" in response.text
    assert "zone-vignettes-liseuse" in response.text
    # Le bouton « Cataloguer » du bandeau (retour édition)
    assert "Cataloguer" in response.text


def test_liseuse_route_chip_mode_actif_dans_header(
    client_demo: TestClient,
) -> None:
    """Sur la liseuse, le header affiche le chip distinctif
    « Mode consultation actif » au lieu du bouton bascule classique."""
    response = client_demo.get("/lire/HK/HK-001")
    assert response.status_code == 200
    assert "Mode consultation actif" in response.text


def test_liseuse_route_404_si_cote_inconnue(client_demo: TestClient) -> None:
    response = client_demo.get("/lire/HK/HK-NOPE")
    assert response.status_code == 404


def test_liseuse_route_404_si_fonds_inconnu(client_demo: TestClient) -> None:
    response = client_demo.get("/lire/NOPE/HK-001")
    assert response.status_code == 404


def test_liseuse_route_position_clampee(client_demo: TestClient) -> None:
    """`?fichier=N` trop grand est clampé sur le dernier fichier (idem
    page item édition). Pas de crash."""
    response = client_demo.get("/lire/HK/HK-001?fichier=999")
    assert response.status_code == 200


def test_partial_visionneuse_rend_200(
    client_demo: TestClient, db_demo_factory
) -> None:
    """GET /lire/<fonds>/<cote>/visionneuse/<id> renvoie le HTML d'une
    visionneuse pour swap HTMX (sans le chrome page complet)."""
    with db_demo_factory() as db:
        f = db.scalar(
            select(Fichier)
            .join(Item, Item.id == Fichier.item_id)
            .where(Item.cote == "HK-001")
            .limit(1)
        )
        fid = f.id

    response = client_demo.get(f"/lire/HK/HK-001/visionneuse/{fid}")
    assert response.status_code == 200
    # Pas de chrome complet : pas de <html>, juste le composant
    assert "<html" not in response.text.lower()
    # Le composant visionneuse_osd produit un .visionneuse-osd ou un
    # fallback message — l'un ou l'autre doit être présent.
    assert (
        "visionneuse-osd" in response.text
        or "Aucun aperçu disponible" in response.text
    )


def test_partial_visionneuse_contient_les_3_fragments_oob(
    client_demo: TestClient, db_demo_factory
) -> None:
    """Le partial renvoie 3 fragments simultanés (Lot 1 fix bug
    navigation après 1er clic) :
    - cible principale (visionneuse, sans wrapper OOB)
    - out-of-band #bandeau-liseuse (boutons Page rafraîchis)
    - out-of-band #liste-vignettes-liseuse (highlight déplacé)

    Sans ces 3 swaps, les boutons Page restent figés après le 1er
    clic et la navigation ne fonctionne plus."""
    with db_demo_factory() as db:
        f = db.scalar(
            select(Fichier)
            .join(Item, Item.id == Fichier.item_id)
            .where(Item.cote == "HK-001")
            .limit(1)
        )
        fid = f.id

    response = client_demo.get(f"/lire/HK/HK-001/visionneuse/{fid}")
    assert response.status_code == 200
    # OOB swap pour le bandeau (boutons Page à jour pour le nouveau fichier).
    assert 'hx-swap-oob="outerHTML:#bandeau-liseuse"' in response.text
    # OOB swap pour la liste vignettes (highlight `est_courant` à jour).
    assert 'id="liste-vignettes-liseuse"' in response.text
    assert 'hx-swap-oob="true"' in response.text
    # Cible principale : visionneuse OU fallback "Aucun aperçu" (HK demo).
    assert (
        "visionneuse-osd" in response.text
        or "Aucun aperçu disponible" in response.text
    )


def test_liseuse_item_sans_fichier_rend_sans_crash(
    client_demo: TestClient, db_demo_factory
) -> None:
    """Edge case : un item sans aucun Fichier doit rendre la liseuse
    proprement (visionneuse vide, panneau "Aucun fichier rattaché",
    boutons Page disabled, pas de crash 500)."""
    from archives_tool.api.services.fonds import (
        FormulaireFonds, creer_fonds,
    )
    from archives_tool.api.services.items import (
        FormulaireItem, creer_item,
    )

    # Crée un fonds + item sans Fichier dans la base demo.
    with db_demo_factory() as db:
        creer_fonds(db, FormulaireFonds(cote="VIDE", titre="Vide"))
        from archives_tool.api.services.fonds import lire_fonds_par_cote

        fonds_vide = lire_fonds_par_cote(db, "VIDE")
        creer_item(
            db,
            FormulaireItem(
                cote="VIDE-001", titre="Item vide", fonds_id=fonds_vide.id,
            ),
        )

    response = client_demo.get("/lire/VIDE/VIDE-001")
    assert response.status_code == 200
    # Le panneau vignettes affiche le message "Aucun fichier rattaché".
    assert "Aucun fichier rattaché" in response.text
    # Le bandeau affiche "Page 1 / 0" — le compteur reste cohérent.
    assert "Page" in response.text


def test_partial_visionneuse_404_si_fichier_autre_item(
    client_demo: TestClient, db_demo_factory
) -> None:
    """Anti-confused-deputy : un fichier appartenant à un autre item
    renvoie 404, même si l'ID existe."""
    with db_demo_factory() as db:
        # Récupère un fichier d'un AUTRE item que HK-001
        autre = db.scalar(
            select(Fichier)
            .join(Item, Item.id == Fichier.item_id)
            .where(Item.cote != "HK-001")
            .limit(1)
        )
        autre_id = autre.id

    response = client_demo.get(f"/lire/HK/HK-001/visionneuse/{autre_id}")
    assert response.status_code == 404


def test_page_item_affiche_bouton_mode_consultation(
    client_demo: TestClient,
) -> None:
    """Bouton « Mode consultation » du header présent sur la page
    item édition avec l'URL pointant vers la liseuse."""
    response = client_demo.get("/item/HK-001?fonds=HK")
    assert response.status_code == 200
    assert "Mode consultation" in response.text
    assert 'href="/lire/HK/HK-001"' in response.text


def test_page_fonds_affiche_bouton_mode_consultation(
    client_demo: TestClient,
) -> None:
    """Bouton « Mode consultation » du header présent sur la page
    fonds avec l'URL pointant sur le 1er item alphabétique."""
    response = client_demo.get("/fonds/HK")
    assert response.status_code == 200
    assert "Mode consultation" in response.text
    # Pointe vers /lire/HK/<premier item alphabétique>
    assert 'href="/lire/HK/HK-' in response.text


def test_page_collection_miroir_affiche_bouton_mode_consultation(
    client_demo: TestClient,
) -> None:
    """Bouton « Mode consultation » sur la page collection miroir."""
    response = client_demo.get("/collection/HK?fonds=HK")
    assert response.status_code == 200
    assert "Mode consultation" in response.text
    assert 'href="/lire/HK/HK-' in response.text


def test_liseuse_panneau_vignettes_utilise_hx_get(
    client_demo: TestClient,
) -> None:
    """Les vignettes du panneau droite utilisent `hx-get` vers le
    partial visionneuse au lieu d'un href reload (validation du
    mode_consultation=True dans `liste_vignettes`)."""
    response = client_demo.get("/lire/HK/HK-001")
    assert response.status_code == 200
    # Au moins une vignette pointe vers le partial visionneuse
    assert "/lire/HK/HK-001/visionneuse/" in response.text
    assert 'hx-target="#zone-visionneuse"' in response.text


def test_liseuse_bandeau_navigation_page_separee_de_item(
    client_demo: TestClient,
) -> None:
    """Le bandeau liseuse expose 2 zones de navigation distinctes :
    `Page` (fichiers de l'item courant) et `Item` (items du fonds).
    Résout la friction principale décrite par l'utilisateur."""
    response = client_demo.get("/lire/HK/HK-001")
    assert response.status_code == 200
    # Labels distincts dans le bandeau
    assert "Navigation pages" in response.text
    assert "Navigation items" in response.text
