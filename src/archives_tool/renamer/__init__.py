"""Renommage transactionnel des fichiers.

Pipeline en quatre temps :
1. `template.py` : évaluation d'un template de nommage canonique.
2. `plan.py` : construction du plan de renommage et détection des
   conflits (intra-batch, externes, cycles).
3. `execution.py` : exécution transactionnelle avec rollback
   compensateur en cas d'erreur disque mid-batch.
4. `annulation.py` : retour en arrière d'un batch déjà appliqué via
   son `batch_id`.

Le journal est tenu dans `OperationFichier`, partagé avec d'autres
opérations destructives sur fichiers.
"""

from __future__ import annotations

from .annulation import annuler_batch
from .execution import executer_plan
from .plan import Perimetre, construire_plan
from .rapport import (
    CodeConflit,
    Conflit,
    OperationRenommage,
    RapportAnnulation,
    RapportExecution,
    RapportPlan,
    StatutPlan,
)
from .formatteurs_json import (
    formatter_annulation_json,
    formatter_execution_json,
    formatter_historique_json,
    formatter_plan_json,
)
from .template import EchecTemplate, evaluer_template

__all__ = [
    "annuler_batch",
    "executer_plan",
    "construire_plan",
    "evaluer_template",
    "formatter_annulation_json",
    "formatter_execution_json",
    "formatter_historique_json",
    "formatter_plan_json",
    "Perimetre",
    "EchecTemplate",
    "CodeConflit",
    "Conflit",
    "OperationRenommage",
    "RapportAnnulation",
    "RapportExecution",
    "RapportPlan",
    "StatutPlan",
]
