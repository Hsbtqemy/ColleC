"""Route du tableau de bord."""

from __future__ import annotations

from pathlib import Path

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

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request,
    db: Session = Depends(get_db),
    utilisateur: str = Depends(get_utilisateur_courant),
    nom_base: str = Depends(get_nom_base),
    racines: dict[str, Path] = Depends(get_racines),
) -> HTMLResponse:
    from archives_tool.api.main import templates  # éviter import circulaire

    statistiques = calculer_statistiques_globales(db)
    collections = lister_collections_dashboard(db)
    activite = lister_activite_recente(db)
    vigilance = lister_points_vigilance(db, racines=racines)

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "utilisateur": utilisateur,
            "nom_base": nom_base,
            "statistiques": statistiques,
            "collections": collections,
            "activite": activite,
            "vigilance": vigilance,
        },
    )
