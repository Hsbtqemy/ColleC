"""Routes de la vue collection (3 onglets : items, sous-coll., fichiers).

Pattern « même route, deux modes » :
- accès direct (full reload) → page complète, bandeau + onglets ;
- accès via HTMX (`HX-Request`) → partiel, juste le contenu de
  l'onglet pour swap dans `#tab-content`.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from archives_tool.api.deps import get_db, get_nom_base, get_utilisateur_courant
from archives_tool.api.services import collection as svc
from archives_tool.api.templating import templates

router = APIRouter()


# Onglet (slug URL) → (clé du contenu dans le contexte, fonction de listing).
# La clé sert aussi à composer le nom de partial (`collection_<cle>.html`).
_ONGLETS: dict[str, tuple[str, Callable[[Session, str], list]]] = {
    "items": ("items", svc.lister_items),
    "sous-collections": ("sous_collections", svc.lister_sous_collections),
    "fichiers": ("fichiers", svc.lister_fichiers),
}


@router.get("/collection/{cote}")
def vue_collection_racine(cote: str) -> RedirectResponse:
    """Redirige vers l'onglet items (premier onglet par défaut)."""
    return RedirectResponse(url=f"/collection/{cote}/items", status_code=307)


@router.get("/collection/{cote}/{onglet}", response_class=HTMLResponse)
def vue_collection(
    request: Request,
    cote: str,
    onglet: Literal["items", "sous-collections", "fichiers"],
    db: Session = Depends(get_db),
    utilisateur: str = Depends(get_utilisateur_courant),
    nom_base: str = Depends(get_nom_base),
) -> HTMLResponse:
    cle, lister = _ONGLETS[onglet]
    try:
        listing = lister(db, cote)
    except svc.CollectionIntrouvable:
        raise HTTPException(
            status_code=404, detail=f"Collection {cote!r} introuvable."
        ) from None

    partial_template = f"partials/collection_{cle}.html"
    contexte: dict = {cle: listing}

    # Sur HX-Request, seul le partiel est renvoyé : on évite le
    # détail (header + 4 requêtes d'agrégat) qui n'apparaît pas
    # dans le swap.
    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(request, partial_template, contexte)

    contexte.update(
        nom_base=nom_base,
        utilisateur=utilisateur,
        detail=svc.collection_detail(db, cote),
        onglet=onglet,
        partial_template=partial_template,
    )
    return templates.TemplateResponse(request, "pages/collection.html", contexte)
