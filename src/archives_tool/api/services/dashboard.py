"""Composition du dashboard : fonds + collections rattachées + transversales.

Une seule fonction publique `composer_dashboard(db)` retourne un
`DashboardResume` prêt à être consommé par le template. Les
compteurs sont obtenus en 3 agrégats SQL (par fonds, par collection,
par fonds-représenté-dans-une-transversale) — pas de N+1.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from archives_tool.models import (
    Collection,
    Fonds,
    Item,
    ItemCollection,
    TypeCollection,
)


@dataclass(frozen=True)
class CollectionResume:
    cote: str
    titre: str
    type_collection: str  # "miroir" ou "libre"
    nb_items: int
    fonds_id: int | None  # None pour transversale


@dataclass(frozen=True)
class FondsRepresente:
    cote: str
    titre: str


@dataclass(frozen=True)
class TransversaleResume:
    cote: str
    titre: str
    nb_items: int
    fonds_representes: tuple[FondsRepresente, ...]


@dataclass(frozen=True)
class FondsArborescence:
    """Vue arborescente d'un fonds pour le dashboard : ses compteurs +
    sa miroir + ses libres rattachées.

    Distinct de `services.fonds.FondsResume` qui sert le listing
    table simple — les deux entités ont des shapes différents. La
    confusion serait subtile, le nom `FondsArborescence` la prévient.
    """

    cote: str
    titre: str
    nb_items: int
    collection_miroir: CollectionResume | None
    collections_libres: tuple[CollectionResume, ...]


@dataclass(frozen=True)
class DashboardResume:
    fonds: tuple[FondsArborescence, ...]
    transversales: tuple[TransversaleResume, ...]

    @property
    def nb_fonds(self) -> int:
        return len(self.fonds)

    @property
    def nb_transversales(self) -> int:
        return len(self.transversales)


def composer_dashboard(db: Session) -> DashboardResume:
    """Charge fonds + collections + transversales en agrégats SQL.

    Coût indépendant du nombre de fonds : ~4-5 queries (select Fonds,
    select Collection, GROUP BY items par fonds, GROUP BY items par
    collection, plus un join pour les fonds représentés dans les
    transversales — uniquement si ≥1 transversale).
    """
    fonds_rows = list(db.scalars(select(Fonds).order_by(Fonds.cote)).all())
    collection_rows = list(db.scalars(select(Collection).order_by(Collection.titre)).all())

    nb_items_par_fonds: dict[int, int] = dict(
        db.execute(
            select(Item.fonds_id, func.count(Item.id)).group_by(Item.fonds_id)
        ).all()
    )
    nb_items_par_collection: dict[int, int] = dict(
        db.execute(
            select(ItemCollection.collection_id, func.count(ItemCollection.item_id))
            .group_by(ItemCollection.collection_id)
        ).all()
    )

    # Index des collections par fonds_id pour l'attache rapide.
    collections_par_fonds: dict[int | None, list[Collection]] = {}
    for c in collection_rows:
        collections_par_fonds.setdefault(c.fonds_id, []).append(c)

    fonds_resumes: list[FondsArborescence] = []
    for f in fonds_rows:
        cols = collections_par_fonds.get(f.id, [])
        miroir: CollectionResume | None = None
        libres: list[CollectionResume] = []
        for c in cols:
            resume = CollectionResume(
                cote=c.cote,
                titre=c.titre,
                type_collection=c.type_collection,
                nb_items=nb_items_par_collection.get(c.id, 0),
                fonds_id=c.fonds_id,
            )
            if c.type_collection == TypeCollection.MIROIR.value:
                miroir = resume
            else:
                libres.append(resume)
        fonds_resumes.append(
            FondsArborescence(
                cote=f.cote,
                titre=f.titre,
                nb_items=nb_items_par_fonds.get(f.id, 0),
                collection_miroir=miroir,
                collections_libres=tuple(libres),
            )
        )

    # Transversales : collections sans fonds_id. Pour chacune, lister
    # les fonds dont elles tirent leurs items via ItemCollection ⨝ Item.
    transversales_rows = [c for c in collection_rows if c.fonds_id is None]
    fonds_par_transv: dict[int, list[FondsRepresente]] = {}
    if transversales_rows:
        transv_ids = [c.id for c in transversales_rows]
        rows = db.execute(
            select(ItemCollection.collection_id, Fonds.cote, Fonds.titre)
            .join(Item, Item.id == ItemCollection.item_id)
            .join(Fonds, Fonds.id == Item.fonds_id)
            .where(ItemCollection.collection_id.in_(transv_ids))
            .distinct()
        ).all()
        for col_id, cote, titre in rows:
            fonds_par_transv.setdefault(col_id, []).append(
                FondsRepresente(cote=cote, titre=titre)
            )
        for liste in fonds_par_transv.values():
            liste.sort(key=lambda f: f.titre)

    transversales: list[TransversaleResume] = [
        TransversaleResume(
            cote=c.cote,
            titre=c.titre,
            nb_items=nb_items_par_collection.get(c.id, 0),
            fonds_representes=tuple(fonds_par_transv.get(c.id, [])),
        )
        for c in transversales_rows
    ]

    return DashboardResume(
        fonds=tuple(fonds_resumes),
        transversales=tuple(transversales),
    )
