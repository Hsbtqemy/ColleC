"""Route du tableau de bord."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from archives_tool.api.deps import (
    get_db,
    get_nom_base,
    get_racines,
    get_utilisateur_courant,
)
from archives_tool.api.services.dashboard import (
    calculer_statistiques_globales,
    lister_activite_recente,
    lister_collections_dashboard,
    lister_points_vigilance,
)
from archives_tool.api.templating import templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request,
    tri: str | None = None,
    ordre: Literal["asc", "desc"] = "desc",
    db: Session = Depends(get_db),
    utilisateur: str = Depends(get_utilisateur_courant),
    nom_base: str = Depends(get_nom_base),
    racines: dict[str, Path] = Depends(get_racines),
) -> HTMLResponse:
    statistiques = calculer_statistiques_globales(db)
    collections = lister_collections_dashboard(db, tri=tri, ordre=ordre)
    activite = lister_activite_recente(db)
    vigilance = lister_points_vigilance(db, racines=racines)

    contexte = {
        "utilisateur": utilisateur,
        "nom_base": nom_base,
        "statistiques": statistiques,
        "collections": collections,
        "activite": activite,
        "vigilance": vigilance,
    }

    # Sur HX-Request, renvoie le partial du tableau (swap interne au
    # dashboard quand l'utilisateur clique sur un en-tête de colonne).
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(
            request, "partials/dashboard_collections.html", contexte
        )
    return templates.TemplateResponse(request, "dashboard.html", contexte)
