"""Vue historique des batchs de renommage."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from archives_tool.models import OperationFichier, StatutOperation


@dataclass
class EntreeHistorique:
    batch_id: str
    nb_operations: int
    types_operations: list[str] = field(default_factory=list)
    execute_le_premier: datetime | None = None
    execute_par: str | None = None
    annule_par_batch_id: str | None = None
    annule: bool = False


def lister_batchs(session: Session, *, limite: int = 50) -> list[EntreeHistorique]:
    """Liste les batchs en triant du plus récent au plus ancien.

    Un batch dont *toutes* les opérations originales ont un
    `annule_par_batch_id` non nul est considéré comme annulé.
    """
    nb_annulees = func.sum(
        case((OperationFichier.annule_par_batch_id.is_not(None), 1), else_=0)
    )
    stmt = (
        select(
            OperationFichier.batch_id,
            func.count(OperationFichier.id).label("nb"),
            func.min(OperationFichier.execute_le).label("debut"),
            func.max(OperationFichier.execute_par).label("par"),
            func.group_concat(OperationFichier.type_operation.distinct()).label(
                "types"
            ),
            nb_annulees.label("nb_annulees"),
            func.max(OperationFichier.annule_par_batch_id).label("annule_par"),
        )
        .where(OperationFichier.statut == StatutOperation.REUSSIE.value)
        .group_by(OperationFichier.batch_id)
        .order_by(func.min(OperationFichier.execute_le).desc())
        .limit(limite)
    )

    entrees: list[EntreeHistorique] = []
    for batch_id, nb, debut, par, types, nb_ann, annule_par in session.execute(
        stmt
    ).all():
        types_list = sorted((types or "").split(",")) if types else []
        entrees.append(
            EntreeHistorique(
                batch_id=batch_id,
                nb_operations=nb,
                types_operations=types_list,
                execute_le_premier=debut,
                execute_par=par,
                annule_par_batch_id=annule_par,
                annule=(nb_ann == nb),
            )
        )
    return entrees
