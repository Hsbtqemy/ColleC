"""Tests Lot 4a — étiquettes colorées : service CRUD + étiquetage + cascade.

Validation au niveau service (sans HTTP). La parité modèle ↔ migration des
tables `etiquette` / `item_etiquette` est couverte par `test_migration.py`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from archives_tool.api.main import app
from archives_tool.api.services.etiquettes import (
    COULEUR_DEFAUT,
    EtiquetteIntrouvable,
    EtiquetteInvalide,
    FormulaireEtiquette,
    creer_etiquette,
    etiqueter_item,
    etiquette_par_id,
    etiquettes_de_item,
    lister_etiquettes,
    modifier_etiquette,
    retirer_etiquette_item,
    supprimer_etiquette,
)
from archives_tool.api.services.fonds import (
    FormulaireFonds,
    creer_fonds,
    lire_fonds_par_cote,
)
from archives_tool.api.services.items import (
    FormulaireItem,
    creer_item,
    supprimer_item,
)
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.demo import peupler_base
from archives_tool.models import Item, ItemEtiquette


def _item(session: Session):
    creer_fonds(session, FormulaireFonds(cote="HK", titre="HK"))
    fonds = lire_fonds_par_cote(session, "HK")
    return creer_item(
        session, FormulaireItem(cote="HK-1", titre="Numéro 1", fonds_id=fonds.id)
    )


# --- CRUD étiquette ---------------------------------------------------------


def test_creer_etiquette(session: Session) -> None:
    et = creer_etiquette(
        session,
        FormulaireEtiquette(libelle="Litigieux", couleur="#E24B4A"),
        cree_par="Marie",
    )
    assert et.id is not None
    assert et.libelle == "Litigieux"
    assert et.couleur == "#E24B4A"
    assert et.cree_par == "Marie"
    assert lister_etiquettes(session) == [et]


def test_creer_etiquette_libelle_obligatoire(session: Session) -> None:
    with pytest.raises(EtiquetteInvalide) as exc:
        creer_etiquette(
            session, FormulaireEtiquette(libelle="   ", couleur=COULEUR_DEFAUT)
        )
    assert "libelle" in exc.value.erreurs


def test_creer_etiquette_couleur_hors_palette(session: Session) -> None:
    with pytest.raises(EtiquetteInvalide) as exc:
        creer_etiquette(session, FormulaireEtiquette(libelle="X", couleur="#abcdef"))
    assert "couleur" in exc.value.erreurs


def test_creer_etiquette_doublon_insensible_casse(session: Session) -> None:
    creer_etiquette(session, FormulaireEtiquette(libelle="Litigieux", couleur=COULEUR_DEFAUT))
    with pytest.raises(EtiquetteInvalide):
        creer_etiquette(
            session, FormulaireEtiquette(libelle="litigieux", couleur=COULEUR_DEFAUT)
        )


def test_modifier_etiquette(session: Session) -> None:
    et = creer_etiquette(session, FormulaireEtiquette(libelle="A", couleur="#E24B4A"))
    modifier_etiquette(
        session, et.id, FormulaireEtiquette(libelle="B", couleur="#639922")
    )
    et2 = etiquette_par_id(session, et.id)
    assert et2.libelle == "B"
    assert et2.couleur == "#639922"


# --- étiquetage des items ---------------------------------------------------


def test_etiqueter_item_idempotent(session: Session) -> None:
    item = _item(session)
    et = creer_etiquette(session, FormulaireEtiquette(libelle="Relu", couleur=COULEUR_DEFAUT))
    etiqueter_item(session, item.id, et.id, ajoute_par="Marie")
    etiqueter_item(session, item.id, et.id)  # 2e fois → pas de doublon
    assert etiquettes_de_item(session, item.id) == [et]
    n = session.scalar(
        select(func.count()).select_from(ItemEtiquette).where(
            ItemEtiquette.item_id == item.id
        )
    )
    assert n == 1


def test_retirer_etiquette_idempotent(session: Session) -> None:
    item = _item(session)
    et = creer_etiquette(session, FormulaireEtiquette(libelle="Relu", couleur=COULEUR_DEFAUT))
    etiqueter_item(session, item.id, et.id)
    retirer_etiquette_item(session, item.id, et.id)
    retirer_etiquette_item(session, item.id, et.id)  # no-op
    assert etiquettes_de_item(session, item.id) == []


def test_etiqueter_item_etiquette_inconnue(session: Session) -> None:
    item = _item(session)
    with pytest.raises(EtiquetteIntrouvable):
        etiqueter_item(session, item.id, 9999)


# --- cascades ---------------------------------------------------------------


def test_supprimer_etiquette_retire_les_etiquetages(session: Session) -> None:
    item = _item(session)
    et = creer_etiquette(session, FormulaireEtiquette(libelle="Relu", couleur=COULEUR_DEFAUT))
    etiqueter_item(session, item.id, et.id)
    supprimer_etiquette(session, et.id)
    assert etiquettes_de_item(session, item.id) == []
    assert session.scalar(select(func.count()).select_from(ItemEtiquette)) == 0


def test_supprimer_item_retire_les_etiquetages_mais_garde_letiquette(
    session: Session,
) -> None:
    item = _item(session)
    et = creer_etiquette(session, FormulaireEtiquette(libelle="Relu", couleur=COULEUR_DEFAUT))
    etiqueter_item(session, item.id, et.id)
    item_id = item.id
    supprimer_item(session, item_id)
    assert (
        session.scalar(
            select(func.count()).select_from(ItemEtiquette).where(
                ItemEtiquette.item_id == item_id
            )
        )
        == 0
    )
    assert etiquette_par_id(session, et.id) is not None  # l'étiquette survit


# --- Routes web (gestion + étiquetage) --------------------------------------


@pytest.fixture
def base_demo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "demo.db"
    peupler_base(db)
    monkeypatch.setenv("ARCHIVES_DB", str(db))
    return db


def _session_demo(db_path: Path) -> Session:
    return creer_session_factory(creer_engine(db_path))()


def _premier_item(db_path: Path) -> tuple[str, str]:
    with _session_demo(db_path) as db:
        item = db.scalars(select(Item).order_by(Item.id)).first()
        assert item is not None
        return item.cote, item.fonds.cote


def test_page_etiquettes_creer_et_lister(base_demo: Path) -> None:
    client = TestClient(app, follow_redirects=False)
    r = client.post(
        "/etiquettes/creer", data={"libelle": "Litigieux", "couleur": "#E24B4A"}
    )
    assert r.status_code == 303
    page = client.get("/etiquettes")
    assert page.status_code == 200
    assert "Litigieux" in page.text


def test_page_etiquettes_doublon_renvoie_400(base_demo: Path) -> None:
    client = TestClient(app, follow_redirects=False)
    client.post("/etiquettes/creer", data={"libelle": "Dup", "couleur": "#E24B4A"})
    r = client.post("/etiquettes/creer", data={"libelle": "Dup", "couleur": "#E24B4A"})
    assert r.status_code == 400
    assert "existe déjà" in r.text


def test_etiqueter_et_detacher_via_routes(base_demo: Path) -> None:
    cote, fonds_cote = _premier_item(base_demo)
    with _session_demo(base_demo) as db:
        et = creer_etiquette(
            db, FormulaireEtiquette(libelle="Relu", couleur="#639922")
        )
        et_id = et.id

    client = TestClient(app)
    r = client.post(
        f"/item/{cote}/etiquettes",
        params={"fonds": fonds_cote},
        data={"etiquette_id": et_id},
    )
    assert r.status_code == 200
    assert "Relu" in r.text  # chip ajoutée

    r2 = client.post(
        f"/item/{cote}/etiquettes/{et_id}/retirer", params={"fonds": fonds_cote}
    )
    assert r2.status_code == 200
    assert "Aucune étiquette" in r2.text


def test_fiche_item_porte_la_section_etiquettes(base_demo: Path) -> None:
    cote, fonds_cote = _premier_item(base_demo)
    client = TestClient(app)
    r = client.get(f"/item/{cote}", params={"fonds": fonds_cote})
    assert r.status_code == 200
    assert "section-etiquettes-item" in r.text


def test_lien_etiquettes_dans_header(base_demo: Path) -> None:
    client = TestClient(app)
    r = client.get("/")
    assert r.status_code == 200
    assert 'href="/etiquettes"' in r.text


def test_page_etiquettes_confirm_suppression_generique(base_demo: Path) -> None:
    """Garde-fou injection : le confirm de suppression ne doit PAS interpoler
    le libellé (une apostrophe, décodée par le navigateur depuis `&#39;`,
    casserait le JS / l'injecterait). Message générique + page stable avec un
    libellé piégé."""
    with _session_demo(base_demo) as db:
        creer_etiquette(db, FormulaireEtiquette(libelle="O'Brien", couleur="#E24B4A"))
    client = TestClient(app)
    r = client.get("/etiquettes")
    assert r.status_code == 200
    assert "Supprimer cette étiquette ?" in r.text  # confirm générique
    assert "O&#39;Brien" in r.text  # libellé affiché, échappé (contexte HTML)
