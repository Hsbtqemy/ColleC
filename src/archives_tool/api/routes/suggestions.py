"""Endpoint d'autocomplete : suggestions de valeurs existantes (Lot 3 UI⁺).

Consommé par `inline_edit.js` pour attacher un `<datalist>` aux champs
libres marqués `data-edit-suggest="<type>:<champ>"`. Lecture seule ; la
whitelist des colonnes vit dans `services/suggestions.py`.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from archives_tool.api.deps import get_db
from archives_tool.api.services.suggestions import suggerer_valeurs

router = APIRouter()


@router.get("/api/suggestions")
def get_suggestions(
    type: Annotated[str, Query()],
    champ: Annotated[str, Query()],
    q: Annotated[str, Query()] = "",
    db: Session = Depends(get_db),
) -> list[str]:
    """Valeurs existantes pour (type, champ) — whitelisté ; `[]` sinon."""
    return suggerer_valeurs(db, type_entite=type, champ=champ, prefixe=q)
