"""Composition des vues : dashboard, page fonds, page collection, page item.

Quatre fonctions publiques :
- `composer_dashboard(db)` : `DashboardResume` (tous les fonds + transversales).
- `composer_page_fonds(db, cote)` : `FondsDetail` (un fonds, ses
  collections, items récents, collaborateurs groupés).
- `composer_page_collection(db, cote, fonds_id=None)` :
  `CollectionDetail` (une collection, ses items paginés, le fonds
  parent ou les fonds représentés si transversale).
- `composer_page_item(db, cote, fonds, fichier_courant_pos=1)` :
  `ItemDetail` (un item, ses fichiers, collections d'appartenance,
  fichier sélectionné dans la visionneuse).

Les compteurs et listings sont obtenus en agrégats SQL — pas de N+1.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from archives_tool.affichage.formatters import temps_relatif
from archives_tool.api.services.collaborateurs_fonds import (
    CollaborateurFondsResume,
    lister_collaborateurs_fonds_par_role,
)
from archives_tool.api.services.fonds import FondsIntrouvable
from archives_tool.api.services.items import ItemIntrouvable, ItemResume
from archives_tool.api.services.sources_image import (
    SourceImage,
    resoudre_source_image,
)
from archives_tool.models import (
    ChampPersonnalise,
    Collection,
    EtatCatalogage,
    Fichier,
    Fonds,
    Item,
    ItemCollection,
    RoleCollaborateur,
    TypeCollection,
)

# Clés de répartition des états de catalogage utilisées par le composant
# `avancement.html`. L'ordre n'a pas d'importance ici (le template les
# itère lui-même dans son ordre de présentation), mais on garantit que
# toutes les clés sont présentes (à 0) pour éviter les `KeyError`
# côté Jinja.
_ETATS_REPARTITION: tuple[str, ...] = tuple(e.value for e in EtatCatalogage)


def _repartition_vide() -> dict[str, int]:
    return {k: 0 for k in _ETATS_REPARTITION}


@dataclass(frozen=True)
class CollectionResume:
    cote: str
    titre: str
    type_collection: str  # "miroir" ou "libre"
    nb_items: int
    fonds_id: int | None  # None pour transversale
    nb_fichiers: int = 0
    href: str = ""
    repartition_etats: dict[str, int] = field(default_factory=_repartition_vide)
    modifie_par: str | None = None
    modifie_le: datetime | None = None
    phase: str | None = None  # PhaseChantier (libelle court côté Collection)

    @property
    def est_miroir(self) -> bool:
        return self.type_collection == TypeCollection.MIROIR.value

    @property
    def est_transversale(self) -> bool:
        return self.fonds_id is None

    # ---- Contrat avec la macro `tableau_collections` ----------------
    # La macro Jinja accède à : cote, titre, phase, sous_collections,
    # nb_items, nb_fichiers, repartition, modifie_par, modifie_depuis,
    # href. Les 4 derniers (sous_collections, repartition, modifie_depuis,
    # plus l'absence de `repartition_etats` dans la macro) sont exposés
    # via les @property ci-dessous pour servir une seule classe sur les
    # deux contextes (vue arborescence dashboard + vue tableau page Fonds).
    # Si la macro change (rename d'attribut), seul un test d'intégration
    # de la route `/fonds/{cote}` le remontera — il en existe un.

    @property
    def repartition(self) -> dict[str, int]:
        return self.repartition_etats

    @property
    def modifie_depuis(self) -> str:
        return temps_relatif(self.modifie_le)

    @property
    def sous_collections(self) -> int:
        # Le modèle V0.9.0 est plat (pas de Collection.parent_id) ;
        # toujours 0. La macro accepte 0 sans rendre la mention.
        return 0


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
    repartition_etats: dict[str, int] = field(default_factory=_repartition_vide)
    modifie_par: str | None = None
    modifie_le: datetime | None = None
    phase: str | None = None


@dataclass(frozen=True)
class FondsArborescence:
    """Vue arborescente d'un fonds pour le dashboard : ses compteurs +
    sa miroir + ses libres rattachées + traçabilité.

    Distinct de `services.fonds.FondsResume` qui sert le listing
    table simple — les deux entités ont des shapes différents. La
    confusion serait subtile, le nom `FondsArborescence` la prévient.
    """

    cote: str
    titre: str
    nb_items: int
    collection_miroir: CollectionResume | None
    collections_libres: tuple[CollectionResume, ...]
    nb_fichiers: int = 0
    repartition_etats: dict[str, int] = field(default_factory=_repartition_vide)
    modifie_par: str | None = None
    modifie_le: datetime | None = None

    # ---- Contrat avec la macro `tableau_collections` ---------------
    # Le dashboard rend chaque fonds comme une rangée du tableau ; les
    # @property ci-dessous projettent les champs internes sur le schéma
    # attendu par la macro (cote, titre, phase, sous_collections,
    # nb_items, nb_fichiers, repartition, modifie_par, modifie_depuis,
    # href). Cohérent avec le contrat déjà exposé par CollectionResume.

    @property
    def href(self) -> str:
        return f"/fonds/{self.cote}"

    @property
    def phase(self) -> str | None:
        # Les fonds ne portent pas de phase (c'est une notion collection).
        return None

    @property
    def sous_collections(self) -> int:
        n = len(self.collections_libres)
        if self.collection_miroir is not None:
            n += 1
        return n

    @property
    def repartition(self) -> dict[str, int]:
        return self.repartition_etats

    @property
    def modifie_depuis(self) -> str:
        return temps_relatif(self.modifie_le)


@dataclass(frozen=True)
class DashboardStats:
    """Compteurs globaux affichés en haut du dashboard."""

    nb_fonds: int
    nb_collections: int  # toutes confondues (miroirs + libres + transversales)
    nb_items: int
    nb_fichiers: int
    nb_items_valides: int

    @property
    def pct_valides(self) -> float:
        return (self.nb_items_valides / self.nb_items * 100) if self.nb_items else 0.0


@dataclass(frozen=True)
class ActiviteRecente:
    """Dernière modification d'une entité, pour le bandeau d'activité."""

    type: Literal["item", "collection", "fonds"]
    cote: str
    titre: str
    fonds_cote: (
        str | None
    )  # cote du fonds parent pour les items et collections rattachées
    modifie_par: str | None
    modifie_le: datetime


@dataclass(frozen=True)
class DashboardResume:
    fonds: tuple[FondsArborescence, ...]
    transversales: tuple[TransversaleResume, ...]
    stats: DashboardStats
    activite_recente: tuple[ActiviteRecente, ...]


def _plus_recent(
    le_a: datetime | None,
    par_a: str | None,
    le_b: datetime | None,
    par_b: str | None,
) -> tuple[datetime | None, str | None]:
    """Retourne `(le, par)` du tuple le plus récent — utile pour fusionner
    la modif propre d'une entité avec la modif d'une de ses sous-entités
    (par ex. fonds vs son dernier item modifié) sans perdre `par`.

    Si les deux dates sont None, retourne `(None, None)`. Si une seule
    est définie, retourne le couple correspondant. À égalité parfaite,
    on prend `a` (priorité au caller-supplied first argument).
    """
    if le_a is None and le_b is None:
        return None, None
    if le_b is None:
        return le_a, par_a
    if le_a is None or le_a < le_b:
        return le_b, par_b
    return le_a, par_a


def _agreger_repartition(
    rows: list[tuple[int | None, str, int]],
) -> dict[int | None, dict[str, int]]:
    """Convertit un résultat `(group_key, etat, count)` en dict imbriqué
    `{group_key: {etat: count, …}}` avec toutes les clés `_ETATS_REPARTITION`
    présentes (à 0)."""
    par_groupe: dict[int | None, dict[str, int]] = {}
    for cle, etat, n in rows:
        cible = par_groupe.setdefault(cle, _repartition_vide())
        if etat in cible:
            cible[etat] = n
    return par_groupe


def _tracabilite_fusionnee_avec_dernier_item(
    db: Session,
    *,
    portee_items,
    propre_le: datetime | None,
    propre_par: str | None,
) -> tuple[datetime | None, str | None]:
    """Pour une entité (fonds ou collection), fusionne sa propre
    dernière modif avec celle du plus récent de ses items, en
    propageant `modifie_par`.

    `portee_items` est un filtre SQLAlchemy (par ex.
    `Item.fonds_id == X` ou `Item.id.in_(...)`). 1 query émise.
    """
    derniere = db.execute(
        select(Item.modifie_le, Item.modifie_par)
        .where(portee_items, Item.modifie_le.is_not(None))
        .order_by(Item.modifie_le.desc())
        .limit(1)
    ).first()
    if derniere is None:
        return propre_le, propre_par
    return _plus_recent(propre_le, propre_par, derniere[0], derniere[1])


def composer_dashboard(db: Session) -> DashboardResume:
    """Charge fonds + collections + transversales + stats globales +
    activité récente en agrégats SQL.

    Coût indépendant du nombre de fonds : ~9-10 queries quel que soit
    le volume (un seul GROUP BY par dimension métier). Les boucles
    Python ne font qu'attacher les agrégats préalablement calculés.
    """
    fonds_rows = list(db.scalars(select(Fonds).order_by(Fonds.cote)).all())
    collection_rows = list(
        db.scalars(select(Collection).order_by(Collection.titre)).all()
    )

    # ---- Répartitions d'états (1 query par dimension) ---------------
    # Les compteurs `nb_items` par fonds / par collection sont dérivés
    # directement des répartitions (somme sur les états), pas
    # re-querysés.
    repartition_par_fonds = _agreger_repartition(
        [
            (fonds_id, etat, n)
            for fonds_id, etat, n in db.execute(
                select(
                    Item.fonds_id, Item.etat_catalogage, func.count(Item.id)
                ).group_by(Item.fonds_id, Item.etat_catalogage)
            ).all()
        ]
    )
    repartition_par_collection = _agreger_repartition(
        [
            (col_id, etat, n)
            for col_id, etat, n in db.execute(
                select(
                    ItemCollection.collection_id,
                    Item.etat_catalogage,
                    func.count(Item.id),
                )
                .join(Item, Item.id == ItemCollection.item_id)
                .group_by(ItemCollection.collection_id, Item.etat_catalogage)
            ).all()
        ]
    )

    nb_items_par_fonds: dict[int, int] = {
        fid: sum(rep.values()) for fid, rep in repartition_par_fonds.items()
    }
    nb_items_par_collection: dict[int, int] = {
        cid: sum(rep.values()) for cid, rep in repartition_par_collection.items()
    }

    # ---- Dernière modification d'un item par fonds : on garde le
    # tuple (modifie_le, modifie_par) du plus récent — pour pouvoir
    # afficher « modifié par Marie · il y a 2h » sur la carte fonds
    # même quand le timestamp le plus récent vient d'un de ses items.
    # 1 query : on récupère tous les couples (fonds_id, le, par)
    # triés par date DESC, et on garde le premier vu par fonds.
    max_modif_item_par_fonds: dict[int, tuple[datetime, str | None]] = {}
    for fid, le, par in db.execute(
        select(Item.fonds_id, Item.modifie_le, Item.modifie_par)
        .where(Item.modifie_le.is_not(None))
        .order_by(Item.modifie_le.desc())
    ).all():
        if fid not in max_modif_item_par_fonds:
            max_modif_item_par_fonds[fid] = (le, par)

    # ---- nb_fichiers par fonds (GROUP BY Fichier ⨝ Item, pas N+1).
    # Item.fonds_id est NOT NULL, donc le total global se dérive de
    # la somme du dict — pas besoin d'une seconde requête COUNT(*).
    nb_fichiers_par_fonds: dict[int, int] = dict(
        db.execute(
            select(Item.fonds_id, func.count(Fichier.id))
            .join(Fichier, Fichier.item_id == Item.id)
            .group_by(Item.fonds_id)
        ).all()
    )
    nb_fichiers: int = sum(nb_fichiers_par_fonds.values())
    # nb_items_valides se dérive de repartition_par_fonds en sommant
    # l'état VALIDE par fonds — pas de requête supplémentaire.
    nb_items_valides = sum(
        rep.get(EtatCatalogage.VALIDE.value, 0)
        for rep in repartition_par_fonds.values()
    )

    nb_items_total = sum(nb_items_par_fonds.values())
    stats = DashboardStats(
        nb_fonds=len(fonds_rows),
        nb_collections=len(collection_rows),
        nb_items=nb_items_total,
        nb_fichiers=nb_fichiers,
        nb_items_valides=nb_items_valides,
    )

    # ---- Index collections par fonds_id pour l'attache rapide.
    collections_par_fonds: dict[int | None, list[Collection]] = {}
    for c in collection_rows:
        collections_par_fonds.setdefault(c.fonds_id, []).append(c)

    def _modifie_de_collection(c: Collection) -> tuple[str | None, datetime | None]:
        """Pour une collection, prend le plus récent de sa propre modif
        et de la dernière modif d'un de ses items."""
        # Dernière modif d'item pour cette collection : on a déjà la
        # répartition par collection mais pas le timestamp. Chercher
        # par requête ciblée serait un N+1 ; on s'appuie ici sur
        # `Collection.modifie_le` seulement (la modif d'un item se
        # reflète sur le fonds, pas sur les collections).
        return c.modifie_par, c.modifie_le

    fonds_resumes: list[FondsArborescence] = []
    for f in fonds_rows:
        cols = collections_par_fonds.get(f.id, [])
        miroir: CollectionResume | None = None
        libres: list[CollectionResume] = []
        for c in cols:
            mod_par, mod_le = _modifie_de_collection(c)
            resume = CollectionResume(
                cote=c.cote,
                titre=c.titre,
                type_collection=c.type_collection,
                nb_items=nb_items_par_collection.get(c.id, 0),
                fonds_id=c.fonds_id,
                repartition_etats=repartition_par_collection.get(
                    c.id, _repartition_vide()
                ),
                modifie_par=mod_par,
                modifie_le=mod_le,
                phase=c.phase,
            )
            if c.est_miroir:
                miroir = resume
            else:
                libres.append(resume)

        # Pour le fonds, on prend le plus récent entre sa propre modif
        # et la modif la plus récente d'un de ses items.
        modif_item = max_modif_item_par_fonds.get(f.id)
        if modif_item is None:
            f_mod_le, f_mod_par = f.modifie_le, f.modifie_par
        else:
            f_mod_le, f_mod_par = _plus_recent(
                f.modifie_le, f.modifie_par, modif_item[0], modif_item[1]
            )

        fonds_resumes.append(
            FondsArborescence(
                cote=f.cote,
                titre=f.titre,
                nb_items=nb_items_par_fonds.get(f.id, 0),
                collection_miroir=miroir,
                collections_libres=tuple(libres),
                nb_fichiers=nb_fichiers_par_fonds.get(f.id, 0),
                repartition_etats=repartition_par_fonds.get(f.id, _repartition_vide()),
                modifie_par=f_mod_par,
                modifie_le=f_mod_le,
            )
        )

    # ---- Transversales (collections sans fonds_id) ------------------
    transversales_rows = [c for c in collection_rows if c.est_transversale]
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
            repartition_etats=repartition_par_collection.get(c.id, _repartition_vide()),
            modifie_par=c.modifie_par,
            modifie_le=c.modifie_le,
            phase=c.phase,
        )
        for c in transversales_rows
    ]

    # ---- Activité récente : 10 dernières modifications mélangées ----
    activite = _composer_activite_recente(db, limite=10)

    return DashboardResume(
        fonds=tuple(fonds_resumes),
        transversales=tuple(transversales),
        stats=stats,
        activite_recente=activite,
    )


def _composer_activite_recente(
    db: Session, *, limite: int = 10
) -> tuple[ActiviteRecente, ...]:
    """Mélange items + collections + fonds modifiés, garde les `limite`
    plus récents.

    Implémentation : trois requêtes (une par type) limitées à `limite`
    chacune, puis tri Python. Volumétrie minuscule (3 × `limite` lignes)
    et indépendante du volume total — pas la peine d'un UNION SQL plus
    complexe.
    """
    candidats: list[ActiviteRecente] = []

    # Items : on a besoin de la cote du fonds parent.
    rows_items = db.execute(
        select(Item, Fonds.cote)
        .join(Fonds, Fonds.id == Item.fonds_id)
        .where(Item.modifie_le.is_not(None))
        .order_by(Item.modifie_le.desc())
        .limit(limite)
    ).all()
    for item, fonds_cote in rows_items:
        candidats.append(
            ActiviteRecente(
                type="item",
                cote=item.cote,
                titre=item.titre or "",
                fonds_cote=fonds_cote,
                modifie_par=item.modifie_par,
                modifie_le=item.modifie_le,
            )
        )

    # Collections : la cote du fonds parent peut être null (transversales).
    rows_cols = db.execute(
        select(Collection, Fonds.cote)
        .outerjoin(Fonds, Fonds.id == Collection.fonds_id)
        .where(Collection.modifie_le.is_not(None))
        .order_by(Collection.modifie_le.desc())
        .limit(limite)
    ).all()
    for col, fonds_cote in rows_cols:
        candidats.append(
            ActiviteRecente(
                type="collection",
                cote=col.cote,
                titre=col.titre,
                fonds_cote=fonds_cote,
                modifie_par=col.modifie_par,
                modifie_le=col.modifie_le,
            )
        )

    # Fonds.
    rows_fonds = db.execute(
        select(Fonds)
        .where(Fonds.modifie_le.is_not(None))
        .order_by(Fonds.modifie_le.desc())
        .limit(limite)
    ).all()
    for (fonds,) in rows_fonds:
        candidats.append(
            ActiviteRecente(
                type="fonds",
                cote=fonds.cote,
                titre=fonds.titre,
                fonds_cote=fonds.cote,
                modifie_par=fonds.modifie_par,
                modifie_le=fonds.modifie_le,
            )
        )

    candidats.sort(key=lambda a: a.modifie_le, reverse=True)
    return tuple(candidats[:limite])


# ---------------------------------------------------------------------------
# Page fonds (lecture)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FondsDetail:
    fonds: Fonds  # modèle ORM (le template lit ses champs métadonnées)
    nb_items: int
    nb_fichiers: int
    collections_resume: tuple[CollectionResume, ...]
    items_recents: tuple[ItemResume, ...]
    collaborateurs_par_role: dict[RoleCollaborateur, list[CollaborateurFondsResume]]
    repartition_etats: dict[str, int] = field(default_factory=_repartition_vide)
    modifie_par: str | None = None
    modifie_le: datetime | None = None

    @property
    def miroir_resume(self) -> CollectionResume | None:
        """Référence directe à la miroir, sans dépendre de l'ordre du tri."""
        for c in self.collections_resume:
            if c.est_miroir:
                return c
        return None


def composer_page_fonds(db: Session, cote: str) -> FondsDetail:
    """Charge un fonds + ses collections (enrichies de répartition d'états,
    nb_fichiers, traçabilité) + 10 items les plus récents + collaborateurs
    groupés par rôle.

    Coût SQL borné (≤9 queries) indépendamment du nombre de collections,
    cf. test garde-fou `test_page_fonds_n_emet_pas_plus_de_9_requetes`.

    Lève `FondsIntrouvable` si la cote est inconnue.
    """
    fonds = db.scalar(select(Fonds).where(Fonds.cote == cote))
    if fonds is None:
        raise FondsIntrouvable(cote)

    collections_rows = list(
        db.scalars(
            select(Collection)
            .where(Collection.fonds_id == fonds.id)
            .order_by(Collection.titre)
        ).all()
    )

    # ---- Répartition par collection (1 query) -----------------------
    # `nb_items_par_collection` se dérive ensuite par `sum(rep.values())`
    # — pas de requête séparée.
    col_ids = [c.id for c in collections_rows]
    repartition_par_collection: dict[int | None, dict[str, int]] = (
        _agreger_repartition(
            list(
                db.execute(
                    select(
                        ItemCollection.collection_id,
                        Item.etat_catalogage,
                        func.count(Item.id),
                    )
                    .join(Item, Item.id == ItemCollection.item_id)
                    .where(ItemCollection.collection_id.in_(col_ids))
                    .group_by(ItemCollection.collection_id, Item.etat_catalogage)
                ).all()
            )
        )
        if col_ids
        else {}
    )

    # ---- Nb fichiers par collection (1 query) -----------------------
    nb_fichiers_par_collection: dict[int, int] = (
        dict(
            db.execute(
                select(ItemCollection.collection_id, func.count(Fichier.id))
                .join(Item, Item.id == ItemCollection.item_id)
                .join(Fichier, Fichier.item_id == Item.id)
                .where(ItemCollection.collection_id.in_(col_ids))
                .group_by(ItemCollection.collection_id)
            ).all()
        )
        if col_ids
        else {}
    )

    # ---- Répartition fonds-level (1 query) --------------------------
    # `nb_items` du fonds se dérive ensuite par `sum(rep.values())`.
    # On réutilise `_agreger_repartition` avec une clé bidon `None`.
    repartition_fonds: dict[str, int] = _agreger_repartition(
        [
            (None, etat, n)
            for etat, n in db.execute(
                select(Item.etat_catalogage, func.count(Item.id))
                .where(Item.fonds_id == fonds.id)
                .group_by(Item.etat_catalogage)
            ).all()
        ]
    ).get(None, _repartition_vide())
    nb_items = sum(repartition_fonds.values())

    # ---- Nb fichiers fonds-level (1 query) --------------------------
    nb_fichiers_fonds: int = (
        db.scalar(
            select(func.count(Fichier.id))
            .join(Item, Item.id == Fichier.item_id)
            .where(Item.fonds_id == fonds.id)
        )
        or 0
    )

    # ---- Traçabilité fusionnée avec le dernier item du fonds (1 query)
    f_mod_le, f_mod_par = _tracabilite_fusionnee_avec_dernier_item(
        db,
        portee_items=Item.fonds_id == fonds.id,
        propre_le=fonds.modifie_le,
        propre_par=fonds.modifie_par,
    )

    # ---- Construction des CollectionResume enrichies ----------------
    collections_resume = tuple(
        sorted(
            (
                CollectionResume(
                    cote=c.cote,
                    titre=c.titre,
                    type_collection=c.type_collection,
                    nb_items=sum(
                        repartition_par_collection.get(
                            c.id, _repartition_vide()
                        ).values()
                    ),
                    fonds_id=c.fonds_id,
                    nb_fichiers=nb_fichiers_par_collection.get(c.id, 0),
                    href=f"/collection/{c.cote}?fonds={fonds.cote}",
                    repartition_etats=repartition_par_collection.get(
                        c.id, _repartition_vide()
                    ),
                    modifie_par=c.modifie_par,
                    modifie_le=c.modifie_le,
                    phase=c.phase,
                )
                for c in collections_rows
            ),
            # Miroir d'abord (False < True), puis ordre alphabétique titre.
            key=lambda r: (r.type_collection != TypeCollection.MIROIR.value, r.titre),
        )
    )

    # ---- Items récents (1 query) ------------------------------------
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
        nb_fichiers=nb_fichiers_fonds,
        collections_resume=collections_resume,
        items_recents=items_recents,
        collaborateurs_par_role=lister_collaborateurs_fonds_par_role(db, fonds.id),
        repartition_etats=repartition_fonds,
        modifie_par=f_mod_par,
        modifie_le=f_mod_le,
    )


# ---------------------------------------------------------------------------
# Page collection (lecture)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OptionsFiltresCollection:
    """Valeurs distinctes présentes dans la collection, pour alimenter
    les sélecteurs du panneau de filtres."""

    langues: tuple[str, ...] = ()
    types_coar: tuple[str, ...] = ()
    annee_min: int | None = None
    annee_max: int | None = None


@dataclass(frozen=True)
class FiltresCollection:
    """Filtres effectivement actifs sur la page Collection.

    Construits par `parser_filtres_collection` à partir de la query
    string + des `OptionsFiltresCollection` de la collection. Les
    valeurs hors whitelist sont silencieusement ignorées (jamais
    de 400 sur paramètre invalide).
    """

    etats: tuple[str, ...] = ()
    langues: tuple[str, ...] = ()
    types_coar: tuple[str, ...] = ()
    annee_de: int | None = None
    annee_a: int | None = None

    @property
    def actifs(self) -> bool:
        return bool(
            self.etats
            or self.langues
            or self.types_coar
            or self.annee_de is not None
            or self.annee_a is not None
        )

    @property
    def nb_filtres_actifs(self) -> int:
        n = (
            (1 if self.etats else 0)
            + (1 if self.langues else 0)
            + (1 if self.types_coar else 0)
        )
        if self.annee_de is not None or self.annee_a is not None:
            n += 1
        return n

    @property
    def compteur_libelle(self) -> str:
        n = self.nb_filtres_actifs
        if n == 0:
            return "aucun"
        return f"{n} actif{'s' if n > 1 else ''}"

    def to_query_string(
        self,
        *,
        retire_etat: str | None = None,
        retire_langue: str | None = None,
        retire_type_coar: str | None = None,
        retire_periode: bool = False,
    ) -> str:
        """Sérialise les filtres actifs en query string.

        Optionnellement, retire une valeur précise (par ex. pour les
        pastilles cliquables qui ouvrent le retrait d'un seul filtre)
        ou la période entière. Les autres filtres sont conservés tels
        quels.

        Retourne une chaîne sans `?` initial (à concaténer par le
        caller). Vide si aucun filtre n'est actif.
        """
        params: list[str] = []
        etats = tuple(e for e in self.etats if e != retire_etat)
        if etats:
            params.append("etat=" + ",".join(etats))
        langues = tuple(lang for lang in self.langues if lang != retire_langue)
        if langues:
            params.append("langue=" + ",".join(langues))
        types_coar = tuple(t for t in self.types_coar if t != retire_type_coar)
        if types_coar:
            params.append("type_coar=" + ",".join(types_coar))
        if not retire_periode:
            if self.annee_de is not None:
                params.append(f"annee_de={self.annee_de}")
            if self.annee_a is not None:
                params.append(f"annee_a={self.annee_a}")
        return "&".join(params)


def _csv_to_liste(valeur: str | list[str] | None) -> list[str]:
    """Parse une valeur multi-valuée en liste de chaînes.

    Accepte deux formats :
    - chaîne CSV `a,b,c` (depuis un lien forgé à la main),
    - liste de chaînes `["a", "b"]` (depuis un `<select multiple>`
      qui envoie `?key=a&key=b` — FastAPI déserialise en liste).

    Strip + dédoublonne en préservant l'ordre. Vide sur None ou vide.
    """
    if valeur is None:
        return []
    parts: list[str]
    if isinstance(valeur, str):
        parts = valeur.split(",")
    else:
        # FastAPI passe `list[str]` quand la query a la même clé
        # plusieurs fois ; chaque valeur peut elle-même contenir une
        # CSV (cas mixte) — on aplatit.
        parts = []
        for v in valeur:
            parts.extend(v.split(","))
    vu: set[str] = set()
    sortie: list[str] = []
    for part in parts:
        v = part.strip()
        if v and v not in vu:
            vu.add(v)
            sortie.append(v)
    return sortie


def parser_filtres_collection(
    *,
    etat: str | list[str] | None,
    langue: str | list[str] | None,
    type_coar: str | list[str] | None,
    annee_de: int | None,
    annee_a: int | None,
    options: OptionsFiltresCollection,
) -> FiltresCollection:
    """Parse les filtres reçus en query string + valide contre les
    options dynamiques de la collection. Les valeurs hors whitelist
    sont silencieusement ignorées.

    Accepte les multi-valeurs via deux serialisations :
    - clés répétées (`?etat=a&etat=b`, format browser pour
      `<select multiple>`),
    - CSV (`?etat=a,b`, format pour les liens forgés à la main).

    `annee_de` / `annee_a` : entiers, clampés à `[annee_min, annee_max]`.
    Si `annee_de > annee_a` (intervalle inversé), on swap pour donner
    une plage cohérente plutôt qu'un résultat vide muet.
    """
    etats_valides = {e.value for e in EtatCatalogage}
    etats = tuple(e for e in _csv_to_liste(etat) if e in etats_valides)
    langues = tuple(lang for lang in _csv_to_liste(langue) if lang in options.langues)
    types_coar = tuple(t for t in _csv_to_liste(type_coar) if t in options.types_coar)

    def _valider_annee(v: int | None) -> int | None:
        if v is None:
            return None
        if options.annee_min is None or options.annee_max is None:
            return None
        if v < options.annee_min or v > options.annee_max:
            return None
        return v

    de = _valider_annee(annee_de)
    a = _valider_annee(annee_a)
    if de is not None and a is not None and de > a:
        # Intervalle inversé : on swap pour donner un résultat
        # exploitable (la pastille affichera la plage normalisée).
        de, a = a, de

    return FiltresCollection(
        etats=etats,
        langues=langues,
        types_coar=types_coar,
        annee_de=de,
        annee_a=a,
    )


@dataclass(frozen=True)
class CollectionDetail:
    collection: Collection  # modèle ORM
    nb_items: int
    nb_fichiers: int
    fonds_parent: Fonds | None  # None pour transversale
    fonds_representes: tuple[FondsRepresente, ...]  # vide si rattachée à un fonds
    repartition_etats: dict[str, int] = field(default_factory=_repartition_vide)
    modifie_par: str | None = None
    modifie_le: datetime | None = None
    options_filtres: OptionsFiltresCollection = field(
        default_factory=OptionsFiltresCollection
    )

    @property
    def est_miroir(self) -> bool:
        return self.collection.type_collection == TypeCollection.MIROIR.value

    @property
    def est_transversale(self) -> bool:
        return self.collection.fonds_id is None

    @property
    def est_libre_rattachee(self) -> bool:
        return not self.est_miroir and not self.est_transversale


def composer_page_collection(db: Session, collection: Collection) -> CollectionDetail:
    """Charge le contexte d'affichage d'une collection : compteurs,
    répartition d'états, traçabilité, options de filtres dynamiques.

    `collection` doit déjà être chargée (la route fait le lookup +
    désambiguïsation, ce service ne re-lit pas la DB pour ça).

    Coût SQL : ~7 queries indépendamment du volume."""
    # ---- Répartition d'états sur les items de la collection ---------
    repartition: dict[str, int] = _agreger_repartition(
        [
            (None, etat, n)
            for etat, n in db.execute(
                select(Item.etat_catalogage, func.count(Item.id))
                .join(ItemCollection, ItemCollection.item_id == Item.id)
                .where(ItemCollection.collection_id == collection.id)
                .group_by(Item.etat_catalogage)
            ).all()
        ]
    ).get(None, _repartition_vide())
    nb_items = sum(repartition.values())

    # ---- Compteurs fichiers (1 query) -------------------------------
    nb_fichiers: int = (
        db.scalar(
            select(func.count(Fichier.id))
            .join(Item, Item.id == Fichier.item_id)
            .join(ItemCollection, ItemCollection.item_id == Item.id)
            .where(ItemCollection.collection_id == collection.id)
        )
        or 0
    )

    # ---- Options dynamiques pour le panneau filtres -----------------
    # Une seule query récupère langues + types distincts + bornes
    # d'année. Le résultat est petit (≤ ~20 valeurs distinctes par
    # collection en pratique).
    langues_set: set[str] = set()
    types_set: set[str] = set()
    annee_min: int | None = None
    annee_max: int | None = None
    for lang, type_coar, annee in db.execute(
        select(Item.langue, Item.type_coar, Item.annee)
        .join(ItemCollection, ItemCollection.item_id == Item.id)
        .where(ItemCollection.collection_id == collection.id)
        .distinct()
    ).all():
        if lang:
            langues_set.add(lang)
        if type_coar:
            types_set.add(type_coar)
        if annee is not None:
            annee_min = annee if annee_min is None else min(annee_min, annee)
            annee_max = annee if annee_max is None else max(annee_max, annee)
    options_filtres = OptionsFiltresCollection(
        langues=tuple(sorted(langues_set)),
        types_coar=tuple(sorted(types_set)),
        annee_min=annee_min,
        annee_max=annee_max,
    )

    # ---- Traçabilité fusionnée avec le dernier item de la collection
    c_mod_le, c_mod_par = _tracabilite_fusionnee_avec_dernier_item(
        db,
        portee_items=Item.id.in_(
            select(ItemCollection.item_id).where(
                ItemCollection.collection_id == collection.id
            )
        ),
        propre_le=collection.modifie_le,
        propre_par=collection.modifie_par,
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
        nb_fichiers=nb_fichiers,
        fonds_parent=fonds_parent,
        fonds_representes=fonds_representes,
        repartition_etats=repartition,
        modifie_par=c_mod_par,
        modifie_le=c_mod_le,
        options_filtres=options_filtres,
    )


# ---------------------------------------------------------------------------
# Page item (lecture)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FichierResume:
    """Vue figée d'un fichier pour la page item — détache du modèle ORM.

    Inclut la `SourceImage` pré-résolue : la visionneuse n'a plus
    qu'à passer `source_image.primary` à OpenSeadragon, et le panneau
    fichiers utilise `vignette_url`.
    """

    id: int
    nom_fichier: str
    extension: str  # minuscules, sans le point
    type_page: str
    ordre: int
    taille_octets: int | None
    largeur_px: int | None
    hauteur_px: int | None
    format: str | None
    source_image: SourceImage

    @property
    def dimensions(self) -> str | None:
        if self.largeur_px and self.hauteur_px:
            return f"{self.largeur_px}×{self.hauteur_px}"
        return None

    @property
    def vignette_url(self) -> str | None:
        return self.source_image.vignette_url


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


TypeChampMetadonnee = Literal[
    "texte", "date", "etat", "uri", "multiligne", "entier", "liste", "calcule"
]


@dataclass(frozen=True)
class ChampMetadonnee:
    """Une cellule du cartouche : libellé + valeur + hooks d'édition.

    `editable` est True structurellement (les hooks `data-edit-*` sont
    posés sur tous les champs), mais aucun JS d'édition inline n'est
    actif. Le `type_donnee` pilote le rendu côté template (par ex.
    `uri` → lien cliquable via la macro `lien_doi`).
    """

    cle: str  # identifiant technique (ex. "cote", "titre", "Auteur")
    libelle: str  # affiché à gauche du cartouche
    valeur: str | None
    type_donnee: TypeChampMetadonnee = "texte"
    editable: bool = True


@dataclass(frozen=True)
class ItemAdjacent:
    cote: str
    titre: str | None
    fonds_cote: str


@dataclass(frozen=True)
class NavigationItem:
    """Précédent / suivant dans la miroir du fonds parent.

    Les filtres éventuels appliqués sur la page Collection d'origine
    ne sont pas préservés.
    """

    precedent: ItemAdjacent | None
    suivant: ItemAdjacent | None


@dataclass(frozen=True)
class ItemDetail:
    item: Item  # ORM (le template lit ses champs métadonnées)
    fonds: Fonds
    fichiers: tuple[FichierResume, ...]
    fichier_courant: FichierResume | None
    position_courante: int  # 1-indexed
    nb_fichiers: int
    collections: tuple[CollectionAppartenance, ...]
    metadonnees_par_section: dict[str, list[ChampMetadonnee]]
    navigation: NavigationItem


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
        source_image=resoudre_source_image(f),
    )


_LIBELLES_IDENTIFICATION: tuple[tuple[str, str, str], ...] = (
    # (clé, libellé, type_donnee)
    ("cote", "Cote", "texte"),
    ("titre", "Titre", "texte"),
    ("type_coar", "Type COAR", "texte"),
    ("date", "Date", "date"),
    ("annee", "Année", "texte"),
    ("langue", "Langue", "texte"),
    ("numero", "Numéro", "texte"),
)


def composer_metadonnees_par_section(
    item: Item,
    champs_personnalises: list[ChampPersonnalise],
) -> dict[str, list[ChampMetadonnee]]:
    """Organise les métadonnées de l'item en 4 sections affichables.

    - Identification : champs structurants (cote, titre, type, date, langue...)
    - Champs personnalisés : extraits de `item.metadonnees` selon les
      `ChampPersonnalise` des collections d'appartenance (déduplication
      par `cle`, ordre stable).
    - Identifiants externes : DOI Nakala (rendu en lien cliquable).
    - Description : texte libre multi-ligne.

    Une section vide est conservée (la macro Jinja affiche un placeholder
    « non renseigné » pour les valeurs absentes — la section reste un
    point d'entrée pour l'édition future).
    """
    identification: list[ChampMetadonnee] = [
        ChampMetadonnee(
            cle=cle,
            libelle=lib,
            valeur=getattr(item, cle, None),
            type_donnee=td,
        )
        for cle, lib, td in _LIBELLES_IDENTIFICATION
    ]

    metadonnees_brutes = item.metadonnees or {}
    vus: set[str] = set()
    perso: list[ChampMetadonnee] = []
    for champ in sorted(champs_personnalises, key=lambda c: (c.ordre, c.cle)):
        if champ.cle in vus:
            continue
        vus.add(champ.cle)
        valeur = metadonnees_brutes.get(champ.cle)
        # Les listes (vocabulaires multi-valeurs) sont rendues en CSV.
        if isinstance(valeur, list):
            valeur_str: str | None = ", ".join(str(v) for v in valeur) or None
        elif valeur in (None, ""):
            valeur_str = None
        else:
            valeur_str = str(valeur)
        perso.append(
            ChampMetadonnee(
                cle=champ.cle,
                libelle=champ.libelle,
                valeur=valeur_str,
                type_donnee=champ.type,
            )
        )

    identifiants: list[ChampMetadonnee] = [
        ChampMetadonnee(
            cle="doi_nakala",
            libelle="DOI Nakala",
            valeur=item.doi_nakala,
            type_donnee="uri",
        ),
        ChampMetadonnee(
            cle="doi_collection_nakala",
            libelle="DOI collection",
            valeur=item.doi_collection_nakala,
            type_donnee="uri",
        ),
    ]

    description: list[ChampMetadonnee] = [
        ChampMetadonnee(
            cle="description",
            libelle="Description",
            valeur=item.description,
            type_donnee="multiligne",
        ),
        ChampMetadonnee(
            cle="notes_internes",
            libelle="Notes internes",
            valeur=item.notes_internes,
            type_donnee="multiligne",
        ),
    ]

    return {
        "Identification": identification,
        "Champs personnalisés": perso,
        "Identifiants externes": identifiants,
        "Description": description,
    }


def navigation_items(
    db: Session,
    item: Item,
    fonds: Fonds,
) -> NavigationItem:
    """Retourne les items précédent/suivant adjacents dans la miroir
    du fonds parent (tri par cote ASC). Bornes incluses : `None` si on
    est au début ou à la fin.
    """
    base_filtre = (
        Item.fonds_id == fonds.id,
        Item.id != item.id,
    )
    precedent_row = db.execute(
        select(Item.cote, Item.titre)
        .where(*base_filtre, Item.cote < item.cote)
        .order_by(Item.cote.desc())
        .limit(1)
    ).one_or_none()
    suivant_row = db.execute(
        select(Item.cote, Item.titre)
        .where(*base_filtre, Item.cote > item.cote)
        .order_by(Item.cote.asc())
        .limit(1)
    ).one_or_none()

    return NavigationItem(
        precedent=(
            ItemAdjacent(
                cote=precedent_row.cote,
                titre=precedent_row.titre,
                fonds_cote=fonds.cote,
            )
            if precedent_row
            else None
        ),
        suivant=(
            ItemAdjacent(
                cote=suivant_row.cote, titre=suivant_row.titre, fonds_cote=fonds.cote
            )
            if suivant_row
            else None
        ),
    )


def composer_page_item(
    db: Session,
    cote: str,
    fonds: Fonds,
    *,
    fichier_courant_pos: int = 1,
) -> ItemDetail:
    """Charge un item avec ses fichiers, collections d'appartenance,
    métadonnées par section et navigation prev/next.

    Le `Fonds` doit déjà être chargé par la route (cohérent avec
    `composer_page_collection`) — évite une requête redondante.
    Eager loading sur les fichiers. Les collections d'appartenance et
    leurs ChampPersonnalise sont chargés via JOIN distincts. La
    `SourceImage` de chaque fichier est pré-résolue côté service.
    """
    item = db.scalar(
        select(Item)
        .options(selectinload(Item.fichiers))
        .where(Item.cote == cote, Item.fonds_id == fonds.id)
    )
    if item is None:
        raise ItemIntrouvable(f"cote={cote!r} dans le fonds {fonds.id}")

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

    # Champs personnalisés mutualisés sur l'ensemble des collections
    # d'appartenance (déduplication par `cle` côté composer).
    champs = list(
        db.scalars(
            select(ChampPersonnalise)
            .join(
                ItemCollection,
                ItemCollection.collection_id == ChampPersonnalise.collection_id,
            )
            .where(ItemCollection.item_id == item.id)
        ).all()
    )

    return ItemDetail(
        item=item,
        fonds=fonds,
        fichiers=fichiers,
        fichier_courant=fichier_courant,
        position_courante=pos,
        nb_fichiers=nb_fichiers,
        collections=collections,
        metadonnees_par_section=composer_metadonnees_par_section(item, champs),
        navigation=navigation_items(db, item, fonds),
    )
