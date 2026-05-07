"""Route de la vue item (trois zones : fichiers, visionneuse, métadonnées)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from archives_tool.api.deps import get_db, get_nom_base, get_utilisateur_courant
from archives_tool.api.services import item as svc
from archives_tool.api.templating import templates

router = APIRouter()


@router.get("/item/{cote}", response_class=HTMLResponse)
def vue_item(
    request: Request,
    cote: str,
    collection: str | None = None,
    fichier: int | None = None,
    db: Session = Depends(get_db),
    utilisateur: str = Depends(get_utilisateur_courant),
    nom_base: str = Depends(get_nom_base),
) -> HTMLResponse:
    """`?collection=` désambiguïse si la cote item n'est pas unique.

    `?fichier=<id>` permet de pré-sélectionner un fichier dans la
    visionneuse (URL bookmarkable après JS swap côté client).
    """
    try:
        detail = svc.item_detail(db, cote, collection_cote=collection)
    except svc.ItemIntrouvable:
        raise HTTPException(
            status_code=404, detail=f"Item {cote!r} introuvable."
        ) from None

    sources_par_id = {
        f.id: {
            "primary": f.source.primary,
            "fallback": f.source.fallback,
        }
        for f in detail.fichiers
    }

    return templates.TemplateResponse(
        request,
        "pages/item.html",
        {
            "nom_base": nom_base,
            "utilisateur": utilisateur,
            "detail": detail,
            "fichier_initial_id": fichier,
            "sources_par_id": sources_par_id,
        },
    )
