"""Helpers partagés entre routers web : résolution d'entités → 404 propre."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from archives_tool.api.services.fonds import (
    FondsIntrouvable,
    lire_fonds_par_cote,
)
from archives_tool.api.services.items import (
    ItemIntrouvable,
    lire_item_par_cote,
)
from archives_tool.models import Fonds, Item


def charger_fonds_ou_404(db: Session, cote: str) -> Fonds:
    try:
        return lire_fonds_par_cote(db, cote)
    except FondsIntrouvable as e:
        raise HTTPException(
            status_code=404, detail=f"Fonds {cote!r} introuvable."
        ) from e


def resoudre_item_ou_404(
    db: Session, cote: str, fonds_cote: str
) -> tuple[Item, Fonds]:
    """Charge un item par (cote, fonds_cote). Lève 404 si l'un des deux
    est introuvable."""
    fonds_obj = charger_fonds_ou_404(db, fonds_cote)
    try:
        return lire_item_par_cote(db, cote, fonds_id=fonds_obj.id), fonds_obj
    except ItemIntrouvable as e:
        raise HTTPException(
            status_code=404, detail=f"Item {cote!r} introuvable."
        ) from e
