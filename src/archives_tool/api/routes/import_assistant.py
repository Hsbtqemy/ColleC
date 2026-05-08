"""Routes de l'assistant d'import (V0.7).

Le menu déroulant du dashboard pointe vers `/import`. La page
complète (upload, mappings, fichiers, aperçu, exécution) est
livrée par étapes — V0.7-alpha sert un placeholder qui guide
l'utilisateur vers la CLI en attendant.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from archives_tool.api.deps import get_nom_base, get_utilisateur_courant
from archives_tool.api.templating import templates

router = APIRouter()


@router.get("/import", response_class=HTMLResponse)
def page_import(
    request: Request,
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "pages/import_placeholder.html",
        {"nom_base": nom_base, "utilisateur": utilisateur},
    )
