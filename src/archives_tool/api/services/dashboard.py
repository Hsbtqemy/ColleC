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

import re
from dataclasses import dataclass, field
from datetime import datetime
from collections import Counter
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from archives_tool.affichage.formatters import temps_relatif
from archives_tool.api.services._filtres_communs import (
    clamper_annee,
    csv_to_liste,
)
from archives_tool.api.services.collaborateurs_fonds import (
    CollaborateurFondsResume,
    lister_collaborateurs_fonds,
)
from archives_tool.api.services.fonds import FondsIntrouvable
from archives_tool.api.services.items import ItemIntrouvable, ItemResume
from archives_tool.api.services.vocabulaires import (
    LANGUES_OPTIONS,
    TYPES_COAR_OPTIONS,
    libelle_pour_valeur,
    resoudre_vocabulaire,
)
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
    collaborateurs: tuple[CollaborateurFondsResume, ...] = ()
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

    @property
    def collaborateurs_par_role(
        self,
    ) -> dict[RoleCollaborateur, list[CollaborateurFondsResume]]:
        """Groupe les collaborateurs par role pour les rendus qui veulent
        cette vue (CLI montrer). L'UI Fonds, elle, prefere la liste plate
        avec chips pour eviter qu'une personne multi-roles apparaisse
        plusieurs fois — chaque doublon ayant un bouton Supprimer qui
        supprime tout."""
        groupes: dict[RoleCollaborateur, list[CollaborateurFondsResume]] = {}
        for role in RoleCollaborateur:
            membres = [c for c in self.collaborateurs if role in c.roles]
            if membres:
                groupes[role] = membres
        return groupes


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
        collaborateurs=tuple(lister_collaborateurs_fonds(db, fonds.id)),
        repartition_etats=repartition_fonds,
        modifie_par=f_mod_par,
        modifie_le=f_mod_le,
    )


# ---------------------------------------------------------------------------
# Synthèse fonds (V0.9.6) — orientation cross-collection
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CollectionDansFonds:
    """Une entrée de la cartographie cross-collection d'un fonds.

    Indique pour chaque collection du fonds : combien d'items elle
    contient, dont combien sont **partagés** avec au moins une autre
    libre (info utile pour repérer les chevauchements thématiques).

    La miroir contient toujours tous les items du fonds par
    invariant ; son nb_partages est égal à `nb_items_dans_au_moins_une_libre`
    (les items présents dans une ou plusieurs libres, plus la miroir).
    """

    cote: str
    titre: str
    type_collection: str  # "miroir" / "libre"
    nb_items: int
    nb_partages: int  # nb items aussi présents dans une autre collection du fonds
    doi_nakala: str | None = None  # DOI public de la collection si publiée

    @property
    def est_miroir(self) -> bool:
        return self.type_collection == TypeCollection.MIROIR.value


@dataclass(frozen=True)
class CartographieCollections:
    """Vue d'ensemble des collections d'un fonds : la miroir + les
    libres avec leurs chevauchements.

    ``nb_items_uniquement_miroir`` : items qui ne sont dans aucune
    libre — la « réserve » non encore classée thématiquement.
    ``nb_items_dans_libres`` : items présents dans au moins une libre.
    ``nb_items_dans_plusieurs_libres`` : items présents dans 2+ libres
    (intersections thématiques).
    """

    entrees: tuple[CollectionDansFonds, ...]
    nb_items_uniquement_miroir: int
    nb_items_dans_libres: int
    nb_items_dans_plusieurs_libres: int

    @property
    def nb_libres(self) -> int:
        return sum(1 for e in self.entrees if not e.est_miroir)

    @property
    def vide(self) -> bool:
        """Vraiment vide : aucune collection rattachée (cas
        pathologique d'un fonds sans miroir). Le composant peut alors
        sauter la section.

        Avant V0.9.6-fix : `nb_libres == 0` — mais ça masquait la
        section sur les fonds usuels qui n'ont que leur miroir, ce qui
        privait l'utilisateur du récap des collections. Maintenant on
        affiche systématiquement la section dès qu'il y a une
        collection (au moins la miroir)."""
        return not self.entrees


@dataclass(frozen=True)
class SyntheseFonds:
    """Vue d'ensemble d'un fonds : qualitatif + temporel + visuel +
    trous + activité + cartographie cross-collection.

    Distincte de :func:`composer_page_fonds` qui produit les données
    du bandeau (compteurs, états, traçabilité) et la liste détaillée
    des collections. La synthèse ajoute l'orientation rapide.

    Garde-fou SQL : ~5 requêtes principales (items + sans-fichier +
    items-récents + vignettes + cross-collection), indépendant du
    volume.
    """

    distribution_temporelle: DistributionTemporelle
    agregats: tuple[AgregatItemQuali, ...]
    vignettes: tuple[VignetteSynthese, ...]
    trous: tuple[TrouCatalographique, ...]
    items_recents: tuple[ItemRecemmentModifie, ...]
    cartographie: CartographieCollections
    nb_items_total: int

    @property
    def vide(self) -> bool:
        """Aucune information à afficher — fonds sans items, sans rien
        d'agrégable. Le composant peut être masqué."""
        return (
            not self.agregats
            and not self.vignettes
            and self.distribution_temporelle.vide
            and not self.trous
            and not self.items_recents
            and self.cartographie.vide
        )


def _composer_cartographie_collections(
    db: Session, fonds: Fonds
) -> CartographieCollections:
    """Calcule la cartographie cross-collection d'un fonds en 2
    requêtes : nb items par collection + map item_id → set(collection_ids)
    pour identifier les partages.

    `nb_partages` d'une collection = nb items qu'elle a en commun avec
    **au moins une autre collection** du fonds (incluant la miroir).
    Pour la miroir, c'est donc `nb_items_dans_libres` (items dans ≥1
    libre). Pour une libre, c'est `nb_items` de cette libre (puisqu'ils
    sont tous aussi dans la miroir) — sauf si on veut compter les
    partages avec d'autres libres, ce qui est plus informatif.

    Choix sémantique : `nb_partages` ignore la miroir comme « autre »
    (sinon toute libre aurait nb_partages = nb_items, trivial). Pour
    la miroir, on compte les items partagés avec ≥1 libre.
    """
    # 1) Liste des collections du fonds, dans l'ordre miroir puis
    # libres alphabétiques.
    collections = list(
        db.scalars(
            select(Collection)
            .where(Collection.fonds_id == fonds.id)
            .order_by(
                (Collection.type_collection != TypeCollection.MIROIR.value),
                Collection.titre,
            )
        ).all()
    )

    if not collections:
        return CartographieCollections(
            entrees=(),
            nb_items_uniquement_miroir=0,
            nb_items_dans_libres=0,
            nb_items_dans_plusieurs_libres=0,
        )

    # 2) Map item_id → set(collection_ids) du fonds, en une query.
    appartenance_rows = db.execute(
        select(ItemCollection.item_id, ItemCollection.collection_id)
        .where(
            ItemCollection.collection_id.in_([c.id for c in collections])
        )
    ).all()
    appartenance: dict[int, set[int]] = {}
    for item_id, col_id in appartenance_rows:
        appartenance.setdefault(item_id, set()).add(col_id)

    miroir_id = next(
        (
            c.id
            for c in collections
            if c.type_collection == TypeCollection.MIROIR.value
        ),
        None,
    )
    libre_ids = {
        c.id
        for c in collections
        if c.type_collection != TypeCollection.MIROIR.value
    }

    # 3) Compteurs cross-collection.
    nb_items_uniquement_miroir = 0
    nb_items_dans_libres = 0
    nb_items_dans_plusieurs_libres = 0
    for item_id, col_set in appartenance.items():
        libres_de_cet_item = col_set & libre_ids
        if libres_de_cet_item:
            nb_items_dans_libres += 1
            if len(libres_de_cet_item) >= 2:
                nb_items_dans_plusieurs_libres += 1
        elif miroir_id in col_set:
            nb_items_uniquement_miroir += 1

    # 4) Construction des entrées par collection.
    entrees: list[CollectionDansFonds] = []
    for c in collections:
        # Items de cette collection.
        items_de_c = {
            item_id
            for item_id, col_set in appartenance.items()
            if c.id in col_set
        }
        # Partages : pour la miroir, items aussi dans ≥1 libre ; pour
        # une libre, items aussi dans une AUTRE libre (la miroir ne
        # compte pas comme « autre » sinon nb_partages = nb_items).
        if c.id == miroir_id:
            nb_partages = sum(
                1 for i in items_de_c if appartenance[i] & libre_ids
            )
        else:
            autres_libres = libre_ids - {c.id}
            nb_partages = sum(
                1 for i in items_de_c if appartenance[i] & autres_libres
            )
        entrees.append(
            CollectionDansFonds(
                cote=c.cote,
                titre=c.titre,
                type_collection=c.type_collection,
                nb_items=len(items_de_c),
                nb_partages=nb_partages,
                doi_nakala=c.doi_nakala,
            )
        )

    return CartographieCollections(
        entrees=tuple(entrees),
        nb_items_uniquement_miroir=nb_items_uniquement_miroir,
        nb_items_dans_libres=nb_items_dans_libres,
        nb_items_dans_plusieurs_libres=nb_items_dans_plusieurs_libres,
    )


def composer_synthese_fonds(db: Session, fonds: Fonds) -> SyntheseFonds:
    """Composition d'une vue d'ensemble d'un fonds.

    Réutilise les helpers de `composer_synthese_collection` pour
    l'aggregation qualitative + temporelle, mais portée à tous les
    items du fonds (pas juste une collection). Ajoute la cartographie
    cross-collection (`CartographieCollections`) qui n'a de sens
    qu'au niveau fonds.

    Garde-fou SQL : ~5-7 requêtes, indépendant du volume.
    """
    # ---- 1. Items du fonds (tous, via Item.fonds_id) ----
    lignes_items = db.execute(
        select(
            Item.id,
            Item.cote,
            Item.titre,
            Item.langue,
            Item.type_coar,
            Item.annee,
            Item.date,
            Item.etat_catalogage,
            Item.metadonnees,
        )
        .where(Item.fonds_id == fonds.id)
        .order_by(Item.cote)
    ).all()
    nb_items_total = len(lignes_items)

    # ---- 2. Agrégats + résolution année effective (idem collection)
    counter_langue: Counter[str] = Counter()
    counter_type: Counter[str] = Counter()
    metas_brutes: list[dict[str, Any] | None] = []
    annees_effectives: list[int] = []
    nb_a_corriger = 0
    nb_sans_titre = 0
    nb_sans_annee = 0
    for (
        _id, _cote, titre, langue, type_coar, annee, date, etat, meta
    ) in lignes_items:
        if langue:
            counter_langue[langue] += 1
        if type_coar:
            counter_type[type_coar] += 1
        metas_brutes.append(meta)
        if etat == EtatCatalogage.A_CORRIGER.value:
            nb_a_corriger += 1
        if not (titre or "").strip():
            nb_sans_titre += 1
        annee_effective = annee if annee is not None else _annee_depuis_date_edtf(date)
        if annee_effective is None:
            nb_sans_annee += 1
        else:
            annees_effectives.append(annee_effective)

    distribution = _calculer_distribution_temporelle(annees_effectives)
    par_cle_meta = _agreger_item_metadonnees_quali(metas_brutes)

    agregats: list[AgregatItemQuali] = []
    if counter_langue:
        counter_langue_humain: Counter[str] = Counter()
        for code, n in counter_langue.items():
            counter_langue_humain[_resoudre_libelle_langue(code)] += n
        agregats.append(
            _agregat_depuis_counter(
                "langue",
                "Langue" if len(counter_langue_humain) == 1 else "Langues",
                counter_langue_humain,
            )
        )
    if counter_type:
        counter_type_humain: Counter[str] = Counter()
        for uri, n in counter_type.items():
            lib = libelle_pour_valeur(uri, TYPES_COAR_OPTIONS) or uri
            counter_type_humain[lib] += n
        agregats.append(
            _agregat_depuis_counter(
                "type_coar",
                "Type" if len(counter_type_humain) == 1 else "Types",
                counter_type_humain,
            )
        )
    agregats_meta_candidats: list[AgregatItemQuali] = []
    for cle, counter in par_cle_meta.items():
        valeur_dominante_count = counter.most_common(1)[0][1] if counter else 0
        if valeur_dominante_count <= 1 and len(counter) >= 5:
            continue
        agregats_meta_candidats.append(
            _agregat_depuis_counter(cle, _libelle_depuis_cle(cle), counter)
        )
    agregats_meta = sorted(
        agregats_meta_candidats,
        key=lambda a: (-sum(tv.count for tv in a.top), a.cle),
    )
    agregats.extend(agregats_meta[:6])

    # ---- 3. Trous (mêmes calculs qu'en collection, à l'échelle fonds)
    nb_sans_fichier = (
        db.scalar(
            select(func.count(Item.id))
            .where(Item.fonds_id == fonds.id, ~Item.fichiers.any())
        )
        or 0
    )

    # Deep-link possible vers la page Fonds qui n'a pas (encore) de
    # filtre par état : pour l'instant on signale sans lien.
    trous: list[TrouCatalographique] = []
    if nb_sans_titre > 0:
        trous.append(
            TrouCatalographique(
                code="sans_titre",
                libelle=f"{nb_sans_titre} sans titre",
                nb=nb_sans_titre,
                filtre_url=None,
            )
        )
    if nb_sans_annee > 0:
        trous.append(
            TrouCatalographique(
                code="sans_annee",
                libelle=f"{nb_sans_annee} sans année",
                nb=nb_sans_annee,
                filtre_url=None,
            )
        )
    if nb_sans_fichier > 0:
        trous.append(
            TrouCatalographique(
                code="sans_fichier",
                libelle=f"{nb_sans_fichier} sans fichier",
                nb=nb_sans_fichier,
                filtre_url=None,
            )
        )
    if nb_a_corriger > 0:
        trous.append(
            TrouCatalographique(
                code="a_corriger",
                libelle=f"{nb_a_corriger} à corriger",
                nb=nb_a_corriger,
                # Pas de filtre par état sur la page fonds aujourd'hui ;
                # on pointe vers la miroir filtrée (cas dominant : fonds
                # = miroir). Pour fonds multi-collection, l'utilisateur
                # ouvre quand même la liste filtrée d'une collection.
                filtre_url=None,
            )
        )

    # ---- 4. Items récemment modifiés ----
    items_recents_rows = db.execute(
        select(
            Item.cote,
            Item.titre,
            Item.modifie_par,
            Item.modifie_le,
        )
        .where(Item.fonds_id == fonds.id)
        .order_by(Item.modifie_le.desc())
        .limit(5)
    ).all()
    items_recents = tuple(
        ItemRecemmentModifie(
            cote=cote,
            titre=titre or cote,
            fonds_cote=fonds.cote,
            modifie_par=mod_par,
            modifie_le=mod_le,
        )
        for cote, titre, mod_par, mod_le in items_recents_rows
        if mod_le is not None
    )

    # ---- 5. Vignettes échantillonnées ----
    ids_ordonnes = [id_ for id_, *_ in lignes_items]
    ids_echantillon = _ids_echantillonnes(ids_ordonnes, _NB_VIGNETTES_SYNTHESE)
    vignettes: tuple[VignetteSynthese, ...] = ()
    if ids_echantillon:
        items_avec_fichier = db.execute(
            select(Item)
            .options(selectinload(Item.fichiers))
            .where(Item.id.in_(ids_echantillon))
        ).all()
        items_par_id = {row[0].id: row[0] for row in items_avec_fichier}
        vignettes_liste: list[VignetteSynthese] = []
        for id_ in ids_echantillon:
            item = items_par_id.get(id_)
            if item is None:
                continue
            first_f = item.fichiers[0] if item.fichiers else None
            src = resoudre_source_image(first_f) if first_f else None
            vignettes_liste.append(
                VignetteSynthese(
                    item_cote=item.cote,
                    item_titre=item.titre or item.cote,
                    fonds_cote=fonds.cote,
                    vignette_url=src.vignette_url if src else None,
                    extension=_extension(first_f.nom_fichier) if first_f else "",
                )
            )
        vignettes = tuple(vignettes_liste)

    # ---- 6. Cartographie cross-collection ----
    cartographie = _composer_cartographie_collections(db, fonds)

    return SyntheseFonds(
        distribution_temporelle=distribution,
        agregats=tuple(agregats),
        vignettes=vignettes,
        trous=tuple(trous),
        items_recents=items_recents,
        cartographie=cartographie,
        nb_items_total=nb_items_total,
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

    Note : etat est validé contre l'enum global `EtatCatalogage`
    (pas contre les options de la collection) — cohérent avec la
    page Collection qui affiche tous les états même non présents,
    pour permettre de pré-filtrer avant d'avoir des items à cet état.
    """
    etats_valides = {e.value for e in EtatCatalogage}
    etats = tuple(e for e in csv_to_liste(etat) if e in etats_valides)
    langues = tuple(lang for lang in csv_to_liste(langue) if lang in options.langues)
    types_coar = tuple(t for t in csv_to_liste(type_coar) if t in options.types_coar)

    de = clamper_annee(annee_de, options.annee_min, options.annee_max)
    a = clamper_annee(annee_a, options.annee_min, options.annee_max)
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
# Synthèse de collection (V0.9.6) — orientation rapide au-dessus du tableau
# ---------------------------------------------------------------------------


#: Clés de `Item.metadonnees` qui sont **structurelles** (décompositions
#: de cote, typologies internes) et n'ont pas vocation à apparaître dans
#: les agrégats qualitatifs. Distinct de :data:`_META_FICHIER_TECHNIQUES`
#: (qui couvre les fingerprints Nakala au niveau fichier).
_META_ITEM_STRUCTURELLES: frozenset[str] = frozenset(
    {"hierarchie", "typologie"}
)

#: Clés de `Item.metadonnees` qui sont **techniques/calculées** (compteurs
#: Nakala, hashes, fingerprints). Exclues des agrégats synthèse parce
#: qu'elles n'apportent rien au « quoi est dedans » — un compte de
#: fichiers par item n'est pas une caractéristique catalographique. Ne
#: touche pas le cartouche (l'utilisateur peut toujours voir et éditer
#: ces clés sur la fiche item).
_META_ITEM_TECHNIQUES_SYNTHESE: frozenset[str] = frozenset(
    {
        "num_files",       # compteur Nakala — bruit
        "hash", "sha", "sha256", "checksum",
        "data_url", "embed_url", "preview_url", "thumb", "thumbnail",
        "iiif", "iiif_url", "iiif_url_nakala", "info_json",
        "categories",      # Nakala-side type aggregation, peu utile
    }
)

#: Mapping ISO 639-1 (2 lettres) → ISO 639-3 (3 lettres) pour les
#: langues les plus courantes. :data:`LANGUES_OPTIONS` indexe en ISO
#: 639-3 (`fra`, `spa`…), mais les imports Nakala / DC arrivent souvent
#: en ISO 639-1 (`fr`, `es`…). Ce mapping rattrape l'affichage sans
#: imposer une migration de données.
_LANGUES_ISO1_VERS_ISO3: dict[str, str] = {
    "fr": "fra", "en": "eng", "es": "spa", "it": "ita",
    "de": "deu", "pt": "por", "nl": "nld", "ar": "ara",
    "ru": "rus", "el": "ell", "la": "lat", "oc": "oci",
    "br": "bre", "ca": "cat",
}

#: Nombre maximum de valeurs distinctes affichées par agrégat. Au-delà,
#: l'utilisateur ouvre le panneau Filtrer ou la page modifier pour le
#: détail. Cap conservateur — ne pas grossir sans repenser le layout.
_TOP_AGREGAT: int = 5

#: Nombre de vignettes échantillonnées dans la synthèse. 12 tient sur
#: 3 colonnes × 4 lignes ou 6 × 2 selon la largeur disponible.
_NB_VIGNETTES_SYNTHESE: int = 12


def _resoudre_libelle_langue(code: str) -> str:
    """Résout un code langue (ISO 639-3 ou 639-1) vers son libellé
    humain. Fallback ISO 639-1 → ISO 639-3 puis lookup dans
    :data:`LANGUES_OPTIONS`. Si rien ne matche, retourne le code brut
    inchangé (l'utilisateur le voit et peut corriger).
    """
    if not code:
        return code
    lib = libelle_pour_valeur(code, LANGUES_OPTIONS)
    if lib and lib != code:
        return lib
    # Le code n'a pas matché : tente la conversion ISO-1 → ISO-3 puis
    # relookup. Couvre `es` → `spa` → `Espagnol`.
    iso3 = _LANGUES_ISO1_VERS_ISO3.get(code.lower())
    if iso3:
        lib2 = libelle_pour_valeur(iso3, LANGUES_OPTIONS)
        if lib2:
            return lib2
    return code


_REGEX_ANNEE_EDTF = re.compile(r"^-?(\d{4})")


def _annee_depuis_date_edtf(date: str | None) -> int | None:
    """Extrait l'année (entier) d'une chaîne de date EDTF tolérante.

    Couvre `1974`, `1974-03`, `1974-03-11`, `vers 1974` (échoue), `19XX`
    (échoue), `-0044` (BCE, retourne -44). Sert de fallback quand
    `Item.annee` n'a pas été peuplé à l'import — la timeline doit
    quand même fonctionner.
    """
    if not date:
        return None
    m = _REGEX_ANNEE_EDTF.match(date.strip())
    if not m:
        return None
    try:
        return int(date.strip().split("-")[0] if date.strip().startswith("-") else m.group(1))
    except ValueError:
        return None


@dataclass(frozen=True)
class TopValeur:
    """Une entrée du top N d'un agrégat qualitatif."""

    valeur: str
    count: int


@dataclass(frozen=True)
class AgregatItemQuali:
    """Synthèse d'un champ qualitatif sur les items d'une collection.

    ``cle`` est la clé technique (ex. ``"auteur"``, ``"type_coar"``,
    ``"langue"``). ``libelle`` est le libellé humain affiché. ``top``
    contient au plus :data:`_TOP_AGREGAT` valeurs ; ``nb_distinct``
    est le total — l'écart révèle « il y a N - 5 autres valeurs ».
    """

    cle: str
    libelle: str
    top: tuple[TopValeur, ...]
    nb_distinct: int

    @property
    def est_uniforme(self) -> bool:
        """True si une seule valeur distincte couvre toute l'agrégat.

        Le template peut alors basculer en rendu compact (une ligne
        « Langue : Espagnol (172) ») plutôt que header + énumération.
        """
        return self.nb_distinct == 1


@dataclass(frozen=True)
class BarreTemporelle:
    """Une barre de la mini-distribution temporelle."""

    annee_debut: int  # inclus
    annee_fin: int  # inclus (= annee_debut si pas annuel)
    count: int


@dataclass(frozen=True)
class DistributionTemporelle:
    """Cartographie temporelle : bornes + barres.

    ``pas`` vaut ``"annee"`` si la plage est étroite (≤ 30 ans), sinon
    ``"decennie"``. Les barres couvrent l'intervalle [annee_min,
    annee_max] sans trou — les années sans item ont count=0 (utile
    visuellement : on voit les vides du chantier).
    """

    annee_min: int | None
    annee_max: int | None
    pas: Literal["annee", "decennie"] | None
    barres: tuple[BarreTemporelle, ...]

    @property
    def vide(self) -> bool:
        return not self.barres

    @property
    def count_max(self) -> int:
        return max((b.count for b in self.barres), default=0)


@dataclass(frozen=True)
class VignetteSynthese:
    """Une vignette échantillonnée — pointe sur la fiche item."""

    item_cote: str
    item_titre: str
    fonds_cote: str
    vignette_url: str | None
    extension: str


@dataclass(frozen=True)
class TrouCatalographique:
    """Une lacune catalographique repérée sur la collection.

    ``filtre_url`` ouvre le tableau d'items filtré si possible (cas
    « à corriger » qui réutilise `?etat=a_corriger`). Sinon ``None`` —
    on signale, on ne deep-link pas (les autres trous demanderaient
    des filtres dédiés non implémentés).
    """

    code: Literal["sans_titre", "sans_annee", "sans_fichier", "a_corriger"]
    libelle: str
    nb: int
    filtre_url: str | None


@dataclass(frozen=True)
class ItemRecemmentModifie:
    """Item récemment modifié — affiché dans la section « Activité »."""

    cote: str
    titre: str
    fonds_cote: str
    modifie_par: str | None
    modifie_le: datetime


@dataclass(frozen=True)
class SyntheseCollection:
    """Vue d'ensemble d'une collection : qualitatif + temporel +
    visuel + trous + activité. Rendue par
    ``components/synthese_collection.html`` au-dessus du tableau
    d'items.

    Garde-fou SQL : 4 requêtes principales indépendamment du volume
    (items + sans-fichier + ids-ordonnes + items-echantillonnes).
    """

    distribution_temporelle: DistributionTemporelle
    agregats: tuple[AgregatItemQuali, ...]
    vignettes: tuple[VignetteSynthese, ...]
    trous: tuple[TrouCatalographique, ...]
    items_recents: tuple[ItemRecemmentModifie, ...]
    nb_items_total: int
    # Identifiants Nakala de la collection elle-même (V0.9.6) — exposés
    # dans la synthèse pour édition inline directe sans détour par la
    # page Modifier. None si non renseigné.
    doi_nakala: str | None = None
    doi_collection_nakala_parent: str | None = None

    @property
    def vide(self) -> bool:
        """Aucune information à afficher — la collection est vide ou
        sans rien d'agrégable. Le composant peut être masqué."""
        return (
            not self.agregats
            and not self.vignettes
            and self.distribution_temporelle.vide
            and not self.trous
            and not self.items_recents
        )


def _calculer_distribution_temporelle(
    annees: list[int],
) -> DistributionTemporelle:
    """Construit la distribution temporelle à partir des années non
    nulles des items. Choisit ``"annee"`` si la plage est ≤ 30 ans,
    ``"decennie"`` au-delà. Garantit des barres sans trou pour
    visualiser les vides.
    """
    if not annees:
        return DistributionTemporelle(
            annee_min=None, annee_max=None, pas=None, barres=()
        )
    a_min = min(annees)
    a_max = max(annees)
    span = a_max - a_min
    pas: Literal["annee", "decennie"]
    barres: list[BarreTemporelle] = []
    if span <= 30:
        pas = "annee"
        counts: Counter[int] = Counter(annees)
        for an in range(a_min, a_max + 1):
            barres.append(
                BarreTemporelle(annee_debut=an, annee_fin=an, count=counts[an])
            )
    else:
        pas = "decennie"
        # Décennie alignée sur le multiple de 10 inférieur — `1973` →
        # décennie `1970`. L'utilisateur reconnaît mieux « années 70 »
        # qu'un découpage `1973-1982`.
        dec_min = (a_min // 10) * 10
        dec_max = (a_max // 10) * 10
        counts_dec: Counter[int] = Counter((a // 10) * 10 for a in annees)
        for dec in range(dec_min, dec_max + 10, 10):
            barres.append(
                BarreTemporelle(
                    annee_debut=dec, annee_fin=dec + 9, count=counts_dec[dec]
                )
            )
    return DistributionTemporelle(
        annee_min=a_min, annee_max=a_max, pas=pas, barres=tuple(barres)
    )


def _agreger_item_metadonnees_quali(
    items_meta: list[dict[str, Any] | None],
) -> dict[str, Counter[str]]:
    """Agrège les valeurs documentaires de ``Item.metadonnees`` pour
    les items d'une collection. Skip les clés structurelles
    (``hierarchie``, ``typologie``), les clés techniques/fingerprints
    (cf. :data:`_META_ITEM_TECHNIQUES_SYNTHESE`), et les valeurs vides.
    Les listes (vocabs multi-valeurs) sont dépiles : chaque valeur
    incrémente son propre compteur.
    """
    par_cle: dict[str, Counter[str]] = {}
    for meta in items_meta:
        if not isinstance(meta, dict):
            continue
        for cle, val in meta.items():
            if cle in _META_ITEM_STRUCTURELLES:
                continue
            if cle in _META_ITEM_TECHNIQUES_SYNTHESE:
                continue
            if isinstance(val, dict):
                # Décomposition structurée — skip ici (montré ailleurs).
                continue
            if isinstance(val, list):
                for v in val:
                    s = _valeur_metadonnee_str(v)
                    if s:
                        par_cle.setdefault(cle, Counter())[s] += 1
            else:
                s = _valeur_metadonnee_str(val)
                if s:
                    par_cle.setdefault(cle, Counter())[s] += 1
    return par_cle


def _agregat_depuis_counter(
    cle: str,
    libelle: str,
    counter: Counter[str],
) -> AgregatItemQuali:
    """Convertit un Counter en AgregatItemQuali (top N + tri stable)."""
    top_items = counter.most_common(_TOP_AGREGAT)
    top = tuple(TopValeur(valeur=v, count=c) for v, c in top_items)
    return AgregatItemQuali(
        cle=cle,
        libelle=libelle,
        top=top,
        nb_distinct=len(counter),
    )


def _ids_echantillonnes(ids_ordonnes: list[int], n: int) -> list[int]:
    """Sélectionne n ids uniformément répartis dans la liste ordonnée.

    Si la liste est plus petite que n, retourne tout. Sinon utilise un
    stride flottant pour répartir équitablement (au lieu de prendre
    les n premiers, qui ne sont pas représentatifs).
    """
    total = len(ids_ordonnes)
    if total == 0:
        return []
    if total <= n:
        return list(ids_ordonnes)
    stride = total / n
    return [ids_ordonnes[int(i * stride)] for i in range(n)]


def composer_synthese_collection(
    db: Session,
    collection: Collection,
    fonds_query: str | None = None,
) -> SyntheseCollection:
    """Composition d'une vue d'ensemble d'une collection.

    Distincte de :func:`composer_page_collection` qui produit les
    données du **bandeau** (compteurs, états, traçabilité) et des
    filtres dynamiques. La synthèse ajoute le **qualitatif** (top N
    auteurs/sujets/types/langues), le **temporel** (mini-timeline),
    le **visuel** (vignettes échantillonnées) et l'**activité**
    (5 derniers items modifiés + trous catalographiques).

    ``fonds_query`` est la cote du fonds telle que présente dans la
    query string courante (pour construire les liens de filtres
    cohérents). ``None`` pour les transversales.

    Garde-fou SQL : 4 requêtes principales pour les compteurs +
    métadonnées, 1 pour les items récents, 2 pour les vignettes. Total
    7, indépendant du volume.
    """
    # ---- 1. Pass principale : tous les items, attributs nécessaires
    #    aux agrégats + au calcul des trous (sauf "sans fichier"). ----
    #    `Item.date` sert de fallback à `Item.annee` quand l'import a
    #    rempli la chaîne EDTF mais pas l'entier dérivé (cas PF —
    #    l'importer Nakala laisse `annee` à NULL).
    lignes_items = db.execute(
        select(
            Item.id,
            Item.cote,
            Item.titre,
            Item.langue,
            Item.type_coar,
            Item.annee,
            Item.date,
            Item.etat_catalogage,
            Item.metadonnees,
        )
        .join(ItemCollection, ItemCollection.item_id == Item.id)
        .where(ItemCollection.collection_id == collection.id)
        .order_by(Item.cote)
    ).all()
    nb_items_total = len(lignes_items)

    # ---- 1a. Agrégats + résolution année effective ----
    #    On dérive l'année effective = `Item.annee` si présent, sinon
    #    extrait des 4 premiers chiffres de `Item.date` (EDTF).
    counter_langue: Counter[str] = Counter()
    counter_type: Counter[str] = Counter()
    metas_brutes: list[dict[str, Any] | None] = []
    annees_effectives: list[int] = []
    nb_a_corriger = 0
    nb_sans_titre = 0
    nb_sans_annee = 0
    for (
        _id, _cote, titre, langue, type_coar, annee, date, etat, meta
    ) in lignes_items:
        if langue:
            counter_langue[langue] += 1
        if type_coar:
            counter_type[type_coar] += 1
        metas_brutes.append(meta)
        if etat == EtatCatalogage.A_CORRIGER.value:
            nb_a_corriger += 1
        if not (titre or "").strip():
            nb_sans_titre += 1
        annee_effective = annee if annee is not None else _annee_depuis_date_edtf(date)
        if annee_effective is None:
            nb_sans_annee += 1
        else:
            annees_effectives.append(annee_effective)

    distribution = _calculer_distribution_temporelle(annees_effectives)
    par_cle_meta = _agreger_item_metadonnees_quali(metas_brutes)

    agregats: list[AgregatItemQuali] = []
    # Langue + type_coar en tête (les plus structurants), avec libellés
    # humains résolus via les vocabulaires hardcoded + fallback ISO 639-1.
    if counter_langue:
        counter_langue_humain: Counter[str] = Counter()
        for code, n in counter_langue.items():
            counter_langue_humain[_resoudre_libelle_langue(code)] += n
        agregats.append(
            _agregat_depuis_counter(
                "langue",
                "Langue" if len(counter_langue_humain) == 1 else "Langues",
                counter_langue_humain,
            )
        )
    if counter_type:
        counter_type_humain: Counter[str] = Counter()
        for uri, n in counter_type.items():
            lib = libelle_pour_valeur(uri, TYPES_COAR_OPTIONS) or uri
            counter_type_humain[lib] += n
        agregats.append(
            _agregat_depuis_counter(
                "type_coar",
                "Type" if len(counter_type_humain) == 1 else "Types",
                counter_type_humain,
            )
        )
    # Puis les agrégats meta — filtrés contre les champs identifiant-like
    # (toutes les valeurs distinctes apparaissent une seule fois → pas
    # d'agrégation possible, juste du bruit) puis triés par nb total
    # d'occurrences décroissant. Cap à ~6 pour rester compact ; au-delà
    # ça devient un mur, l'utilisateur ouvre les pages individuelles.
    agregats_meta_candidats: list[AgregatItemQuali] = []
    for cle, counter in par_cle_meta.items():
        # Heuristique anti-identifiant : si la valeur la plus fréquente
        # n'apparaît qu'une seule fois ET on a au moins 5 valeurs
        # distinctes, c'est presque sûrement un identifiant (cas PF :
        # `ancienne_cote = "Por Favor_1974_ano-1_num-N"`). On l'écarte
        # pour ne pas saturer la colonne.
        valeur_dominante_count = counter.most_common(1)[0][1] if counter else 0
        if valeur_dominante_count <= 1 and len(counter) >= 5:
            continue
        agregats_meta_candidats.append(
            _agregat_depuis_counter(cle, _libelle_depuis_cle(cle), counter)
        )
    agregats_meta = sorted(
        agregats_meta_candidats,
        key=lambda a: (-sum(tv.count for tv in a.top), a.cle),
    )
    agregats.extend(agregats_meta[:6])

    # ---- 2. Trou « sans fichier » ----
    #    Compte les items de la collection qui n'ont aucun Fichier
    #    rattaché. Une seule query agrégée.
    nb_sans_fichier = (
        db.scalar(
            select(func.count(Item.id))
            .join(ItemCollection, ItemCollection.item_id == Item.id)
            .where(
                ItemCollection.collection_id == collection.id,
                ~Item.fichiers.any(),
            )
        )
        or 0
    )

    # Lien deep pour le trou « à corriger » (les autres trous n'ont pas
    # encore de filtre dédié dans `parser_filtres_collection`).
    base_url = f"/collection/{collection.cote}"
    sep_fonds = f"&fonds={fonds_query}" if fonds_query else ""
    url_a_corriger: str | None = (
        f"{base_url}?etat=a_corriger{sep_fonds}"
        if nb_a_corriger > 0
        else None
    )

    trous: list[TrouCatalographique] = []
    if nb_sans_titre > 0:
        trous.append(
            TrouCatalographique(
                code="sans_titre",
                libelle=f"{nb_sans_titre} sans titre",
                nb=nb_sans_titre,
                filtre_url=None,
            )
        )
    if nb_sans_annee > 0:
        trous.append(
            TrouCatalographique(
                code="sans_annee",
                libelle=f"{nb_sans_annee} sans année",
                nb=nb_sans_annee,
                filtre_url=None,
            )
        )
    if nb_sans_fichier > 0:
        trous.append(
            TrouCatalographique(
                code="sans_fichier",
                libelle=f"{nb_sans_fichier} sans fichier",
                nb=nb_sans_fichier,
                filtre_url=None,
            )
        )
    if nb_a_corriger > 0:
        trous.append(
            TrouCatalographique(
                code="a_corriger",
                libelle=f"{nb_a_corriger} à corriger",
                nb=nb_a_corriger,
                filtre_url=url_a_corriger,
            )
        )

    # ---- 3. Items récemment modifiés ----
    items_recents_rows = db.execute(
        select(
            Item.cote,
            Item.titre,
            Item.modifie_par,
            Item.modifie_le,
            Fonds.cote.label("fonds_cote"),
        )
        .join(ItemCollection, ItemCollection.item_id == Item.id)
        .join(Fonds, Fonds.id == Item.fonds_id)
        .where(ItemCollection.collection_id == collection.id)
        .order_by(Item.modifie_le.desc())
        .limit(5)
    ).all()
    items_recents = tuple(
        ItemRecemmentModifie(
            cote=cote,
            titre=titre or cote,
            fonds_cote=fonds_cote,
            modifie_par=mod_par,
            modifie_le=mod_le,
        )
        for cote, titre, mod_par, mod_le, fonds_cote in items_recents_rows
        if mod_le is not None
    )

    # ---- 4. Vignettes échantillonnées ----
    ids_ordonnes = [id_ for id_, *_ in lignes_items]
    ids_echantillon = _ids_echantillonnes(ids_ordonnes, _NB_VIGNETTES_SYNTHESE)
    vignettes: tuple[VignetteSynthese, ...] = ()
    if ids_echantillon:
        items_avec_fichier = db.execute(
            select(Item, Fonds.cote.label("fonds_cote"))
            .options(selectinload(Item.fichiers))
            .join(Fonds, Fonds.id == Item.fonds_id)
            .where(Item.id.in_(ids_echantillon))
        ).all()
        items_par_id = {item.id: (item, fonds_cote) for item, fonds_cote in items_avec_fichier}
        vignettes_liste: list[VignetteSynthese] = []
        for id_ in ids_echantillon:
            entry = items_par_id.get(id_)
            if entry is None:
                continue
            item, fonds_cote = entry
            first_f = item.fichiers[0] if item.fichiers else None
            src = resoudre_source_image(first_f) if first_f else None
            vignettes_liste.append(
                VignetteSynthese(
                    item_cote=item.cote,
                    item_titre=item.titre or item.cote,
                    fonds_cote=fonds_cote,
                    vignette_url=src.vignette_url if src else None,
                    extension=_extension(first_f.nom_fichier) if first_f else "",
                )
            )
        vignettes = tuple(vignettes_liste)

    return SyntheseCollection(
        distribution_temporelle=distribution,
        agregats=tuple(agregats),
        vignettes=vignettes,
        trous=tuple(trous),
        items_recents=items_recents,
        nb_items_total=nb_items_total,
        doi_nakala=collection.doi_nakala,
        doi_collection_nakala_parent=collection.doi_collection_nakala_parent,
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
    #: URL externe de téléchargement si le Fichier n'a pas de chemin
    #: local (cas typique : Fichier Nakala-only). `None` si on doit
    #: passer par la route locale `/item/<cote>/fichiers/<id>` — c.-à-d.
    #: dès qu'on a un fichier disque (la route locale sert le binaire
    #: depuis la racine configurée).
    url_telechargement_externe: str | None = None

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

    `options` (optionnel) : si renseigné, l'édition inline propose un
    `<select>` strict au lieu d'un `<input>` libre. Chaque entrée est
    une paire `(valeur, libelle)` — la valeur est stockée, le libellé
    est ce que voit l'utilisateur dans le dropdown.

    `valeur_affichee` : ce que rend le cartouche en lecture. Identique
    à `valeur` par défaut ; pour les vocabulaires (cf. `options`), le
    composer y stocke le libellé humain associé à la valeur (par ex.
    URI COAR → « Texte »).
    """

    cle: str  # identifiant technique (ex. "cote", "titre", "Auteur")
    libelle: str  # affiché à gauche du cartouche
    valeur: str | None
    type_donnee: TypeChampMetadonnee = "texte"
    editable: bool = True
    options: tuple[tuple[str, str], ...] | None = None
    valeur_affichee: str | None = None
    # V0.9.4 lot 2 : True pour les lignes de la section « Champs
    # personnalisés » issues du fallback Bug C (clés libres dans
    # `Item.metadonnees` sans `ChampPersonnalise` formel). La
    # cartouche affiche alors un mini-bouton « Formaliser » qui crée
    # un `ChampPersonnalise` sur la miroir du fonds avec le libellé
    # synthétisé. La promouvabilité exige que la `cle` soit un slug
    # valide (PATTERN_CLE) — autrement le bouton n'est pas rendu et
    # l'utilisateur devra nettoyer la clé en amont.
    est_libre_promouvable: bool = False


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


# Clés de `Fichier.metadonnees` considérées comme techniques (URLs
# Nakala / data, extension, chiffre interne) — exclues des agrégats
# de la fiche item et du badge « méta non triviales » sur les
# vignettes. Sans cette liste noire, chaque fichier porterait une
# soixantaine de valeurs uniques (data_url, embed_url, …) et les
# agrégats seraient dominés par ces fingerprints sans valeur
# documentaire.
_META_FICHIER_TECHNIQUES: frozenset[str] = frozenset(
    {
        "data_url", "embed_url", "preview_url", "thumb", "thumbnail",
        "iiif", "iiif_url", "iiif_url_nakala", "info_json",
        "chiffre", "ext", "extension",
        "hash", "hash_sha256", "sha", "sha256", "checksum",
    }
)


@dataclass(frozen=True)
class AgregatChampFichier:
    """Synthèse d'une clé de ``Fichier.metadonnees`` sur tous les
    fichiers d'un item : valeurs distinctes + nb d'occurrences.

    Utilisé par la fiche item (V0.9.5) pour montrer en un coup d'œil
    « Dessinateurs (6) : Perich (8) · Maximo (12) … » sans imposer
    le clic page par page.
    """

    cle: str  # clé brute, ex. "collaborateur_dessinateur"
    libelle: str  # synthétisé via `_libelle_depuis_cle`
    valeurs: tuple[tuple[str, int], ...]  # (valeur, count), trié desc puis alpha


@dataclass(frozen=True)
class FichierFicheLigne:
    """Ligne du tableau compact « DÉTAIL » de la colonne fichiers de
    la fiche item. Contient juste ce qui est rendu — pas de source
    image, pas de meta techniques.

    ``ordre`` : valeur du champ `Fichier.ordre` (= numéro de page
    affiché à l'utilisateur, peut avoir des sauts si certains scans
    manquent).
    ``position`` : index 1-based dans la liste triée des fichiers
    de l'item. Utilisé pour construire l'URL visionneuse
    (``?fichier_courant=<position>``) qui attend une position, pas
    un ordre. Différent de ``ordre`` quand il y a des sauts.
    """

    id: int
    ordre: int
    position: int  # 1-indexed dans la liste, pour les liens visionneuse
    nom_fichier: str
    extension: str
    a_meta_documentaires: bool  # True si meta non-triviales (badge ✎)
    meta_extraits: dict[str, str]  # clés non-techniques → str affichable


@dataclass(frozen=True)
class FicheItem:
    """Notice complète d'un item, sans visionneuse (V0.9.5).

    Composée par :func:`composer_fiche_item` ; rendue par
    ``pages/item_fiche.html``. Three columns : item-level metadata,
    fichier aggregates + compact list, vignettes scrollables.
    """

    item: Item
    fonds: Fonds
    collections: tuple[CollectionAppartenance, ...]
    metadonnees_par_section: dict[str, list[ChampMetadonnee]]
    fichiers: tuple[FichierResume, ...]  # source des vignettes col 3
    nb_fichiers: int
    agregats_fichier: tuple[AgregatChampFichier, ...]
    lignes_fichier: tuple[FichierFicheLigne, ...]  # liste compacte col 2
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
        url_telechargement_externe=_url_telechargement_externe(f),
    )


def _url_telechargement_externe(fichier: Fichier) -> str | None:
    """URL de téléchargement externe pour un Fichier Nakala-only.

    Si le Fichier a un chemin local (`chemin_relatif`), on retourne
    `None` — le caller utilisera la route locale qui sert le binaire
    depuis la racine configurée.

    Sinon (Fichier Nakala-only), on cherche une URL de téléchargement
    direct :
    - `iiif_url_nakala` qui pointe sur Nakala : on reconstruit l'URL
      `/data/<doi>/<sha>` (qui sert le binaire — l'`info.json` ne
      sert qu'à OSD et ne contient pas la donnée).
    - `iiif_url_nakala` qui pointe ailleurs : on l'utilise telle quelle.
    - `metadonnees.data_url` (cas non-image où le data brut a été
      conservé tel quel) : fallback de dernière chance.
    - Sinon `None` — le viewer affichera la route locale qui retournera
      404 (cas dégradé, signalé à l'utilisateur).
    """
    from archives_tool.files.nakala import vers_data

    if fichier.chemin_relatif:
        return None
    iiif = fichier.iiif_url_nakala
    if iiif:
        data = vers_data(iiif)
        if data is not None:
            return data
        # URL externe non-Nakala — on garde tel quel (au moins
        # l'utilisateur a un lien fonctionnel).
        return iiif
    meta = fichier.metadonnees or {}
    raw = meta.get("data_url")
    if isinstance(raw, str) and raw.strip().startswith(("http://", "https://")):
        return raw.strip()
    return None


_LIBELLES_IDENTIFICATION: tuple[tuple[str, str, str], ...] = (
    # (clé, libellé, type_donnee)
    # État en tête : c'est le champ qu'on touche le plus souvent pendant
    # une vérification en série (« passer cet item de brouillon à
    # vérifié »). L'avoir au top du cartouche réduit le scroll.
    ("etat_catalogage", "État", "texte"),
    ("cote", "Cote", "texte"),
    ("titre", "Titre", "texte"),
    ("type_coar", "Type COAR", "texte"),
    ("date", "Date", "date"),
    ("annee", "Année", "texte"),
    ("langue", "Langue", "texte"),
    ("numero", "Numéro", "texte"),
)


# Source de vérité unique des champs item éditables inline (clic dans
# le cartouche). Référencée par la route POST /item/{cote}/champ/{field}
# pour valider et par `composer_metadonnees_par_section` pour stamper
# `ChampMetadonnee.editable` — ainsi la macro ne pose `data-editable="1"`
# que sur les lignes vraiment éditables.
#
# Cote, fonds_id, version et les champs personnalisés (JSON) restent
# exclus : la cote touche aux chemins, le fonds_id est immuable, la
# version est technique, le JSON nécessite une UI dédiée (vocabulaires,
# listes). `etat_catalogage` est inclus depuis V0.9.3 — l'exclusion
# précédente (« l'état porte un workflow ») était trop conservatrice :
# en pratique l'utilisateur fait des vérifications en série et avoir
# à passer par la page « Modifier » pour chaque changement d'état
# (~6 clics + reload) était une friction quotidienne.
CHAMPS_ITEM_EDITABLES_INLINE: frozenset[str] = frozenset(
    {
        "etat_catalogage",
        "titre",
        "type_coar",
        "date",
        "annee",
        "langue",
        "numero",
        "description",
        "notes_internes",
        "doi_nakala",
        "doi_collection_nakala",
    }
)


#: Whitelist des champs Collection éditables inline depuis la page
#: lecture (bandeau + section synthèse). Comme pour les items, restent
#: hors whitelist et passent par `/collection/{cote}/modifier` :
#: - `cote` : touche aux URLs et aux exports (renommage côté chantier)
#: - `type_collection` : immuable (miroir vs libre par invariant)
#: - `fonds_id` : immuable pour les miroirs ; pour les libres, demande
#:   une UI dédiée (impact sur la junction `ItemCollection`)
#: - `version` : verrou optimiste, purement technique
#: - `profil_import_id`, `personnalite_associee`, `responsable_archives` :
#:   rarement édités ; restent sur la page Modifier
CHAMPS_COLLECTION_EDITABLES_INLINE: frozenset[str] = frozenset(
    {
        "titre",
        "titre_secondaire",
        "description",
        "description_publique",
        "description_interne",
        "phase",
        "editeur",
        "lieu_edition",
        "periodicite",
        "issn",
        "date_debut",
        "date_fin",
        "doi_nakala",
        "doi_collection_nakala_parent",
        "notes_internes",
    }
)


def _valeur_metadonnee_str(valeur: Any) -> str | None:
    """Rend une valeur de `item.metadonnees` en string pour affichage.

    Trois types non-triviaux à gérer :
    - liste (vocabulaires multi-valeurs) → CSV ;
    - dict (décompositions de cote / typologie produites par
      l'importer dans `metadonnees.hierarchie`, `metadonnees.typologie`)
      → `k: v, k: v` à plat ;
    - vide (`None` ou `""`) → `None` pour que la macro Jinja affiche
      « non renseigné » plutôt qu'une chaîne vide.
    """
    if isinstance(valeur, list):
        return ", ".join(str(v) for v in valeur) or None
    if isinstance(valeur, dict):
        return ", ".join(f"{k}: {v}" for k, v in valeur.items()) or None
    if valeur in (None, ""):
        return None
    return str(valeur)


#: Acronymes à conserver en majuscules dans les libellés synthétisés
#: depuis une slug de `metadonnees.<X>` (Trou #3 V0.9.2-import). Sans
#: cette liste, `_libelle_depuis_cle("doi")` retournerait `"Doi"` —
#: laid pour les utilisateurs habitués au DC.
_ACRONYMES_LIBELLES: frozenset[str] = frozenset(
    {"doi", "iiif", "url", "uri", "ocr", "edtf", "coar", "issn",
     "isbn", "ark", "id", "pdf", "tiff", "jpeg", "png", "svg"}
)


def _libelle_depuis_cle(cle: str) -> str:
    """Synthétise un libellé humain depuis une clé `metadonnees.<X>`
    sans `ChampPersonnalise` déclaré (Bug C V0.9.2-import).

    `ancienne_cote` → ``Ancienne cote``. Simple capitalisation du
    premier mot (pas `title()` qui mettrait toutes les capitales).
    Les mots dans :data:`_ACRONYMES_LIBELLES` (`doi`, `iiif`,
    `url`...) restent en MAJUSCULES — `doi_collection` →
    `DOI collection`, `iiif_url` → `IIIF URL`. Une clé vide tombe
    sur elle-même pour éviter une ligne sans libellé."""
    mots = cle.replace("_", " ").split()
    if not mots:
        return cle
    rendu: list[str] = []
    for i, mot in enumerate(mots):
        if mot.lower() in _ACRONYMES_LIBELLES:
            rendu.append(mot.upper())
        elif i == 0:
            rendu.append(mot[:1].upper() + mot[1:])
        else:
            rendu.append(mot)
    return " ".join(rendu)


def composer_metadonnees_par_section(
    item: Item,
    champs_personnalises: list[ChampPersonnalise],
) -> dict[str, list[ChampMetadonnee]]:
    """Organise les métadonnées de l'item en 4 sections affichables.

    - Identification : champs structurants (cote, titre, type, date, langue...)
    - Champs personnalisés : d'abord les clés couvertes par un
      `ChampPersonnalise` formel des collections d'appartenance
      (déduplication par `cle`, ordre stable), puis (Bug C V0.9.2-import)
      les clés libres restantes de `item.metadonnees` — l'import dump
      tout en JSON sans créer de `ChampPersonnalise`, sans ce fallback
      tout le travail descriptif resterait silencieusement invisible.
    - Identifiants externes : DOI Nakala (rendu en lien cliquable).
    - Description : texte libre multi-ligne.

    Une section vide est conservée (la macro Jinja affiche un placeholder
    « non renseigné » pour les valeurs absentes — la section reste un
    point d'entrée pour l'édition future).
    """
    identification: list[ChampMetadonnee] = []
    for cle, lib, td in _LIBELLES_IDENTIFICATION:
        valeur = getattr(item, cle, None)
        options, libelle = resoudre_vocabulaire(cle, valeur)
        identification.append(
            ChampMetadonnee(
                cle=cle,
                libelle=lib,
                valeur=valeur,
                type_donnee=td,
                editable=cle in CHAMPS_ITEM_EDITABLES_INLINE,
                options=options,
                valeur_affichee=libelle,
            )
        )

    metadonnees_brutes = item.metadonnees or {}
    # Pré-peupler `vus` avec les clés déjà exposées dans les autres
    # sections (Identification, Identifiants externes, Description) :
    # si une clé homonyme apparaît dans `item.metadonnees` (cas
    # pathologique d'un mapping qui pousserait p.ex. `titre` en JSON
    # libre), on évite un doublon visuel et trompeur sur la page item
    # (deux lignes « Titre » dont une vide). La valeur dédiée prime.
    vus: set[str] = {cle for cle, _, _ in _LIBELLES_IDENTIFICATION} | {
        "doi_nakala",
        "doi_collection_nakala",
        "description",
        "notes_internes",
    }
    perso: list[ChampMetadonnee] = []
    # V0.9.4 lot 3c : charger les options des vocabulaires DB associés
    # une seule fois par champ. `options_depuis_vocabulaire` exclut les
    # valeurs dépréciées — les items qui les portent garderont la valeur
    # brute dans `valeur` ; `valeur_affichee` retombera dessus si pas
    # trouvée dans les options actives.
    from archives_tool.api.services.vocabulaires_db import (
        options_depuis_vocabulaire,
    )
    for champ in sorted(champs_personnalises, key=lambda c: (c.ordre, c.cle)):
        if champ.cle in vus:
            continue
        vus.add(champ.cle)
        valeur = metadonnees_brutes.get(champ.cle)
        valeur_str = _valeur_metadonnee_str(valeur)
        options: tuple[tuple[str, str], ...] | None = None
        valeur_affichee: str | None = valeur_str
        if champ.vocabulaire is not None:
            options = options_depuis_vocabulaire(champ.vocabulaire)
            # Libellé humain : « Français » pour le code « fra ».
            # Si la valeur stockée n'est pas dans le vocabulaire
            # (legacy, déprécié), on retombe sur la valeur brute.
            for code, libelle in options:
                if code == valeur_str:
                    valeur_affichee = libelle
                    break
        # V0.9.4 inline-edit-champs-perso : editable sauf
        # liste_multiple (inline_edit.js ne sait pas faire de
        # multi-select via input/select). texte_long mappé sur
        # `multiligne` pour que le JS crée un <textarea>.
        type_donnee_inline = (
            "multiligne" if champ.type == "texte_long" else champ.type
        )
        est_editable_inline = champ.type != "liste_multiple"
        perso.append(
            ChampMetadonnee(
                cle=champ.cle,
                libelle=champ.libelle,
                valeur=valeur_str,
                type_donnee=type_donnee_inline,
                editable=est_editable_inline,
                options=options,
                valeur_affichee=valeur_affichee,
            )
        )

    # Bug C V0.9.2-import : fallback pour les clés libres de
    # `item.metadonnees` sans `ChampPersonnalise` déclaré. Trié
    # alphabétiquement par clé (les ChampPersonnalise gardent leur
    # ordre déclaré en tête, les libres viennent après).
    for cle in sorted(metadonnees_brutes.keys()):
        if cle in vus:
            continue
        vus.add(cle)
        valeur_brute = metadonnees_brutes[cle]
        valeur_str = _valeur_metadonnee_str(valeur_brute)
        # Trou #4 V0.9.2-import : si la valeur est une URL HTTP, on
        # type le champ `uri` pour que la macro Jinja la rende en
        # lien cliquable via `lien_doi`. Détection conservative :
        # str unique commençant par http(s):// — pas de cliquage de
        # listes d'URLs ni de descriptions qui contiendraient un
        # lien au milieu.
        type_donnee: str | None = None
        if (
            isinstance(valeur_brute, str)
            and valeur_brute.strip().startswith(("http://", "https://"))
        ):
            type_donnee = "uri"
        # V0.9.4 lot 2 : marquer promouvable les clés libres dont le
        # slug est valide (PATTERN_CLE de champs_personnalises). Un
        # slug non valide (Unnamed: 15, mots-clés) reste libre — la
        # promotion exige un nettoyage manuel en amont.
        from archives_tool.api.services.champs_personnalises import PATTERN_CLE
        est_promouvable = bool(PATTERN_CLE.match(cle))
        perso.append(
            ChampMetadonnee(
                cle=cle,
                libelle=_libelle_depuis_cle(cle),
                valeur=valeur_str,
                type_donnee=type_donnee,
                editable=False,
                est_libre_promouvable=est_promouvable,
            )
        )

    identifiants: list[ChampMetadonnee] = [
        ChampMetadonnee(
            cle="doi_nakala",
            libelle="DOI Nakala",
            valeur=item.doi_nakala,
            type_donnee="uri",
            editable="doi_nakala" in CHAMPS_ITEM_EDITABLES_INLINE,
        ),
        ChampMetadonnee(
            cle="doi_collection_nakala",
            libelle="DOI collection",
            valeur=item.doi_collection_nakala,
            type_donnee="uri",
            editable="doi_collection_nakala" in CHAMPS_ITEM_EDITABLES_INLINE,
        ),
    ]

    description: list[ChampMetadonnee] = [
        ChampMetadonnee(
            cle="description",
            libelle="Description",
            valeur=item.description,
            type_donnee="multiligne",
            editable="description" in CHAMPS_ITEM_EDITABLES_INLINE,
        ),
        ChampMetadonnee(
            cle="notes_internes",
            libelle="Notes internes",
            valeur=item.notes_internes,
            type_donnee="multiligne",
            editable="notes_internes" in CHAMPS_ITEM_EDITABLES_INLINE,
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
    # d'appartenance (déduplication par `cle` côté composer). Le
    # service helper filtre actif=True, eager-load vocab+valeurs.
    # V0.9.5 : appel via le helper partagé avec /item/<cote>/modifier.
    from archives_tool.api.services.champs_personnalises import (
        lister_champs_actifs_pour_item,
    )
    champs = lister_champs_actifs_pour_item(db, item.id)

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


def _meta_documentaires(meta: dict[str, Any] | None) -> dict[str, str]:
    """Sous-ensemble de ``Fichier.metadonnees`` jugé documentaire :
    on retire les URLs Nakala, hash, extension, chiffre interne
    (cf. :data:`_META_FICHIER_TECHNIQUES`). Renvoie un dict normalisé
    (valeurs converties en str non vide) — vide si rien d'utile.
    """
    if not isinstance(meta, dict):
        return {}
    out: dict[str, str] = {}
    for cle, val in meta.items():
        if cle in _META_FICHIER_TECHNIQUES:
            continue
        s = _valeur_metadonnee_str(val)
        if s:
            out[cle] = s
    return out


def _agreger_fichier_metadonnees(
    fichiers: list[Fichier],
) -> tuple[AgregatChampFichier, ...]:
    """Pour chaque clé non-technique présente dans les
    `Fichier.metadonnees`, agrège les valeurs distinctes + comptes.
    Trié par fréquence décroissante (utile pour la fiche : on voit
    d'abord les valeurs les plus représentées).

    Coût : O(N fichiers × M clés). 7454 × ~5 clés sur PF = 37k ops,
    instantané. Pas d'index SQL : pour des items avec 10k+ fichiers
    il faudrait passer à un GROUP BY json_extract — pas le cas
    aujourd'hui.
    """
    par_cle: dict[str, Counter[str]] = {}
    for f in fichiers:
        for cle, val in _meta_documentaires(f.metadonnees).items():
            par_cle.setdefault(cle, Counter())[val] += 1
    agregats: list[AgregatChampFichier] = []
    for cle, counter in sorted(par_cle.items()):
        valeurs = tuple(
            sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
        )
        agregats.append(
            AgregatChampFichier(
                cle=cle,
                libelle=_libelle_depuis_cle(cle),
                valeurs=valeurs,
            )
        )
    return tuple(agregats)


def composer_fiche_item(
    db: Session,
    cote: str,
    fonds: Fonds,
) -> FicheItem:
    """Notice complète d'un item, sans visionneuse (V0.9.5).

    Mêmes briques que :func:`composer_page_item` (réutilise items,
    fichiers, collections, champs perso) + nouvelles :
    - ``agregats_fichier`` : synthèse des clés documentaires de
      ``Fichier.metadonnees`` sur les N fichiers de l'item ;
    - ``lignes_fichier`` : projection compacte pour le tableau de
      droite (sans `source_image` ni URLs techniques, allégée par
      rapport à `FichierResume`).

    Garde-fou SQL : ≤ 4 requêtes (item + fichiers eager, collections,
    champs perso). Agrégats calculés en Python pour rester portable
    (SQLite + Postgres futur sans JSON ops vendor-specific).
    """
    item = db.scalar(
        select(Item)
        .options(selectinload(Item.fichiers))
        .where(Item.cote == cote, Item.fonds_id == fonds.id)
    )
    if item is None:
        raise ItemIntrouvable(f"cote={cote!r} dans le fonds {fonds.id}")

    fichiers_resume = tuple(_resume_fichier(f) for f in item.fichiers)
    nb_fichiers = len(fichiers_resume)

    # Lignes compactes pour le tableau colonne fichiers. Position
    # 1-indexed = index dans la liste triée par ordre — différent
    # de `Fichier.ordre` si l'item a des sauts dans ses ordres
    # (cas observé sur fac-similés incomplets, scans manquants).
    lignes: list[FichierFicheLigne] = []
    for idx, f in enumerate(item.fichiers, start=1):
        meta_doc = _meta_documentaires(f.metadonnees)
        lignes.append(
            FichierFicheLigne(
                id=f.id,
                ordre=f.ordre,
                position=idx,
                nom_fichier=f.nom_fichier,
                extension=_extension(f.nom_fichier),
                a_meta_documentaires=bool(meta_doc),
                meta_extraits=meta_doc,
            )
        )

    # Collections d'appartenance + métadonnées item — identique au
    # composer_page_item (même flot). Pas DRY'd parce que cohérence
    # de signature vs duplication minime.
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

    from archives_tool.api.services.champs_personnalises import (
        lister_champs_actifs_pour_item,
    )
    champs = lister_champs_actifs_pour_item(db, item.id)

    return FicheItem(
        item=item,
        fonds=fonds,
        collections=collections,
        metadonnees_par_section=composer_metadonnees_par_section(item, champs),
        fichiers=fichiers_resume,
        nb_fichiers=nb_fichiers,
        agregats_fichier=_agreger_fichier_metadonnees(list(item.fichiers)),
        lignes_fichier=tuple(lignes),
        navigation=navigation_items(db, item, fonds),
    )
