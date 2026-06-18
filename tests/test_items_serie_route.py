"""Tests de la route web `/collection/<cote>/items/serie` (V0.9.7)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from archives_tool.api.main import app
from archives_tool.demo import peupler_base
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.models import Item


@pytest.fixture
def base_demo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "demo.db"
    peupler_base(db)
    monkeypatch.setenv("ARCHIVES_DB", str(db))
    return db


def test_get_formulaire_serie_succes(base_demo: Path) -> None:
    """La page formulaire s'affiche pour une miroir."""
    client = TestClient(app)
    r = client.get("/collection/HK/items/serie?fonds=HK")
    assert r.status_code == 200
    assert "Créer une série d'items" in r.text
    # Le pattern par défaut est pré-rempli avec la cote de la collection
    assert "HK-{n:03d}" in r.text
    # Le formulaire pointe sur la bonne URL POST
    assert "/collection/HK/items/serie?fonds=HK" in r.text


def test_get_formulaire_serie_transversale_refuse(base_demo: Path) -> None:
    """Le bouton est masqué sur une transversale, mais l'URL directe
    doit aussi refuser (cas où l'utilisateur tape l'URL à la main)."""
    from archives_tool.api.services.collections import (
        FormulaireCollection,
        creer_collection_libre,
    )

    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        creer_collection_libre(
            s,
            FormulaireCollection(
                cote="TRANS-X",
                titre="Transversale test",
                fonds_id=None,
            ),
        )
    engine.dispose()

    client = TestClient(app)
    r = client.get("/collection/TRANS-X/items/serie")
    assert r.status_code == 400
    assert "transversal" in r.text.lower()


def test_post_serie_succes_redirige_avec_flash(base_demo: Path) -> None:
    """POST avec données valides → 303 vers la collection + query
    `serie_crees=N` lue par le template pour le flash de succès."""
    client = TestClient(app)
    r = client.post(
        "/collection/HK/items/serie?fonds=HK",
        data={
            "pattern_cote": "HK-SERIE-{n:03d}",
            "de_n": "1",
            "a_n": "3",
            "titre_template": "Test série {n}",
            "etat": "brouillon",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    location = r.headers["location"]
    assert "/collection/HK" in location
    assert "serie_crees=3" in location

    # Items effectivement créés
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        n = s.scalar(select(func.count(Item.id)).where(Item.cote.like("HK-SERIE-%")))
        assert n == 3
    engine.dispose()


def test_post_serie_erreur_rerend_form(base_demo: Path) -> None:
    """POST avec pattern invalide → re-rend le formulaire avec les
    erreurs et préserve les valeurs saisies."""
    client = TestClient(app)
    r = client.post(
        "/collection/HK/items/serie?fonds=HK",
        data={
            "pattern_cote": "HK-{inconnu}",  # variable inconnue
            "de_n": "1",
            "a_n": "3",
        },
    )
    assert r.status_code == 400
    assert "Validation refusée" in r.text or "pattern_cote" in r.text
    # Les valeurs saisies sont ré-injectées dans le form
    assert 'value="HK-{inconnu}"' in r.text


def test_flash_succes_lu_par_collection(base_demo: Path) -> None:
    """Après une création réussie, le flash apparaît bien sur la page
    collection (suivi du redirect)."""
    client = TestClient(app)
    r = client.post(
        "/collection/HK/items/serie?fonds=HK",
        data={
            "pattern_cote": "HK-FLASH-{n}",
            "de_n": "1",
            "a_n": "2",
            "etat": "brouillon",
        },
        follow_redirects=True,
    )
    assert r.status_code == 200
    assert "2 item(s) créé(s) en série" in r.text


def test_bouton_creer_serie_present_sur_collection(base_demo: Path) -> None:
    """Le bouton « + Créer une série » apparaît sur la page collection
    (miroir et libres rattachées) si on n'est pas en lecture seule."""
    client = TestClient(app)
    r = client.get("/collection/HK?fonds=HK")
    assert r.status_code == 200
    assert "Créer une série" in r.text
    assert "/collection/HK/items/serie?fonds=HK" in r.text


def test_bouton_masque_sur_transversale(base_demo: Path) -> None:
    """Une collection transversale ne doit pas exposer le bouton
    (création nécessite un fonds explicite, qu'une transversale n'a
    pas par définition)."""
    from archives_tool.api.services.collections import (
        FormulaireCollection,
        creer_collection_libre,
    )

    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        creer_collection_libre(
            s,
            FormulaireCollection(
                cote="TRANS-BTN",
                titre="Transversale",
                fonds_id=None,
            ),
        )
    engine.dispose()

    client = TestClient(app)
    r = client.get("/collection/TRANS-BTN")
    assert r.status_code == 200
    # « + Créer une série » absente — le bouton « + Ajouter des items »
    # peut être present (libre non-miroir), c'est OK.
    assert "/collection/TRANS-BTN/items/serie" not in r.text


def test_bouton_masque_en_lecture_seule(
    base_demo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """En lecture seule, le bouton est masqué (cohérent avec « +
    Ajouter des items » qui suit la même règle)."""
    from archives_tool.api import templating

    monkeypatch.setitem(
        templating.templates.env.globals, "est_lecture_seule", lambda: True
    )
    client = TestClient(app)
    r = client.get("/collection/HK?fonds=HK")
    assert r.status_code == 200
    assert "/collection/HK/items/serie" not in r.text


def test_post_serie_bloque_par_middleware_lecture_seule(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Même si l'utilisateur forge l'URL POST directement, le
    middleware lecture seule renvoie 423 (Locked). Garde-fou
    indépendant du masquage des boutons côté template.

    On configure une base demo + un config_local.yaml avec
    `lecture_seule: true` (méthode utilisée par test_lecture_seule.py)."""
    db = tmp_path / "demo.db"
    peupler_base(db)
    monkeypatch.setenv("ARCHIVES_DB", str(db))
    # Config lecture_seule via fichier YAML (lu par charger_config()
    # auquel le middleware se rattache).
    racine = tmp_path / "miniatures"
    racine.mkdir()
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        f"utilisateur: test\nlecture_seule: true\nracines:\n  demo: {racine}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ARCHIVES_CONFIG", str(cfg))

    client = TestClient(app)
    r = client.post(
        "/collection/HK/items/serie?fonds=HK",
        data={
            "pattern_cote": "HK-PIRATE-{n}",
            "de_n": "1",
            "a_n": "3",
        },
    )
    assert r.status_code == 423
