"""Tests du reliquat Lot 3 UI⁺ — autocomplete des valeurs existantes.

- Service `suggerer_valeurs` : distinct, tri, préfixe, exclusion des
  vides, whitelist des colonnes.
- Route `/api/suggestions` : JSON, whitelist.
- Câblage : la synthèse fonds porte `data-edit-suggest` sur les champs
  libres récurrents.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from archives_tool.api.main import app
from archives_tool.api.services.collections import (
    FormulaireCollection,
    creer_collection_libre,
)
from archives_tool.api.services.fonds import (
    FormulaireFonds,
    creer_fonds,
    lire_fonds_par_cote,
)
from archives_tool.api.services.suggestions import suggerer_valeurs
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.demo import peupler_base
from archives_tool.models import Fonds


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


def _fonds_avec_editeur(session, cote: str, editeur: str | None) -> None:
    f = creer_fonds(session, FormulaireFonds(cote=cote, titre=cote))
    if editeur is not None:
        f.editeur = editeur
    session.commit()


def test_suggerer_valeurs_distinct_trie_et_ignore_vides(session) -> None:
    _fonds_avec_editeur(session, "A", "Éditions du Square")
    _fonds_avec_editeur(session, "B", "Éditions du Square")  # doublon
    _fonds_avec_editeur(session, "C", "Hara-Kiri SARL")
    _fonds_avec_editeur(session, "D", None)  # éditeur vide → ignoré

    vals = suggerer_valeurs(session, type_entite="fonds", champ="editeur")
    assert vals == ["Hara-Kiri SARL", "Éditions du Square"]  # distinct + trié


def test_suggerer_valeurs_filtre_prefixe(session) -> None:
    _fonds_avec_editeur(session, "A", "Éditions du Square")
    _fonds_avec_editeur(session, "C", "Hara-Kiri SARL")
    vals = suggerer_valeurs(session, type_entite="fonds", champ="editeur", prefixe="hara")
    assert vals == ["Hara-Kiri SARL"]  # insensible à la casse


def test_suggerer_valeurs_whitelist(session) -> None:
    """Une colonne hors whitelist (ex. item.titre) renvoie [] — pas
    d'accès arbitraire à une colonne via la query string."""
    _fonds_avec_editeur(session, "A", "Square")
    assert suggerer_valeurs(session, type_entite="item", champ="titre") == []
    assert suggerer_valeurs(session, type_entite="fonds", champ="notes") == []


def test_suggerer_valeurs_collection_generique(session) -> None:
    """L'endpoint est générique : il sait suggérer côté collection aussi
    (même si l'UI ne le câble pas encore)."""
    creer_fonds(session, FormulaireFonds(cote="HK", titre="HK"))
    fonds = lire_fonds_par_cote(session, "HK")
    col = creer_collection_libre(
        session, FormulaireCollection(cote="LIB", titre="Lib", fonds_id=fonds.id)
    )
    col.editeur = "Éditeur collection"
    session.commit()
    assert "Éditeur collection" in suggerer_valeurs(
        session, type_entite="collection", champ="editeur"
    )


# ---------------------------------------------------------------------------
# Route + câblage
# ---------------------------------------------------------------------------


@pytest.fixture
def base_demo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "demo.db"
    peupler_base(db)
    monkeypatch.setenv("ARCHIVES_DB", str(db))
    return db


def test_route_suggestions_renvoie_les_valeurs(base_demo: Path) -> None:
    with creer_session_factory(creer_engine(base_demo))() as db:
        f = db.scalars(select(Fonds).order_by(Fonds.id)).first()
        f.editeur = "Éditions TestUnique"
        db.commit()

    client = TestClient(app)
    r = client.get("/api/suggestions", params={"type": "fonds", "champ": "editeur"})
    assert r.status_code == 200
    assert "Éditions TestUnique" in r.json()


def test_route_suggestions_whitelist_renvoie_vide(base_demo: Path) -> None:
    client = TestClient(app)
    r = client.get("/api/suggestions", params={"type": "item", "champ": "titre"})
    assert r.status_code == 200
    assert r.json() == []


def test_route_suggestions_filtre_par_q(base_demo: Path) -> None:
    """Le paramètre `q` filtre par préfixe (insensible à la casse) — chemin
    end-to-end de l'endpoint, au-delà du test service."""
    with creer_session_factory(creer_engine(base_demo))() as db:
        fonds = db.scalars(select(Fonds).order_by(Fonds.id)).all()
        fonds[0].editeur = "Alpha Press"
        fonds[1].editeur = "Beta Books"
        db.commit()

    client = TestClient(app)
    r = client.get(
        "/api/suggestions", params={"type": "fonds", "champ": "editeur", "q": "bet"}
    )
    assert r.status_code == 200
    vals = r.json()
    assert "Beta Books" in vals
    assert "Alpha Press" not in vals


def test_synthese_fonds_porte_data_edit_suggest(base_demo: Path) -> None:
    with creer_session_factory(creer_engine(base_demo))() as db:
        cote = db.scalars(select(Fonds.cote).order_by(Fonds.id)).first()

    client = TestClient(app)
    r = client.get(f"/fonds/{cote}")
    assert r.status_code == 200
    assert 'data-edit-suggest="fonds:editeur"' in r.text
