"""Routes du panneau de configuration des colonnes (vue items).

Trois endpoints :
- GET  /preferences/colonnes/items/{collection_id}        → modale ouverte
- POST /preferences/colonnes/items/{collection_id}        → sauvegarde + tableau swap
- POST /preferences/colonnes/items/{collection_id}/reset  → reset défauts + tableau swap

Le swap HTMX renvoie le partial `partials/collection_items.html`. Le
serveur émet `HX-Trigger: panneau-colonnes-ferme` pour fermer la
modale côté client.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from archives_tool.api.deps import get_db, get_utilisateur_courant
from archives_tool.api.services import preferences as svc
from archives_tool.api.services.items import lister_items_collection
from archives_tool.api.templating import templates
from archives_tool.models import Collection

router = APIRouter()


def _charger_collection_par_id(db: Session, collection_id: int) -> Collection:
    col = db.scalar(select(Collection).where(Collection.id == collection_id))
    if col is None:
        raise HTTPException(status_code=404, detail="Collection introuvable.")
    return col


@router.get("/preferences/colonnes/items/{collection_id}", response_class=HTMLResponse)
def ouvrir_panneau_colonnes(
    request: Request,
    collection_id: int,
    db: Session = Depends(get_db),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse:
    """Rend le panneau (modale) avec les vraies données contextuelles."""
    col = _charger_collection_par_id(db, collection_id)
    prefs = svc.lire_preferences_colonnes(db, utilisateur, collection_id, "items")
    # La modale a toujours besoin de la liste complète des métadonnées
    # disponibles, peu importe les préférences en cours.
    disponibles = svc.colonnes_disponibles_items(db, collection_id)
    actives = svc.resoudre_colonnes_actives(prefs.colonnes_ordonnees, disponibles)
    actifs_noms = {c.nom for c in actives}
    return templates.TemplateResponse(
        request,
        "components/panneau_colonnes_modale.html",
        {
            "collection": col,
            "actives": actives,
            "disponibles_dediees": [
                c for c in disponibles["dediees"] if c.nom not in actifs_noms
            ],
            "disponibles_metadonnees": [
                c for c in disponibles["metadonnees"] if c.nom not in actifs_noms
            ],
            "par_defaut": prefs.par_defaut,
        },
    )


def _re_render_tableau(
    request: Request,
    db: Session,
    utilisateur: str,
    col: Collection,
) -> HTMLResponse:
    """Rend le partial du tableau items mis à jour, avec HX-Trigger.

    Le swap repart à la page 1 sans filtre — la modale colonnes ne
    transporte pas l'état de filtre/pagination.
    """
    resolu = svc.charger_colonnes_actives(db, utilisateur, col.id, "items")
    listage = lister_items_collection(db, col.id, page=1, par_page=50)
    response = templates.TemplateResponse(
        request,
        "partials/collection_items.html",
        {
            "items": listage,
            "cote": col.cote,
            "colonnes_actives": resolu.actives,
            "collection_id": col.id,
        },
    )
    response.headers["HX-Trigger"] = "panneau-colonnes-ferme"
    return response


@router.post("/preferences/colonnes/items/{collection_id}", response_class=HTMLResponse)
def sauvegarder_panneau_colonnes(
    request: Request,
    collection_id: int,
    colonnes: list[str] | None = Form(default=None),
    db: Session = Depends(get_db),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse:
    col = _charger_collection_par_id(db, collection_id)
    disponibles = svc.colonnes_disponibles_items(db, collection_id)
    try:
        svc.sauvegarder_preferences_colonnes(
            db,
            utilisateur,
            collection_id,
            "items",
            colonnes or [],
            metas_valides=svc.metas_valides_pour(disponibles),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    return _re_render_tableau(request, db, utilisateur, col)


@router.post(
    "/preferences/colonnes/items/{collection_id}/reset",
    response_class=HTMLResponse,
)
def reinitialiser_panneau_colonnes(
    request: Request,
    collection_id: int,
    db: Session = Depends(get_db),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse:
    col = _charger_collection_par_id(db, collection_id)
    svc.reinitialiser_preferences_colonnes(db, utilisateur, collection_id, "items")
    return _re_render_tableau(request, db, utilisateur, col)
