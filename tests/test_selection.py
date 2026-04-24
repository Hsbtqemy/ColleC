"""Tests de la sélection d'items pour export."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from archives_tool.exporters.selection import (
    CritereSelection,
    SelectionErreur,
    selectionner_fichiers,
    selectionner_items,
)
from archives_tool.models import Collection, EtatCatalogage, Fichier, Item


def _poser_hierarchie(session: Session) -> None:
    fonds = Collection(cote_collection="FD", titre="Fonds")
    serie_a = Collection(cote_collection="FD-A", titre="Série A", parent=fonds)
    serie_b = Collection(cote_collection="FD-B", titre="Série B", parent=fonds)
    session.add(fonds)
    session.flush()
    session.add_all(
        [
            Item(
                collection_id=fonds.id,
                cote="FD-0001",
                etat_catalogage=EtatCatalogage.VALIDE.value,
            ),
            Item(
                collection_id=serie_a.id,
                cote="FD-A-01",
                etat_catalogage=EtatCatalogage.BROUILLON.value,
            ),
            Item(
                collection_id=serie_a.id,
                cote="FD-A-02",
                etat_catalogage=EtatCatalogage.VALIDE.value,
            ),
            Item(
                collection_id=serie_b.id,
                cote="FD-B-01",
                etat_catalogage=EtatCatalogage.VERIFIE.value,
            ),
        ]
    )
    session.commit()


def test_selection_simple(session: Session) -> None:
    _poser_hierarchie(session)
    critere = CritereSelection(collection_cote="FD")
    cotes = [i.cote for i in selectionner_items(session, critere)]
    # Sans récursif : uniquement l'item direct de FD, pas ceux de FD-A/FD-B.
    assert cotes == ["FD-0001"]


def test_selection_recursive(session: Session) -> None:
    _poser_hierarchie(session)
    critere = CritereSelection(collection_cote="FD", recursif=True)
    cotes = [i.cote for i in selectionner_items(session, critere)]
    # Tous les items (triés par cote).
    assert cotes == ["FD-0001", "FD-A-01", "FD-A-02", "FD-B-01"]


def test_selection_filtree_par_etat(session: Session) -> None:
    _poser_hierarchie(session)
    critere = CritereSelection(
        collection_cote="FD", recursif=True, etats=["valide", "verifie"]
    )
    cotes = [i.cote for i in selectionner_items(session, critere)]
    assert cotes == ["FD-0001", "FD-A-02", "FD-B-01"]


def test_selection_collection_inexistante(session: Session) -> None:
    with pytest.raises(SelectionErreur, match="introuvable"):
        list(selectionner_items(session, CritereSelection(collection_cote="XXX")))


def test_selection_critere_vide(session: Session) -> None:
    with pytest.raises(SelectionErreur, match="Critère vide"):
        list(selectionner_items(session, CritereSelection()))


def test_selection_fichiers(session: Session) -> None:
    _poser_hierarchie(session)
    # Attacher des fichiers dans un ordre non trié pour vérifier le tri.
    i = session.scalar(select(Item).where(Item.cote == "FD-0001"))
    session.add_all(
        [
            Fichier(
                item_id=i.id,
                racine="r",
                chemin_relatif="a/2.tif",
                nom_fichier="2.tif",
                ordre=2,
            ),
            Fichier(
                item_id=i.id,
                racine="r",
                chemin_relatif="a/1.tif",
                nom_fichier="1.tif",
                ordre=1,
            ),
        ]
    )
    session.commit()
    critere = CritereSelection(collection_cote="FD")
    couples = list(selectionner_fichiers(session, critere))
    assert [(it.cote, f.ordre) for it, f in couples] == [("FD-0001", 1), ("FD-0001", 2)]
