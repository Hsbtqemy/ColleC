"""Tests des services de la vue collection."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from archives_tool.api.services.collection import (
    CollectionIntrouvable,
    collection_detail,
    lister_fichiers,
    lister_items,
    lister_sous_collections,
)
from archives_tool.models import (
    Collection,
    EtatCatalogage,
    Fichier,
    Item,
    PhaseChantier,
)


@pytest.fixture
def base_avec_arbre(session: Session) -> Session:
    parent = Collection(
        cote_collection="P",
        titre="Parent",
        phase=PhaseChantier.CATALOGAGE.value,
    )
    enfant = Collection(
        cote_collection="P-A",
        titre="Sous-coll A",
        parent=parent,
        phase=PhaseChantier.NUMERISATION.value,
    )
    session.add_all([parent, enfant])
    session.flush()
    items = [
        Item(
            collection_id=parent.id,
            cote=f"P-{i:03d}",
            titre=f"Item {i}",
            etat_catalogage=(
                EtatCatalogage.VALIDE.value if i < 2 else EtatCatalogage.BROUILLON.value
            ),
        )
        for i in range(3)
    ]
    session.add_all(items)
    session.flush()
    for it in items[:2]:
        session.add(
            Fichier(
                item_id=it.id,
                racine="s",
                chemin_relatif=f"{it.cote}.png",
                nom_fichier=f"{it.cote}.png",
                ordre=1,
            )
        )
    session.commit()
    return session


def test_collection_detail_repartition(base_avec_arbre: Session) -> None:
    detail = collection_detail(base_avec_arbre, "P")
    assert detail.cote == "P"
    assert detail.nb_items == 3
    assert detail.nb_fichiers == 2
    assert detail.nb_sous_collections == 1
    assert detail.repartition_etats == {"valide": 2, "brouillon": 1}
    assert detail.parent_cote is None


def test_collection_detail_avec_parent(base_avec_arbre: Session) -> None:
    detail = collection_detail(base_avec_arbre, "P-A")
    assert detail.parent_cote == "P"
    assert detail.parent_titre == "Parent"


def test_collection_introuvable(session: Session) -> None:
    with pytest.raises(CollectionIntrouvable):
        collection_detail(session, "N_EXISTE_PAS")


def test_lister_sous_collections(base_avec_arbre: Session) -> None:
    sous = lister_sous_collections(base_avec_arbre, "P")
    assert len(sous) == 1
    assert sous[0].cote == "P-A"
    assert sous[0].phase == PhaseChantier.NUMERISATION


def test_lister_items_tri_et_compteur(base_avec_arbre: Session) -> None:
    items = lister_items(base_avec_arbre, "P")
    assert [i.cote for i in items] == ["P-000", "P-001", "P-002"]
    assert items[0].nb_fichiers == 1
    assert items[2].nb_fichiers == 0


def test_lister_fichiers(base_avec_arbre: Session) -> None:
    fichiers = lister_fichiers(base_avec_arbre, "P")
    assert len(fichiers) == 2
    assert fichiers[0].item_cote == "P-000"
    assert fichiers[0].nom_fichier == "P-000.png"
