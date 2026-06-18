"""Tests du mode lecture seule (`config_local.yaml: lecture_seule: true`).

Quand le flag est actif, le middleware doit retourner 423 sur toute
mutation HTTP (POST/PUT/PATCH/DELETE) et laisser passer les GET.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from archives_tool.api.deps import est_lecture_seule
from archives_tool.api.main import app
from archives_tool.db import assurer_tables_fts, creer_engine
from archives_tool.models import Base


def _ecrire_config(chemin: Path, lecture_seule: bool, racine_demo: Path) -> None:
    chemin.write_text(
        yaml.safe_dump(
            {
                "utilisateur": "test",
                "racines": {"miniatures": str(racine_demo)},
                "lecture_seule": lecture_seule,
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )


def _amorcer_base_vide(tmp_path: Path) -> Path:
    """Crée une SQLite avec uniquement le schéma (tables vides + FTS),
    sans peupler. Les tests qui GET le dashboard / l'accueil import ont
    besoin que les tables existent, mais pas de données — un état
    « première installation » suffit.

    Pourquoi cette fonction et pas `peupler_base` : `peupler_base` crée
    333 items + 1298 fichiers + dérivés JPEG (~plusieurs secondes par
    appel × N tests). Ces tests rendent uniquement la coquille HTML +
    bannière lecture seule + filets JS — un schéma vide est suffisant
    et 100× plus rapide.
    """
    chemin = tmp_path / "test.db"
    engine = creer_engine(chemin)
    Base.metadata.create_all(engine)
    assurer_tables_fts(engine)
    engine.dispose()
    return chemin


@pytest.fixture
def config_lecture_seule(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    racine = tmp_path / "miniatures"
    racine.mkdir()
    cfg = tmp_path / "config.yaml"
    _ecrire_config(cfg, lecture_seule=True, racine_demo=racine)
    monkeypatch.setenv("ARCHIVES_CONFIG", str(cfg))
    # Schéma seul — les tests ici ne consultent pas de données, ils
    # vérifient la coquille HTML + middleware. Sans cette amorce, l'app
    # tombe sur `data/archives.db` (défaut) qui n'existe pas sur un
    # checkout propre → OperationalError au premier SELECT.
    monkeypatch.setenv("ARCHIVES_DB", str(_amorcer_base_vide(tmp_path)))
    return cfg


@pytest.fixture
def config_normale(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    racine = tmp_path / "miniatures"
    racine.mkdir()
    cfg = tmp_path / "config.yaml"
    _ecrire_config(cfg, lecture_seule=False, racine_demo=racine)
    monkeypatch.setenv("ARCHIVES_CONFIG", str(cfg))
    monkeypatch.setenv("ARCHIVES_DB", str(_amorcer_base_vide(tmp_path)))
    return cfg


def test_lecture_seule_flag_lu_depuis_config(config_lecture_seule: Path) -> None:
    assert est_lecture_seule() is True


def test_lecture_seule_flag_absent_par_defaut(config_normale: Path) -> None:
    assert est_lecture_seule() is False


def test_lecture_seule_absent_si_pas_de_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ARCHIVES_CONFIG", str(tmp_path / "absent.yaml"))
    assert est_lecture_seule() is False


def test_post_renvoie_423_en_lecture_seule(config_lecture_seule: Path) -> None:
    client = TestClient(app)
    resp = client.post("/preferences/colonnes/items/1", data={})
    assert resp.status_code == 423
    assert "lecture seule" in resp.text.lower()


def test_post_html_renvoie_page_html(config_lecture_seule: Path) -> None:
    """Un client navigateur (Accept: text/html) reçoit une page HTML
    lisible avec un lien retour, pas du JSON brut."""
    client = TestClient(app)
    resp = client.post(
        "/preferences/colonnes/items/1",
        data={},
        headers={"Accept": "text/html"},
    )
    assert resp.status_code == 423
    assert resp.headers["content-type"].startswith("text/html")
    assert "<title>Mode lecture seule" in resp.text
    assert "javascript:history.back()" in resp.text


def test_post_api_renvoie_json(config_lecture_seule: Path) -> None:
    """Un client API (Accept: application/json) reçoit du JSON
    structuré, pas du HTML."""
    client = TestClient(app)
    resp = client.post(
        "/preferences/colonnes/items/1",
        data={},
        headers={"Accept": "application/json"},
    )
    assert resp.status_code == 423
    assert resp.headers["content-type"].startswith("application/json")
    payload = resp.json()
    assert "detail" in payload
    assert "lecture seule" in payload["detail"].lower()


def test_get_passe_en_lecture_seule(config_lecture_seule: Path) -> None:
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200


def test_delete_renvoie_423_en_lecture_seule(config_lecture_seule: Path) -> None:
    client = TestClient(app)
    resp = client.delete("/collections/CHOSE")
    assert resp.status_code == 423


def test_banniere_lecture_seule_dans_html(config_lecture_seule: Path) -> None:
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Mode lecture seule" in resp.text


def test_pas_de_banniere_en_mode_normal(config_normale: Path) -> None:
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Mode lecture seule" not in resp.text


def test_post_passe_en_mode_normal(config_normale: Path) -> None:
    """En mode normal, le middleware n'intervient pas — on doit
    obtenir la vraie réponse du routeur (404 si la collection
    n'existe pas dans la base de test, 422 si le payload est
    refusé). Code 423 strictement interdit ici, et la réponse ne
    doit pas mentionner « lecture seule »."""
    client = TestClient(app)
    resp = client.post("/preferences/colonnes/items/1", data={})
    assert resp.status_code in {200, 303, 400, 404, 422}
    assert "lecture seule" not in resp.text.lower()


# ---------------------------------------------------------------------------
# Passe de revue V0.9.1 T1 — boutons d'édition masqués en lecture seule
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def base_demo_pour_lecture_seule(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """DB peuplée (1 fonds HK avec items) — partagée avec les tests de
    rendu UI en lecture seule. Coût d'init payé une fois par module."""
    from archives_tool.demo import peupler_base

    chemin = tmp_path_factory.mktemp("lecture_seule_demo") / "demo.db"
    peupler_base(chemin)
    return chemin


@pytest.fixture
def client_demo_lecture_seule(
    base_demo_pour_lecture_seule: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> TestClient:
    """Combine DB peuplée + config lecture_seule=true."""
    racine = tmp_path / "miniatures"
    racine.mkdir()
    cfg = tmp_path / "config.yaml"
    _ecrire_config(cfg, lecture_seule=True, racine_demo=racine)
    monkeypatch.setenv("ARCHIVES_CONFIG", str(cfg))
    monkeypatch.setenv("ARCHIVES_DB", str(base_demo_pour_lecture_seule))
    return TestClient(app)


def test_import_accueil_masque_nouvel_import_en_lecture_seule(
    config_lecture_seule: Path,
) -> None:
    """V0.9.1 T1 — le bouton « Nouvel import » disparaît en lecture seule,
    remplacé par un message explicite."""
    client = TestClient(app)
    resp = client.get("/import")
    assert resp.status_code == 200
    assert 'action="/import/nouveau"' not in resp.text
    assert "Nouvel import" not in resp.text
    assert "imports sont désactivés" in resp.text


def test_import_accueil_affiche_nouvel_import_en_mode_normal(
    config_normale: Path,
) -> None:
    """En mode normal, le bouton est bien rendu."""
    client = TestClient(app)
    resp = client.get("/import")
    assert resp.status_code == 200
    assert 'action="/import/nouveau"' in resp.text


def test_fonds_lecture_masque_modifier_en_lecture_seule(
    client_demo_lecture_seule: TestClient,
) -> None:
    """V0.9.1 T1 — le bouton « Modifier le fonds » disparaît en lecture
    seule. Le lien vers `/collections/nouvelle` aussi (création
    collection libre)."""
    resp = client_demo_lecture_seule.get("/fonds/HK")
    assert resp.status_code == 200
    assert "Modifier le fonds" not in resp.text
    assert "/fonds/HK/modifier" not in resp.text
    assert "Créer une collection libre" not in resp.text


def test_filet_securite_javascript_present_en_lecture_seule(
    config_lecture_seule: Path,
) -> None:
    """Passe de revue — un listener JS intercepte les submits POST en
    lecture seule (filet de sécurité contre ENTER dans un input texte,
    même quand le bouton submit est masqué côté template)."""
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert 'addEventListener("submit"' in resp.text
    assert "preventDefault" in resp.text


def test_filet_securite_javascript_absent_en_mode_normal(
    config_normale: Path,
) -> None:
    """Le filet JS n'est PAS injecté en mode normal — pas de surcoût."""
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert 'addEventListener("submit"' not in resp.text


def test_import_etape_tableur_desactive_en_lecture_seule(
    client_demo_lecture_seule: TestClient,
    base_demo_pour_lecture_seule: Path,
) -> None:
    """V0.9.1 T1 Phase C — si l'utilisateur navigue par URL directe sur
    une étape d'import (session pré-existante), le bouton de soumission
    est remplacé par un message, et « Abandonner » est masqué."""
    # On crée une session import vide pour pouvoir accéder à l'étape tableur.
    # Au moment du POST nouveau on est bloqué par lecture seule, donc on
    # insère directement via SQL.
    from sqlalchemy.orm import sessionmaker
    from archives_tool.db import creer_engine
    from archives_tool.models import SessionImport

    engine = creer_engine(base_demo_pour_lecture_seule)
    with sessionmaker(bind=engine)() as s:
        sess = SessionImport(utilisateur="test", etape="tableur")
        s.add(sess)
        s.commit()
        sid = sess.id
    engine.dispose()

    resp = client_demo_lecture_seule.get(f"/import/{sid}/tableur")
    assert resp.status_code == 200
    assert "Import désactivé" in resp.text
    assert "Analyser le tableur" not in resp.text
    assert "Abandonner cet import" not in resp.text


def test_panneau_colonnes_data_lecture_seule_present(
    client_demo_lecture_seule: TestClient,
) -> None:
    """V0.9.x trous polish — la modale du panneau colonnes porte
    `data-lecture-seule="1"` en lecture seule. `panneau_colonnes.js`
    lit cet attribut pour skip Sortable.create() : sans cela,
    l'utilisateur pouvait drag-drop visuellement mais perdre ses
    changements (« Appliquer » masqué)."""
    # Trouve un id de collection dans la demo.
    from sqlalchemy.orm import sessionmaker
    from archives_tool.db import creer_engine
    from archives_tool.models import Collection

    # On utilise la base demo dans la fixture, on récupère son chemin
    # via ARCHIVES_DB (posé par client_demo_lecture_seule).
    import os

    db_path = os.environ.get("ARCHIVES_DB")
    if not db_path:
        return  # skip silencieux si fixture n'a pas posé l'env
    engine = creer_engine(db_path)
    with sessionmaker(bind=engine)() as s:
        coll = s.query(Collection).first()
        assert coll is not None
        cid = coll.id
    engine.dispose()

    # GET du panneau colonnes via la route /preferences (HTMX).
    resp = client_demo_lecture_seule.get(
        f"/preferences/colonnes/items/{cid}",
        headers={"HX-Request": "true"},
    )
    assert resp.status_code == 200
    assert 'data-lecture-seule="1"' in resp.text


def test_fonds_modifier_remplace_enregistrer_par_message(
    client_demo_lecture_seule: TestClient,
) -> None:
    """V0.9.1 T1 Phase B — si l'utilisateur arrive sur la page modifier
    via URL directe en mode lecture seule, le bouton « Enregistrer »
    est remplacé par un message explicite, et « Annuler » devient
    « Retour »."""
    resp = client_demo_lecture_seule.get("/fonds/HK/modifier")
    assert resp.status_code == 200
    assert "Enregistrement désactivé" in resp.text
    assert "mode lecture seule" in resp.text.lower()
    # Le bouton submit est absent du HTML.
    assert '<button type="submit"' not in resp.text


def test_item_lecture_ne_charge_pas_inline_edit_en_lecture_seule(
    client_demo_lecture_seule: TestClient,
    base_demo_pour_lecture_seule: Path,
) -> None:
    """V0.9.1 T1 — `inline_edit.js` n'est pas chargé en lecture seule.
    Sans ce script, les hooks `data-edit-field` restent dormants et
    l'utilisateur ne peut pas ouvrir un input par accident."""
    # Trouve un item dans la base demo pour construire l'URL.
    from sqlalchemy.orm import sessionmaker
    from archives_tool.db import creer_engine
    from archives_tool.models import Fonds, Item

    engine = creer_engine(base_demo_pour_lecture_seule)
    with sessionmaker(bind=engine)() as s:
        item = s.query(Item).join(Fonds).filter(Fonds.cote == "HK").first()
        assert item is not None, "demo HK doit avoir au moins un item"
        cote_item = item.cote
    engine.dispose()

    resp = client_demo_lecture_seule.get(f"/item/{cote_item}?fonds=HK")
    assert resp.status_code == 200
    assert "inline_edit.js" not in resp.text
    # Le bouton « Modifier » du bandeau item est aussi masqué.
    assert f"/item/{cote_item}/modifier" not in resp.text
