"""Dataclasses et types partagés pour le module qa.

Les contrôles produisent un `ResultatControle` indépendant ; un
`RapportQa` les agrège avec un périmètre et un horodatage. Le module
n'écrit jamais en base — tous les contrôles sont en lecture seule.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import select

from archives_tool.models import Item, ItemCollection


class Severite(enum.StrEnum):
    """Gravité d'un contrôle qui ne passe pas.

    L'ordre de déclaration sert au tri des rapports (erreurs d'abord).
    `StrEnum` (Python 3.11+) : les membres sont des `str` natifs, donc
    sérialisables JSON sans handler custom.
    """

    ERREUR = "erreur"
    AVERTISSEMENT = "avertissement"
    INFO = "info"


@dataclass(frozen=True)
class Exemple:
    """Un cas concret de problème détecté.

    `references` est un dict de pointeurs vers les entités concernées
    (cotes, ids) — utile pour qu'un consommateur JSON puisse remonter
    l'arbre sans parser le `message`.
    """

    message: str
    references: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ResultatControle:
    """Résultat d'un contrôle individuel."""

    id: str
    famille: str
    severite: Severite
    libelle: str
    passe: bool
    compte_total: int
    compte_problemes: int
    exemples: tuple[Exemple, ...] = ()


@dataclass(frozen=True)
class PerimetreControle:
    """Périmètre du contrôle + compteurs globaux pour le bandeau de tête.

    Les compteurs sont **toujours globaux** (décrivent la base entière)
    quel que soit le périmètre : ce sont les contrôles qui filtrent
    selon `fonds_id` / `collection_id`.
    """

    type: Literal["base_complete", "fonds", "collection"]
    fonds_id: int | None
    collection_id: int | None
    fonds_count: int
    collections_count: int
    items_count: int
    fichiers_count: int


@dataclass(frozen=True)
class RapportQa:
    """Rapport complet d'un run qa."""

    version_qa: str
    horodatage: datetime
    perimetre: PerimetreControle
    controles: tuple[ResultatControle, ...]

    def _compter_severite(self, sev: Severite) -> int:
        return sum(
            1 for c in self.controles if c.severite == sev and not c.passe
        )

    @property
    def nb_erreurs(self) -> int:
        return self._compter_severite(Severite.ERREUR)

    @property
    def nb_avertissements(self) -> int:
        return self._compter_severite(Severite.AVERTISSEMENT)

    @property
    def nb_infos(self) -> int:
        return self._compter_severite(Severite.INFO)


# Limite par défaut du nombre d'exemples conservés par contrôle.
# Le compte total reste exact ; seul l'échantillon affiché est tronqué.
MAX_EXEMPLES_DEFAUT = 5


def borner_exemples(
    exemples: list[Exemple], max_exemples: int = MAX_EXEMPLES_DEFAUT
) -> tuple[Exemple, ...]:
    """Convertit la liste mutable construite par les contrôles en tuple
    figé, en bornant la taille."""
    return tuple(exemples[:max_exemples])


def construire_resultat(
    *,
    id: str,
    famille: str,
    severite: Severite,
    libelle: str,
    total: int,
    problemes: list[Exemple],
    compte_problemes: int | None = None,
) -> ResultatControle:
    """Assemble un `ResultatControle` à partir des conventions usuelles :

    - `passe = not problemes`
    - `compte_problemes = len(problemes)` (override possible si un
      contrôle compte différemment, ex. FILE-HASH-DUPLIQUE qui compte
      les fichiers concernés, pas les groupes)
    - `exemples` bornés à `MAX_EXEMPLES_DEFAUT`
    """
    return ResultatControle(
        id=id,
        famille=famille,
        severite=severite,
        libelle=libelle,
        passe=not problemes,
        compte_total=total,
        compte_problemes=compte_problemes if compte_problemes is not None else len(problemes),
        exemples=borner_exemples(problemes),
    )


# ---------------------------------------------------------------------------
# Filtrage par périmètre — partagé par les 4 familles de contrôles
# ---------------------------------------------------------------------------


def restreindre_aux_items(stmt, perimetre: PerimetreControle):
    """Restreint un `select(Item.…)` au périmètre.

    - fonds : `Item.fonds_id == perimetre.fonds_id`.
    - collection : `Item.id IN itemcollection(collection_id)`.
    - base : pas de filtre.
    """
    if perimetre.fonds_id is not None:
        return stmt.where(Item.fonds_id == perimetre.fonds_id)
    if perimetre.collection_id is not None:
        return stmt.where(
            Item.id.in_(
                select(ItemCollection.item_id).where(
                    ItemCollection.collection_id == perimetre.collection_id
                )
            )
        )
    return stmt


def restreindre_aux_fichiers(stmt, perimetre: PerimetreControle):
    """Restreint un `select(Fichier.…)` aux fichiers des items du périmètre.

    Utilise `Fichier.item_id IN (items du périmètre)` — pas de JOIN, pour
    rester compatible avec les SELECT agrégés et préserver le `GROUP BY`."""
    from archives_tool.models import Fichier  # noqa: PLC0415 — évite cycle

    if perimetre.fonds_id is not None:
        return stmt.where(
            Fichier.item_id.in_(
                select(Item.id).where(Item.fonds_id == perimetre.fonds_id)
            )
        )
    if perimetre.collection_id is not None:
        return stmt.where(
            Fichier.item_id.in_(
                select(ItemCollection.item_id).where(
                    ItemCollection.collection_id == perimetre.collection_id
                )
            )
        )
    return stmt
