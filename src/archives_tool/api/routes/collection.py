"""Routes de la vue collection (3 onglets : sous-coll, items, fichiers).

Pattern « même route, deux modes » :
- accès direct (full reload) → page complète, bandeau + onglets ;
- accès via HTMX (`HX-Request`) → partiel, juste le contenu de
  l'onglet pour swap dans `#tab-content`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from archives_tool.api.deps import get_db, get_nom_base, get_utilisateur_courant
from archives_tool.api.services import collection as svc
from archives_tool.api.templating import rendre_avec_partial

router = APIRouter()


def _contexte_base(
    nom_base: str, utilisateur: str, detail: svc.CollectionDetail, onglet: str
) -> dict:
    return {
        "nom_base": nom_base,
        "utilisateur": utilisateur,
        "detail": detail,
        "onglet": onglet,
    }


def _charger_detail(db: Session, cote: str) -> svc.CollectionDetail:
    try:
        return svc.collection_detail(db, cote)
    except svc.CollectionIntrouvable:
        raise HTTPException(
            status_code=404, detail=f"Collection {cote!r} introuvable."
        ) from None


@router.get("/collection/{cote}")
def vue_collection_racine(cote: str) -> RedirectResponse:
    """Redirige vers l'onglet items (premier onglet par défaut)."""
    return RedirectResponse(url=f"/collection/{cote}/items", status_code=307)


@router.get("/collection/{cote}/items", response_class=HTMLResponse)
def vue_items(
    request: Request,
    cote: str,
    db: Session = Depends(get_db),
    utilisateur: str = Depends(get_utilisateur_courant),
    nom_base: str = Depends(get_nom_base),
) -> HTMLResponse:
    detail = _charger_detail(db, cote)
    contexte = _contexte_base(nom_base, utilisateur, detail, onglet="items")
    contexte["items"] = svc.lister_items(db, cote)
    return rendre_avec_partial(
        request,
        page_template="pages/collection_items.html",
        partial_template="partials/collection_items.html",
        contexte=contexte,
    )


@router.get("/collection/{cote}/sous-collections", response_class=HTMLResponse)
def vue_sous(
    request: Request,
    cote: str,
    db: Session = Depends(get_db),
    utilisateur: str = Depends(get_utilisateur_courant),
    nom_base: str = Depends(get_nom_base),
) -> HTMLResponse:
    detail = _charger_detail(db, cote)
    contexte = _contexte_base(nom_base, utilisateur, detail, onglet="sous")
    contexte["sous_collections"] = svc.lister_sous_collections(db, cote)
    return rendre_avec_partial(
        request,
        page_template="pages/collection_sous.html",
        partial_template="partials/collection_sous.html",
        contexte=contexte,
    )


@router.get("/collection/{cote}/fichiers", response_class=HTMLResponse)
def vue_fichiers(
    request: Request,
    cote: str,
    db: Session = Depends(get_db),
    utilisateur: str = Depends(get_utilisateur_courant),
    nom_base: str = Depends(get_nom_base),
) -> HTMLResponse:
    detail = _charger_detail(db, cote)
    contexte = _contexte_base(nom_base, utilisateur, detail, onglet="fichiers")
    contexte["fichiers"] = svc.lister_fichiers(db, cote)
    return rendre_avec_partial(
        request,
        page_template="pages/collection_fichiers.html",
        partial_template="partials/collection_fichiers.html",
        contexte=contexte,
    )
