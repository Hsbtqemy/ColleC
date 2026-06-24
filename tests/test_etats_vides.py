"""États vides explicites des listes héritées (B-hyg-3).

Trois niveaux d'état vide :
- liste de fonds vide (page /fonds) ;
- collection totalement vide (état proactif existant du partial) ;
- tableau d'items avec filtres actifs mais 0 résultat (ligne d'état
  vide de la macro `tableau_items`, ajoutée en B-hyg-3 — avant, le
  corps du tableau restait vide sans message).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from archives_tool.api.main import app
from archives_tool.api.services.fonds import FormulaireFonds, creer_fonds
from archives_tool.api.templating import templates
from archives_tool.db import (
    assurer_tables_fts,
    creer_engine,
    creer_session_factory,
)
from archives_tool.models import Base, Collection, TypeCollection


def _amorcer_base_vide(db: Path) -> None:
    """Schéma seul (sans données) — rapide, suffit pour un rendu vide."""
    engine = creer_engine(db)
    Base.metadata.create_all(engine)
    assurer_tables_fts(engine)
    engine.dispose()


def _rendre_tableau_items(ctx: dict) -> str:
    """Rend la macro `tableau_items` isolément via l'environnement Jinja
    réel (globals TRIS_ITEMS + filtres url_tri/libelle_* inclus)."""
    tmpl = templates.env.get_template("components/tableau_items.html")
    module = tmpl.make_module({})
    return module.tableau_items(ctx)


def _ctx_items_vide(compteur_filtres: str) -> dict:
    return {
        "colonnes": ["cote", "titre", "etat"],
        "sort": "cote",
        "ordre": "asc",
        "cible_url": "/collection/X",
        "id": "tableau-items",
        "items": [],
        "pagination": {"page": 1, "per_page": 50, "total": 0, "pages": 0},
        "compteur_filtres": compteur_filtres,
        "nb_colonnes_actives": 3,
        "url_panneau_colonnes": None,
        "url_retirer_template": None,
        "etat_editable": False,
    }


def test_fonds_liste_vide_affiche_etat_vide(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sur une base sans fonds, /fonds rend un appel à l'import, pas un
    tableau vide."""
    db = tmp_path / "vide.db"
    _amorcer_base_vide(db)
    monkeypatch.setenv("ARCHIVES_DB", str(db))

    client = TestClient(app)
    r = client.get("/fonds")
    assert r.status_code == 200
    assert "Aucun fonds en base" in r.text
    # Pas de <table> rendue quand la liste est vide.
    assert "<table" not in r.text


def test_collection_totalement_vide_affiche_etat_proactif(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La miroir d'un fonds neuf (0 item, 0 filtre) montre l'état proactif
    du partial (avec CTA import), pas un tableau vide."""
    db = tmp_path / "un_fonds.db"
    _amorcer_base_vide(db)

    engine = creer_engine(db)
    factory = creer_session_factory(engine)
    with factory() as s:
        fonds = creer_fonds(s, FormulaireFonds(cote="VIDE", titre="Fonds sans item"))
        miroir = s.scalar(
            select(Collection).where(
                Collection.fonds_id == fonds.id,
                Collection.type_collection == TypeCollection.MIROIR.value,
            )
        )
        miroir_cote = miroir.cote
    engine.dispose()

    monkeypatch.setenv("ARCHIVES_DB", str(db))
    client = TestClient(app)
    r = client.get(f"/collection/{miroir_cote}?fonds=VIDE")
    assert r.status_code == 200
    assert "Cette collection ne contient aucun item" in r.text


def test_tableau_items_avec_filtres_sans_resultat() -> None:
    """Tableau rendu avec des filtres actifs mais 0 item : ligne d'état
    vide distinguant le cas « filtres trop stricts »."""
    html = _rendre_tableau_items(_ctx_items_vide("1 actif"))
    assert "Aucun item ne correspond aux filtres actifs" in html


def test_tableau_items_vide_sans_filtre() -> None:
    """Sans filtre, la même macro tombe sur le message « collection vide »
    (cas atteint par d'autres consommateurs que le partial collection)."""
    html = _rendre_tableau_items(_ctx_items_vide("aucun"))
    assert "Aucun item dans cette collection" in html
