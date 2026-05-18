"""Helpers partagés entre routers web : contexte de rendu et
résolution d'entités → 404 propre."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from archives_tool.api.services.fonds import (
    FondsIntrouvable,
    lire_fonds_par_cote,
)
from archives_tool.api.services.import_web import (
    SessionImportIntrouvable,
    lire_session,
)
from archives_tool.api.services.items import (
    ItemIntrouvable,
    lire_item_par_cote,
)
from archives_tool.models import Fonds, Item, SessionImport


def contexte_base(
    nom_base: str, utilisateur: str, **extra: object
) -> dict[str, object]:
    """Contexte minimal commun à tous les templates de page : nom de la
    base courante + utilisateur (rendus dans le header de `base.html`)."""
    return {"nom_base": nom_base, "utilisateur": utilisateur, **extra}


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


def charger_session_import_ou_404(
    db: Session, session_id: int
) -> SessionImport:
    """Charge une session d'import par id. Lève 404 si absente."""
    try:
        return lire_session(db, session_id)
    except SessionImportIntrouvable as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
