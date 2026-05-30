"""Tests du bouton « − Retirer » dans le tableau d'items d'une collection.

Restauration d'une feature documentée en V0.9.0-beta.2.1 (« bouton
retrait par ligne (idempotent, permis sur miroir) ») mais disparue
silencieusement à un moment du refactor — Lot A.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from archives_tool.api.main import app
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.demo import peupler_base
from archives_tool.models import (
    Collection,
    Item,
    ItemCollection,
    TypeCollection,
)


@pytest.fixture
def base_demo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "demo.db"
    peupler_base(db)
    monkeypatch.setenv("ARCHIVES_DB", str(db))
    return db


def test_bouton_retirer_present_sur_libre_rattachee(base_demo: Path) -> None:
    """Sur une libre rattachée, chaque ligne du tableau d'items expose
    le bouton retirer pointant sur /collection/<cote>/items/<id>/retirer."""
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        libre = s.scalar(
            select(Collection).where(
                Collection.type_collection == TypeCollection.LIBRE.value
            )
        )
        cote = libre.cote
        fonds_cote = libre.fonds.cote if libre.fonds else None
    engine.dispose()

    client = TestClient(app)
    url = f"/collection/{cote}"
    if fonds_cote:
        url += f"?fonds={fonds_cote}"
    r = client.get(url)
    assert r.status_code == 200
    # URL d'action présente (format générique avec /retirer dans l'URL)
    assert f"/collection/{cote}/items/" in r.text
    assert "/retirer" in r.text


def test_bouton_retirer_present_sur_miroir(base_demo: Path) -> None:
    """Sur une miroir, le bouton est aussi rendu (service le permet —
    l'item reste dans le fonds, invariant 7)."""
    client = TestClient(app)
    r = client.get("/collection/HK?fonds=HK")
    assert r.status_code == 200
    # Cherche une URL retirer pour un item de la miroir HK
    assert "/collection/HK/items/" in r.text
    assert "/retirer" in r.text


def test_post_retirer_item_retire_la_liaison(base_demo: Path) -> None:
    """POST sur /collection/<cote>/items/<id>/retirer supprime la
    liaison ItemCollection. L'item reste en base."""
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        # Trouve une libre avec au moins un item
        libre = s.scalar(
            select(Collection).where(
                Collection.type_collection == TypeCollection.LIBRE.value
            )
        )
        liaison = s.scalars(
            select(ItemCollection).where(
                ItemCollection.collection_id == libre.id
            )
        ).first()
        assert liaison is not None, "Demo doit avoir au moins une libre avec items"
        item_id = liaison.item_id
        collection_id = libre.id
        cote = libre.cote
        fonds_cote = libre.fonds.cote if libre.fonds else None
    engine.dispose()

    client = TestClient(app, follow_redirects=False)
    url = f"/collection/{cote}/items/{item_id}/retirer"
    if fonds_cote:
        url += f"?fonds={fonds_cote}"
    r = client.post(url)
    assert r.status_code == 303
    # Redirect vers la page collection
    assert f"/collection/{cote}" in r.headers["location"]

    # Vérifie en base : la liaison est partie, l'item existe encore
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        l_apres = s.get(ItemCollection, (item_id, collection_id))
        assert l_apres is None
        item = s.get(Item, item_id)
        assert item is not None
    engine.dispose()


def test_post_retirer_idempotent(base_demo: Path) -> None:
    """Re-jouer le POST = no-op (idempotent côté service)."""
    engine = creer_engine(base_demo)
    factory = creer_session_factory(engine)
    with factory() as s:
        libre = s.scalar(
            select(Collection).where(
                Collection.type_collection == TypeCollection.LIBRE.value
            )
        )
        liaison = s.scalars(
            select(ItemCollection).where(
                ItemCollection.collection_id == libre.id
            )
        ).first()
        item_id = liaison.item_id
        cote = libre.cote
        fonds_cote = libre.fonds.cote if libre.fonds else None
    engine.dispose()

    client = TestClient(app, follow_redirects=False)
    url = f"/collection/{cote}/items/{item_id}/retirer"
    if fonds_cote:
        url += f"?fonds={fonds_cote}"
    # Premier POST
    r1 = client.post(url)
    assert r1.status_code == 303
    # Deuxième POST : pas d'erreur
    r2 = client.post(url)
    assert r2.status_code == 303


def test_bouton_retirer_absent_en_lecture_seule(
    base_demo: Path, monkeypatch, tmp_path: Path
) -> None:
    """En lecture seule, le bouton n'apparaît pas dans le HTML. Le
    middleware bloquerait le POST de toute façon, mais on évite le
    bouton trompeur."""
    racine = tmp_path / "miniatures"
    racine.mkdir()
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        f"utilisateur: test\nlecture_seule: true\nracines:\n  d: {racine}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ARCHIVES_CONFIG", str(cfg))

    client = TestClient(app)
    r = client.get("/collection/HK?fonds=HK")
    assert r.status_code == 200
    # Pas d'URL /retirer dans le HTML
    assert "/retirer" not in r.text
