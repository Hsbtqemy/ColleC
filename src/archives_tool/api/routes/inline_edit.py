"""Édition inline des champs item (cartouche métadonnées).

Réponse au handoff V0.7 : les hooks `[data-edit-field]` /
`[data-value]` sont posés depuis le départ dans le markup ; cette
route câble le JS au backend.

Whitelist stricte de champs : seules les valeurs simples sont
éditables inline. La cote, le fonds_id, l'état de catalogage et la
version restent gérés par la page `/item/{cote}/modifier` complète
(le changement de cote touche les chemins, l'état porte des
implications workflow, etc.).
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
from archives_tool.api.services.conflits import ConflitVersion
from archives_tool.api.services.fonds import FondsIntrouvable, lire_fonds_par_cote
from archives_tool.api.services.items import (
    FormulaireItem,
    ItemIntrouvable,
    ItemInvalide,
    formulaire_depuis_item,
    lire_item_par_cote,
    modifier_item,
)
from archives_tool.api.templating import templates

router = APIRouter()


# Whitelist des champs éditables inline. Mappe la clé HTTP au nom de
# l'attribut du formulaire (généralement identique). Tout ce qui n'est
# pas listé ici est refusé en 403.
CHAMPS_EDITABLES_INLINE: frozenset[str] = frozenset(
    {
        "titre",
        "date",
        "annee",
        "langue",
        "type_coar",
        "numero",
        "description",
        "notes_internes",
        "doi_nakala",
        "doi_collection_nakala",
    }
)


def _resoudre_item(db: Session, cote: str, fonds_cote: str):
    try:
        fonds_obj = lire_fonds_par_cote(db, fonds_cote)
    except FondsIntrouvable as e:
        raise HTTPException(
            status_code=404, detail=f"Fonds {fonds_cote!r} introuvable."
        ) from e
    try:
        item = lire_item_par_cote(db, cote, fonds_id=fonds_obj.id)
    except ItemIntrouvable as e:
        raise HTTPException(
            status_code=404, detail=f"Item {cote!r} introuvable dans {fonds_cote}."
        ) from e
    return item, fonds_obj


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
    if field not in CHAMPS_EDITABLES_INLINE:
        raise HTTPException(
            status_code=403, detail=f"Champ {field!r} non éditable inline."
        )

    item, _fonds_obj = _resoudre_item(db, cote, fonds)
    # Pré-remplit le formulaire avec l'état actuel, change uniquement
    # le champ ciblé. modifier_item gère le verrou + l'incrément.
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

    return templates.TemplateResponse(
        request,
        "partials/inline_edit_valeur.html",
        {"item": item_modifie, "field": field},
    )
