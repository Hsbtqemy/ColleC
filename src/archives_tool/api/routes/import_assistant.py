"""Routes de l'assistant d'import (V0.7).

Le menu déroulant du dashboard pointe vers `/import`. La page
complète (upload, mappings, fichiers, aperçu, exécution) est
livrée par étapes — V0.7-alpha sert un placeholder qui guide
l'utilisateur vers la CLI en attendant.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from archives_tool.api.templating import templates

router = APIRouter()


@router.get("/import", response_class=HTMLResponse)
def page_import(request: Request) -> HTMLResponse:
    """Placeholder V0.7 — la page complète de l'assistant arrivera
    par étapes. Pas de deps utilisateur/base : la page ne les rend pas.
    """
    return templates.TemplateResponse(request, "pages/import_placeholder.html", {})
