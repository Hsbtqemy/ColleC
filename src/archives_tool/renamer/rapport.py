"""Dataclasses du plan et des rapports de renommage."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field


class StatutPlan(enum.StrEnum):
    PRET = "pret"  # nom cible calculé, pas de conflit
    NO_OP = "no_op"  # cible == source, rien à faire
    EN_CYCLE = "en_cycle"  # appartient à un cycle (résolu via pivot)
    BLOQUE = "bloque"  # conflit non résoluble (collision, template KO)


@dataclass
class OperationRenommage:
    fichier_id: int
    racine: str
    chemin_avant: str
    chemin_apres: str
    statut: StatutPlan = StatutPlan.PRET
    raison: str | None = None


@dataclass
class Conflit:
    """Anomalie détectée à la construction du plan."""

    code: str  # 'collision_intra_batch' | 'collision_externe' | 'template_invalide'
    message: str
    fichier_ids: list[int] = field(default_factory=list)


@dataclass
class RapportPlan:
    operations: list[OperationRenommage] = field(default_factory=list)
    conflits: list[Conflit] = field(default_factory=list)
    duree_secondes: float = 0.0

    @property
    def nb_renommages(self) -> int:
        return sum(
            1
            for op in self.operations
            if op.statut in (StatutPlan.PRET, StatutPlan.EN_CYCLE)
        )

    @property
    def nb_no_op(self) -> int:
        return sum(1 for op in self.operations if op.statut == StatutPlan.NO_OP)

    @property
    def nb_bloques(self) -> int:
        return sum(1 for op in self.operations if op.statut == StatutPlan.BLOQUE)

    @property
    def applicable(self) -> bool:
        """True si l'exécution peut être lancée (aucun conflit critique)."""
        return not self.conflits and self.nb_bloques == 0


@dataclass
class RapportExecution:
    dry_run: bool
    batch_id: str | None = None
    operations_reussies: int = 0
    operations_echouees: int = 0
    operations_compensees: int = 0
    erreurs: list[str] = field(default_factory=list)
    duree_secondes: float = 0.0


@dataclass
class RapportAnnulation:
    dry_run: bool
    batch_id_original: str
    batch_id_annulation: str | None = None
    operations_inversees: int = 0
    operations_echouees: int = 0
    erreurs: list[str] = field(default_factory=list)
    duree_secondes: float = 0.0
