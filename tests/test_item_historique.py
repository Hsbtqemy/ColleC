"""Tests du Lot 2 UI⁺ — historique des modifications d'un item.

Deux volets :
- Producteur : `modifier_item` journalise une `ModificationItem` par champ
  changé (colonnes DC + clés `metadonnees`), et rien si rien ne change.
- Consommateur : `lister_modifications_item` (ordre) + route HTMX
  `/item/{cote}/historique` (rendu du fragment + état vide) + bouton de
  chargement paresseux présent sur la fiche.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from archives_tool.api.main import app
from archives_tool.api.services.fonds import (
    FormulaireFonds,
    creer_fonds,
    lire_fonds_par_cote,
    supprimer_fonds,
)
from archives_tool.api.services.items import (
    FormulaireItem,
    creer_item,
    formulaire_depuis_item,
    lister_modifications_item,
    modifier_item,
    supprimer_item,
)
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.demo import peupler_base
from archives_tool.models import Item, ModificationItem


# ---------------------------------------------------------------------------
# Producteur : modifier_item → ModificationItem
# ---------------------------------------------------------------------------


def _item_hk(session: Session) -> Item:
    creer_fonds(session, FormulaireFonds(cote="HK", titre="Hara-Kiri"))
    fonds = lire_fonds_par_cote(session, "HK")
    return creer_item(
        session, FormulaireItem(cote="HK-1", titre="Ancien titre", fonds_id=fonds.id)
    )


def test_modifier_item_journalise_colonne_et_metadonnee(session: Session) -> None:
    item = _item_hk(session)
    form = formulaire_depuis_item(item)
    form.version = item.version
    form.titre = "Nouveau titre"
    form.metadonnees["auteur"] = "Copi"
    modifier_item(session, item.id, form, modifie_par="Marie")

    mods = lister_modifications_item(session, item.id)
    champs = {m.champ for m in mods}
    assert "titre" in champs
    assert "meta.auteur" in champs

    titre_mod = next(m for m in mods if m.champ == "titre")
    assert titre_mod.valeur_avant == "Ancien titre"
    assert titre_mod.valeur_apres == "Nouveau titre"
    assert titre_mod.modifie_par == "Marie"

    auteur_mod = next(m for m in mods if m.champ == "meta.auteur")
    assert auteur_mod.valeur_avant is None  # clé nouvelle
    assert auteur_mod.valeur_apres == "Copi"


def test_modifier_item_sans_changement_ne_journalise_rien(session: Session) -> None:
    """Re-sauver à l'identique (cas d'un inline edit qui ne change rien)
    incrémente la version mais ne crée AUCUNE ligne d'historique."""
    item = _item_hk(session)
    form = formulaire_depuis_item(item)
    form.version = item.version
    modifier_item(session, item.id, form, modifie_par="Marie")
    assert lister_modifications_item(session, item.id) == []


def test_lister_modifications_recent_dabord(session: Session) -> None:
    item = _item_hk(session)

    f1 = formulaire_depuis_item(item)
    f1.version = item.version
    f1.titre = "Titre 2"
    it = modifier_item(session, item.id, f1, modifie_par="A")

    f2 = formulaire_depuis_item(it)
    f2.version = it.version
    f2.description = "Description 2"
    modifier_item(session, item.id, f2, modifie_par="B")

    mods = lister_modifications_item(session, item.id)
    assert mods[0].champ == "description"  # le plus récent en tête
    assert mods[-1].champ == "titre"


def _nb_modifications(session: Session, item_id: int) -> int:
    return session.scalar(
        select(func.count(ModificationItem.id)).where(
            ModificationItem.item_id == item_id
        )
    )


def test_supprimer_item_avec_historique_cascade(session: Session) -> None:
    """Régression introduite par Lot 2 : maintenant que ModificationItem
    est réellement écrit, supprimer un item AVEC historique doit cascader
    (relation Item.modifications = delete-orphan), pas violer la FK."""
    item = _item_hk(session)
    form = formulaire_depuis_item(item)
    form.version = item.version
    form.titre = "Titre 2"
    modifier_item(session, item.id, form, modifie_par="A")
    item_id = item.id
    assert _nb_modifications(session, item_id) > 0

    supprimer_item(session, item_id, execute_par="A")  # ne doit pas lever
    assert _nb_modifications(session, item_id) == 0


def test_supprimer_fonds_avec_item_historise_cascade(session: Session) -> None:
    """Suppression d'un fonds dont un item a un historique : la cascade ORM
    fonds→items→modifications doit tout nettoyer sans violer la FK
    ModificationItem.item_id (qui n'a pas d'ON DELETE SQL)."""
    item = _item_hk(session)
    fonds_id = item.fonds_id
    item_id = item.id
    form = formulaire_depuis_item(item)
    form.version = item.version
    form.titre = "Titre 2"
    modifier_item(session, item.id, form, modifie_par="A")
    assert _nb_modifications(session, item_id) > 0

    supprimer_fonds(session, fonds_id, execute_par="A")  # ne doit pas lever
    assert session.get(Item, item_id) is None
    assert _nb_modifications(session, item_id) == 0


# ---------------------------------------------------------------------------
# Consommateur : route HTMX + fiche
# ---------------------------------------------------------------------------


@pytest.fixture
def base_demo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "demo.db"
    peupler_base(db)
    monkeypatch.setenv("ARCHIVES_DB", str(db))
    return db


def _premier_item(db_path: Path) -> tuple[str, str, int]:
    with creer_session_factory(creer_engine(db_path))() as db:
        item = db.scalars(select(Item).order_by(Item.id)).first()
        assert item is not None
        return item.cote, item.fonds.cote, item.id


def test_route_historique_etat_vide(base_demo: Path) -> None:
    cote, fonds_cote, _ = _premier_item(base_demo)
    client = TestClient(app)
    r = client.get(f"/item/{cote}/historique", params={"fonds": fonds_cote})
    assert r.status_code == 200
    assert "Aucune modification enregistrée" in r.text


def test_route_historique_rend_une_modification(base_demo: Path) -> None:
    cote, fonds_cote, item_id = _premier_item(base_demo)
    with creer_session_factory(creer_engine(base_demo))() as db:
        db.add(
            ModificationItem(
                item_id=item_id,
                champ="titre",
                valeur_avant="X",
                valeur_apres="Y",
                modifie_par="Marie",
            )
        )
        db.commit()

    client = TestClient(app)
    r = client.get(f"/item/{cote}/historique", params={"fonds": fonds_cote})
    assert r.status_code == 200
    assert "titre" in r.text
    assert "Marie" in r.text
    assert "Y" in r.text


def test_fiche_item_porte_le_bouton_historique(base_demo: Path) -> None:
    cote, fonds_cote, _ = _premier_item(base_demo)
    client = TestClient(app)
    r = client.get(f"/item/{cote}", params={"fonds": fonds_cote})
    assert r.status_code == 200
    assert "/historique?fonds=" in r.text
    assert "Historique des modifications" in r.text
