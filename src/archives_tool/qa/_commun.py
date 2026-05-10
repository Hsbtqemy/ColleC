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


class Severite(str, enum.Enum):
    """Gravité d'un contrôle qui ne passe pas.

    L'ordre de déclaration sert au tri des rapports (erreurs d'abord).
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
    """Périmètre du contrôle + compteurs globaux pour le bandeau de tête."""

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
