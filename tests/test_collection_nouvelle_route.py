"""Tests de la route web `/collections/nouvelle` (création libre, Lot A).

Restauration d'une route disparue lors du refactor V0.9.0-alpha — les
liens depuis `menu_importer.html` et `fonds_lecture.html` menaient à un
404 avant cette livraison.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from archives_tool.api.main import app
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.demo import peupler_base
from archives_tool.models import Collection, TypeCollection


@pytest.fixture
def base_demo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "demo.db"
    peupler_base(db)
    monkeypatch.setenv("ARCHIVES_DB", str(db))
    return db


def test_get_formulaire_avec_fonds_verrouille(base_demo: Path) -> None:
    """`?fonds=HK` : champ verrouillé en hidden, libellé read-only."""
    client = TestClient(app)
    r = client.get("/collections/nouvelle?fonds=HK")
    assert r.status_code == 200
    # Hidden input pour le rattachement
    assert 'name="fonds_id"' in r.text
    assert 'type="hidden"' in r.text
    # Libellé du fonds visible
    assert "HK" in r.text
    # Pas de sélecteur
    assert '<select id="fonds_id"' not in r.text


def test_get_formulaire_sans_fonds_montre_selecteur(base_demo: Path) -> None:
    """Sans `?fonds=`, le formulaire propose un sélecteur de tous les
    fonds existants (pour rattacher la libre à l'un d'eux)."""
    client = TestClient(app)
    r = client.get("/collections/nouvelle")
    assert r.status_code == 200
    # Selector présent
    assert '<select id="fonds_id" name="fonds_id" required' in r.text
    # Au moins le fonds HK de la demo
    assert "HK" in r.text


def test_get_fonds_inconnu_renvoie_404(base_demo: Path) -> None:
    """`?fonds=INCONNU` → 404 (pas de fonds avec cette cote)."""
    client = TestClient(app)
    r = client.get("/collections/nouvelle?fonds=INCONNU")
    assert r.status_code == 404


def test_post_creation_libre_redirige_vers_collection(base_demo: Path) -> None:
    """POST avec form valide → 303 vers /collection/<cote>?fonds=<cote>.
    La collection est créée en base avec le bon rattachement."""
    # On résout l'id du fonds HK pour le poster côté form
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        fonds_id = s.scalar(
            select(Collection.fonds_id).where(Collection.cote == "HK")
        )
    engine.dispose()
    assert fonds_id is not None

    client = TestClient(app, follow_redirects=False)
    r = client.post(
        "/collections/nouvelle",
        data={
            "fonds_id": str(fonds_id),
            "cote": "HK-FAVORIS-TEST",
            "titre": "Favoris de test",
            "description": "",
            "description_publique": "",
            "description_interne": "",
            "phase": "catalogage",
            "doi_nakala": "",
            "doi_collection_nakala_parent": "",
            "personnalite_associee": "",
            "responsable_archives": "",
        },
    )
    assert r.status_code == 303
    assert "/collection/HK-FAVORIS-TEST" in r.headers["location"]
    assert "fonds=HK" in r.headers["location"]

    # Vérifie en base
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        col = s.scalar(
            select(Collection).where(Collection.cote == "HK-FAVORIS-TEST")
        )
        assert col is not None
        assert col.type_collection == TypeCollection.LIBRE.value
        assert col.fonds_id == fonds_id
    engine.dispose()


def test_post_cote_vide_reaffiche_erreurs(base_demo: Path) -> None:
    """POST avec cote vide → 400 + form re-affiché avec erreurs."""
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        fonds_id = s.scalar(
            select(Collection.fonds_id).where(Collection.cote == "HK")
        )
    engine.dispose()

    client = TestClient(app)
    r = client.post(
        "/collections/nouvelle",
        data={
            "fonds_id": str(fonds_id),
            "cote": "",
            "titre": "Quelque chose",
            "phase": "catalogage",
        },
    )
    assert r.status_code == 400
    # Form ré-affiché avec le titre saisi
    assert "Quelque chose" in r.text
    # Message d'erreur sur la cote
    assert "cote" in r.text.lower()


def test_post_cote_collision_meme_fonds_reaffiche_erreurs(
    base_demo: Path,
) -> None:
    """Cote déjà prise dans le même fonds → 400 avec erreur explicite."""
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        # HK existe déjà comme miroir
        fonds_id = s.scalar(
            select(Collection.fonds_id).where(Collection.cote == "HK")
        )
    engine.dispose()

    client = TestClient(app)
    r = client.post(
        "/collections/nouvelle",
        data={
            "fonds_id": str(fonds_id),
            "cote": "HK",  # collision avec la miroir
            "titre": "Doublon",
            "phase": "catalogage",
        },
    )
    assert r.status_code == 400


def test_post_erreur_en_mode_selecteur_garde_selecteur(
    base_demo: Path,
) -> None:
    """Bug évité : un utilisateur venu en mode sélecteur (sans ?fonds=)
    qui choisit fonds X puis se trompe de cote ne doit PAS être bloqué
    sur X au re-render — il doit pouvoir re-choisir un autre fonds.
    Mécanisme : POST sans `?fonds=` → mode sélecteur préservé."""
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        fonds_id = s.scalar(
            select(Collection.fonds_id).where(Collection.cote == "HK")
        )
    engine.dispose()

    client = TestClient(app)
    # POST nu (mode sélecteur), cote vide → erreur
    r = client.post(
        "/collections/nouvelle",
        data={
            "fonds_id": str(fonds_id),
            "cote": "",
            "titre": "X",
            "phase": "catalogage",
        },
    )
    assert r.status_code == 400
    # Le re-render doit afficher le sélecteur (pas le mode locked)
    assert '<select id="fonds_id" name="fonds_id" required' in r.text
    # Pas de hidden field unique (mode locked)
    assert 'name="fonds_id"\n             value="' not in r.text


def test_post_erreur_en_mode_locked_garde_locked(base_demo: Path) -> None:
    """Symétrique : un utilisateur venu avec ?fonds=HK qui se trompe
    reste sur HK au re-render (pas de sélecteur pour changer)."""
    client = TestClient(app)
    r = client.post(
        "/collections/nouvelle?fonds=HK",
        data={
            "fonds_id": "1",  # arbitraire, écrasé par le service
            "cote": "",
            "titre": "X",
            "phase": "catalogage",
        },
    )
    assert r.status_code == 400
    # Pas de sélecteur (mode locked)
    assert '<select id="fonds_id" name="fonds_id"' not in r.text
    # Hidden input présent
    assert 'type="hidden"' in r.text


def test_post_lecture_seule_bloque(
    base_demo: Path, monkeypatch, tmp_path: Path
) -> None:
    """Middleware lecture seule renvoie 423 sur le POST, sans création."""
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        fonds_id = s.scalar(
            select(Collection.fonds_id).where(Collection.cote == "HK")
        )
    engine.dispose()

    racine = tmp_path / "miniatures"
    racine.mkdir()
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        f"utilisateur: test\nlecture_seule: true\nracines:\n  d: {racine}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ARCHIVES_CONFIG", str(cfg))

    client = TestClient(app)
    r = client.post(
        "/collections/nouvelle",
        data={
            "fonds_id": str(fonds_id),
            "cote": "HK-FAVORIS-RO",
            "titre": "Test RO",
            "phase": "catalogage",
        },
    )
    assert r.status_code == 423


def test_lien_creer_collection_libre_actif_depuis_fonds(
    base_demo: Path,
) -> None:
    """Bouton « + Créer une collection libre » sur la page fonds pointe
    vers /collections/nouvelle?fonds=<cote> — vérification que le lien
    est rendu et que la cible répond 200 (pas 404 comme avant le fix)."""
    client = TestClient(app)
    r = client.get("/fonds/HK")
    assert r.status_code == 200
    assert "/collections/nouvelle?fonds=HK" in r.text
    # Et la cible répond
    r2 = client.get("/collections/nouvelle?fonds=HK")
    assert r2.status_code == 200
