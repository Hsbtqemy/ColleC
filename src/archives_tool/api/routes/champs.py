"""Gestion structurelle des champs personnalisés d'une collection (V0.9.4).

Routes web pour créer / modifier / renommer / déprécier les
``ChampPersonnalise`` d'une collection. Cible : combler le gap V0.7
backlog (l'import dumpait jusqu'ici toutes les colonnes hors socle
DC en clés libres dans ``Item.metadonnees``, sans aucun moyen de les
formaliser depuis l'UI).

Le rename propage la nouvelle clé dans ``Item.metadonnees`` de tous
les items de la collection (cf. ``renommer_champ``).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from archives_tool.api.deps import (
    get_db,
    get_nom_base,
    get_utilisateur_courant,
)
from archives_tool.api.routes._helpers import (
    contexte_base as _contexte_base,
    resoudre_collection_ou_404,
    resoudre_item_ou_404,
)
from archives_tool.api.services.champs_personnalises import (
    ChampInvalide,
    CleNonPromouvable,
    FormulaireChamp,
    champ_par_id,
    creer_champ,
    deprecier_champ,
    formulaire_depuis_champ,
    lister_champs,
    modifier_champ,
    promouvoir_cle_libre_en_champ,
    reactiver_champ,
    renommer_champ,
    supprimer_champ,
)
from archives_tool.api.services.vocabulaires_db import lister_vocabulaires
from archives_tool.api.templating import templates
from archives_tool.models import ChampPersonnalise, TypeChamp

router = APIRouter()


def _url_champs(cote: str, fonds: str | None) -> str:
    return f"/collection/{cote}/champs" + (f"?fonds={fonds}" if fonds else "")


def _valider_appartenance(champ: ChampPersonnalise, collection_id: int) -> None:
    """Garde anti-confused-deputy : un POST sur
    ``/collection/COTE_A/champs/ID`` où l'ID appartient en réalité à
    la collection B doit être rejeté en 404. Sinon un utilisateur qui
    bricole l'URL pourrait modifier un champ d'une autre collection."""
    if champ.collection_id != collection_id:
        raise HTTPException(
            status_code=404,
            detail=f"Champ {champ.id} introuvable sur cette collection.",
        )


@router.get(
    "/collection/{cote}/champs",
    response_class=HTMLResponse,
    response_model=None,
)
def page_champs(
    cote: str,
    request: Request,
    fonds: str | None = Query(None),
    db: Session = Depends(get_db),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse:
    """Page de gestion : liste les champs (actifs et dépréciés) +
    formulaire de création en bas."""
    collection = resoudre_collection_ou_404(db, cote, fonds)
    champs = lister_champs(db, collection.id, inclure_deprecies=True)
    return templates.TemplateResponse(
        request,
        "pages/collection_champs.html",
        _contexte_base(
            nom_base,
            utilisateur,
            collection=collection,
            champs=champs,
            formulaire=FormulaireChamp(),
            erreurs={},
            fonds_query=fonds,
            types_champ=list(TypeChamp),
            vocabulaires_disponibles=lister_vocabulaires(db),
        ),
    )


@router.post(
    "/collection/{cote}/champs/creer",
    response_class=HTMLResponse,
    response_model=None,
)
def soumettre_creer_champ(
    cote: str,
    request: Request,
    formulaire: Annotated[FormulaireChamp, Form()],
    fonds: str | None = Query(None),
    db: Session = Depends(get_db),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse | RedirectResponse:
    collection = resoudre_collection_ou_404(db, cote, fonds)
    try:
        creer_champ(db, collection.id, formulaire)
    except ChampInvalide as e:
        champs = lister_champs(db, collection.id, inclure_deprecies=True)
        return templates.TemplateResponse(
            request,
            "pages/collection_champs.html",
            _contexte_base(
                nom_base,
                utilisateur,
                collection=collection,
                champs=champs,
                formulaire=formulaire,
                erreurs=e.erreurs,
                fonds_query=fonds,
                types_champ=list(TypeChamp),
                vocabulaires_disponibles=lister_vocabulaires(db),
            ),
            status_code=400,
        )
    return RedirectResponse(_url_champs(cote, fonds), status_code=303)


@router.get(
    "/collection/{cote}/champs/{champ_id}/modifier",
    response_class=HTMLResponse,
    response_model=None,
)
def page_modifier_champ(
    cote: str,
    champ_id: int,
    request: Request,
    fonds: str | None = Query(None),
    db: Session = Depends(get_db),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse:
    collection = resoudre_collection_ou_404(db, cote, fonds)
    champ = champ_par_id(db, champ_id)
    _valider_appartenance(champ, collection.id)
    return templates.TemplateResponse(
        request,
        "pages/collection_champ_modifier.html",
        _contexte_base(
            nom_base,
            utilisateur,
            collection=collection,
            champ=champ,
            formulaire=formulaire_depuis_champ(champ),
            erreurs={},
            fonds_query=fonds,
            types_champ=list(TypeChamp),
            vocabulaires_disponibles=lister_vocabulaires(db),
        ),
    )


@router.post(
    "/collection/{cote}/champs/{champ_id}/modifier",
    response_class=HTMLResponse,
    response_model=None,
)
def soumettre_modifier_champ(
    cote: str,
    champ_id: int,
    request: Request,
    formulaire: Annotated[FormulaireChamp, Form()],
    fonds: str | None = Query(None),
    db: Session = Depends(get_db),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse | RedirectResponse:
    collection = resoudre_collection_ou_404(db, cote, fonds)
    champ = champ_par_id(db, champ_id)
    _valider_appartenance(champ, collection.id)
    # On garde la cle d'origine (le formulaire de modif n'expose pas
    # le champ ; le renommage est une opération distincte).
    formulaire.cle = champ.cle
    try:
        modifier_champ(db, champ_id, formulaire)
    except ChampInvalide as e:
        return templates.TemplateResponse(
            request,
            "pages/collection_champ_modifier.html",
            _contexte_base(
                nom_base,
                utilisateur,
                collection=collection,
                champ=champ,
                formulaire=formulaire,
                erreurs=e.erreurs,
                fonds_query=fonds,
                types_champ=list(TypeChamp),
                vocabulaires_disponibles=lister_vocabulaires(db),
            ),
            status_code=400,
        )
    return RedirectResponse(_url_champs(cote, fonds), status_code=303)


@router.post(
    "/collection/{cote}/champs/{champ_id}/renommer",
    response_class=HTMLResponse,
    response_model=None,
)
def soumettre_renommer_champ(
    cote: str,
    champ_id: int,
    request: Request,
    nouvelle_cle: Annotated[str, Form()],
    fonds: str | None = Query(None),
    db: Session = Depends(get_db),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse | RedirectResponse:
    collection = resoudre_collection_ou_404(db, cote, fonds)
    champ = champ_par_id(db, champ_id)
    _valider_appartenance(champ, collection.id)
    try:
        renommer_champ(db, champ_id, nouvelle_cle, modifie_par=utilisateur)
    except ChampInvalide as e:
        # Réaffiche la page modifier avec l'erreur sur le champ
        # `cle`. Le formulaire principal repart de l'état persisté.
        return templates.TemplateResponse(
            request,
            "pages/collection_champ_modifier.html",
            _contexte_base(
                nom_base,
                utilisateur,
                collection=collection,
                champ=champ,
                formulaire=formulaire_depuis_champ(champ),
                erreurs={"cle": e.erreurs.get("cle", "Clé invalide.")},
                tentative_renommage=nouvelle_cle,
                fonds_query=fonds,
                types_champ=list(TypeChamp),
                vocabulaires_disponibles=lister_vocabulaires(db),
            ),
            status_code=400,
        )
    return RedirectResponse(_url_champs(cote, fonds), status_code=303)


@router.post(
    "/collection/{cote}/champs/{champ_id}/deprecier",
    response_class=HTMLResponse,
    response_model=None,
)
def soumettre_deprecier_champ(
    cote: str,
    champ_id: int,
    fonds: str | None = Query(None),
    db: Session = Depends(get_db),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> RedirectResponse:
    collection = resoudre_collection_ou_404(db, cote, fonds)
    champ = champ_par_id(db, champ_id)
    _valider_appartenance(champ, collection.id)
    deprecier_champ(db, champ_id)
    return RedirectResponse(_url_champs(cote, fonds), status_code=303)


@router.post(
    "/collection/{cote}/champs/{champ_id}/reactiver",
    response_class=HTMLResponse,
    response_model=None,
)
def soumettre_reactiver_champ(
    cote: str,
    champ_id: int,
    fonds: str | None = Query(None),
    db: Session = Depends(get_db),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> RedirectResponse:
    collection = resoudre_collection_ou_404(db, cote, fonds)
    champ = champ_par_id(db, champ_id)
    _valider_appartenance(champ, collection.id)
    reactiver_champ(db, champ_id)
    return RedirectResponse(_url_champs(cote, fonds), status_code=303)


@router.post(
    "/item/{cote}/promouvoir-cle",
    response_class=HTMLResponse,
    response_model=None,
)
def soumettre_promouvoir_cle(
    cote: str,
    cle: Annotated[str, Form()],
    fonds: Annotated[str, Query(...)],
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """V0.9.4 lot 2 : formalise une clé libre de ``item.metadonnees``
    en ``ChampPersonnalise`` sur la miroir du fonds de l'item.

    En cas de succès, redirige vers la page item — l'utilisateur voit
    immédiatement le champ passer en section formelle (libellé
    synthétisé). Pour raffiner (libellé, type, ordre), naviguer vers
    la page de gestion des champs via la collection miroir.

    En cas d'erreur (clé non promouvable), redirige aussi vers la
    page item — l'erreur n'a pas de page dédiée et le bouton est
    masqué sur le cartouche pour les clés invalides, donc cet
    embranchement ne devrait être atteint que par bricolage URL.
    """
    item, _fonds_obj = resoudre_item_ou_404(db, cote, fonds)
    try:
        promouvoir_cle_libre_en_champ(db, item, cle)
    except CleNonPromouvable:
        # Pas de message d'erreur affiché — la page item n'a pas de
        # flash et le bouton est filtré côté cartouche pour ne
        # s'afficher que sur les clés promouvables. Si on arrive
        # ici, c'est un bricolage URL — silent fallback.
        pass
    return RedirectResponse(f"/item/{cote}?fonds={fonds}", status_code=303)


@router.post(
    "/collection/{cote}/champs/{champ_id}/supprimer",
    response_class=HTMLResponse,
    response_model=None,
)
def soumettre_supprimer_champ(
    cote: str,
    champ_id: int,
    fonds: str | None = Query(None),
    db: Session = Depends(get_db),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> RedirectResponse:
    """Suppression définitive (hard delete). À utiliser avec parcimonie :
    préférer déprécier dans la majorité des cas."""
    collection = resoudre_collection_ou_404(db, cote, fonds)
    champ = champ_par_id(db, champ_id)
    _valider_appartenance(champ, collection.id)
    supprimer_champ(db, champ_id)
    return RedirectResponse(_url_champs(cote, fonds), status_code=303)
