"""Rapport qa au format JSON.

Structure documentée et stable pour intégration CI : pas de breaking
change avant V1.0. Si une évolution est nécessaire, bumper
`RapportQa.version_qa`.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime
from enum import Enum
from typing import Any

from archives_tool.qa._commun import RapportQa


def _serialize(obj: Any) -> Any:
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, Enum):
        return obj.value
    raise TypeError(f"Non sérialisable : {type(obj).__name__}")


def formatter_rapport_json(rapport: RapportQa, *, indent: int = 2) -> str:
    """Génère un rapport JSON déterministe.

    Le bilan est calculé côté Python via les `@property` du rapport ;
    on le matérialise dans le JSON pour éviter au consommateur de
    refaire les comptages."""
    data = asdict(rapport)
    data["bilan"] = {
        "erreurs": rapport.nb_erreurs,
        "avertissements": rapport.nb_avertissements,
        "infos": rapport.nb_infos,
    }
    return json.dumps(
        data, default=_serialize, indent=indent, ensure_ascii=False, sort_keys=False
    )
