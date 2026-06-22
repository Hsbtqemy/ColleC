"""Changement rapide d'état d'un item depuis le tableau de collection.

Quick-action « workflow de vérification en série » : parcourir une
collection et faire passer les items brouillon → à vérifier → vérifié →
validé sans ouvrir chaque fiche.

Trois temps, tout en HTMX (aucun JS dédié) :
- `GET  /item/{cote}/etat`           → ouvre l'éditeur (<select>), version
  lue **fraîche** à cet instant (fenêtre de conflit ≈ durée du menu) ;
- `GET  /item/{cote}/etat?annuler=1` → reswap le badge sans rien écrire ;
- `POST /item/{cote}/etat`           → applique l'état via `modifier_item`
  (donc journalisé `ModificationItem` + verrou optimiste) et reswap le
  badge.

Le POST est bloqué 423 par le middleware en lecture seule ; le déclencheur
▾ est en outre masqué côté template (`etat_editable=false`). La validation
de l'état est explicite ici car `setattr` sur le formulaire Pydantic ne
relance pas le `field_validator` (`validate_assignment` désactivé).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from archives_tool.api.deps import est_lecture_seule, get_db, get_utilisateur_courant
from archives_tool.api.routes._helpers import resoudre_item_ou_404
from archives_tool.api.services.conflits import ConflitVersion
from archives_tool.api.services.items import (
    ItemInvalide,
    formulaire_depuis_item,
    modifier_item,
)
from archives_tool.api.services.vocabulaires import ETATS_OPTIONS
from archives_tool.api.templating import templates

router = APIRouter()

#: Codes acceptés au POST = exactement ceux que le `<select>` propose.
#: Lier la validation à l'offre (plutôt qu'au seul enum `EtatCatalogage`)
#: empêche de poser via un POST forgé un état que l'UI ne propose pas.
_CODES_OFFERTS: frozenset[str] = frozenset(code for code, _ in ETATS_OPTIONS)


def _fragment_affichage(
    request: Request, item, fonds_cote: str, *, note: str = ""
) -> HTMLResponse:
    """Rend la cellule en mode badge (déclencheur ▾ si pas en lecture seule)."""
    return templates.TemplateResponse(
        request,
        "partials/etat_cellule.html",
        {
            "item_id": item.id,
            "cote": item.cote,
            "fonds_cote": fonds_cote,
            "etat": item.etat_catalogage,
            "editable": not est_lecture_seule(),
            "note": note,
        },
    )


@router.get("/item/{cote}/etat", response_class=HTMLResponse, response_model=None)
def ouvrir_editeur_etat(
    cote: str,
    request: Request,
    fonds: Annotated[str, Query(...)],
    annuler: Annotated[bool, Query()] = False,
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Ouvre l'éditeur d'état (`<select>`) ou, si `annuler`, reswap le badge.

    La version du verrou optimiste est lue ici, fraîche, et embarquée dans
    l'éditeur — minimise la fenêtre de conflit avec une édition concurrente.
    """
    item, fonds_obj = resoudre_item_ou_404(db, cote, fonds)
    if annuler:
        return _fragment_affichage(request, item, fonds_obj.cote)
    return templates.TemplateResponse(
        request,
        "partials/etat_editeur.html",
        {
            "item_id": item.id,
            "cote": item.cote,
            "fonds_cote": fonds_obj.cote,
            "etat": item.etat_catalogage,
            "version": item.version,
            "etats_options": ETATS_OPTIONS,
        },
    )


@router.post("/item/{cote}/etat", response_class=HTMLResponse, response_model=None)
def changer_etat(
    cote: str,
    request: Request,
    fonds: Annotated[str, Query(...)],
    version: Annotated[int, Form(...)],
    valeur: Annotated[str, Form(...)],
    db: Session = Depends(get_db),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse:
    """Applique le nouvel état et reswap le badge.

    - état hors vocabulaire → 400 (le `<select>` ne propose que des codes
      valides ; garde-fou contre un POST forgé, car `setattr` contourne le
      validateur Pydantic) ;
    - conflit de version (édition concurrente pendant l'ouverture du menu)
      → badge **rechargé** depuis la base avec une note, plutôt qu'une
      erreur 409 invisible (HTMX ne swap pas les réponses 4xx).
    """
    item, fonds_obj = resoudre_item_ou_404(db, cote, fonds)
    if valeur not in _CODES_OFFERTS:
        raise HTTPException(status_code=400, detail=f"État inconnu : {valeur!r}.")

    formulaire = formulaire_depuis_item(item)
    formulaire.version = version
    formulaire.etat_catalogage = valeur
    try:
        item = modifier_item(db, item.id, formulaire, modifie_par=utilisateur)
    except ConflitVersion:
        # On a muté l'item en session avant le contrôle de version ;
        # rollback puis relecture pour afficher l'état réel courant.
        db.rollback()
        item, fonds_obj = resoudre_item_ou_404(db, cote, fonds)
        return _fragment_affichage(
            request,
            item,
            fonds_obj.cote,
            note="État rechargé — modifié entre-temps.",
        )
    except ItemInvalide as e:
        raise HTTPException(status_code=400, detail=str(e.erreurs)) from e

    return _fragment_affichage(request, item, fonds_obj.cote)
