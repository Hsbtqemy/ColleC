"""Édition inline d'un champ item (cartouche métadonnées).

Whitelist stricte de champs simples : cote, fonds_id, etat_catalogage
et version restent gérés par la page `/item/{cote}/modifier` complète
(la cote touche aux chemins, l'état porte des implications workflow,
le fonds_id est immuable, la version est purement technique).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from archives_tool.api.deps import (
    get_db,
    get_utilisateur_courant,
)
from archives_tool.api.routes._helpers import resoudre_item_ou_404
from archives_tool.api.services.conflits import ConflitVersion
from archives_tool.api.services.dashboard import (
    CHAMPS_ITEM_EDITABLES_INLINE,
    libelle_pour_valeur,
)
from archives_tool.api.services.vocabulaires import OPTIONS_PAR_CHAMP
from archives_tool.api.services.items import (
    ItemInvalide,
    formulaire_depuis_item,
    modifier_item,
)
from archives_tool.api.templating import templates

router = APIRouter()


@router.post(
    "/item/{cote}/champ/{field}",
    response_class=HTMLResponse,
    response_model=None,
)
def soumettre_edition_inline(
    cote: str,
    field: str,
    request: Request,
    fonds: Annotated[str, Query(...)],
    version: Annotated[int, Form(...)],
    valeur: Annotated[str, Form()] = "",
    db: Session = Depends(get_db),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse:
    """Modifie un seul champ. Retourne :
    - 200 + fragment HTML pour swap dans `[data-value]` ;
    - 409 + fragment d'erreur si la version est périmée ;
    - 400 + fragment d'erreur si la valeur est invalide ;
    - 403 si le champ n'est pas dans la whitelist.
    """
    if field not in CHAMPS_ITEM_EDITABLES_INLINE:
        raise HTTPException(
            status_code=403, detail=f"Champ {field!r} non éditable inline."
        )

    item, _fonds_obj = resoudre_item_ou_404(db, cote, fonds)
    formulaire = formulaire_depuis_item(item)
    formulaire.version = version
    setattr(formulaire, field, valeur)

    try:
        item_modifie = modifier_item(db, item.id, formulaire, modifie_par=utilisateur)
    except ConflitVersion as e:
        return templates.TemplateResponse(
            request,
            "partials/inline_edit_conflit.html",
            {"field": field, "exc": e, "valeur": valeur},
            status_code=409,
        )
    except ItemInvalide as e:
        return templates.TemplateResponse(
            request,
            "partials/inline_edit_erreur.html",
            {"field": field, "erreurs": e.erreurs, "valeur": valeur},
            status_code=400,
        )

    # Pour les champs à vocabulaire, on renvoie le libellé humain
    # (« Texte » plutôt que l'URI COAR) avec la valeur brute stockée
    # dans `data-edit-raw` pour que la prochaine édition pré-remplisse
    # correctement le <select>.
    options = OPTIONS_PAR_CHAMP.get(field)
    valeur_brute = getattr(item_modifie, field, None)
    valeur_affichee = libelle_pour_valeur(valeur_brute, options)
    return templates.TemplateResponse(
        request,
        "partials/inline_edit_valeur.html",
        {
            "item": item_modifie,
            "field": field,
            "valeur_brute": valeur_brute,
            "valeur_affichee": valeur_affichee,
            "vocabulaire": options is not None,
        },
    )
