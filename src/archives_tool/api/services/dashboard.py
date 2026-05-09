"""Composition des vues : dashboard, page fonds, page collection, page item.

Quatre fonctions publiques :
- `composer_dashboard(db)` : `DashboardResume` (tous les fonds + transversales).
- `composer_page_fonds(db, cote)` : `FondsDetail` (un fonds, ses
  collections, items récents, collaborateurs groupés).
- `composer_page_collection(db, cote, fonds_id=None)` :
  `CollectionDetail` (une collection, ses items paginés, le fonds
  parent ou les fonds représentés si transversale).
- `composer_page_item(db, cote, fonds_id, fichier_courant_pos=1)` :
  `ItemDetail` (un item, ses fichiers, collections d'appartenance,
  fichier sélectionné dans la visionneuse).

Les compteurs et listings sont obtenus en agrégats SQL — pas de N+1.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from archives_tool.api.services.collaborateurs_fonds import (
    CollaborateurFondsResume,
    lister_collaborateurs_fonds_par_role,
)
from archives_tool.api.services.fonds import FondsIntrouvable
from archives_tool.api.services.items import ItemIntrouvable, ItemResume
from archives_tool.models import (
    Collection,
    Fichier,
    Fonds,
    Item,
    ItemCollection,
    RoleCollaborateur,
    TypeCollection,
)


@dataclass(frozen=True)
class CollectionResume:
    cote: str
    titre: str
    type_collection: str  # "miroir" ou "libre"
    nb_items: int
    fonds_id: int | None  # None pour transversale

    @property
    def est_miroir(self) -> bool:
        return self.type_collection == TypeCollection.MIROIR.value

    @property
    def est_transversale(self) -> bool:
        return self.fonds_id is None


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


# ---------------------------------------------------------------------------
# Page fonds (lecture)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FondsDetail:
    fonds: Fonds  # modèle ORM (le template lit ses champs métadonnées)
    nb_items: int
    collections_resume: tuple[CollectionResume, ...]
    items_recents: tuple[ItemResume, ...]
    collaborateurs_par_role: dict[RoleCollaborateur, list[CollaborateurFondsResume]]

    @property
    def miroir_resume(self) -> CollectionResume | None:
        """Référence directe à la miroir, sans dépendre de l'ordre du tri."""
        for c in self.collections_resume:
            if c.est_miroir:
                return c
        return None


def composer_page_fonds(db: Session, cote: str) -> FondsDetail:
    """Charge un fonds + ses collections + 10 items les plus récents
    + ses collaborateurs groupés par rôle.

    Lève `FondsIntrouvable` si la cote est inconnue.
    """
    fonds = db.scalar(select(Fonds).where(Fonds.cote == cote))
    if fonds is None:
        raise FondsIntrouvable(cote)

    nb_items = (
        db.scalar(select(func.count(Item.id)).where(Item.fonds_id == fonds.id)) or 0
    )

    collections_rows = list(
        db.scalars(
            select(Collection)
            .where(Collection.fonds_id == fonds.id)
            .order_by(Collection.titre)
        ).all()
    )
    nb_items_par_collection: dict[int, int] = dict(
        db.execute(
            select(ItemCollection.collection_id, func.count(ItemCollection.item_id))
            .where(
                ItemCollection.collection_id.in_([c.id for c in collections_rows])
            )
            .group_by(ItemCollection.collection_id)
        ).all()
    ) if collections_rows else {}

    # Miroir d'abord, puis les libres triées par titre.
    collections_resume = tuple(
        sorted(
            (
                CollectionResume(
                    cote=c.cote,
                    titre=c.titre,
                    type_collection=c.type_collection,
                    nb_items=nb_items_par_collection.get(c.id, 0),
                    fonds_id=c.fonds_id,
                )
                for c in collections_rows
            ),
            # Miroir d'abord (False < True), puis ordre alphabétique titre.
            key=lambda r: (r.type_collection != TypeCollection.MIROIR.value, r.titre),
        )
    )

    # « Récents » = ordre de modification effective si l'item a été
    # modifié, sinon ordre de création (le plus récent d'abord). Cote
    # DESC en tie-breaker pour offrir une vue stable et inversée.
    items_rows = list(
        db.scalars(
            select(Item)
            .where(Item.fonds_id == fonds.id)
            .order_by(
                func.coalesce(Item.modifie_le, Item.cree_le).desc(),
                Item.cote.desc(),
            )
            .limit(10)
        ).all()
    )
    items_recents = tuple(
        ItemResume(
            id=i.id,
            cote=i.cote,
            titre=i.titre,
            fonds_id=i.fonds_id,
            fonds_cote=fonds.cote,
            etat=i.etat_catalogage,
            date=i.date,
            annee=i.annee,
            type_coar=i.type_coar,
            modifie_le=i.modifie_le,
        )
        for i in items_rows
    )

    return FondsDetail(
        fonds=fonds,
        nb_items=nb_items,
        collections_resume=collections_resume,
        items_recents=items_recents,
        collaborateurs_par_role=lister_collaborateurs_fonds_par_role(db, fonds.id),
    )


# ---------------------------------------------------------------------------
# Page collection (lecture)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CollectionDetail:
    collection: Collection  # modèle ORM
    nb_items: int
    fonds_parent: Fonds | None  # None pour transversale
    fonds_representes: tuple[FondsRepresente, ...]  # vide si rattachée à un fonds

    @property
    def est_miroir(self) -> bool:
        return self.collection.type_collection == TypeCollection.MIROIR.value

    @property
    def est_transversale(self) -> bool:
        return self.collection.fonds_id is None

    @property
    def est_libre_rattachee(self) -> bool:
        return not self.est_miroir and not self.est_transversale


def composer_page_collection(
    db: Session, collection: Collection
) -> CollectionDetail:
    """Charge le contexte d'affichage d'une collection.

    `collection` doit déjà être chargée (la route fait le lookup +
    désambiguïsation, ce service ne re-lit pas la DB pour ça)."""
    nb_items = (
        db.scalar(
            select(func.count(ItemCollection.item_id)).where(
                ItemCollection.collection_id == collection.id
            )
        )
        or 0
    )

    fonds_parent: Fonds | None = None
    fonds_representes: tuple[FondsRepresente, ...] = ()

    if collection.fonds_id is not None:
        fonds_parent = db.get(Fonds, collection.fonds_id)
    else:
        # Transversale : agrégation des fonds représentés via JOIN.
        rows = db.execute(
            select(Fonds.cote, Fonds.titre)
            .join(Item, Item.fonds_id == Fonds.id)
            .join(ItemCollection, ItemCollection.item_id == Item.id)
            .where(ItemCollection.collection_id == collection.id)
            .distinct()
            .order_by(Fonds.titre)
        ).all()
        fonds_representes = tuple(
            FondsRepresente(cote=cote, titre=titre) for cote, titre in rows
        )

    return CollectionDetail(
        collection=collection,
        nb_items=nb_items,
        fonds_parent=fonds_parent,
        fonds_representes=fonds_representes,
    )


# ---------------------------------------------------------------------------
# Page item (lecture)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FichierResume:
    """Vue figée d'un fichier pour la page item — détache du modèle ORM."""

    id: int
    nom_fichier: str
    extension: str  # minuscules, sans le point
    type_page: str
    ordre: int
    taille_octets: int | None
    largeur_px: int | None
    hauteur_px: int | None
    format: str | None

    @property
    def dimensions(self) -> str | None:
        if self.largeur_px and self.hauteur_px:
            return f"{self.largeur_px}×{self.hauteur_px}"
        return None


@dataclass(frozen=True)
class CollectionAppartenance:
    cote: str
    titre: str
    type_collection: str  # miroir / libre
    fonds_id: int | None  # None si transversale
    fonds_cote: str | None  # cote du fonds parent (None si transversale)

    @property
    def est_miroir(self) -> bool:
        return self.type_collection == TypeCollection.MIROIR.value

    @property
    def est_transversale(self) -> bool:
        return self.fonds_id is None


@dataclass(frozen=True)
class ItemDetail:
    item: Item  # ORM (le template lit ses champs métadonnées)
    fonds: Fonds
    fichiers: tuple[FichierResume, ...]
    fichier_courant: FichierResume | None
    position_courante: int  # 1-indexed
    nb_fichiers: int
    collections: tuple[CollectionAppartenance, ...]


def _extension(nom_fichier: str) -> str:
    if "." in nom_fichier:
        return nom_fichier.rsplit(".", 1)[1].lower()
    return ""


def _resume_fichier(f: Fichier) -> FichierResume:
    return FichierResume(
        id=f.id,
        nom_fichier=f.nom_fichier,
        extension=_extension(f.nom_fichier),
        type_page=f.type_page,
        ordre=f.ordre,
        taille_octets=f.taille_octets,
        largeur_px=f.largeur_px,
        hauteur_px=f.hauteur_px,
        format=f.format,
    )


def composer_page_item(
    db: Session,
    cote: str,
    fonds_id: int,
    *,
    fichier_courant_pos: int = 1,
) -> ItemDetail:
    """Charge un item avec ses fichiers, collections d'appartenance et
    fichier courant. Lève `ItemIntrouvable` si la cote n'existe pas
    dans le fonds donné.

    Eager loading sur les fichiers (one-to-many ordonné). Les
    collections d'appartenance sont chargées via une requête JOIN
    distincte qui inclut la cote du fonds parent (None si transversale)
    — utile pour afficher les liens vers les bons fonds.
    """
    item = db.scalar(
        select(Item)
        .options(selectinload(Item.fichiers))
        .where(Item.cote == cote, Item.fonds_id == fonds_id)
    )
    if item is None:
        raise ItemIntrouvable(f"cote={cote!r} dans le fonds {fonds_id}")

    fonds = db.get(Fonds, fonds_id)
    assert fonds is not None  # garanti par la FK

    fichiers = tuple(_resume_fichier(f) for f in item.fichiers)
    nb_fichiers = len(fichiers)
    pos = max(1, min(fichier_courant_pos, nb_fichiers)) if nb_fichiers else 1
    fichier_courant = fichiers[pos - 1] if nb_fichiers else None

    rows = db.execute(
        select(
            Collection.cote,
            Collection.titre,
            Collection.type_collection,
            Collection.fonds_id,
            Fonds.cote.label("fonds_cote"),
        )
        .join(ItemCollection, ItemCollection.collection_id == Collection.id)
        .outerjoin(Fonds, Fonds.id == Collection.fonds_id)
        .where(ItemCollection.item_id == item.id)
        # Miroir d'abord, puis libres par titre.
        .order_by(
            (Collection.type_collection != TypeCollection.MIROIR.value),
            Collection.titre,
        )
    ).all()
    collections = tuple(
        CollectionAppartenance(
            cote=cote_c,
            titre=titre,
            type_collection=type_c,
            fonds_id=fonds_id_c,
            fonds_cote=fonds_cote,
        )
        for cote_c, titre, type_c, fonds_id_c, fonds_cote in rows
    )

    return ItemDetail(
        item=item,
        fonds=fonds,
        fichiers=fichiers,
        fichier_courant=fichier_courant,
        position_courante=pos,
        nb_fichiers=nb_fichiers,
        collections=collections,
    )
