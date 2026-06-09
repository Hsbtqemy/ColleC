"""Tests du service cache + réconciliation Nakala (P1b)."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from archives_tool.api.services.items import FormulaireItem, creer_item
from archives_tool.api.services.nakala import (
    TYPE_RELATION_DEPOT,
    mettre_en_cache_depot,
    reconcilier_item,
    source_nakala,
    upsert_ressource,
)
from archives_tool.external.nakala.mapper import DepotNakala
from archives_tool.models import (
    Fonds,
    Item,
    LienExterneItem,
    RessourceExterne,
    SourceExterne,
)

_DOI = "10.34847/nkl.abcdef12"


def _depot(identifiant: str = _DOI, titre: str = "Titre") -> DepotNakala:
    return DepotNakala(
        identifiant=identifiant,
        statut="published",
        titre=titre,
        createurs=["Topor, Roland"],
        date="1969-09",
        type_coar="http://purl.org/coar/resource_type/c_2fe3",
        langues=["fra"],
        description="desc",
        sujets=["satire"],
        licence="CC-BY-4.0",
    )


def _item_avec_doi(session: Session, fonds: Fonds, cote: str, doi: str) -> Item:
    item = creer_item(session, FormulaireItem(cote=cote, titre="X", fonds_id=fonds.id))
    item.doi_nakala = doi
    session.commit()
    return item


# ---------------------------------------------------------------------------
# source_nakala
# ---------------------------------------------------------------------------


def test_source_nakala_idempotent(session: Session) -> None:
    s1 = source_nakala(session)
    s2 = source_nakala(session)
    assert s1.id == s2.id
    assert s1.code == "nakala"
    assert session.scalar(select(func.count(SourceExterne.id))) == 1


# ---------------------------------------------------------------------------
# upsert_ressource
# ---------------------------------------------------------------------------


def test_upsert_ressource_insert_puis_update(session: Session) -> None:
    source = source_nakala(session)
    r1 = upsert_ressource(session, source, _depot(titre="V1"), {"v": 1})
    premier_recup = r1.recupere_le
    assert r1.titre == "V1"
    assert r1.metadonnees_brutes == {"v": 1}
    assert r1.auteurs == ["Topor, Roland"]

    # Re-pull même DOI → met à jour, ne duplique pas.
    r2 = upsert_ressource(session, source, _depot(titre="V2"), {"v": 2})
    assert r2.id == r1.id
    assert r2.titre == "V2"
    assert r2.metadonnees_brutes == {"v": 2}
    assert r2.recupere_le >= premier_recup  # bumpé
    assert session.scalar(select(func.count(RessourceExterne.id))) == 1


# ---------------------------------------------------------------------------
# reconcilier_item
# ---------------------------------------------------------------------------


def test_reconcilier_cree_lien_si_item_de_meme_doi(
    session: Session, fonds_hk: Fonds
) -> None:
    item = _item_avec_doi(session, fonds_hk, "HK-001", _DOI)
    source = source_nakala(session)
    ressource = upsert_ressource(session, source, _depot(), {})

    lie = reconcilier_item(session, ressource, cree_par="Marie")
    assert lie is not None and lie.id == item.id
    lien = session.scalar(select(LienExterneItem))
    assert lien.item_id == item.id
    assert lien.ressource_externe_id == ressource.id
    assert lien.type_relation == TYPE_RELATION_DEPOT
    assert lien.cree_par == "Marie"

    # Idempotent : 2e appel ne duplique pas le lien.
    reconcilier_item(session, ressource)
    assert session.scalar(select(func.count(LienExterneItem.id))) == 1


def test_reconcilier_sans_item_retourne_none(session: Session) -> None:
    source = source_nakala(session)
    ressource = upsert_ressource(session, source, _depot(), {})
    assert reconcilier_item(session, ressource) is None
    assert session.scalar(select(func.count(LienExterneItem.id))) == 0


# ---------------------------------------------------------------------------
# mettre_en_cache_depot (end-to-end)
# ---------------------------------------------------------------------------


def test_mettre_en_cache_end_to_end_avec_item(
    session: Session, fonds_hk: Fonds
) -> None:
    item = _item_avec_doi(session, fonds_hk, "HK-001", _DOI)
    ressource, lie = mettre_en_cache_depot(
        session, _depot(), {"identifier": _DOI}, cree_par="Jean"
    )
    assert lie is not None and lie.id == item.id
    assert ressource.identifiant_externe == _DOI
    assert session.scalar(select(func.count(SourceExterne.id))) == 1
    assert session.scalar(select(func.count(RessourceExterne.id))) == 1
    assert session.scalar(select(func.count(LienExterneItem.id))) == 1


def test_mettre_en_cache_sans_item_correspondant(session: Session) -> None:
    ressource, lie = mettre_en_cache_depot(session, _depot(), {"identifier": _DOI})
    assert lie is None
    assert ressource.identifiant_externe == _DOI  # caché quand même
    assert session.scalar(select(func.count(LienExterneItem.id))) == 0
