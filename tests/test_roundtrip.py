"""Round-trip minimal : création + relecture via relations (modèle v2).

Le modèle V0.9.0 : un Item appartient à exactement un Fonds
(`fonds_id`, ON DELETE CASCADE) et figure dans 0..N collections via
la junction `ItemCollection`. La hiérarchie `Collection.parent` a
été supprimée. Ces tests vérifient les relations ORM, la cascade et
l'enforcement des FK au niveau base.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from archives_tool.models import (
    EtatCatalogage,
    Fichier,
    Fonds,
    Item,
    TypePage,
)


def test_creation_et_navigation_relations(session: Session) -> None:
    fonds = Fonds(cote="REV-1", titre="Revue d'essai")
    item = Item(
        fonds=fonds,
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
    session.add(fonds)
    session.commit()

    recharge = session.get(Fonds, fonds.id)
    assert recharge is not None
    assert len(recharge.items) == 1
    (item_relu,) = recharge.items
    assert item_relu.cote == "1923-N01"
    assert len(item_relu.fichiers) == 1
    assert item_relu.fichiers[0].nom_fichier == "0001.tif"
    assert item_relu.fichiers[0].type_page == "couverture"


def test_cascade_suppression_fonds(session: Session) -> None:
    # Pré-condition explicite : le cascade ne « passe » que si les FK
    # sont actives. Sans ça, un test_cascade vert pourrait masquer
    # des FK désactivées par inadvertance dans la config de test.
    assert session.execute(text("PRAGMA foreign_keys")).scalar() == 1

    fonds = Fonds(cote="REV-2", titre="Temp")
    item = Item(fonds=fonds, cote="X")
    session.add_all([fonds, item])
    session.commit()
    item_id = item.id

    # Item.fonds_id porte ON DELETE CASCADE : supprimer le fonds
    # emporte ses items.
    session.delete(fonds)
    session.commit()

    assert session.get(Item, item_id) is None


def test_doi_nakala_roundtrip(session: Session) -> None:
    fonds = Fonds(cote="REV-DOI", titre="Revue avec DOI")
    Item(
        fonds=fonds,
        cote="N1",
        doi_nakala="10.34847/nkl.item_xyz",
        doi_collection_nakala="10.34847/nkl.coll_abc",
    )
    session.add(fonds)
    session.commit()

    fonds_relu = session.get(Fonds, fonds.id)
    assert fonds_relu is not None
    (item_relu,) = fonds_relu.items
    assert item_relu.doi_nakala == "10.34847/nkl.item_xyz"
    assert item_relu.doi_collection_nakala == "10.34847/nkl.coll_abc"


def test_descriptions_internes_et_responsable_archives(
    session: Session,
) -> None:
    """Les champs descriptifs et d'audit du fonds sont libres et mutables."""
    fonds = Fonds(
        cote="CHANTIER-1",
        titre="Revue en cours",
        description="Publication trimestrielle du XIXᵉ siècle.",
        description_interne=(
            "Chantier repris en 2026 ; cotes antérieures à 1870 à vérifier "
            "contre l'inventaire manuscrit."
        ),
        personnalite_associee="George Sand",
        responsable_archives="Marie Dupont",
        # Champs d'audit en texte libre (pas de FK Utilisateur).
        cree_par="Marie Dupont",
    )
    session.add(fonds)
    session.commit()

    relu = session.get(Fonds, fonds.id)
    assert relu is not None
    assert relu.description.startswith("Publication")
    assert relu.description_interne.startswith("Chantier repris")
    assert relu.personnalite_associee == "George Sand"
    assert relu.responsable_archives == "Marie Dupont"
    assert relu.cree_par == "Marie Dupont"

    # Les champs sont mutables sans contrainte.
    relu.responsable_archives = "Jean Martin"
    relu.description_interne = None
    relu.modifie_par = "Jean Martin"
    session.commit()
    rerelu = session.get(Fonds, fonds.id)
    assert rerelu.responsable_archives == "Jean Martin"
    assert rerelu.description_interne is None
    assert rerelu.modifie_par == "Jean Martin"


def test_fk_rejette_fonds_id_inexistant(session: Session) -> None:
    # Vérification directe que les FK sont *enforced* au niveau base,
    # pas uniquement au niveau ORM. Si les pragmas tombent, ce test
    # passe de rouge à vert silencieusement.
    session.add(Item(fonds_id=99999, cote="orphelin"))
    with pytest.raises(IntegrityError):
        session.commit()
