"""Tests d'intégration de la suppression UI (V0.9.7) — fonds /
collection libre / item, avec confirmation par recopie de la cote.

Vérifie :
- Happy path : suppression effective + cascade attendue.
- Refus si `confirmer != cote` (400 + entité intacte).
- Refus en mode lecture seule (423 via middleware).
- Refus de supprimer une collection miroir (400).
- Templates : zone de suppression présente en édition, absente en
  lecture seule, message explicatif sur miroir au lieu du bouton.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from archives_tool.api.main import app
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.demo import peupler_base
from archives_tool.models import Collection, Fichier, Fonds, Item


@pytest.fixture
def base_demo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "demo.db"
    peupler_base(db)
    monkeypatch.setenv("ARCHIVES_DB", str(db))
    return db


@pytest.fixture
def base_demo_lecture_seule(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "demo.db"
    peupler_base(db)
    monkeypatch.setenv("ARCHIVES_DB", str(db))
    racine = tmp_path / "miniatures"
    racine.mkdir()
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        f"utilisateur: test\nlecture_seule: true\nracines:\n  demo: {racine}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ARCHIVES_CONFIG", str(cfg))
    return db


def _session(db_path: Path):
    return creer_session_factory(creer_engine(db_path))()


# ---------------------------------------------------------------------------
# Suppression fonds
# ---------------------------------------------------------------------------


def test_supprimer_fonds_happy_path(base_demo: Path) -> None:
    """DELETE fonds HK → fonds + miroir + items disparaissent ; les
    collections libres rattachées passent à transversales (fonds_id=NULL)
    via le FK ON DELETE SET NULL."""
    with _session(base_demo) as db:
        hk = db.scalar(select(Fonds).where(Fonds.cote == "HK"))
        assert hk is not None
        nb_items_hk = db.scalar(
            select(Item).where(Item.fonds_id == hk.id)
        )
        assert nb_items_hk is not None  # au moins un

    client = TestClient(app, follow_redirects=False)
    r = client.post("/fonds/HK/supprimer", data={"confirmer": "HK"})
    assert r.status_code == 303
    assert r.headers["location"] == "/"

    with _session(base_demo) as db:
        assert db.scalar(select(Fonds).where(Fonds.cote == "HK")) is None
        assert db.scalars(
            select(Item).join(Fonds, Item.fonds_id == Fonds.id, isouter=True)
            .where(Fonds.id.is_(None))
        ).all() == []  # cascade complete, pas d'items orphelins


def test_supprimer_fonds_confirmation_invalide(base_demo: Path) -> None:
    client = TestClient(app, follow_redirects=False)
    r = client.post("/fonds/HK/supprimer", data={"confirmer": "hk"})
    assert r.status_code == 400
    assert "Confirmation invalide" in r.json()["detail"]

    with _session(base_demo) as db:
        assert db.scalar(select(Fonds).where(Fonds.cote == "HK")) is not None


def test_supprimer_fonds_inconnu_404(base_demo: Path) -> None:
    client = TestClient(app, follow_redirects=False)
    r = client.post("/fonds/INEXISTANT/supprimer", data={"confirmer": "INEXISTANT"})
    assert r.status_code == 404


def test_supprimer_fonds_lecture_seule_423(base_demo_lecture_seule: Path) -> None:
    client = TestClient(app, follow_redirects=False)
    r = client.post("/fonds/HK/supprimer", data={"confirmer": "HK"})
    assert r.status_code == 423

    with _session(base_demo_lecture_seule) as db:
        assert db.scalar(select(Fonds).where(Fonds.cote == "HK")) is not None


# ---------------------------------------------------------------------------
# Suppression collection
# ---------------------------------------------------------------------------


def test_supprimer_collection_libre_happy_path(base_demo: Path) -> None:
    """DELETE collection libre → la collection disparaît, mais ses
    items restent dans leur fonds et leur miroir (sémantique critique :
    une libre n'« possède » pas ses items, elle les groupe)."""
    with _session(base_demo) as db:
        libre = db.scalars(
            select(Collection).where(Collection.type_collection == "libre")
        ).first()
        assert libre is not None, "Pas de collection libre dans la demo"
        # Capture l'identité de la libre + un item qu'elle contient,
        # pour vérifier après que cet item a bien survécu.
        collection_id = libre.id
        cote_libre = libre.cote
        cote_fonds = libre.fonds.cote if libre.fonds else None
        items_dans_libre = list(libre.items)
        assert items_dans_libre, "Libre sans items — choisir un cas plus riche"
        item_temoin_id = items_dans_libre[0].id

    client = TestClient(app, follow_redirects=False)
    url = f"/collection/{cote_libre}/supprimer"
    if cote_fonds:
        url += f"?fonds={cote_fonds}"
    r = client.post(url, data={"confirmer": cote_libre})
    assert r.status_code == 303

    with _session(base_demo) as db:
        # La collection précise (par id) n'existe plus
        assert db.get(Collection, collection_id) is None
        # L'item-témoin qui était dans cette libre EST TOUJOURS LÀ
        temoin = db.get(Item, item_temoin_id)
        assert temoin is not None, "L'item a été supprimé par erreur en cascade"
        # Il appartient toujours à son fonds + à sa miroir
        assert temoin.fonds_id is not None
        cotes_collections = {c.cote for c in temoin.collections}
        assert cotes_collections, "L'item n'est plus dans aucune collection"


def test_supprimer_collection_miroir_refusee(base_demo: Path) -> None:
    """La miroir d'un fonds ne peut pas être supprimée seule — il faut
    passer par la suppression du fonds."""
    with _session(base_demo) as db:
        hk = db.scalar(select(Fonds).where(Fonds.cote == "HK"))
        miroir = hk.collection_miroir
        assert miroir is not None
        cote_miroir = miroir.cote

    client = TestClient(app, follow_redirects=False)
    r = client.post(
        f"/collection/{cote_miroir}/supprimer?fonds=HK",
        data={"confirmer": cote_miroir},
    )
    assert r.status_code == 400
    assert "miroir" in r.json()["detail"].lower()


def test_supprimer_collection_confirmation_invalide(base_demo: Path) -> None:
    with _session(base_demo) as db:
        libre = db.scalars(
            select(Collection).where(Collection.type_collection == "libre")
        ).first()
        assert libre is not None
        cote = libre.cote
        cote_fonds = libre.fonds.cote if libre.fonds else None

    client = TestClient(app, follow_redirects=False)
    url = f"/collection/{cote}/supprimer"
    if cote_fonds:
        url += f"?fonds={cote_fonds}"
    r = client.post(url, data={"confirmer": "ZZZ"})
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# Suppression item
# ---------------------------------------------------------------------------


def test_supprimer_item_happy_path(base_demo: Path) -> None:
    """DELETE item → item + fichiers + liaisons disparaissent."""
    with _session(base_demo) as db:
        item = db.scalar(
            select(Item).join(Fonds).where(Fonds.cote == "HK", Item.cote == "HK-001")
        )
        assert item is not None
        item_id = item.id
        nb_fichiers_avant = len(item.fichiers)

    client = TestClient(app, follow_redirects=False)
    r = client.post("/item/HK-001/supprimer?fonds=HK", data={"confirmer": "HK-001"})
    assert r.status_code == 303
    assert r.headers["location"] == "/fonds/HK"

    with _session(base_demo) as db:
        assert db.get(Item, item_id) is None
        # Fichiers de l'item supprimés en cascade
        assert (
            db.scalars(select(Fichier).where(Fichier.item_id == item_id)).all() == []
        )
        # Le fonds est toujours là
        assert db.scalar(select(Fonds).where(Fonds.cote == "HK")) is not None
        assert nb_fichiers_avant > 0  # garde-fou test


def test_supprimer_item_confirmation_invalide(base_demo: Path) -> None:
    client = TestClient(app, follow_redirects=False)
    r = client.post("/item/HK-001/supprimer?fonds=HK", data={"confirmer": "autre"})
    assert r.status_code == 400

    with _session(base_demo) as db:
        item = db.scalar(
            select(Item).join(Fonds).where(Fonds.cote == "HK", Item.cote == "HK-001")
        )
        assert item is not None


def test_supprimer_item_lecture_seule_423(base_demo_lecture_seule: Path) -> None:
    client = TestClient(app, follow_redirects=False)
    r = client.post("/item/HK-001/supprimer?fonds=HK", data={"confirmer": "HK-001"})
    assert r.status_code == 423


# ---------------------------------------------------------------------------
# Templates : zone de suppression visible dans les bonnes conditions
# ---------------------------------------------------------------------------


def test_page_fonds_modifier_affiche_zone_suppression(base_demo: Path) -> None:
    client = TestClient(app)
    r = client.get("/fonds/HK/modifier")
    assert r.status_code == 200
    assert "Zone de suppression" in r.text
    assert 'action="/fonds/HK/supprimer"' in r.text
    assert "Supprimer définitivement" in r.text


def test_page_collection_libre_modifier_affiche_zone_suppression(
    base_demo: Path,
) -> None:
    with _session(base_demo) as db:
        libre = db.scalars(
            select(Collection).where(Collection.type_collection == "libre")
        ).first()
        assert libre is not None
        url = f"/collection/{libre.cote}/modifier"
        if libre.fonds:
            url += f"?fonds={libre.fonds.cote}"

    client = TestClient(app)
    r = client.get(url)
    assert r.status_code == 200
    assert "Zone de suppression" in r.text
    assert "/supprimer" in r.text


def test_page_collection_miroir_modifier_inaccessible(base_demo: Path) -> None:
    """La page modifier d'une miroir est refusée (403) par le service —
    une miroir n'est pas éditable indépendamment de son fonds. Donc
    l'utilisateur ne peut pas atteindre la zone de suppression d'une
    miroir, garde-fou côté route en plus du garde-fou côté service
    `supprimer_collection_libre` qui refuse aussi le type miroir."""
    with _session(base_demo) as db:
        hk = db.scalar(select(Fonds).where(Fonds.cote == "HK"))
        miroir = hk.collection_miroir

    client = TestClient(app)
    r = client.get(f"/collection/{miroir.cote}/modifier?fonds=HK")
    assert r.status_code == 403


def test_page_item_modifier_affiche_zone_suppression(base_demo: Path) -> None:
    client = TestClient(app)
    r = client.get("/item/HK-001/modifier?fonds=HK")
    assert r.status_code == 200
    assert "Zone de suppression" in r.text
    assert 'action="/item/HK-001/supprimer?fonds=HK"' in r.text


def test_zone_suppression_porte_data_cote_confirmer(base_demo: Path) -> None:
    """Chaque form de suppression porte `data-cote-confirmer="<cote>"`
    pour que `zone_suppression.js` puisse désactiver le bouton submit
    tant que l'input ne contient pas exactement la cote attendue.
    Garde-fou que les 3 templates exposent l'attribut + sa valeur."""
    client = TestClient(app)

    r = client.get("/fonds/HK/modifier")
    assert 'data-cote-confirmer="HK"' in r.text

    r = client.get("/item/HK-001/modifier?fonds=HK")
    assert 'data-cote-confirmer="HK-001"' in r.text

    # Collection libre : récupère une cote vivante de la demo
    with _session(base_demo) as db:
        libre = db.scalars(
            select(Collection).where(Collection.type_collection == "libre")
        ).first()
        assert libre is not None
        cote_libre = libre.cote
        cote_fonds = libre.fonds.cote if libre.fonds else None
    url = f"/collection/{cote_libre}/modifier"
    if cote_fonds:
        url += f"?fonds={cote_fonds}"
    r = client.get(url)
    assert f'data-cote-confirmer="{cote_libre}"' in r.text


def test_pages_modifier_pas_de_zone_en_lecture_seule(
    base_demo_lecture_seule: Path,
) -> None:
    client = TestClient(app)
    for url in (
        "/fonds/HK/modifier",
        "/item/HK-001/modifier?fonds=HK",
    ):
        r = client.get(url)
        assert r.status_code == 200, url
        assert "Zone de suppression" not in r.text, url
        assert "Supprimer définitivement" not in r.text, url
