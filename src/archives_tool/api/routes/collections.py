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

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from archives_tool.api.deps import get_db, get_nom_base, get_utilisateur_courant
from archives_tool.api.services import collection as svc_col
from archives_tool.api.services import collections_creation as svc
from archives_tool.api.templating import templates
from archives_tool.models import PhaseChantier

router = APIRouter()


@router.get("/collections/nouvelle", response_class=HTMLResponse)
def formulaire_nouvelle_collection(
    request: Request,
    parent: str | None = None,
    db: Session = Depends(get_db),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse:
    """`?parent=COTE` pré-remplit le champ « Collection parente ».

    Si la cote ne correspond à aucune collection existante, le champ
    est laissé vide (silencieusement — l'utilisateur saisira ce qu'il
    veut).
    """
    formulaire = svc.FormulaireCollection()
    if parent:
        parent_existant = svc.lire_collection_par_cote(db, parent.strip())
        if parent_existant is not None:
            formulaire.parent_cote = parent_existant.cote_collection
    return templates.TemplateResponse(
        request,
        "pages/collection_nouvelle.html",
        {
            "nom_base": nom_base,
            "utilisateur": utilisateur,
            "formulaire": formulaire,
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


# ---------------------------------------------------------------------------
# Modification d'une collection existante (V0.7.x)
# ---------------------------------------------------------------------------


def _charger_pour_edition(db: Session, cote: str):
    col = svc.lire_collection_par_cote(db, cote)
    if col is None:
        raise HTTPException(status_code=404, detail=f"Collection {cote!r} introuvable.")
    return col


@router.get("/collection/{cote}/modifier", response_class=HTMLResponse)
def formulaire_modifier_collection(
    request: Request,
    cote: str,
    db: Session = Depends(get_db),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse:
    col = _charger_pour_edition(db, cote)
    return templates.TemplateResponse(
        request,
        "pages/collection_modifier.html",
        {
            "nom_base": nom_base,
            "utilisateur": utilisateur,
            "collection": col,
            "formulaire": svc.formulaire_depuis_collection(col),
            "erreurs": {},
            "phases": list(PhaseChantier),
            "crumbs": svc_col.fil_ariane_collection(col, page_courante="Modifier"),
        },
    )


@router.post("/collection/{cote}/modifier", response_class=HTMLResponse)
def modifier_collection_post(
    request: Request,
    cote: str,
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
    col = _charger_pour_edition(db, cote)
    # La cote n'est jamais lue depuis le formulaire — verrouillée par
    # design. Toute valeur envoyée est ignorée silencieusement.
    formulaire = svc.FormulaireCollection(
        cote=col.cote_collection,
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
    res = svc.valider_modification(db, col, formulaire)
    if not res.ok:
        return templates.TemplateResponse(
            request,
            "pages/collection_modifier.html",
            {
                "nom_base": nom_base,
                "utilisateur": utilisateur,
                "collection": col,
                "formulaire": formulaire,
                "erreurs": res.erreurs,
                "phases": list(PhaseChantier),
                "crumbs": svc_col.fil_ariane_collection(col, page_courante="Modifier"),
            },
            status_code=400,
        )
    svc.modifier_collection(
        db, col, formulaire, modifie_par=utilisateur, parent=res.parent_resolu
    )
    return RedirectResponse(url=f"/collection/{cote}/items", status_code=303)
