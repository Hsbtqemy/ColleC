"""Page Contrôles de cohérence (`/controler`, lecture seule).

Surface en UI le module `qa` (14 contrôles invariants / fichiers /
métadonnées / cross), jusque-là consultable uniquement en CLI
(`archives-tool controler`). Aucune mutation : la page se contente
d'exécuter la suite (read-only garanti) et de la rendre.

Périmètre : base entière (défaut) ou `?fonds=COTE`. Le périmètre
collection reste CLI-only (cf. `services/controle_web`).
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from archives_tool.api.deps import (
    get_db,
    get_nom_base,
    get_racines,
    get_utilisateur_courant,
)
from archives_tool.api.routes._helpers import charger_fonds_ou_404, contexte_base
from archives_tool.api.services.controle_web import composer_page_controle
from archives_tool.api.templating import templates

router = APIRouter()


@router.get("/controler", response_class=HTMLResponse)
def page_controler(
    request: Request,
    fonds: Annotated[str | None, Query()] = None,
    db: Session = Depends(get_db),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
    racines: dict[str, Path] = Depends(get_racines),
) -> HTMLResponse:
    """Bilan de santé de la base (lecture seule). `?fonds=COTE` restreint
    le périmètre à un fonds ; sans paramètre, contrôle la base entière."""
    # Une cote vide (`?fonds=`) équivaut à « base entière ». `charger_fonds_ou_404`
    # gère le 404 (helper partagé) — le composeur reçoit l'entité résolue.
    fonds_obj = charger_fonds_ou_404(db, fonds) if fonds else None
    vue = composer_page_controle(db, racines=racines, fonds=fonds_obj)
    return templates.TemplateResponse(
        request,
        "pages/controle.html",
        contexte_base(nom_base, utilisateur, vue=vue),
    )
