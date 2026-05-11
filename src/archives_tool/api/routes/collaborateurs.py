# Archivé V0.8 — non mounté. Voir api/main.py.
"""Routes HTMX de gestion des collaborateurs d'une collection (archivé).

Toutes les routes :
- exigent une collection existante (404 sinon, via
  `_charger_collection_ou_404`) ;
- sont conçues pour HTMX (réponses fragments, swap in-place) ;
- vérifient que le collaborateur appartient bien à la collection
  donnée (anti-confused-deputy) avant toute mutation.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from archives_tool.api.deps import get_db
from archives_tool.api.services import collaborateurs as svc
from archives_tool.api.templating import templates
from archives_tool.models import (
    Collection,
    CollaborateurCollection,
    LIBELLES_ROLE,
    RoleCollaborateur,
)

router = APIRouter()


def _charger_collection_ou_404(db: Session, cote: str) -> Collection:
    """Charge une collection par cote ou 404 (premier match, cote non
    globalement unique — module non mounté, le comportement dégradé
    n'a aucune conséquence en prod).
    """
    col = db.scalar(select(Collection).where(Collection.cote == cote))
    if col is None:
        raise HTTPException(status_code=404, detail="Collection introuvable.")
    return col

ROLES_OPTIONS: list[str] = [r.value for r in RoleCollaborateur]


def _collaborateur_appartenant(
    db: Session, collaborateur_id: int, collection_id: int
) -> CollaborateurCollection:
    c = db.get(CollaborateurCollection, collaborateur_id)
    if c is None or c.collection_id != collection_id:
        raise HTTPException(status_code=404, detail="Collaborateur introuvable.")
    return c


def _contexte_section(db: Session, cote: str, collection_id: int) -> dict:
    return {
        "collection_cote": cote,
        "groupes_par_role": svc.lister_collaborateurs_par_role(db, collection_id),
    }


def _contexte_formulaire(
    cote: str,
    formulaire: svc.FormulaireCollaborateur,
    erreurs: dict[str, str],
    mode: Literal["ajouter", "modifier"],
    collaborateur_id: int | None,
) -> dict:
    return {
        "collection_cote": cote,
        "formulaire": formulaire,
        "erreurs": erreurs,
        "mode": mode,
        "collaborateur_id": collaborateur_id,
        "roles_options": ROLES_OPTIONS,
        "libelles_roles": LIBELLES_ROLE,
    }


def _reponse_section(
    request: Request, db: Session, cote: str, collection_id: int
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "components/section_collaborateurs.html",
        _contexte_section(db, cote, collection_id),
    )


def _reponse_formulaire_avec_erreurs(
    request: Request,
    cote: str,
    formulaire: svc.FormulaireCollaborateur,
    erreurs: dict[str, str],
    mode: Literal["ajouter", "modifier"],
    collaborateur_id: int | None,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "partials/_formulaire_collaborateur.html",
        _contexte_formulaire(cote, formulaire, erreurs, mode, collaborateur_id),
        status_code=400,
    )


@router.get("/collection/{cote}/collaborateurs", response_class=HTMLResponse)
def section_collaborateurs(
    request: Request, cote: str, db: Session = Depends(get_db)
) -> HTMLResponse:
    """Section complète, utilisée pour le swap HTMX après save/delete."""
    col = _charger_collection_ou_404(db, cote)
    return _reponse_section(request, db, cote, col.id)


@router.get("/collection/{cote}/collaborateurs/nouveau", response_class=HTMLResponse)
def formulaire_nouveau(
    request: Request, cote: str, db: Session = Depends(get_db)
) -> HTMLResponse:
    """Fragment HTML du formulaire vide, à insérer dans `#formulaire-collaborateur`."""
    _charger_collection_ou_404(db, cote)
    return templates.TemplateResponse(
        request,
        "partials/_formulaire_collaborateur.html",
        _contexte_formulaire(cote, svc.FormulaireCollaborateur(), {}, "ajouter", None),
    )


@router.get(
    "/collection/{cote}/collaborateurs/{collaborateur_id}/modifier",
    response_class=HTMLResponse,
)
def formulaire_modifier(
    request: Request,
    cote: str,
    collaborateur_id: int,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Fragment formulaire pré-rempli."""
    col = _charger_collection_ou_404(db, cote)
    c = _collaborateur_appartenant(db, collaborateur_id, col.id)
    formulaire = svc.FormulaireCollaborateur(
        nom=c.nom,
        roles=list(c.roles or []),
        periode=c.periode or "",
        notes=c.notes or "",
    )
    return templates.TemplateResponse(
        request,
        "partials/_formulaire_collaborateur.html",
        _contexte_formulaire(cote, formulaire, {}, "modifier", collaborateur_id),
    )


@router.post("/collection/{cote}/collaborateurs", response_class=HTMLResponse)
def ajouter(
    request: Request,
    cote: str,
    formulaire: Annotated[svc.FormulaireCollaborateur, Form()],
    db: Session = Depends(get_db),
) -> HTMLResponse:
    col = _charger_collection_ou_404(db, cote)
    try:
        svc.ajouter_collaborateur(db, col.id, formulaire)
    except svc.CollaborateurInvalide as e:
        return _reponse_formulaire_avec_erreurs(
            request, cote, formulaire, e.erreurs, "ajouter", None
        )
    return _reponse_section(request, db, cote, col.id)


@router.post(
    "/collection/{cote}/collaborateurs/{collaborateur_id}",
    response_class=HTMLResponse,
)
def modifier(
    request: Request,
    cote: str,
    collaborateur_id: int,
    formulaire: Annotated[svc.FormulaireCollaborateur, Form()],
    db: Session = Depends(get_db),
) -> HTMLResponse:
    col = _charger_collection_ou_404(db, cote)
    _collaborateur_appartenant(db, collaborateur_id, col.id)
    try:
        svc.modifier_collaborateur(db, collaborateur_id, formulaire)
    except svc.CollaborateurInvalide as e:
        return _reponse_formulaire_avec_erreurs(
            request, cote, formulaire, e.erreurs, "modifier", collaborateur_id
        )
    return _reponse_section(request, db, cote, col.id)


@router.post(
    "/collection/{cote}/collaborateurs/{collaborateur_id}/supprimer",
    response_class=HTMLResponse,
)
def supprimer(
    request: Request,
    cote: str,
    collaborateur_id: int,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    col = _charger_collection_ou_404(db, cote)
    _collaborateur_appartenant(db, collaborateur_id, col.id)
    svc.supprimer_collaborateur(db, collaborateur_id)
    return _reponse_section(request, db, cote, col.id)
