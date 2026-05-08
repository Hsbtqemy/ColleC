"""Routes de la vue collection (3 onglets : items, sous-coll., fichiers).

Pattern « même route, deux modes » :
- accès direct (full reload) → page complète, bandeau + onglets ;
- accès via HTMX (`HX-Request`) → partiel, juste le contenu de
  l'onglet pour swap dans `#tab-content` ou sur le tableau lui-même.

`tri`, `ordre`, `page` et les filtres sont validés via whitelist côté
service (cf. `services/tri.py` et helpers `appliquer_filtres_*`) —
toute valeur hors whitelist retombe sur le défaut sans erreur.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from archives_tool.api.deps import get_db, get_nom_base, get_utilisateur_courant
from archives_tool.api.services import collection as svc
from archives_tool.api.templating import templates

router = APIRouter()


def _csv(valeur: str | None) -> list[str] | None:
    if not valeur:
        return None
    items = [v.strip() for v in valeur.split(",") if v.strip()]
    return items or None


@router.get("/collection/{cote}")
def vue_collection_racine(cote: str) -> RedirectResponse:
    """Redirige vers l'onglet items (premier onglet par défaut)."""
    return RedirectResponse(url=f"/collection/{cote}/items", status_code=307)


@router.get("/collection/{cote}/{onglet}", response_class=HTMLResponse)
def vue_collection(
    request: Request,
    cote: str,
    onglet: Literal["items", "sous-collections", "fichiers"],
    tri: str | None = None,
    ordre: Literal["asc", "desc"] = "asc",
    page: int = 1,
    # Filtres items
    etat: str | None = None,
    type: str | None = None,  # noqa: A002 (paramètre URL, shadow voulu)
    annee_debut: int | None = None,
    annee_fin: int | None = None,
    q: str | None = None,
    # Filtres fichiers
    type_page: str | None = None,
    format: str | None = None,  # noqa: A002
    db: Session = Depends(get_db),
    utilisateur: str = Depends(get_utilisateur_courant),
    nom_base: str = Depends(get_nom_base),
) -> HTMLResponse:
    try:
        if onglet == "items":
            partial = "partials/collection_items.html"
            cle = "items"
            listing = svc.lister_items(
                db, cote,
                tri=tri, ordre=ordre, page=page,
                etat=_csv(etat),
                type_coar=_csv(type),
                annee_debut=annee_debut, annee_fin=annee_fin,
                q=q,
            )
        elif onglet == "fichiers":
            partial = "partials/collection_fichiers.html"
            cle = "fichiers"
            listing = svc.lister_fichiers(
                db, cote,
                tri=tri, ordre=ordre, page=page,
                etat=_csv(etat),
                type_page=_csv(type_page),
                format=_csv(format),
                q=q,
            )
        else:  # sous-collections
            partial = "partials/collection_sous_collections.html"
            cle = "sous_collections"
            listing = svc.lister_sous_collections(db, cote)
    except svc.CollectionIntrouvable:
        raise HTTPException(
            status_code=404, detail=f"Collection {cote!r} introuvable."
        ) from None

    contexte: dict = {cle: listing, "cote": cote}

    if request.headers.get("HX-Request"):
        return templates.TemplateResponse(request, partial, contexte)

    contexte.update(
        nom_base=nom_base,
        utilisateur=utilisateur,
        detail=svc.collection_detail(db, cote),
        onglet=onglet,
        partial_template=partial,
    )
    return templates.TemplateResponse(request, "pages/collection.html", contexte)
