"""Étiquettes colorées (Lot 4b UI⁺) : page de gestion + étiquetage des items.

- Gestion `/etiquettes` : créer / renommer-recolorer / supprimer (PRG,
  comme `/vocabulaires`).
- Étiquetage : attacher / détacher une étiquette sur un item depuis sa
  fiche, en HTMX (la section se rafraîchit sans recharger la page).

Tout est bloqué en lecture seule par le middleware ; les contrôles sont
en outre masqués côté template.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from archives_tool.api.deps import (
    get_db,
    get_nom_base,
    get_utilisateur_courant,
)
from archives_tool.api.routes._helpers import contexte_base, resoudre_item_ou_404
from archives_tool.api.services.etiquettes import (
    PALETTE_ETIQUETTES,
    EtiquetteIntrouvable,
    EtiquetteInvalide,
    FormulaireEtiquette,
    creer_etiquette,
    etiqueter_item,
    etiquettes_courantes_et_disponibles,
    lister_etiquettes,
    modifier_etiquette,
    retirer_etiquette_item,
    supprimer_etiquette,
)
from archives_tool.api.templating import templates

router = APIRouter()


# ---------------------------------------------------------------------------
# Gestion des étiquettes (page autonome)
# ---------------------------------------------------------------------------


@router.get("/etiquettes", response_class=HTMLResponse)
def page_etiquettes(
    request: Request,
    db: Session = Depends(get_db),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse:
    """Liste des étiquettes + formulaire de création."""
    return templates.TemplateResponse(
        request,
        "pages/etiquettes.html",
        contexte_base(
            nom_base,
            utilisateur,
            etiquettes=lister_etiquettes(db),
            palette=PALETTE_ETIQUETTES,
            formulaire=FormulaireEtiquette(),
            erreurs={},
        ),
    )


@router.post("/etiquettes/creer", response_class=HTMLResponse, response_model=None)
def soumettre_creer_etiquette(
    request: Request,
    formulaire: Annotated[FormulaireEtiquette, Form()],
    db: Session = Depends(get_db),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse | RedirectResponse:
    try:
        creer_etiquette(db, formulaire, cree_par=utilisateur)
    except EtiquetteInvalide as e:
        return templates.TemplateResponse(
            request,
            "pages/etiquettes.html",
            contexte_base(
                nom_base,
                utilisateur,
                etiquettes=lister_etiquettes(db),
                palette=PALETTE_ETIQUETTES,
                formulaire=formulaire,
                erreurs=e.erreurs,
            ),
            status_code=400,
        )
    return RedirectResponse("/etiquettes", status_code=303)


@router.post(
    "/etiquettes/{etiquette_id}/modifier",
    response_class=HTMLResponse,
    response_model=None,
)
def soumettre_modifier_etiquette(
    etiquette_id: int,
    request: Request,
    formulaire: Annotated[FormulaireEtiquette, Form()],
    db: Session = Depends(get_db),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse | RedirectResponse:
    try:
        modifier_etiquette(db, etiquette_id, formulaire)
    except EtiquetteIntrouvable as e:
        raise HTTPException(status_code=404, detail="Étiquette introuvable.") from e
    except EtiquetteInvalide as e:
        return templates.TemplateResponse(
            request,
            "pages/etiquettes.html",
            contexte_base(
                nom_base,
                utilisateur,
                etiquettes=lister_etiquettes(db),
                palette=PALETTE_ETIQUETTES,
                formulaire=FormulaireEtiquette(),
                erreurs=e.erreurs,
            ),
            status_code=400,
        )
    return RedirectResponse("/etiquettes", status_code=303)


@router.post(
    "/etiquettes/{etiquette_id}/supprimer",
    response_class=HTMLResponse,
    response_model=None,
)
def soumettre_supprimer_etiquette(
    etiquette_id: int,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    try:
        supprimer_etiquette(db, etiquette_id)
    except EtiquetteIntrouvable as e:
        raise HTTPException(status_code=404, detail="Étiquette introuvable.") from e
    return RedirectResponse("/etiquettes", status_code=303)


# ---------------------------------------------------------------------------
# Étiquetage d'un item (HTMX, depuis la fiche)
# ---------------------------------------------------------------------------


def _fragment_section(
    request: Request, item, fonds_cote: str, db: Session
) -> HTMLResponse:
    courantes, disponibles = etiquettes_courantes_et_disponibles(db, item.id)
    return templates.TemplateResponse(
        request,
        "partials/item_etiquettes.html",
        {
            "item": item,
            "fonds_cote": fonds_cote,
            "etiquettes": courantes,
            "etiquettes_disponibles": disponibles,
        },
    )


@router.post(
    "/item/{cote}/etiquettes",
    response_class=HTMLResponse,
    response_model=None,
)
def attacher_etiquette(
    cote: str,
    request: Request,
    fonds: Annotated[str, Query(...)],
    etiquette_id: Annotated[int, Form(...)],
    db: Session = Depends(get_db),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse:
    """Attache une étiquette à l'item → fragment de section rafraîchi."""
    item, fonds_obj = resoudre_item_ou_404(db, cote, fonds)
    try:
        etiqueter_item(db, item.id, etiquette_id, ajoute_par=utilisateur)
    except EtiquetteIntrouvable as e:
        raise HTTPException(status_code=404, detail="Étiquette introuvable.") from e
    return _fragment_section(request, item, fonds_obj.cote, db)


@router.post(
    "/item/{cote}/etiquettes/{etiquette_id}/retirer",
    response_class=HTMLResponse,
    response_model=None,
)
def detacher_etiquette(
    cote: str,
    etiquette_id: int,
    request: Request,
    fonds: Annotated[str, Query(...)],
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Détache une étiquette de l'item → fragment de section rafraîchi."""
    item, fonds_obj = resoudre_item_ou_404(db, cote, fonds)
    retirer_etiquette_item(db, item.id, etiquette_id)
    return _fragment_section(request, item, fonds_obj.cote, db)
