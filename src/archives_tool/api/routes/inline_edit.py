"""Édition inline d'un champ item (cartouche métadonnées).

Whitelist stricte (cf. `CHAMPS_ITEM_EDITABLES_INLINE`). Restent
exclus et gérés par la page `/item/{cote}/modifier` complète :
- `cote` : touche aux chemins fichiers (renommage)
- `fonds_id` : immuable (suppression + recréation pour déplacer)
- `version` : purement technique (verrou optimiste)
- champs personnalisés JSON : nécessitent une UI dédiée
  (vocabulaires, listes)

`etat_catalogage` est inclus dans l'inline depuis V0.9.3 — workflow
de vérification en série (cf. dashboard.CHAMPS_ITEM_EDITABLES_INLINE).
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
from archives_tool.api.services.champs_personnalises import (
    lister_champs_actifs_pour_item,
)
from archives_tool.api.services.conflits import ConflitVersion
from archives_tool.api.services.dashboard import CHAMPS_ITEM_EDITABLES_INLINE
from archives_tool.api.services.vocabulaires import resoudre_vocabulaire
from archives_tool.api.services.vocabulaires_db import (
    options_depuis_vocabulaire,
)
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
    item, _fonds_obj = resoudre_item_ou_404(db, cote, fonds)

    # V0.9.4 inline-edit-champs-perso : un `field` est valide soit
    # via la whitelist DC core, soit via les ChampPersonnalise actifs
    # des collections de l'item. On distingue les deux pour router
    # l'ecriture (setattr vs metadonnees) et la resolution de
    # libelle humain (OPTIONS_PAR_CHAMP hardcoded vs vocab DB).
    champ_perso = None
    if field not in CHAMPS_ITEM_EDITABLES_INLINE:
        for c in lister_champs_actifs_pour_item(db, item.id):
            if c.cle == field and c.type != "liste_multiple":
                champ_perso = c
                break
        if champ_perso is None:
            raise HTTPException(
                status_code=403, detail=f"Champ {field!r} non éditable inline."
            )

    # `formulaire_depuis_item` initialise deja
    # `formulaire.metadonnees = dict(item.metadonnees)` -> on modifie
    # cette copie sans craindre d'ecraser les autres cles (cf. fix
    # bug observe sur PF-002 dans /modifier — preservation).
    formulaire = formulaire_depuis_item(item)
    formulaire.version = version
    if champ_perso is None:
        setattr(formulaire, field, valeur)
    elif valeur:
        formulaire.metadonnees[field] = valeur
    else:
        formulaire.metadonnees.pop(field, None)

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
    if champ_perso is None:
        valeur_brute = getattr(item_modifie, field, None)
        options, valeur_affichee = resoudre_vocabulaire(field, valeur_brute)
    else:
        # Champ perso : valeur dans metadonnees, vocab via DB.
        valeur_brute = (item_modifie.metadonnees or {}).get(field)
        options = None
        valeur_affichee = valeur_brute
        if champ_perso.vocabulaire is not None:
            options = options_depuis_vocabulaire(champ_perso.vocabulaire)
            for code, libelle in options:
                if code == valeur_brute:
                    valeur_affichee = libelle
                    break
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
