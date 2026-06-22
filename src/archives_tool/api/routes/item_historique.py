"""Historique des modifications d'un item (chargement paresseux HTMX).

`ModificationItem` est alimenté par `modifier_item` (inline + page
Modifier) ; cette route le surface en fragment, chargé à la demande
depuis la fiche item pour ne pas peser sur `composer_page_item`.
Lecture seule (GET) — consultable même en mode lecture seule.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from archives_tool.api.deps import get_db
from archives_tool.api.routes._helpers import resoudre_item_ou_404
from archives_tool.api.services.items import lister_modifications_item
from archives_tool.api.templating import templates

router = APIRouter()


@router.get("/item/{cote}/historique", response_class=HTMLResponse)
def historique_item(
    cote: str,
    request: Request,
    fonds: Annotated[str, Query(...)],
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Fragment HTMX : tableau des modifications de l'item, récentes d'abord."""
    item, _fonds_obj = resoudre_item_ou_404(db, cote, fonds)
    modifications = lister_modifications_item(db, item.id)
    return templates.TemplateResponse(
        request,
        "partials/item_historique.html",
        {"modifications": modifications},
    )
