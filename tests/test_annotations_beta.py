"""Tests d'intégration de la beta annotations (V0.9.7) — vérifie que
la page visionneuse charge Annotorious + le bouton et que le contexte
DOM nécessaire est rendu.

Pas de test fonctionnel JS (Annotorious tourne côté client). On
s'assure du contrat HTML/CSS/JS : si quelqu'un casse le wiring,
ce test le signale.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from archives_tool.api.main import app
from archives_tool.demo import peupler_base


@pytest.fixture
def base_demo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "demo.db"
    peupler_base(db)
    monkeypatch.setenv("ARCHIVES_DB", str(db))
    return db


def test_visionneuse_inclut_annotorious_css_et_js(base_demo: Path) -> None:
    """La page item visionneuse charge la CSS + le plugin Annotorious
    + le script de wiring. Sans ces 3 inclusions, le mode édition
    annotations ne s'active pas."""
    client = TestClient(app)
    resp = client.get("/item/HK-001/visionneuse?fonds=HK")
    assert resp.status_code == 200
    # CSS Annotorious
    assert "annotorious.min.css" in resp.text
    # Plugin OSD + Annotorious
    assert "openseadragon-annotorious.min.js" in resp.text
    # Script de wiring REST
    assert "annotations_osd.js" in resp.text


def test_visionneuse_bouton_annoter_present(base_demo: Path) -> None:
    """Le bouton « Annoter » est rendu avec `data-annoter-toggle`
    pointant sur l'ID du viewer. Le JS écoute ce data-attr pour
    basculer Annotorious entre lecture et édition."""
    client = TestClient(app)
    resp = client.get("/item/HK-001/visionneuse?fonds=HK")
    assert resp.status_code == 200
    assert "data-annoter-toggle=" in resp.text
    # Le toggle vise l'ID du viewer (visionneuse-<fichier_id>)
    assert 'data-annoter-toggle="visionneuse-' in resp.text


def test_visionneuse_data_fichier_id_expose(base_demo: Path) -> None:
    """Le `data-source` du viewer expose `fichier_id`, lu par
    `annotations_osd.js` pour construire les URLs REST
    `/api/fichiers/<id>/annotations`."""
    client = TestClient(app)
    resp = client.get("/item/HK-001/visionneuse?fonds=HK")
    assert resp.status_code == 200
    # data-fichier-id sur le wrapper
    assert "data-fichier-id=" in resp.text
    # fichier_id aussi dans le JSON data-source pour le JS.
    # L'attribut HTML utilise des single-quotes (data-source='{...}')
    # donc les double-quotes JSON restent intactes — pas d'entities.
    assert '"fichier_id":' in resp.text


def test_visionneuse_pas_d_annotorious_en_lecture_seule(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """En lecture seule, on ne charge pas Annotorious : le mode
    édition serait inutile (le POST serait bloqué par le middleware
    en 423) et le bouton « Annoter » trompeur."""
    db = tmp_path / "demo.db"
    peupler_base(db)
    monkeypatch.setenv("ARCHIVES_DB", str(db))
    # Config lecture seule via env (pattern testé dans test_lecture_seule)
    racine = tmp_path / "miniatures"
    racine.mkdir()
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        f"utilisateur: test\n"
        f"lecture_seule: true\n"
        f"racines:\n  demo: {racine}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ARCHIVES_CONFIG", str(cfg))

    client = TestClient(app)
    resp = client.get("/item/HK-001/visionneuse?fonds=HK")
    assert resp.status_code == 200
    # Annotorious absent — pas de CSS, pas de script
    assert "annotorious.min.css" not in resp.text
    assert "annotations_osd.js" not in resp.text
    # Bouton « Annoter » absent
    assert "data-annoter-toggle=" not in resp.text


def test_routes_annotations_accessibles_depuis_visionneuse(
    base_demo: Path,
) -> None:
    """Garde-fou contrat client/serveur : depuis la page visionneuse,
    le JS appellerait GET /api/fichiers/<id>/annotations. On vérifie
    que ces routes sont mountées et renvoient bien une AnnotationPage."""
    client = TestClient(app)
    # Récupère un fichier_id du HTML de la page
    resp = client.get("/item/HK-001/visionneuse?fonds=HK")
    assert resp.status_code == 200
    import re
    m = re.search(r'data-fichier-id="(\d+)"', resp.text)
    assert m, "data-fichier-id introuvable dans la page visionneuse"
    fichier_id = int(m.group(1))

    # Appelle l'endpoint REST comme le ferait Annotorious au load
    r_api = client.get(f"/api/fichiers/{fichier_id}/annotations")
    assert r_api.status_code == 200
    page = r_api.json()
    assert page["type"] == "AnnotationPage"
    assert "items" in page


def test_fiche_item_pas_d_annotorious(base_demo: Path) -> None:
    """La fiche item `/item/<cote>` (sans /visionneuse) n'a pas
    Annotorious — c'est la notice catalographique, pas la visionneuse.
    L'édition d'annotations vit sur /visionneuse."""
    client = TestClient(app)
    resp = client.get("/item/HK-001?fonds=HK")
    assert resp.status_code == 200
    assert "annotations_osd.js" not in resp.text
