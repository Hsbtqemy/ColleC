"""Famille 4 — cohérence cross-entités.

Les contrôles de cette famille opèrent toujours sur la base entière,
même si le périmètre est restreint à un fonds/collection : la
duplication de cote ou un fonds vide sont des problèmes globaux dont
la détection ne dépend pas du périmètre.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from archives_tool.models import Fonds, Item
from archives_tool.qa._commun import (
    Exemple,
    PerimetreControle,
    ResultatControle,
    Severite,
    borner_exemples,
)

FAMILLE = "cross"


def controler_cross_cote_dupliquee_fonds(
    db: Session, perimetre: PerimetreControle
) -> ResultatControle:
    """CROSS-COTE-DUPLIQUEE-FONDS : deux fonds avec la même cote.

    L'index UNIQUE sur Fonds.cote rend ce cas impossible via API ; ce
    contrôle est un filet pour les bases manipulées hors API. Toujours
    sur la base entière (l'unicité est globale)."""
    rows = db.execute(
        select(Fonds.cote, func.count(Fonds.id).label("nb"))
        .group_by(Fonds.cote)
        .having(func.count(Fonds.id) > 1)
        .order_by(Fonds.cote)
    ).all()
    nb_fonds = db.scalar(select(func.count(Fonds.id))) or 0
    problemes = [
        Exemple(
            message=f"Cote de fonds dupliquée : {cote!r} apparaît {nb} fois",
            references={"fonds_cote": cote, "nb": nb},
        )
        for cote, nb in rows
    ]
    return ResultatControle(
        id="CROSS-COTE-DUPLIQUEE-FONDS",
        famille=FAMILLE,
        severite=Severite.ERREUR,
        libelle="Cotes de fonds uniques globalement",
        passe=not problemes,
        compte_total=nb_fonds,
        compte_problemes=len(problemes),
        exemples=borner_exemples(problemes),
    )


def controler_cross_fonds_vide(
    db: Session, perimetre: PerimetreControle
) -> ResultatControle:
    """CROSS-FONDS-VIDE : fonds sans aucun item (info).

    Cas légitime (fonds en cours d'import, fonds réservé à l'avance)
    mais signalé pour information."""
    rows = db.execute(
        select(Fonds.id, Fonds.cote, func.count(Item.id).label("nb"))
        .outerjoin(Item, Item.fonds_id == Fonds.id)
        .group_by(Fonds.id, Fonds.cote)
        .order_by(Fonds.cote)
    ).all()
    problemes = [
        Exemple(
            message=f"Fonds {cote} sans aucun item",
            references={"fonds_cote": cote, "fonds_id": fid},
        )
        for fid, cote, nb in rows
        if nb == 0
    ]
    return ResultatControle(
        id="CROSS-FONDS-VIDE",
        famille=FAMILLE,
        severite=Severite.INFO,
        libelle="Fonds peuplé d'au moins un item",
        passe=not problemes,
        compte_total=len(rows),
        compte_problemes=len(problemes),
        exemples=borner_exemples(problemes),
    )
