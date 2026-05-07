"""Vue collection : détail + listings des trois onglets."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from archives_tool.models import (
    Collection,
    EtatCatalogage,
    EtatFichier,
    Fichier,
    Item,
    PhaseChantier,
)


class CollectionIntrouvable(LookupError):
    """La cote demandée n'existe pas en base."""


@dataclass
class CollectionDetail:
    id: int
    cote: str
    titre: str
    titre_secondaire: str | None
    editeur: str | None
    lieu_edition: str | None
    periodicite: str | None
    date_debut: str | None
    date_fin: str | None
    issn: str | None
    doi_nakala: str | None
    description: str | None
    description_interne: str | None
    auteur_principal: str | None
    phase: PhaseChantier
    parent_cote: str | None
    parent_titre: str | None
    nb_sous_collections: int
    nb_items: int
    nb_fichiers: int
    repartition_etats: dict[str, int] = field(default_factory=dict)


@dataclass
class SousCollectionResume:
    id: int
    cote: str
    titre: str
    phase: PhaseChantier
    nb_items: int
    nb_fichiers: int


@dataclass
class ItemResume:
    id: int
    cote: str
    titre: str | None
    date: str | None
    annee: int | None
    etat: EtatCatalogage
    nb_fichiers: int
    modifie_le: datetime | None


@dataclass
class FichierResume:
    id: int
    item_cote: str
    nom_fichier: str
    ordre: int
    type_page: str
    folio: str | None
    taille_octets: int | None
    largeur_px: int | None
    hauteur_px: int | None
    derive_genere: bool
    etat: EtatFichier


def _charger_collection(session: Session, cote: str) -> Collection:
    col = session.scalar(select(Collection).where(Collection.cote_collection == cote))
    if col is None:
        raise CollectionIntrouvable(cote)
    return col


def collection_detail(session: Session, cote: str) -> CollectionDetail:
    col = _charger_collection(session, cote)

    nb_items = (
        session.scalar(select(func.count(Item.id)).where(Item.collection_id == col.id))
        or 0
    )
    nb_fichiers = (
        session.scalar(
            select(func.count(Fichier.id))
            .join(Item, Fichier.item_id == Item.id)
            .where(Item.collection_id == col.id)
        )
        or 0
    )
    nb_sous_collections = (
        session.scalar(
            select(func.count(Collection.id)).where(Collection.parent_id == col.id)
        )
        or 0
    )

    repartition: dict[str, int] = {}
    for etat, n in session.execute(
        select(Item.etat_catalogage, func.count(Item.id))
        .where(Item.collection_id == col.id)
        .group_by(Item.etat_catalogage)
    ).all():
        repartition[etat] = n

    return CollectionDetail(
        id=col.id,
        cote=col.cote_collection,
        titre=col.titre,
        titre_secondaire=col.titre_secondaire,
        editeur=col.editeur,
        lieu_edition=col.lieu_edition,
        periodicite=col.periodicite,
        date_debut=col.date_debut,
        date_fin=col.date_fin,
        issn=col.issn,
        doi_nakala=col.doi_nakala,
        description=col.description,
        description_interne=col.description_interne,
        auteur_principal=col.auteur_principal,
        phase=PhaseChantier(col.phase),
        parent_cote=col.parent.cote_collection if col.parent else None,
        parent_titre=col.parent.titre if col.parent else None,
        nb_sous_collections=nb_sous_collections,
        nb_items=nb_items,
        nb_fichiers=nb_fichiers,
        repartition_etats=repartition,
    )


def lister_sous_collections(session: Session, cote: str) -> list[SousCollectionResume]:
    col = _charger_collection(session, cote)
    enfants = list(
        session.scalars(
            select(Collection)
            .where(Collection.parent_id == col.id)
            .order_by(Collection.cote_collection)
        ).all()
    )
    if not enfants:
        return []

    ids = [e.id for e in enfants]
    items_par_col = dict(
        session.execute(
            select(Item.collection_id, func.count(Item.id))
            .where(Item.collection_id.in_(ids))
            .group_by(Item.collection_id)
        ).all()
    )
    fichiers_par_col = dict(
        session.execute(
            select(Item.collection_id, func.count(Fichier.id))
            .join(Fichier, Fichier.item_id == Item.id)
            .where(Item.collection_id.in_(ids))
            .group_by(Item.collection_id)
        ).all()
    )

    return [
        SousCollectionResume(
            id=e.id,
            cote=e.cote_collection,
            titre=e.titre,
            phase=PhaseChantier(e.phase),
            nb_items=items_par_col.get(e.id, 0),
            nb_fichiers=fichiers_par_col.get(e.id, 0),
        )
        for e in enfants
    ]


def lister_items(session: Session, cote: str) -> list[ItemResume]:
    col = _charger_collection(session, cote)
    items = list(
        session.scalars(
            select(Item).where(Item.collection_id == col.id).order_by(Item.cote)
        ).all()
    )
    if not items:
        return []

    nb_fichiers_par_item = dict(
        session.execute(
            select(Fichier.item_id, func.count(Fichier.id))
            .where(Fichier.item_id.in_([i.id for i in items]))
            .group_by(Fichier.item_id)
        ).all()
    )

    return [
        ItemResume(
            id=it.id,
            cote=it.cote,
            titre=it.titre,
            date=it.date,
            annee=it.annee,
            etat=EtatCatalogage(it.etat_catalogage),
            nb_fichiers=nb_fichiers_par_item.get(it.id, 0),
            modifie_le=it.modifie_le,
        )
        for it in items
    ]


def lister_fichiers(session: Session, cote: str) -> list[FichierResume]:
    col = _charger_collection(session, cote)
    rows = list(
        session.execute(
            select(Fichier, Item.cote)
            .join(Item, Fichier.item_id == Item.id)
            .where(Item.collection_id == col.id)
            .order_by(Item.cote, Fichier.ordre)
        ).all()
    )
    return [
        FichierResume(
            id=f.id,
            item_cote=item_cote,
            nom_fichier=f.nom_fichier,
            ordre=f.ordre,
            type_page=f.type_page,
            folio=f.folio,
            taille_octets=f.taille_octets,
            largeur_px=f.largeur_px,
            hauteur_px=f.hauteur_px,
            derive_genere=f.derive_genere,
            etat=EtatFichier(f.etat),
        )
        for f, item_cote in rows
    ]
