"""Vue historique des batchs de renommage."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import func, select
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
    stmt = (
        select(
            OperationFichier.batch_id,
            func.count(OperationFichier.id).label("nb"),
            func.min(OperationFichier.execute_le).label("debut"),
            func.max(OperationFichier.execute_par).label("par"),
        )
        .where(OperationFichier.statut == StatutOperation.REUSSIE.value)
        .group_by(OperationFichier.batch_id)
        .order_by(func.min(OperationFichier.execute_le).desc())
        .limit(limite)
    )

    entrees: list[EntreeHistorique] = []
    for batch_id, nb, debut, par in session.execute(stmt).all():
        types = list(
            session.scalars(
                select(OperationFichier.type_operation)
                .where(OperationFichier.batch_id == batch_id)
                .distinct()
            ).all()
        )
        nb_annulees = (
            session.scalar(
                select(func.count(OperationFichier.id))
                .where(OperationFichier.batch_id == batch_id)
                .where(OperationFichier.annule_par_batch_id.is_not(None))
            )
            or 0
        )
        # Le batch d'annulation auquel appartient ce batch s'il a été annulé.
        annule_par = session.scalar(
            select(OperationFichier.annule_par_batch_id)
            .where(OperationFichier.batch_id == batch_id)
            .where(OperationFichier.annule_par_batch_id.is_not(None))
            .limit(1)
        )
        entrees.append(
            EntreeHistorique(
                batch_id=batch_id,
                nb_operations=nb,
                types_operations=types,
                execute_le_premier=debut,
                execute_par=par,
                annule_par_batch_id=annule_par,
                annule=(nb_annulees == nb),
            )
        )
    return entrees
