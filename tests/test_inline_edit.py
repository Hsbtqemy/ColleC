"""Tests de la route d'édition inline du cartouche."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

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


def _version_courante(db_path: Path, cote: str) -> int:
    engine = creer_engine(db_path)
    factory = creer_session_factory(engine)
    with factory() as s:
        item = s.scalar(select(Item).where(Item.cote == cote))
        version = item.version
    engine.dispose()
    return version


def test_inline_edit_succes_retourne_fragment(base_demo: Path) -> None:
    """POST sur un champ éditable avec la bonne version : 200 +
    fragment HTML contenant la nouvelle valeur et un marqueur
    `data-edit-new-version`."""
    client = TestClient(app)
    v = _version_courante(base_demo, "HK-001")
    resp = client.post(
        "/item/HK-001/champ/titre?fonds=HK",
        data={"version": str(v), "valeur": "Nouveau titre inline"},
    )
    assert resp.status_code == 200
    assert "Nouveau titre inline" in resp.text
    assert "data-edit-new-version" in resp.text
    assert f'data-edit-new-version="{v + 1}"' in resp.text


def test_inline_edit_version_perimee_409(base_demo: Path) -> None:
    """POST avec une version périmée : 409 + fragment de conflit."""
    client = TestClient(app)
    v = _version_courante(base_demo, "HK-001")
    # Premier save : OK.
    r1 = client.post(
        "/item/HK-001/champ/titre?fonds=HK",
        data={"version": str(v), "valeur": "Premier"},
    )
    assert r1.status_code == 200
    # Second save avec la version d'origine (devenue stale).
    r2 = client.post(
        "/item/HK-001/champ/titre?fonds=HK",
        data={"version": str(v), "valeur": "Stale"},
    )
    assert r2.status_code == 409
    assert "Conflit" in r2.text
    assert "Recharger" in r2.text


def test_inline_edit_champ_hors_whitelist_403(base_demo: Path) -> None:
    """Champs sensibles (cote, version, fonds_id, etat_catalogage)
    interdits — passe par la page /modifier complète."""
    client = TestClient(app)
    v = _version_courante(base_demo, "HK-001")
    resp = client.post(
        "/item/HK-001/champ/cote?fonds=HK",
        data={"version": str(v), "valeur": "HK-XXX"},
    )
    assert resp.status_code == 403


def test_inline_edit_item_inexistant_404(base_demo: Path) -> None:
    client = TestClient(app)
    resp = client.post(
        "/item/N_EXISTE_PAS/champ/titre?fonds=HK",
        data={"version": "1", "valeur": "X"},
    )
    assert resp.status_code == 404


def test_inline_edit_fonds_inexistant_404(base_demo: Path) -> None:
    client = TestClient(app)
    resp = client.post(
        "/item/HK-001/champ/titre?fonds=N_EXISTE",
        data={"version": "1", "valeur": "X"},
    )
    assert resp.status_code == 404


def test_inline_edit_chaine_vide_efface(base_demo: Path) -> None:
    """Envoyer une chaîne vide efface le champ (rendu « non renseigné »
    dans le fragment retourné)."""
    client = TestClient(app)
    v = _version_courante(base_demo, "HK-001")
    resp = client.post(
        "/item/HK-001/champ/description?fonds=HK",
        data={"version": str(v), "valeur": ""},
    )
    assert resp.status_code == 200
    assert "non renseigné" in resp.text


def test_whitelist_inline_aligne_sur_cartouche(base_demo: Path) -> None:
    """Garde-fou anti-drift : chaque `ChampMetadonnee.editable=True`
    rendu par le cartouche doit être accepté par la route POST. Sinon
    l'utilisateur cliquerait sur une zone marquée éditable et recevrait
    un 403 silencieux."""
    from archives_tool.api.services.dashboard import (
        CHAMPS_ITEM_EDITABLES_INLINE,
        composer_metadonnees_par_section,
    )

    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        item = s.scalar(select(Item).where(Item.cote == "HK-001"))
        sections = composer_metadonnees_par_section(item, [])
    engine.dispose()

    editables_rendues = {
        champ.cle for champs in sections.values() for champ in champs
        if champ.editable
    }
    # Tout champ rendu éditable est dans la whitelist (le contraire
    # — un champ dans la whitelist non rendu — est OK : champs perso
    # ou champs absents par construction).
    assert editables_rendues <= CHAMPS_ITEM_EDITABLES_INLINE, (
        f"Champs rendus éditables hors whitelist : "
        f"{editables_rendues - CHAMPS_ITEM_EDITABLES_INLINE}"
    )


def test_meta_item_context_dans_page(base_demo: Path) -> None:
    """La page item lecture expose `<meta name="item-context">` lu
    par le JS d'édition inline."""
    client = TestClient(app)
    resp = client.get("/item/HK-001?fonds=HK")
    assert resp.status_code == 200
    assert 'name="item-context"' in resp.text
    assert 'data-cote="HK-001"' in resp.text
    assert 'data-fonds="HK"' in resp.text
    assert "data-version=" in resp.text
    assert "inline_edit.js" in resp.text
