"""Routes du panneau de configuration des colonnes (vue items).

Trois endpoints :
- GET  /preferences/colonnes/items/{collection_id}      → modale ouverte
- POST /preferences/colonnes/items/{collection_id}      → sauvegarde + tableau swap
- POST /preferences/colonnes/items/{collection_id}/reset → reset défauts + tableau swap

V0.6.3 — onglet items uniquement. La validation côté serveur est
déléguée au service (whitelist par catégorie). Réponse au POST :
le tableau d'items mis à jour, avec un en-tête `HX-Trigger`
`panneau-colonnes-ferme` que le JS écoute pour fermer la modale.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from archives_tool.api.deps import get_db, get_utilisateur_courant
from archives_tool.api.services import collection as svc_collection
from archives_tool.api.services import preferences as svc
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
    """Rend le partial du tableau items mis à jour, avec HX-Trigger."""
    prefs = svc.lire_preferences_colonnes(db, utilisateur, col.id, "items")
    disponibles = svc.colonnes_disponibles_items(db, col.id)
    actives = svc.resoudre_colonnes_actives(prefs.colonnes_ordonnees, disponibles)
    listing = svc_collection.lister_items(
        db, col.cote_collection, colonnes=[c.nom for c in actives]
    )
    response = templates.TemplateResponse(
        request,
        "partials/collection_items.html",
        {
            "items": listing,
            "cote": col.cote_collection,
            "colonnes_actives": actives,
            "collection_id": col.id,
        },
    )
    response.headers["HX-Trigger"] = "panneau-colonnes-ferme"
    return response


@router.post("/preferences/colonnes/items/{collection_id}", response_class=HTMLResponse)
def sauvegarder_panneau_colonnes(
    request: Request,
    collection_id: int,
    colonnes: list[str] = Form(default=[]),
    db: Session = Depends(get_db),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse:
    col = _charger_collection_par_id(db, collection_id)
    metas = svc.metas_valides_pour(svc.colonnes_disponibles_items(db, collection_id))
    try:
        svc.sauvegarder_preferences_colonnes(
            db,
            utilisateur,
            collection_id,
            "items",
            colonnes,
            metas_valides=metas,
        )
    except ValueError as e:
        # Liste totalement invalide après filtrage.
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
