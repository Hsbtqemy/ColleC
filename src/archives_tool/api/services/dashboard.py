"""Service métier du tableau de bord.

Quatre fonctions pures session → dataclasses :
- statistiques agrégées globales ;
- résumés des collections (avec répartition des états calculée en
  une seule requête `GROUP BY` plutôt qu'une par collection) ;
- activité récente (fusion de trois journaux, tri, top-N) ;
- points de vigilance (réutilise `qa.controler_tout`).
"""

from __future__ import annotations

import enum
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from archives_tool.affichage.formatters import temps_relatif
from archives_tool.api.services.tri import Listage, Ordre, appliquer_tri
from archives_tool.models import (
    Collection,
    EtatCatalogage,
    Fichier,
    Item,
    ModificationItem,
    OperationFichier,
    OperationImport,
    PhaseChantier,
)
from archives_tool.qa.controles import CODES_CONTROLES, controler_tout

# Le dashboard re-rend à chaque visite ; le contrôle « orphelins-disque »
# fait un rglob complet sous chaque racine — trop coûteux pour la
# homepage. On le laisse à la commande `archives-tool controler` ou
# à un futur endpoint dédié.
_CHECKS_DASHBOARD: tuple[str, ...] = tuple(
    c for c in CODES_CONTROLES if c != "orphelins-disque"
)


# ---------------------------------------------------------------------------
# Dataclasses exposées au template
# ---------------------------------------------------------------------------


@dataclass
class StatistiquesGlobales:
    nb_collections: int = 0
    nb_collections_racines: int = 0
    nb_sous_collections: int = 0
    nb_items: int = 0
    nb_items_recents: int = 0
    nb_fichiers: int = 0
    volume_octets: int = 0
    nb_items_valides: int = 0
    pourcentage_valides: float = 0.0


@dataclass
class CollectionResume:
    """Schéma aligné sur le composant `tableau_collections` du bundle.

    `modifie_depuis` est le rendu pré-calculé de `modifie_le` (le composant
    attend une chaîne déjà formatée — pas de filtre Jinja appliqué côté
    template).
    """

    id: int
    cote: str
    titre: str
    phase: PhaseChantier
    href: str = ""
    sous_collections: int = 0
    nb_items: int = 0
    nb_fichiers: int = 0
    repartition: dict[str, int] = field(default_factory=dict)
    modifie_par: str | None = None
    modifie_le: datetime | None = None
    modifie_depuis: str = ""


class TypeEvenement(enum.StrEnum):
    IMPORT = "import"
    MODIFICATION = "modification"
    RENOMMAGE = "renommage"
    DERIVE = "derive"
    EXPORT = "export"


@dataclass
class EvenementActivite:
    type: TypeEvenement
    description: str
    cote_concernee: str | None
    utilisateur: str | None
    horodatage: datetime


@dataclass
class PointVigilance:
    type: Literal[
        "fichiers_manquants",
        "doublons",
        "items_sans_fichier",
        "orphelins_disque",
    ]
    titre: str
    detail: str
    nombre: int
    lien_action: str


# ---------------------------------------------------------------------------
# Statistiques globales
# ---------------------------------------------------------------------------


def calculer_statistiques_globales(session: Session) -> StatistiquesGlobales:
    nb_total = session.scalar(select(func.count(Collection.id))) or 0
    nb_racines = (
        session.scalar(
            select(func.count(Collection.id)).where(Collection.parent_id.is_(None))
        )
        or 0
    )
    nb_items = session.scalar(select(func.count(Item.id))) or 0

    seuil_recent = datetime.now() - timedelta(days=7)
    nb_recents = (
        session.scalar(select(func.count(Item.id)).where(Item.cree_le >= seuil_recent))
        or 0
    )

    nb_valides = (
        session.scalar(
            select(func.count(Item.id)).where(
                Item.etat_catalogage == EtatCatalogage.VALIDE.value
            )
        )
        or 0
    )

    nb_fichiers, volume = session.execute(
        select(
            func.count(Fichier.id),
            func.coalesce(func.sum(Fichier.taille_octets), 0),
        )
    ).one()

    pourcentage = (nb_valides / nb_items * 100) if nb_items else 0.0

    return StatistiquesGlobales(
        nb_collections=nb_total,
        nb_collections_racines=nb_racines,
        nb_sous_collections=nb_total - nb_racines,
        nb_items=nb_items,
        nb_items_recents=nb_recents,
        nb_fichiers=int(nb_fichiers or 0),
        volume_octets=int(volume or 0),
        nb_items_valides=nb_valides,
        pourcentage_valides=pourcentage,
    )


# ---------------------------------------------------------------------------
# Résumé des collections
# ---------------------------------------------------------------------------


def _comptes_par_collection(
    session: Session,
) -> tuple[dict[int, int], dict[int, dict[str, int]]]:
    """Deux agrégations : fichiers, répartition des états par collection.

    Le compte d'items est dérivable de `sum(repartition[col_id].values())`,
    inutile de le requêter séparément. Évite la N+1 d'une boucle qui
    interrogerait la base par collection.
    """
    fichiers = dict(
        session.execute(
            select(Item.collection_id, func.count(Fichier.id))
            .join(Fichier, Fichier.item_id == Item.id)
            .group_by(Item.collection_id)
        ).all()
    )
    repartition: dict[int, dict[str, int]] = {}
    for col_id, etat, n in session.execute(
        select(Item.collection_id, Item.etat_catalogage, func.count(Item.id)).group_by(
            Item.collection_id, Item.etat_catalogage
        )
    ).all():
        repartition.setdefault(col_id, {})[etat] = n
    return fichiers, repartition


def _comptes_sous_collections(session: Session) -> dict[int, int]:
    rows = session.execute(
        select(Collection.parent_id, func.count(Collection.id))
        .where(Collection.parent_id.is_not(None))
        .group_by(Collection.parent_id)
    ).all()
    return dict(rows)


# V0.9.0-alpha : ce module fonctionne encore sur l'ancien schéma (Item.
# collection_id, Collection.parent_id) et ses fonctions cassent à
# l'exécution. Reconstruction prévue en V0.9.0-gamma. Le dict ci-dessous
# garde les références neuves pour permettre l'import du module.
_TRI_SQL_COLLECTIONS = {
    "cote": Collection.cote,
    "titre": Collection.titre,
    "modifie": Collection.modifie_le,
}
# Tris portés en Python (compteurs dérivés des dicts d'agrégats).
_TRI_CALCULE_COLLECTIONS = ("items", "fichiers")


def lister_collections_dashboard(
    session: Session,
    limite: int = 10,
    *,
    tri: str | None = None,
    ordre: Ordre = "desc",
) -> "Listage[CollectionResume]":
    """Collections racines triées par tri/ordre, à défaut modifie DESC.

    Tris admis : `cote`, `titre`, `modifie` (colonnes SQL via
    `appliquer_tri`) et `items`, `fichiers` (compteurs calculés,
    tri Python sur la liste avant slice). Tout autre tri retombe
    sur le défaut (`modifie` DESC).
    """
    fichiers_par_col, etats_par_col = _comptes_par_collection(session)
    sous_col_par_parent = _comptes_sous_collections(session)

    stmt = select(Collection).where(Collection.parent_id.is_(None))
    if tri in _TRI_CALCULE_COLLECTIONS:
        cle, sens = tri, ordre if ordre in ("asc", "desc") else "desc"
        # Pas de LIMIT : on a besoin de tous les compteurs pour trier.
        stmt = stmt.order_by(Collection.cote_collection)
    else:
        stmt, cle, sens = appliquer_tri(
            stmt, _TRI_SQL_COLLECTIONS, tri, ordre, defaut=("modifie", "desc")
        )
        # Égalité de la clé de tri → ordre stable par cote.
        stmt = stmt.order_by(Collection.cote_collection).limit(limite)
    racines = list(session.scalars(stmt).all())

    maintenant = datetime.now()
    resumes = [
        CollectionResume(
            id=col.id,
            cote=col.cote_collection,
            titre=col.titre,
            phase=PhaseChantier(col.phase),
            href=f"/collection/{col.cote_collection}",
            sous_collections=sous_col_par_parent.get(col.id, 0),
            nb_items=sum(etats_par_col.get(col.id, {}).values()),
            nb_fichiers=fichiers_par_col.get(col.id, 0),
            repartition=etats_par_col.get(col.id, {}),
            modifie_par=col.modifie_par,
            modifie_le=col.modifie_le,
            modifie_depuis=temps_relatif(col.modifie_le, maintenant=maintenant),
        )
        for col in racines
    ]
    if cle in _TRI_CALCULE_COLLECTIONS:
        cle_attr = {"items": "nb_items", "fichiers": "nb_fichiers"}[cle]
        resumes.sort(key=lambda r: getattr(r, cle_attr), reverse=(sens == "desc"))
        resumes = resumes[:limite]

    return Listage(items=resumes, tri=cle, ordre=sens)


# ---------------------------------------------------------------------------
# Activité récente
# ---------------------------------------------------------------------------


def lister_activite_recente(
    session: Session, limite: int = 4
) -> list[EvenementActivite]:
    """Fusion top-N des trois journaux : édition, opération fichier, import."""
    evenements: list[EvenementActivite] = []

    for op in session.scalars(
        select(OperationImport)
        .order_by(OperationImport.execute_le.desc())
        .limit(limite)
    ).all():
        evenements.append(
            EvenementActivite(
                type=TypeEvenement.IMPORT,
                description=(
                    f"Import : {op.items_crees} items créés, "
                    f"{op.fichiers_ajoutes} fichiers ajoutés"
                ),
                cote_concernee=None,
                utilisateur=op.execute_par,
                horodatage=op.execute_le,
            )
        )

    for of, cote_item in session.execute(
        select(OperationFichier, Item.cote)
        .outerjoin(Fichier, OperationFichier.fichier_id == Fichier.id)
        .outerjoin(Item, Fichier.item_id == Item.id)
        .order_by(OperationFichier.execute_le.desc())
        .limit(limite)
    ).all():
        type_evt = (
            TypeEvenement.RENOMMAGE
            if of.type_operation in ("rename", "restore")
            else TypeEvenement.DERIVE
        )
        evenements.append(
            EvenementActivite(
                type=type_evt,
                description=f"{of.type_operation} de {of.chemin_avant} → {of.chemin_apres}"
                if of.chemin_apres
                else f"{of.type_operation} de {of.chemin_avant}",
                cote_concernee=cote_item,
                utilisateur=of.execute_par,
                horodatage=of.execute_le,
            )
        )

    for mi, cote_item in session.execute(
        select(ModificationItem, Item.cote)
        .join(Item, ModificationItem.item_id == Item.id)
        .order_by(ModificationItem.modifie_le.desc())
        .limit(limite)
    ).all():
        evenements.append(
            EvenementActivite(
                type=TypeEvenement.MODIFICATION,
                description=f"Édition champ « {mi.champ} »",
                cote_concernee=cote_item,
                utilisateur=mi.modifie_par,
                horodatage=mi.modifie_le,
            )
        )

    evenements.sort(key=lambda e: e.horodatage, reverse=True)
    return evenements[:limite]


# ---------------------------------------------------------------------------
# Points de vigilance
# ---------------------------------------------------------------------------


_LIBELLES_VIGILANCE: dict[str, tuple[str, str, str]] = {
    "fichiers-manquants": (
        "fichiers_manquants",
        "Fichiers introuvables sur le disque",
        "Référencés en base mais absents",
    ),
    "orphelins-disque": (
        "orphelins_disque",
        "Fichiers disque non référencés",
        "Présents sous une racine, pas en base",
    ),
    "items-vides": (
        "items_sans_fichier",
        "Items sans fichier rattaché",
        "Aucun scan associé",
    ),
    "doublons": (
        "doublons",
        "Doublons potentiels",
        "Mêmes hashes SHA-256",
    ),
}


def lister_points_vigilance(
    session: Session,
    *,
    racines: Mapping[str, Path] | None = None,
) -> list[PointVigilance]:
    """Réutilise les contrôles qa et synthétise les compteurs.

    Le contrôle « orphelins-disque » nécessite des racines configurées ;
    sans elles, qa renvoie un avertissement sans anomalie — on filtre
    de la liste.
    """
    rapport = controler_tout(session, racines=racines or {}, checks=_CHECKS_DASHBOARD)
    points: list[PointVigilance] = []
    for ctrl in rapport.controles:
        meta = _LIBELLES_VIGILANCE.get(ctrl.code)
        if meta is None or ctrl.nb_anomalies == 0:
            continue
        type_, titre, detail = meta
        points.append(
            PointVigilance(
                type=type_,  # type: ignore[arg-type]
                titre=titre,
                detail=detail,
                nombre=ctrl.nb_anomalies,
                lien_action="#",  # TODO v0.6 : lien réel vers vue détaillée
            )
        )
    return points
