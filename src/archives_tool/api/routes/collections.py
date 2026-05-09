"""Routes de création / édition de collections (V0.7+).

À distinguer de `routes/collection.py` (singulier) qui gère la vue
détail d'une collection. Ici, opérations sur la ressource elle-même :
création, plus tard édition / suppression.

Pas d'HTMX swap pour le formulaire de création : on submet en POST
classique et on re-rend la page entière avec les erreurs si la
validation échoue (plus simple, marche sans JS, redirect en cas
de succès).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from archives_tool.api.deps import get_db, get_nom_base, get_utilisateur_courant
from archives_tool.api.services import collections_creation as svc
from archives_tool.api.templating import templates
from archives_tool.models import PhaseChantier

router = APIRouter()


@router.get("/collections/nouvelle", response_class=HTMLResponse)
def formulaire_nouvelle_collection(
    request: Request,
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "pages/collection_nouvelle.html",
        {
            "nom_base": nom_base,
            "utilisateur": utilisateur,
            "formulaire": svc.FormulaireCollection(),
            "erreurs": {},
            "phases": list(PhaseChantier),
        },
    )


@router.post("/collections", response_class=HTMLResponse)
def creer_collection_post(
    request: Request,
    cote: str = Form(default=""),
    titre: str = Form(default=""),
    description: str = Form(default=""),
    description_interne: str = Form(default=""),
    editeur: str = Form(default=""),
    lieu_edition: str = Form(default=""),
    personnalite_associee: str = Form(default=""),
    responsable_archives: str = Form(default=""),
    date_debut: str = Form(default=""),
    date_fin: str = Form(default=""),
    phase: str = Form(default="catalogage"),
    parent_cote: str = Form(default=""),
    doi_nakala: str = Form(default=""),
    db: Session = Depends(get_db),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse:
    formulaire = svc.FormulaireCollection(
        cote=cote,
        titre=titre,
        description=description,
        description_interne=description_interne,
        editeur=editeur,
        lieu_edition=lieu_edition,
        personnalite_associee=personnalite_associee,
        responsable_archives=responsable_archives,
        date_debut=date_debut,
        date_fin=date_fin,
        phase=phase,
        parent_cote=parent_cote,
        doi_nakala=doi_nakala,
    )
    res = svc.valider_formulaire(db, formulaire)
    if not res.ok:
        return templates.TemplateResponse(
            request,
            "pages/collection_nouvelle.html",
            {
                "nom_base": nom_base,
                "utilisateur": utilisateur,
                "formulaire": formulaire,
                "erreurs": res.erreurs,
                "phases": list(PhaseChantier),
            },
            status_code=400,
        )
    col = svc.creer_collection(
        db, formulaire, cree_par=utilisateur, parent=res.parent_resolu
    )
    return RedirectResponse(url=f"/collection/{col.cote_collection}", status_code=303)
