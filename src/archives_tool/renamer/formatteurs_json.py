"""Sérialisation JSON des rapports du module renamer.

Parité avec `qa` et `montrer` : chaque commande CLI a un mode
`--format json` qui produit un payload structuré, déterministe,
consommable par un script de CI ou un wrapper supérieur.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from typing import Any

from .historique import EntreeHistorique
from .rapport import RapportAnnulation, RapportExecution, RapportPlan


def _serialize(obj: Any) -> Any:
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Non sérialisable : {type(obj).__name__}")


def _dumps(payload: dict[str, Any], indent: int) -> str:
    return json.dumps(
        payload,
        default=_serialize,
        indent=indent,
        ensure_ascii=False,
        sort_keys=False,
    )


def formatter_plan_json(rapport: RapportPlan, *, indent: int = 2) -> str:
    """Sérialise un `RapportPlan` (sortie de `construire_plan`)."""
    data = asdict(rapport)
    data["bilan"] = {
        "nb_renommages": rapport.nb_renommages,
        "nb_no_op": rapport.nb_no_op,
        "nb_bloques": rapport.nb_bloques,
        "applicable": rapport.applicable,
    }
    return _dumps(data, indent)


def formatter_execution_json(rapport: RapportExecution, *, indent: int = 2) -> str:
    """Sérialise un `RapportExecution` (sortie de `executer_plan`)."""
    return _dumps(asdict(rapport), indent)


def formatter_annulation_json(rapport: RapportAnnulation, *, indent: int = 2) -> str:
    """Sérialise un `RapportAnnulation` (sortie de `annuler_batch`)."""
    return _dumps(asdict(rapport), indent)


def formatter_historique_json(
    entrees: list[EntreeHistorique], *, indent: int = 2
) -> str:
    """Sérialise la liste des batchs renvoyée par `lister_batchs`."""
    return _dumps({"batchs": [asdict(e) for e in entrees]}, indent)
