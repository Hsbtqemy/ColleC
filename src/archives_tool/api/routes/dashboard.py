"""Routes web — dashboard + pages détail (fonds / collection / item).

Précédence sur les cotes ambiguës :
- `/fonds/{cote}` : recherche stricte par fonds.cote.
- `/collection/{cote}` : si la cote correspond à un fonds existant
  ET aucun `?fonds=` n'est précisé, redirige vers `/fonds/{cote}`.
  Le param `?fonds=COTE_FONDS` désambiguïse explicitement.
- `/item/{cote}` : `?fonds=COTE` est obligatoire (les cotes d'items
  ne sont uniques que par fonds).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from archives_tool.api.deps import get_db, get_nom_base, get_utilisateur_courant
from archives_tool.api.services.collections import (
    CollectionIntrouvable,
    lire_collection_par_cote,
)
from archives_tool.api.services.dashboard import composer_dashboard
from archives_tool.api.services.fonds import (
    FondsIntrouvable,
    lire_fonds_par_cote,
    lister_fonds,
)
from archives_tool.api.services.items import (
    ItemIntrouvable,
    lire_item_par_cote,
)
from archives_tool.api.templating import templates
from archives_tool.models import Fonds

router = APIRouter()


def _contexte_base(
    nom_base: str, utilisateur: str, **extra: object
) -> dict[str, object]:
    return {"nom_base": nom_base, "utilisateur": utilisateur, **extra}


@router.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request,
    db: Session = Depends(get_db),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse:
    resume = composer_dashboard(db)
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        _contexte_base(nom_base, utilisateur, resume=resume),
    )


@router.get("/fonds", response_class=HTMLResponse)
def liste_fonds(
    request: Request,
    db: Session = Depends(get_db),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse:
    """Vue liste sobre des fonds (alternative au dashboard)."""
    fonds = lister_fonds(db)
    return templates.TemplateResponse(
        request,
        "pages/fonds_liste.html",
        _contexte_base(nom_base, utilisateur, fonds=fonds),
    )


@router.get("/fonds/{cote}", response_class=HTMLResponse)
def page_fonds(
    cote: str,
    request: Request,
    db: Session = Depends(get_db),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse:
    """Affiche un fonds (titre + métadonnées ; tableau d'items à venir)."""
    try:
        fonds = lire_fonds_par_cote(db, cote)
    except FondsIntrouvable as e:
        raise HTTPException(
            status_code=404, detail=f"Fonds {cote!r} introuvable."
        ) from e
    return templates.TemplateResponse(
        request,
        "pages/_placeholder_fonds.html",
        _contexte_base(nom_base, utilisateur, fonds=fonds),
    )


@router.get("/collection/{cote}", response_class=HTMLResponse, response_model=None)
def page_collection(
    cote: str,
    request: Request,
    fonds: str | None = Query(
        None, description="Cote du fonds pour désambiguïser une cote partagée."
    ),
    db: Session = Depends(get_db),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse | RedirectResponse:
    """Affiche une collection (titre + type ; tableau d'items à venir).

    Précédence cote ambiguë : si `cote` matche un fonds et qu'aucun
    `?fonds=` n'est passé, redirige vers `/fonds/{cote}` (le cas
    typique : la cote d'une miroir = la cote de son fonds).
    """
    if fonds is None:
        fonds_meme_cote = db.scalar(select(Fonds).where(Fonds.cote == cote))
        if fonds_meme_cote is not None:
            return RedirectResponse(f"/fonds/{cote}", status_code=303)

    fonds_id: int | None = None
    if fonds is not None:
        try:
            fonds_id = lire_fonds_par_cote(db, fonds).id
        except FondsIntrouvable as e:
            raise HTTPException(
                status_code=404, detail=f"Fonds {fonds!r} introuvable."
            ) from e
    try:
        collection = lire_collection_par_cote(db, cote, fonds_id=fonds_id)
    except CollectionIntrouvable as e:
        raise HTTPException(
            status_code=404, detail=f"Collection {cote!r} introuvable."
        ) from e
    return templates.TemplateResponse(
        request,
        "pages/_placeholder_collection.html",
        _contexte_base(nom_base, utilisateur, collection=collection),
    )


@router.get("/item/{cote}", response_class=HTMLResponse)
def page_item(
    cote: str,
    request: Request,
    fonds: str = Query(
        ..., description="Cote du fonds (obligatoire : les cotes d'items ne sont uniques que par fonds)."
    ),
    db: Session = Depends(get_db),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse:
    """Affiche un item (titre + cote ; visionneuse + métadonnées à venir)."""
    try:
        fonds_obj = lire_fonds_par_cote(db, fonds)
    except FondsIntrouvable as e:
        raise HTTPException(
            status_code=404, detail=f"Fonds {fonds!r} introuvable."
        ) from e
    try:
        item = lire_item_par_cote(db, cote, fonds_id=fonds_obj.id)
    except ItemIntrouvable as e:
        raise HTTPException(
            status_code=404, detail=f"Item {cote!r} introuvable."
        ) from e
    return templates.TemplateResponse(
        request,
        "pages/_placeholder_item.html",
        _contexte_base(
            nom_base, utilisateur, item=item, fonds_cote=fonds_obj.cote
        ),
    )
