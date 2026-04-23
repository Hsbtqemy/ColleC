"""Contraintes d'unicité et d'intégrité sur le modèle."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from archives_tool.models import Collection, Fichier, Item


def _nouvelle_collection(session: Session, cote: str = "COL-A") -> Collection:
    col = Collection(cote_collection=cote, titre=f"Revue {cote}")
    session.add(col)
    session.flush()
    return col


def test_cote_item_unique_dans_collection(session: Session) -> None:
    col = _nouvelle_collection(session)
    session.add(Item(collection_id=col.id, cote="1923-01"))
    session.flush()
    session.add(Item(collection_id=col.id, cote="1923-01"))
    with pytest.raises(IntegrityError):
        session.flush()


def test_meme_cote_autorisee_dans_collections_differentes(session: Session) -> None:
    col_a = _nouvelle_collection(session, "COL-A")
    col_b = _nouvelle_collection(session, "COL-B")
    session.add(Item(collection_id=col_a.id, cote="1923-01"))
    session.add(Item(collection_id=col_b.id, cote="1923-01"))
    session.flush()  # ne doit pas lever


def test_cote_collection_globale_unique(session: Session) -> None:
    _nouvelle_collection(session, "COL-X")
    session.add(Collection(cote_collection="COL-X", titre="Doublon"))
    with pytest.raises(IntegrityError):
        session.flush()


def test_ordre_fichier_unique_dans_item(session: Session) -> None:
    col = _nouvelle_collection(session)
    item = Item(collection_id=col.id, cote="N1")
    session.add(item)
    session.flush()
    session.add(
        Fichier(
            item_id=item.id,
            racine="scans",
            chemin_relatif="a/1.tif",
            nom_fichier="1.tif",
            ordre=1,
        )
    )
    session.flush()
    session.add(
        Fichier(
            item_id=item.id,
            racine="scans",
            chemin_relatif="a/2.tif",
            nom_fichier="2.tif",
            ordre=1,
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_meme_ordre_autorise_sur_items_differents(session: Session) -> None:
    col = _nouvelle_collection(session)
    item_a = Item(collection_id=col.id, cote="N1")
    item_b = Item(collection_id=col.id, cote="N2")
    session.add_all([item_a, item_b])
    session.flush()
    session.add(
        Fichier(
            item_id=item_a.id,
            racine="scans",
            chemin_relatif="a/1.tif",
            nom_fichier="1.tif",
            ordre=1,
        )
    )
    session.add(
        Fichier(
            item_id=item_b.id,
            racine="scans",
            chemin_relatif="b/1.tif",
            nom_fichier="1.tif",
            ordre=1,
        )
    )
    session.flush()


def test_chemin_fichier_globalement_unique(session: Session) -> None:
    col = _nouvelle_collection(session)
    item = Item(collection_id=col.id, cote="N1")
    session.add(item)
    session.flush()
    session.add(
        Fichier(
            item_id=item.id,
            racine="scans",
            chemin_relatif="dup/1.tif",
            nom_fichier="1.tif",
            ordre=1,
        )
    )
    session.flush()
    session.add(
        Fichier(
            item_id=item.id,
            racine="scans",
            chemin_relatif="dup/1.tif",
            nom_fichier="1.tif",
            ordre=2,
        )
    )
    with pytest.raises(IntegrityError):
        session.flush()


def test_doi_nakala_collection_unique(session: Session) -> None:
    doi = "10.34847/nkl.abc123"
    session.add(Collection(cote_collection="A", titre="A", doi_nakala=doi))
    session.flush()
    session.add(Collection(cote_collection="B", titre="B", doi_nakala=doi))
    with pytest.raises(IntegrityError):
        session.flush()


def test_doi_nakala_collection_null_non_unique(session: Session) -> None:
    # Les NULL ne sont pas considérés comme égaux : plusieurs collections
    # sans DOI Nakala doivent coexister.
    session.add(Collection(cote_collection="A", titre="A"))
    session.add(Collection(cote_collection="B", titre="B"))
    session.flush()


def test_doi_nakala_item_unique(session: Session) -> None:
    col = _nouvelle_collection(session)
    doi = "10.34847/nkl.item001"
    session.add(Item(collection_id=col.id, cote="N1", doi_nakala=doi))
    session.flush()
    session.add(Item(collection_id=col.id, cote="N2", doi_nakala=doi))
    with pytest.raises(IntegrityError):
        session.flush()


def test_doi_collection_nakala_item_partageable(session: Session) -> None:
    # Contrepartie critique : plusieurs items doivent pouvoir pointer
    # vers la même collection Nakala. Aucune contrainte d'unicité.
    col = _nouvelle_collection(session)
    doi_col = "10.34847/nkl.coll001"
    session.add(Item(collection_id=col.id, cote="N1", doi_collection_nakala=doi_col))
    session.add(Item(collection_id=col.id, cote="N2", doi_collection_nakala=doi_col))
    session.add(Item(collection_id=col.id, cote="N3", doi_collection_nakala=doi_col))
    session.flush()  # ne doit pas lever


def test_collection_racine_valide(session: Session) -> None:
    col = Collection(cote_collection="RACINE", titre="Fonds", parent_id=None)
    session.add(col)
    session.flush()
    assert col.parent is None
    assert col.parent_id is None


def test_sous_collection_valide(session: Session) -> None:
    parent = Collection(cote_collection="FONDS-A", titre="Fonds A")
    enfant = Collection(cote_collection="FONDS-A-1", titre="Série 1", parent=parent)
    session.add(parent)
    session.flush()
    assert enfant.parent_id == parent.id
    assert enfant in parent.enfants


def test_cascade_suppression_parent(session: Session) -> None:
    # Pré-condition : FK actives pour que l'ORM déclenche le cascade à la
    # session. Sinon on ne teste pas ce qu'on croit.
    from sqlalchemy import text

    assert session.execute(text("PRAGMA foreign_keys")).scalar() == 1

    parent = Collection(cote_collection="P", titre="Parent")
    enfant = Collection(cote_collection="P-1", titre="Enfant", parent=parent)
    item = Item(collection=enfant, cote="X1")
    session.add(parent)
    session.commit()

    enfant_id, item_id = enfant.id, item.id
    session.delete(parent)
    session.commit()

    assert session.get(Collection, enfant_id) is None
    assert session.get(Item, item_id) is None


def test_anti_cycle_auto_reference(session: Session) -> None:
    col = Collection(cote_collection="CYC1", titre="Auto")
    session.add(col)
    session.flush()
    col.parent = col
    with pytest.raises(ValueError, match="propre parent"):
        session.flush()


def test_anti_cycle_profond(session: Session) -> None:
    a = Collection(cote_collection="CYC-A", titre="A")
    b = Collection(cote_collection="CYC-B", titre="B", parent=a)
    c = Collection(cote_collection="CYC-C", titre="C", parent=b)
    session.add(a)
    session.commit()

    # A > B > C ; puis on tente C -> parent de A, ce qui fermerait la boucle.
    a.parent = c
    with pytest.raises(ValueError, match="[Cc]ycle"):
        session.flush()


def test_etat_catalogage_check_constraint(session: Session) -> None:
    col = _nouvelle_collection(session)
    session.add(Item(collection_id=col.id, cote="N1", etat_catalogage="inexistant"))
    with pytest.raises(IntegrityError):
        session.flush()
