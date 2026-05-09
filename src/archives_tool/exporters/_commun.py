"""Helpers partagés par les exporters DC / Nakala / xlsx.

Centralise la logique de chargement « contexte d'export d'une
collection » : items + leur fonds d'origine + leurs fichiers, dans
un objet immuable consommé par les trois formats.

Sémantique d'export : on exporte **une collection** au sens Nakala
(miroir, libre rattachée, ou transversale). Le fonds n'est jamais
l'unité d'export — on exporte sa miroir si on veut tout.
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
    peut venir d'un fonds différent). Accès direct via `ipe.fonds.cote`,
    `ipe.fonds.titre` etc. — pas de property d'indirection.
    """

    item: Item
    fonds: Fonds


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

    Une seule requête principale (Item + JOIN ItemCollection + JOIN
    Fonds pour le tri) plus deux SELECT IN(...) émis par selectinload
    pour `fichiers` et `fonds` — pas de N+1.

    Items triés par (fonds.cote, item.cote) : pour les rattachées
    c'est un tri par cote item ; pour les transversales, regroupe par
    fonds dans la sortie, ce qui est plus lisible.
    """
    items_orm = list(
        db.scalars(
            select(Item)
            .options(selectinload(Item.fichiers), selectinload(Item.fonds))
            .join(ItemCollection, ItemCollection.item_id == Item.id)
            .where(ItemCollection.collection_id == collection.id)
            .join(Fonds, Fonds.id == Item.fonds_id)
            .order_by(Fonds.cote, Item.cote)
        ).all()
    )
    items_export = tuple(ItemPourExport(item=it, fonds=it.fonds) for it in items_orm)

    fonds_parent: Fonds | None = None
    fonds_representes: tuple[Fonds, ...] = ()

    if collection.fonds_id is not None:
        # Pour une rattachée non vide, le fonds est déjà chargé via
        # selectinload(Item.fonds). On évite un db.get supplémentaire ;
        # le fallback couvre le cas (rare) d'une rattachée sans items.
        fonds_parent = (
            items_export[0].fonds
            if items_export
            else db.get(Fonds, collection.fonds_id)
        )
    else:
        seen: dict[int, Fonds] = {}
        for ipe in items_export:
            seen.setdefault(ipe.fonds.id, ipe.fonds)
        fonds_representes = tuple(sorted(seen.values(), key=lambda f: f.cote))

    return CollectionPourExport(
        collection=collection,
        fonds_parent=fonds_parent,
        fonds_representes=fonds_representes,
        items=items_export,
    )
