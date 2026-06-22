"""Page Journal (traçabilité, lecture seule).

Surface en UI les trois journaux que les services métier alimentent déjà
mais qui n'étaient consultables qu'en CLI : suppressions d'entités, push
de fichiers Nakala, batchs de renommage. Aucune mutation — la page est
purement consultative (sert la traçabilité, principe directeur n°4, et
prépare la confiance multi-utilisateurs de la V1.0).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from archives_tool.api.deps import (
    get_db,
    get_nom_base,
    get_utilisateur_courant,
)
from archives_tool.api.routes._helpers import contexte_base
from archives_tool.api.services.journal_web import composer_journal
from archives_tool.api.templating import templates

router = APIRouter()


@router.get("/journal", response_class=HTMLResponse)
def page_journal(
    request: Request,
    db: Session = Depends(get_db),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse:
    """Journal de traçabilité : suppressions, push Nakala, renommages."""
    vue = composer_journal(db)
    return templates.TemplateResponse(
        request,
        "pages/journal.html",
        contexte_base(nom_base, utilisateur, journal=vue),
    )
