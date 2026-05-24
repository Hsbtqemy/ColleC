"""Tests de la route /recherche (Lot B V0.9.x)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from archives_tool.api.main import app
from archives_tool.db import (
    assurer_tables_fts,
    creer_engine,
    creer_session_factory,
    reindexer_fts,
)
from archives_tool.demo import peupler_base
from archives_tool.models import Fonds, Item
from archives_tool.models.base import Base


@pytest.fixture
def base_demo_path(tmp_path: Path) -> Path:
    """Base demo avec FTS5 créées + peuplées depuis l'existant.
    Le seeder demo ne crée pas les FTS (pas dans le modèle ORM),
    donc on les ajoute via `assurer_tables_fts` puis on les peuple
    via `reindexer_fts` (factorisation propre, même SQL que la
    migration)."""
    chemin = tmp_path / "demo.db"
    peupler_base(chemin)
    engine = creer_engine(chemin)
    assurer_tables_fts(engine)
    reindexer_fts(engine)
    engine.dispose()
    return chemin


@pytest.fixture
def client_demo(base_demo_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("ARCHIVES_DB", str(base_demo_path))
    return TestClient(app)


def test_route_recherche_sans_query_rend_page_vide(client_demo: TestClient) -> None:
    """GET /recherche sans `q` rend la page avec le formulaire mais
    aucun résultat — invite à taper une requête."""
    response = client_demo.get("/recherche")
    assert response.status_code == 200
    assert "Recherche" in response.text
    # Pas de message "X résultats" puisque pas de query
    assert "résultat" not in response.text or "résultats" not in response.text
    # Le placeholder du champ visible
    assert "Mot, cote, expression" in response.text


def test_route_recherche_avec_query_renvoie_resultats(
    client_demo: TestClient,
) -> None:
    """Recherche sur la cote partielle d'un item demo."""
    response = client_demo.get("/recherche?q=HK-001")
    assert response.status_code == 200
    assert "HK-001" in response.text
    # Lien direct vers l'item
    assert 'href="/item/HK-001?fonds=HK"' in response.text


def test_route_recherche_filtre_types(client_demo: TestClient) -> None:
    """Avec `types=item`, seuls les items remontent (pas les fonds
    ou collections, même si la query matcherait)."""
    response = client_demo.get("/recherche?q=Hara&types=item")
    assert response.status_code == 200
    # Hara-Kiri matche le fonds HK ET les items HK-001/002/003 par
    # cote (HK-001 → préfixe HK matche tous via wildcard).
    # Avec types=item, on a les items mais pas le badge FONDS.
    assert "HK-001" in response.text or "HK-002" in response.text
    # Aucun badge "FONDS" visible
    assert ">Fonds</span>" not in response.text


def test_route_recherche_scope_fonds(
    client_demo: TestClient, base_demo_path: Path,
) -> None:
    """Avec fonds_id, les résultats sont limités aux items/collections
    du fonds. Le bandeau indique le filtre actif."""
    engine = creer_engine(base_demo_path)
    SessionLocal = creer_session_factory(engine)
    with SessionLocal() as db:
        fonds_hk = db.scalar(select(Fonds).where(Fonds.cote == "HK"))
        fonds_id = fonds_hk.id
    engine.dispose()

    response = client_demo.get(f"/recherche?q=HK&fonds_id={fonds_id}")
    assert response.status_code == 200
    # Filtre actif visible
    assert "Limité au fonds" in response.text


def test_route_recherche_snippet_html_safe(client_demo: TestClient) -> None:
    """Le snippet FTS5 inclut des balises <mark> qui doivent être
    rendues telles quelles (pas échappées) pour surligner les matchs.
    `satirique` est dans la description du fonds HK du seeder demo —
    match riche garanti."""
    response = client_demo.get("/recherche?q=satirique")
    assert response.status_code == 200
    # Les <mark> du snippet apparaissent dans le HTML (le mot dans
    # le snippet de description du fonds HK).
    assert "<mark>" in response.text
    # Et le mot recherché est rendu.
    assert "satirique" in response.text.lower()


def test_route_recherche_aucun_resultat(client_demo: TestClient) -> None:
    """Recherche qui ne matche rien : message clair, pas de crash."""
    response = client_demo.get("/recherche?q=zzzznonexistantzzzz")
    assert response.status_code == 200
    assert "Aucun résultat" in response.text


def test_recherche_snippet_html_echappe_protege_xss(
    client_demo: TestClient, base_demo_path: Path,
) -> None:
    """Passe de revue : un Item dont la description contient du HTML
    malveillant (cas réel : metadonnees libre venant d'un tableur
    avec contenu utilisateur arbitraire) ne doit PAS être injecté
    tel quel dans la page de recherche. Le filtre `snippet_fts_safe`
    échappe le HTML utilisateur ET préserve les balises `<mark>` du
    snippet FTS5."""
    from archives_tool.api.services.fonds import lire_fonds_par_cote
    from archives_tool.api.services.items import (
        FormulaireItem, creer_item,
    )

    engine = creer_engine(base_demo_path)
    SessionLocal = creer_session_factory(engine)
    with SessionLocal() as db:
        fonds_hk = lire_fonds_par_cote(db, "HK")
        creer_item(
            db,
            FormulaireItem(
                cote="HK-XSS",
                titre="Item piégé pour XSS test",
                description="<script>alert('xss')</script>",
                fonds_id=fonds_hk.id,
            ),
        )
    engine.dispose()

    response = client_demo.get("/recherche?q=HK-XSS")
    assert response.status_code == 200
    # Le <script> brut doit être échappé (apparaît en &lt;script&gt;
    # ou similaire), pas exécutable.
    assert "<script>alert" not in response.text
    # Mais la balise <mark> du snippet doit être présente (non échappée).
    assert "<mark>" in response.text


def test_combo_scope_et_types(
    client_demo: TestClient, base_demo_path: Path,
) -> None:
    """Passe de revue : scope (limite géographique) + types (filtre
    entité) fonctionnent en combo. Un fonds_id avec types=item ne
    doit pas remonter le fonds lui-même même s'il matcherait."""
    engine = creer_engine(base_demo_path)
    SessionLocal = creer_session_factory(engine)
    with SessionLocal() as db:
        fonds_hk = db.scalar(select(Fonds).where(Fonds.cote == "HK"))
        fonds_id = fonds_hk.id
    engine.dispose()

    response = client_demo.get(
        f"/recherche?q=HK&fonds_id={fonds_id}&types=item"
    )
    assert response.status_code == 200
    assert "Limité au fonds" in response.text
    # Pas de badge Fonds (types=item l'exclut)
    assert ">Fonds</span>" not in response.text


def test_barre_recherche_globale_dans_header(
    client_demo: TestClient,
) -> None:
    """Lot C V0.9.x : la barre de recherche est dans le header global,
    visible sur toutes les pages. Submit GET → /recherche."""
    response = client_demo.get("/")
    assert response.status_code == 200
    # Barre input présente
    assert 'id="recherche-globale-input"' in response.text
    # Form pointe sur /recherche
    assert 'action="/recherche"' in response.text
    # Hint placeholder visible
    assert "/  pour focus" in response.text


def test_script_raccourci_recherche_charge(client_demo: TestClient) -> None:
    """Lot C V0.9.x : `js/recherche_globale.js` est chargé sur toutes
    les pages (via base.html) pour le raccourci `/` ou Cmd+K."""
    response = client_demo.get("/")
    assert response.status_code == 200
    assert "js/recherche_globale.js" in response.text


def test_route_recherche_query_invalide_pas_de_crash(
    client_demo: TestClient,
) -> None:
    """Caractères réservés FTS5 dans la query → 200 sans résultats
    plutôt que 500 (le service les échappe via _preparer_requete_fts)."""
    response = client_demo.get('/recherche?q=":()*+')
    assert response.status_code == 200
