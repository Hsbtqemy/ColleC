"""Routes de l'assistant d'import web (V0.7).

Sous-étape 1 : cycle de vie d'une `SessionImport` — page d'accueil
(liste des imports en cours + bouton nouvel import), création,
abandon. Les étapes du wizard (upload tableur, fonds, mapping,
fichiers, aperçu) sont livrées par les sous-étapes suivantes.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from archives_tool.api.deps import get_db, get_nom_base, get_utilisateur_courant
from archives_tool.api.routes._helpers import (
    charger_session_import_ou_404,
    contexte_base as _contexte_base,
)
from archives_tool.api.services.import_web import (
    abandonner_session,
    creer_session,
    lister_sessions_en_cours,
)
from archives_tool.api.templating import templates

router = APIRouter()


@router.get("/import", response_class=HTMLResponse)
def page_import(
    request: Request,
    db: Session = Depends(get_db),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse:
    """Accueil de l'assistant : imports en cours + démarrer un import."""
    sessions = lister_sessions_en_cours(db)
    return templates.TemplateResponse(
        request,
        "pages/import_accueil.html",
        _contexte_base(nom_base, utilisateur, sessions=sessions),
    )


@router.post("/import/nouveau", response_class=HTMLResponse, response_model=None)
def nouveau_import(
    db: Session = Depends(get_db),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> RedirectResponse:
    """Crée une session d'import vierge et ouvre sa première étape."""
    session = creer_session(db, utilisateur)
    return RedirectResponse(f"/import/{session.id}", status_code=303)


@router.get("/import/{session_id}", response_class=HTMLResponse)
def page_session_import(
    session_id: int,
    request: Request,
    db: Session = Depends(get_db),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse:
    """Vue d'une session d'import. Sous-étape 1 : stub affichant
    l'étape courante. Le wizard complet arrive aux sous-étapes 2-4."""
    session = charger_session_import_ou_404(db, session_id)
    return templates.TemplateResponse(
        request,
        "pages/import_session.html",
        _contexte_base(nom_base, utilisateur, session=session),
    )


@router.post(
    "/import/{session_id}/abandonner",
    response_class=HTMLResponse,
    response_model=None,
)
def abandonner_import(
    session_id: int,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Abandonne une session : statut `abandonnee`, tableur temporaire
    supprimé. Idempotent."""
    session = charger_session_import_ou_404(db, session_id)
    abandonner_session(db, session)
    return RedirectResponse("/import", status_code=303)
