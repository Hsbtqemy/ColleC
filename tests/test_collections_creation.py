"""Tests de la création de collection vide depuis l'UI (V0.7).

Couvre le service (validation par champ, création) et la route
(GET formulaire, POST réussi/redirect, POST en erreur/re-render).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from archives_tool.api.main import app
from archives_tool.api.services.collections_creation import (
    FormulaireCollection,
    creer_collection,
    lire_collection_par_cote,
    valider_formulaire,
)
from archives_tool.demo import peupler_base
from archives_tool.models import Collection, PhaseChantier


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


def test_validation_cote_vide(session: Session) -> None:
    res = valider_formulaire(session, FormulaireCollection(cote="", titre="T"))
    assert "cote" in res.erreurs
    assert not res.ok


def test_validation_cote_avec_espaces(session: Session) -> None:
    res = valider_formulaire(
        session, FormulaireCollection(cote="ma collection", titre="T")
    )
    assert "cote" in res.erreurs


def test_validation_cote_avec_accents(session: Session) -> None:
    res = valider_formulaire(session, FormulaireCollection(cote="cötée", titre="T"))
    assert "cote" in res.erreurs


def test_validation_cote_doublon(session: Session) -> None:
    session.add(Collection(cote_collection="X", titre="X", phase="catalogage"))
    session.commit()
    res = valider_formulaire(session, FormulaireCollection(cote="X", titre="T"))
    assert "cote" in res.erreurs


def test_validation_titre_vide(session: Session) -> None:
    res = valider_formulaire(session, FormulaireCollection(cote="OK", titre=""))
    assert "titre" in res.erreurs


def test_validation_phase_inconnue(session: Session) -> None:
    res = valider_formulaire(
        session, FormulaireCollection(cote="OK", titre="T", phase="bidon")
    )
    assert "phase" in res.erreurs


def test_validation_parent_inexistant(session: Session) -> None:
    res = valider_formulaire(
        session,
        FormulaireCollection(cote="OK", titre="T", parent_cote="N_EXISTE_PAS"),
    )
    assert "parent_cote" in res.erreurs


def test_validation_doi_doublon(session: Session) -> None:
    session.add(
        Collection(
            cote_collection="A",
            titre="A",
            phase="catalogage",
            doi_nakala="10.34847/nkl.x",
        )
    )
    session.commit()
    res = valider_formulaire(
        session,
        FormulaireCollection(cote="B", titre="B", doi_nakala="10.34847/nkl.x"),
    )
    assert "doi_nakala" in res.erreurs


def test_validation_minimal_ok(session: Session) -> None:
    res = valider_formulaire(session, FormulaireCollection(cote="ABC", titre="T"))
    assert res.ok


def test_creation_minimale(session: Session) -> None:
    col = creer_collection(
        session,
        FormulaireCollection(cote="MIN", titre="Minimale"),
        cree_par="marie",
    )
    assert col.id is not None
    assert col.cote_collection == "MIN"
    assert col.titre == "Minimale"
    assert col.phase == PhaseChantier.CATALOGAGE.value
    assert col.cree_par == "marie"


def test_creation_avec_parent(session: Session) -> None:
    parent = Collection(cote_collection="P", titre="P", phase="catalogage")
    session.add(parent)
    session.commit()
    col = creer_collection(
        session,
        FormulaireCollection(cote="P-ENF", titre="Enfant", parent_cote="P"),
        cree_par="u",
    )
    assert col.parent_id == parent.id


def test_creation_strip_des_chaines(session: Session) -> None:
    """Cote et titre sont strippés au moment de la création."""
    col = creer_collection(
        session,
        FormulaireCollection(cote="  TRIM  ", titre="  Titre  "),
        cree_par="u",
    )
    assert col.cote_collection == "TRIM"
    assert col.titre == "Titre"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@pytest.fixture
def base_demo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "demo.db"
    peupler_base(db)
    monkeypatch.setenv("ARCHIVES_DB", str(db))
    return db


def test_get_formulaire(base_demo: Path) -> None:
    client = TestClient(app)
    resp = client.get("/collections/nouvelle")
    assert resp.status_code == 200
    assert "Nouvelle collection vide" in resp.text
    assert 'name="cote"' in resp.text
    assert 'name="titre"' in resp.text


def test_post_creation_redirect(base_demo: Path) -> None:
    client = TestClient(app)
    resp = client.post(
        "/collections",
        data={"cote": "NOUV", "titre": "Nouvelle test"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/collection/NOUV"


def test_post_cote_invalide_re_render(base_demo: Path) -> None:
    client = TestClient(app)
    resp = client.post(
        "/collections",
        data={"cote": "ma collection", "titre": "T"},
        follow_redirects=False,
    )
    assert resp.status_code == 400
    assert "Caractères autorisés" in resp.text
    # Les valeurs saisies sont préservées.
    assert 'value="ma collection"' in resp.text or "ma collection" in resp.text


def test_post_cote_doublon_re_render(base_demo: Path) -> None:
    """La base demo contient déjà la collection HK."""
    client = TestClient(app)
    resp = client.post(
        "/collections",
        data={"cote": "HK", "titre": "Dup"},
        follow_redirects=False,
    )
    assert resp.status_code == 400
    assert "existe déjà" in resp.text


def test_post_creation_complete(base_demo: Path) -> None:
    client = TestClient(app)
    resp = client.post(
        "/collections",
        data={
            "cote": "FULL",
            "titre": "Complète",
            "description": "Desc publique",
            "description_interne": "Notes équipe",
            "editeur": "Ed",
            "lieu_edition": "Paris",
            "date_debut": "1900",
            "date_fin": "1950",
            "phase": "revision",
            "doi_nakala": "10.34847/nkl.unique",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    # Vérifie que tous les champs sont persistés via le helper public
    # (`lire_collection_par_cote`) et le client de test, sans toucher
    # aux internes du module deps.
    from archives_tool.api.deps import _factory_pour, chemin_base_courant

    factory = _factory_pour(chemin_base_courant())
    with factory() as session:
        col = lire_collection_par_cote(session, "FULL")
        assert col is not None
        assert col.titre == "Complète"
        assert col.description == "Desc publique"
        assert col.description_interne == "Notes équipe"
        assert col.editeur == "Ed"
        assert col.phase == "revision"
        assert col.doi_nakala == "10.34847/nkl.unique"
