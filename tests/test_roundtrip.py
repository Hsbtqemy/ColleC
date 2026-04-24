"""Round-trip minimal : création + relecture via relations."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from archives_tool.models import (
    Collection,
    EtatCatalogage,
    Fichier,
    Item,
    TypePage,
)


def test_creation_et_navigation_relations(session: Session) -> None:
    collection = Collection(cote_collection="REV-1", titre="Revue d'essai")
    item = Item(
        collection=collection,
        cote="1923-N01",
        numero="1",
        annee=1923,
        etat_catalogage=EtatCatalogage.BROUILLON.value,
    )
    Fichier(
        item=item,
        racine="scans",
        chemin_relatif="rev1/1923/01/0001.tif",
        nom_fichier="0001.tif",
        ordre=1,
        type_page=TypePage.COUVERTURE.value,
    )
    session.add(collection)
    session.commit()

    rechargee = session.get(Collection, collection.id)
    assert rechargee is not None
    assert len(rechargee.items) == 1
    (item_relu,) = rechargee.items
    assert item_relu.cote == "1923-N01"
    assert len(item_relu.fichiers) == 1
    assert item_relu.fichiers[0].nom_fichier == "0001.tif"
    assert item_relu.fichiers[0].type_page == "couverture"


def test_cascade_suppression_collection(session: Session) -> None:
    # Pré-condition explicite : le cascade ne « passe » que si les FK
    # sont actives. Sans ça, un test_cascade vert pourrait masquer
    # des FK désactivées par inadvertance dans la config de test.
    assert session.execute(text("PRAGMA foreign_keys")).scalar() == 1

    collection = Collection(cote_collection="REV-2", titre="Temp")
    item = Item(collection=collection, cote="X")
    session.add_all([collection, item])
    session.commit()
    item_id = item.id

    session.delete(collection)
    session.commit()

    assert session.get(Item, item_id) is None


def test_doi_nakala_roundtrip(session: Session) -> None:
    collection = Collection(
        cote_collection="REV-DOI",
        titre="Revue avec DOI",
        doi_nakala="10.34847/nkl.coll_abc",
    )
    Item(
        collection=collection,
        cote="N1",
        doi_nakala="10.34847/nkl.item_xyz",
        doi_collection_nakala="10.34847/nkl.coll_abc",
    )
    session.add(collection)
    session.commit()

    col_relue = session.get(Collection, collection.id)
    assert col_relue is not None
    assert col_relue.doi_nakala == "10.34847/nkl.coll_abc"
    (item_relu,) = col_relue.items
    assert item_relu.doi_nakala == "10.34847/nkl.item_xyz"
    assert item_relu.doi_collection_nakala == "10.34847/nkl.coll_abc"


def test_roundtrip_hierarchie_collections(session: Session) -> None:
    fonds = Collection(cote_collection="AINSA", titre="Fonds Ainsa")
    serie = Collection(cote_collection="AINSA-01", titre="Correspondance", parent=fonds)
    sous_serie = Collection(
        cote_collection="AINSA-01-A", titre="Lettres reçues", parent=serie
    )
    item = Item(collection=sous_serie, cote="AINSA-01-A-1923-001")
    session.add(fonds)
    session.commit()

    item_relu = session.get(Item, item.id)
    assert item_relu is not None
    # Remontée complète de l'arbre depuis l'item-feuille.
    assert item_relu.collection.cote_collection == "AINSA-01-A"
    assert item_relu.collection.parent.cote_collection == "AINSA-01"
    assert item_relu.collection.parent.parent.cote_collection == "AINSA"
    assert item_relu.collection.parent.parent.parent is None


def test_description_interne_et_auteur_principal(session: Session) -> None:
    collection = Collection(
        cote_collection="CHANTIER-1",
        titre="Revue en cours",
        description="Publication trimestrielle du XIXᵉ siècle.",
        description_interne=(
            "Chantier repris en 2026 ; cotes antérieures à 1870 à vérifier "
            "contre l'inventaire manuscrit."
        ),
        auteur_principal="Marie Dupont",
        # Champs d'audit désormais en texte libre (pas de FK Utilisateur).
        cree_par="Marie Dupont",
    )
    session.add(collection)
    session.commit()

    relue = session.get(Collection, collection.id)
    assert relue is not None
    assert relue.description.startswith("Publication")
    assert relue.description_interne.startswith("Chantier repris")
    assert relue.auteur_principal == "Marie Dupont"
    assert relue.cree_par == "Marie Dupont"

    # Les champs sont mutables sans contrainte.
    relue.auteur_principal = "Jean Martin"
    relue.description_interne = None
    relue.modifie_par = "Jean Martin"
    session.commit()
    rerelue = session.get(Collection, collection.id)
    assert rerelue.auteur_principal == "Jean Martin"
    assert rerelue.description_interne is None
    assert rerelue.modifie_par == "Jean Martin"


def test_fk_rejette_collection_id_inexistant(session: Session) -> None:
    # Vérification directe que les FK sont *enforced* au niveau base,
    # pas uniquement au niveau ORM. Si les pragmas tombent, ce test
    # passe de rouge à vert silencieusement.
    session.add(Item(collection_id=99999, cote="orphelin"))
    with pytest.raises(IntegrityError):
        session.commit()
