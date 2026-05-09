"""Helpers partagés par les exporters DC / Nakala / xlsx.

Centralise la logique de chargement « contexte d'export d'une
collection » : items + leur fonds d'origine + leurs fichiers, dans
un objet immuable consommé par les trois formats.

Sémantique d'export (V0.9.0-gamma.2) : on exporte **une collection**
au sens Nakala (miroir, libre rattachée, ou transversale). Le fonds
n'est jamais l'unité d'export — on exporte sa miroir si on veut tout.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from archives_tool.models import (
    Collection,
    Fonds,
    Item,
    ItemCollection,
    TypeCollection,
)


@dataclass(frozen=True)
class ItemPourExport:
    """Vue figée d'un item dans le contexte d'un export.

    Inclut le fonds d'origine pour les transversales (où chaque item
    peut venir d'un fonds différent).
    """

    item: Item
    fonds: Fonds

    @property
    def fonds_cote(self) -> str:
        return self.fonds.cote

    @property
    def fonds_titre(self) -> str:
        return self.fonds.titre


@dataclass(frozen=True)
class CollectionPourExport:
    """Vue figée d'une collection à exporter.

    `fonds_parent` : le fonds rattaché (None si transversale).
    `fonds_representes` : tuple des fonds dont les items proviennent
    (vide si rattachée — tous les items viennent du `fonds_parent`).
    `items` : tuple des items à exporter, triés par cote.
    """

    collection: Collection
    fonds_parent: Fonds | None
    fonds_representes: tuple[Fonds, ...]
    items: tuple[ItemPourExport, ...]

    @property
    def est_miroir(self) -> bool:
        return self.collection.type_collection == TypeCollection.MIROIR.value

    @property
    def est_transversale(self) -> bool:
        return self.collection.fonds_id is None


def composer_export(db: Session, collection: Collection) -> CollectionPourExport:
    """Charge le contexte d'export d'une collection.

    Une seule requête principale qui ramène les items + leurs fichiers
    + leur fonds. Les fonds représentés (utile pour les transversales)
    sont déduits côté Python — pas de second JOIN.

    Items triés par (fonds.cote, item.cote) : pour les rattachées
    c'est un tri par cote item ; pour les transversales, regroupe par
    fonds dans la sortie, ce qui est plus lisible.
    """
    rows = list(
        db.scalars(
            select(Item)
            .options(selectinload(Item.fichiers), selectinload(Item.fonds))
            .join(ItemCollection, ItemCollection.item_id == Item.id)
            .where(ItemCollection.collection_id == collection.id)
            .join(Fonds, Fonds.id == Item.fonds_id)
            .order_by(Fonds.cote, Item.cote)
        ).all()
    )

    items_export = tuple(ItemPourExport(item=it, fonds=it.fonds) for it in rows)

    fonds_parent: Fonds | None = None
    fonds_representes: tuple[Fonds, ...] = ()

    if collection.fonds_id is not None:
        fonds_parent = db.get(Fonds, collection.fonds_id)
    else:
        # Transversale : déduit l'ensemble des fonds représentés depuis
        # les items déjà chargés. Préserve l'ordre alphabétique de cote.
        seen: dict[int, Fonds] = {}
        for ipe in items_export:
            seen.setdefault(ipe.fonds.id, ipe.fonds)
        fonds_representes = tuple(
            sorted(seen.values(), key=lambda f: f.cote)
        )

    return CollectionPourExport(
        collection=collection,
        fonds_parent=fonds_parent,
        fonds_representes=fonds_representes,
        items=items_export,
    )
