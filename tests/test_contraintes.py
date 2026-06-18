"""Contraintes d'unicité et d'intégrité **au niveau SQL** (IntegrityError).

Défense en profondeur : ces contraintes valent même si la couche service
est contournée. Couverture **unique** non assurée ailleurs :
`uq_fichier_item_ordre`, `uq_fichier_chemin`, `uq_item_doi_nakala`,
`uq_collection_doi_nakala` (+ NULL non-égaux), `ck_item_etat_catalogage`.

Migré V0.9.0 (2026-06-18) : modèle Fonds / Collection / Item refondu. Les
tests d'unicité de cote (désormais `uq_item_fonds_cote` / cote collection
par fonds) sont couverts par `test_fonds.py` ; les tests de hiérarchie
`Collection.parent_id` sont supprimés (fonctionnalité retirée à la refonte).
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from archives_tool.models import Collection, Fichier, Fonds, Item


def _fonds(session: Session, cote: str = "F") -> Fonds:
    fonds = Fonds(cote=cote, titre=f"Fonds {cote}")
    session.add(fonds)
    session.flush()
    return fonds


def _item(session: Session, fonds: Fonds, cote: str, **kwargs) -> Item:
    item = Item(fonds_id=fonds.id, cote=cote, **kwargs)
    session.add(item)
    session.flush()
    return item


def _fichier(item: Item, ordre: int, chemin: str) -> Fichier:
    return Fichier(
        item_id=item.id,
        racine="scans",
        chemin_relatif=chemin,
        nom_fichier=chemin.rsplit("/", 1)[-1],
        ordre=ordre,
    )


# --- Fichier : ordre unique par item, chemin globalement unique ---


def test_ordre_fichier_unique_dans_item(session: Session) -> None:
    item = _item(session, _fonds(session), "N1")
    session.add(_fichier(item, ordre=1, chemin="a/1.tif"))
    session.flush()
    session.add(_fichier(item, ordre=1, chemin="a/2.tif"))  # même ordre
    with pytest.raises(IntegrityError):
        session.flush()


def test_meme_ordre_autorise_sur_items_differents(session: Session) -> None:
    fonds = _fonds(session)
    item_a = _item(session, fonds, "N1")
    item_b = _item(session, fonds, "N2")
    session.add(_fichier(item_a, ordre=1, chemin="a/1.tif"))
    session.add(_fichier(item_b, ordre=1, chemin="b/1.tif"))
    session.flush()  # ne doit pas lever


def test_chemin_fichier_globalement_unique(session: Session) -> None:
    item = _item(session, _fonds(session), "N1")
    session.add(_fichier(item, ordre=1, chemin="dup/1.tif"))
    session.flush()
    session.add(_fichier(item, ordre=2, chemin="dup/1.tif"))  # même (racine, chemin)
    with pytest.raises(IntegrityError):
        session.flush()


# --- DOI Nakala : unique sur collection et item, NULL non-égaux ---


def test_doi_nakala_collection_unique(session: Session) -> None:
    doi = "10.34847/nkl.abc123"
    session.add(Collection(cote="A", titre="A", doi_nakala=doi))
    session.flush()
    session.add(Collection(cote="B", titre="B", doi_nakala=doi))
    with pytest.raises(IntegrityError):
        session.flush()


def test_doi_nakala_collection_null_non_unique(session: Session) -> None:
    # Les NULL ne sont pas considérés comme égaux : plusieurs collections
    # sans DOI Nakala doivent coexister.
    session.add(Collection(cote="A", titre="A"))
    session.add(Collection(cote="B", titre="B"))
    session.flush()


def test_doi_nakala_item_unique(session: Session) -> None:
    fonds = _fonds(session)
    doi = "10.34847/nkl.item001"
    _item(session, fonds, "N1", doi_nakala=doi)
    session.add(Item(fonds_id=fonds.id, cote="N2", doi_nakala=doi))
    with pytest.raises(IntegrityError):
        session.flush()


def test_doi_collection_nakala_item_partageable(session: Session) -> None:
    # Contrepartie critique : plusieurs items doivent pouvoir pointer vers
    # la même collection Nakala. Aucune contrainte d'unicité.
    fonds = _fonds(session)
    doi_col = "10.34847/nkl.coll001"
    for cote in ("N1", "N2", "N3"):
        session.add(Item(fonds_id=fonds.id, cote=cote, doi_collection_nakala=doi_col))
    session.flush()  # ne doit pas lever


# --- CHECK état de catalogage ---


def test_etat_catalogage_check_constraint(session: Session) -> None:
    fonds = _fonds(session)
    session.add(Item(fonds_id=fonds.id, cote="N1", etat_catalogage="inexistant"))
    with pytest.raises(IntegrityError):
        session.flush()
