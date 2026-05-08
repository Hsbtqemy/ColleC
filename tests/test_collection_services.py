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
    listage = lister_items(base_avec_arbre, "P")
    assert listage.tri == "cote"
    assert listage.ordre == "asc"
    assert [i.cote for i in listage.items] == ["P-000", "P-001", "P-002"]
    assert listage.items[0].nb_fichiers == 1
    assert listage.items[2].nb_fichiers == 0
    assert listage.total == 3
    assert listage.pages == 1


def test_lister_items_tri_invalide_retombe_par_defaut(
    base_avec_arbre: Session,
) -> None:
    listage = lister_items(base_avec_arbre, "P", tri="injection", ordre="bad")
    assert listage.tri == "cote"
    assert listage.ordre == "asc"


def test_lister_items_tri_par_etat_desc(base_avec_arbre: Session) -> None:
    listage = lister_items(base_avec_arbre, "P", tri="etat", ordre="desc")
    assert listage.tri == "etat"
    assert listage.ordre == "desc"


def test_lister_items_pagination(base_avec_arbre: Session) -> None:
    page1 = lister_items(base_avec_arbre, "P", page=1, par_page=2)
    assert len(page1.items) == 2
    assert page1.total == 3
    assert page1.pages == 2
    page2 = lister_items(base_avec_arbre, "P", page=2, par_page=2)
    assert len(page2.items) == 1


def test_lister_fichiers(base_avec_arbre: Session) -> None:
    listage = lister_fichiers(base_avec_arbre, "P")
    assert len(listage.items) == 2
    assert listage.items[0].item_cote == "P-000"
    assert listage.items[0].nom_fichier == "P-000.png"
    assert listage.tri == "item"
    assert listage.total == 2


def test_lister_fichiers_pagination(base_avec_arbre: Session) -> None:
    page1 = lister_fichiers(base_avec_arbre, "P", page=1, par_page=1)
    assert len(page1.items) == 1
    assert page1.total == 2
    assert page1.pages == 2


def test_filtres_items_par_etat(base_avec_arbre: Session) -> None:
    listage = lister_items(base_avec_arbre, "P", etat=["valide"])
    assert {i.etat for i in listage.items} == {"valide"}
    assert listage.filtres["etat"] == ["valide"]
    assert listage.nb_filtres_actifs == 1


def test_filtres_items_etat_inconnu_ignore(base_avec_arbre: Session) -> None:
    listage = lister_items(base_avec_arbre, "P", etat=["nimporte_quoi"])
    # L'état inconnu est silencieusement ignoré : aucun filtre appliqué.
    assert "etat" not in listage.filtres
    assert listage.total == 3


def test_filtres_items_recherche_titre(base_avec_arbre: Session) -> None:
    listage = lister_items(base_avec_arbre, "P", q="Item 1")
    assert all("Item 1" in (i.titre or "") for i in listage.items)


def test_filtres_fichiers_par_q(base_avec_arbre: Session) -> None:
    from archives_tool.api.services.collection import lister_fichiers as lf

    listage = lf(base_avec_arbre, "P", q="P-000")
    assert all("P-000" in f.nom_fichier for f in listage.items)
