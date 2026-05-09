"""Routes web — dashboard + pages détail (fonds / collection / item).

Précédence sur les cotes ambiguës :
- `/fonds/{cote}` : recherche stricte par fonds.cote.
- `/collection/{cote}` : si la cote correspond à un fonds existant
  ET aucun `?fonds=` n'est précisé, redirige vers `/fonds/{cote}`.
  Le param `?fonds=COTE_FONDS` désambiguïse explicitement.
- `/item/{cote}` : `?fonds=COTE` est obligatoire (les cotes d'items
  ne sont uniques que par fonds).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from archives_tool.api.deps import get_db, get_nom_base, get_utilisateur_courant
from archives_tool.api.services.collaborateurs_fonds import (
    CollaborateurFondsIntrouvable,
    CollaborateurFondsInvalide,
    FormulaireCollaborateurFonds,
    ajouter_collaborateur_fonds,
    modifier_collaborateur_fonds,
    supprimer_collaborateur_fonds,
)
from archives_tool.api.services.collections import (
    CollectionIntrouvable,
    CollectionInvalide,
    FormulaireCollection,
    ajouter_items_a_collection,
    formulaire_depuis_collection,
    items_disponibles_pour_collection,
    lire_collection_par_cote,
    modifier_collection,
    retirer_item_de_collection,
)
from archives_tool.api.services.dashboard import (
    composer_dashboard,
    composer_page_collection,
    composer_page_fonds,
)
from archives_tool.api.services.fonds import (
    FondsIntrouvable,
    FondsInvalide,
    FormulaireFonds,
    formulaire_depuis_fonds,
    lire_fonds_par_cote,
    lister_fonds,
    modifier_fonds,
)
from archives_tool.api.services.items import (
    ItemIntrouvable,
    lire_item_par_cote,
    lister_items_collection,
)
from archives_tool.api.templating import templates
from archives_tool.models import (
    CollaborateurFonds,
    Fonds,
    LIBELLES_ROLE,
    PhaseChantier,
    RoleCollaborateur,
    TypeCollection,
)

router = APIRouter()

ROLES_OPTIONS: list[str] = [r.value for r in RoleCollaborateur]


def _contexte_base(
    nom_base: str, utilisateur: str, **extra: object
) -> dict[str, object]:
    return {"nom_base": nom_base, "utilisateur": utilisateur, **extra}


# ---------------------------------------------------------------------------
# Dashboard + listes
# ---------------------------------------------------------------------------


@router.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request,
    db: Session = Depends(get_db),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse:
    resume = composer_dashboard(db)
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        _contexte_base(nom_base, utilisateur, resume=resume),
    )


@router.get("/fonds", response_class=HTMLResponse)
def liste_fonds(
    request: Request,
    db: Session = Depends(get_db),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse:
    """Vue liste sobre des fonds (alternative au dashboard)."""
    fonds = lister_fonds(db)
    return templates.TemplateResponse(
        request,
        "pages/fonds_liste.html",
        _contexte_base(nom_base, utilisateur, fonds=fonds),
    )


# ---------------------------------------------------------------------------
# Fonds : lecture + modification
# ---------------------------------------------------------------------------


@router.get("/fonds/{cote}", response_class=HTMLResponse)
def page_fonds(
    cote: str,
    request: Request,
    db: Session = Depends(get_db),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse:
    """Page lecture d'un fonds : bandeau, collections, collaborateurs, items récents."""
    try:
        detail = composer_page_fonds(db, cote)
    except FondsIntrouvable as e:
        raise HTTPException(
            status_code=404, detail=f"Fonds {cote!r} introuvable."
        ) from e
    return templates.TemplateResponse(
        request,
        "pages/fonds_lecture.html",
        _contexte_base(
            nom_base,
            utilisateur,
            detail=detail,
            roles_options=ROLES_OPTIONS,
            libelles_roles=LIBELLES_ROLE,
        ),
    )


@router.get("/fonds/{cote}/modifier", response_class=HTMLResponse)
def formulaire_modifier_fonds(
    cote: str,
    request: Request,
    db: Session = Depends(get_db),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse:
    fonds = _charger_fonds_ou_404(db, cote)
    formulaire = formulaire_depuis_fonds(fonds)
    return templates.TemplateResponse(
        request,
        "pages/fonds_modifier.html",
        _contexte_base(
            nom_base,
            utilisateur,
            fonds=fonds,
            formulaire=formulaire,
            erreurs={},
            phases=list(PhaseChantier),
        ),
    )


@router.post("/fonds/{cote}/modifier", response_class=HTMLResponse, response_model=None)
def soumettre_modification_fonds(
    cote: str,
    request: Request,
    formulaire: Annotated[FormulaireFonds, Form()],
    db: Session = Depends(get_db),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse | RedirectResponse:
    fonds = _charger_fonds_ou_404(db, cote)
    # La cote est verrouillée : on impose la valeur du chemin.
    formulaire.cote = fonds.cote
    try:
        modifier_fonds(db, fonds.id, formulaire, modifie_par=utilisateur)
    except FondsInvalide as e:
        return templates.TemplateResponse(
            request,
            "pages/fonds_modifier.html",
            _contexte_base(
                nom_base,
                utilisateur,
                fonds=fonds,
                formulaire=formulaire,
                erreurs=e.erreurs,
                phases=list(PhaseChantier),
            ),
            status_code=400,
        )
    return RedirectResponse(f"/fonds/{cote}", status_code=303)


# ---------------------------------------------------------------------------
# Collection : lecture
# ---------------------------------------------------------------------------


def _resoudre_collection(db: Session, cote: str, fonds: str | None):
    """Résout la collection cible des routes `/collection/{cote}/...`
    en respectant la désambiguïsation `?fonds=`. Lève `HTTPException`
    404 si le fonds ou la collection sont introuvables."""
    fonds_id: int | None = None
    if fonds is not None:
        try:
            fonds_obj = lire_fonds_par_cote(db, fonds)
            fonds_id = fonds_obj.id
        except FondsIntrouvable as e:
            raise HTTPException(
                status_code=404, detail=f"Fonds {fonds!r} introuvable."
            ) from e
    try:
        collection = lire_collection_par_cote(db, cote, fonds_id=fonds_id)
    except CollectionIntrouvable as e:
        raise HTTPException(
            status_code=404, detail=f"Collection {cote!r} introuvable."
        ) from e
    return collection


def _refuser_si_miroir(collection) -> None:
    if collection.type_collection == TypeCollection.MIROIR.value:
        raise HTTPException(
            status_code=403,
            detail=(
                "Une collection miroir n'est pas modifiable indépendamment "
                "de son fonds."
            ),
        )


def _url_collection(cote: str, fonds: str | None) -> str:
    return f"/collection/{cote}" + (f"?fonds={fonds}" if fonds else "")


@router.get("/collection/{cote}", response_class=HTMLResponse, response_model=None)
def page_collection(
    cote: str,
    request: Request,
    fonds: str | None = Query(
        None, description="Cote du fonds pour désambiguïser une cote partagée."
    ),
    page: int = Query(1, ge=1),
    par_page: int = Query(50, ge=10, le=200),
    tri: str | None = Query(None),
    ordre: str = Query("asc"),
    etat: str | None = Query(
        None, description="Filtre par état (CSV : brouillon,valide,…)"
    ),
    db: Session = Depends(get_db),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse | RedirectResponse:
    """Affiche une collection avec items + contexte fonds parent (ou
    fonds représentés si transversale)."""
    if fonds is None:
        fonds_meme_cote = db.scalar(select(Fonds).where(Fonds.cote == cote))
        if fonds_meme_cote is not None:
            return RedirectResponse(f"/fonds/{cote}", status_code=303)

    collection = _resoudre_collection(db, cote, fonds)
    detail = composer_page_collection(db, collection)
    filtres_etat = [e.strip() for e in (etat or "").split(",") if e.strip()]
    listage = lister_items_collection(
        db,
        collection.id,
        tri=tri,
        ordre=ordre if ordre in ("asc", "desc") else "asc",
        page=page,
        par_page=par_page,
        etat=filtres_etat[0] if filtres_etat else None,
    )
    return templates.TemplateResponse(
        request,
        "pages/collection_lecture.html",
        _contexte_base(
            nom_base,
            utilisateur,
            detail=detail,
            listage=listage,
            fonds_query=fonds,
            etat_actif=filtres_etat[0] if filtres_etat else None,
        ),
    )


# ---------------------------------------------------------------------------
# Collection : édition (libres uniquement)
# ---------------------------------------------------------------------------


@router.get(
    "/collection/{cote}/modifier",
    response_class=HTMLResponse,
)
def page_collection_modifier(
    cote: str,
    request: Request,
    fonds: str | None = Query(None),
    db: Session = Depends(get_db),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse:
    collection = _resoudre_collection(db, cote, fonds)
    _refuser_si_miroir(collection)
    formulaire = formulaire_depuis_collection(collection)
    return templates.TemplateResponse(
        request,
        "pages/collection_modifier.html",
        _contexte_base(
            nom_base,
            utilisateur,
            collection=collection,
            formulaire=formulaire,
            erreurs={},
            fonds_query=fonds,
            phases=list(PhaseChantier),
        ),
    )


@router.post(
    "/collection/{cote}/modifier",
    response_class=HTMLResponse,
    response_model=None,
)
def soumettre_collection_modifier(
    cote: str,
    request: Request,
    formulaire: Annotated[FormulaireCollection, Form()],
    fonds: str | None = Query(None),
    db: Session = Depends(get_db),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse | RedirectResponse:
    collection = _resoudre_collection(db, cote, fonds)
    _refuser_si_miroir(collection)
    # La cote est verrouillée : on impose la valeur du chemin.
    formulaire.cote = collection.cote
    # `fonds_id` est immuable côté UI (cf. décision V0.9.0-alpha.1).
    formulaire.fonds_id = collection.fonds_id
    try:
        modifier_collection(
            db, collection.id, formulaire, modifie_par=utilisateur
        )
    except CollectionInvalide as e:
        return templates.TemplateResponse(
            request,
            "pages/collection_modifier.html",
            _contexte_base(
                nom_base,
                utilisateur,
                collection=collection,
                formulaire=formulaire,
                erreurs=e.erreurs,
                fonds_query=fonds,
                phases=list(PhaseChantier),
            ),
            status_code=400,
        )
    return RedirectResponse(_url_collection(cote, fonds), status_code=303)


# ---------------------------------------------------------------------------
# Collection : items picker + ajout + retrait
# ---------------------------------------------------------------------------


@router.get(
    "/collection/{cote}/items/picker",
    response_class=HTMLResponse,
)
def page_picker_items(
    cote: str,
    request: Request,
    fonds: str | None = Query(None),
    fonds_filter: str | None = Query(
        None, description="Cote d'un fonds pour restreindre les candidats."
    ),
    recherche: str | None = Query(None),
    page: int = Query(1, ge=1),
    db: Session = Depends(get_db),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse:
    """Page de sélection d'items à ajouter à une collection libre."""
    collection = _resoudre_collection(db, cote, fonds)
    _refuser_si_miroir(collection)

    # Détermine le filtre fonds par défaut : si la collection est
    # rattachée et qu'aucun filtre n'est explicite, on propose les
    # items du fonds parent.
    fonds_filter_id: int | None = None
    if fonds_filter:
        try:
            fonds_filter_id = lire_fonds_par_cote(db, fonds_filter).id
        except FondsIntrouvable as e:
            raise HTTPException(
                status_code=404,
                detail=f"Fonds {fonds_filter!r} introuvable.",
            ) from e
    elif collection.fonds_id is not None:
        fonds_filter_id = collection.fonds_id

    disponibles = items_disponibles_pour_collection(
        db,
        collection.id,
        fonds_id=fonds_filter_id,
        recherche=recherche,
        page=page,
    )
    return templates.TemplateResponse(
        request,
        "pages/items_picker.html",
        _contexte_base(
            nom_base,
            utilisateur,
            collection=collection,
            disponibles=disponibles,
            fonds_options=lister_fonds(db),
            fonds_filter=fonds_filter,
            fonds_filter_effectif=db.get(Fonds, fonds_filter_id)
            if fonds_filter_id
            else None,
            recherche=recherche or "",
            fonds_query=fonds,
        ),
    )


@router.post(
    "/collection/{cote}/items",
    response_class=HTMLResponse,
    response_model=None,
)
def soumettre_ajouter_items(
    cote: str,
    request: Request,
    item_ids: Annotated[list[int], Form()] = [],
    fonds: str | None = Query(None),
    db: Session = Depends(get_db),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> RedirectResponse:
    """Ajoute la sélection (multi-id) à la collection. Idempotent."""
    collection = _resoudre_collection(db, cote, fonds)
    _refuser_si_miroir(collection)
    ajouter_items_a_collection(
        db, collection.id, item_ids, ajoute_par=utilisateur
    )
    return RedirectResponse(_url_collection(cote, fonds), status_code=303)


@router.post(
    "/collection/{cote}/items/{item_id}/retirer",
    response_class=HTMLResponse,
    response_model=None,
)
def soumettre_retirer_item(
    cote: str,
    item_id: int,
    fonds: str | None = Query(None),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Retire un item de la collection. Idempotent. Permis sur miroir
    aussi (l'item reste dans le fonds, invariant 7)."""
    collection = _resoudre_collection(db, cote, fonds)
    retirer_item_de_collection(db, item_id, collection.id)
    return RedirectResponse(_url_collection(cote, fonds), status_code=303)


# ---------------------------------------------------------------------------
# Item : placeholder (V0.9.0-beta.3 livrera la page complète)
# ---------------------------------------------------------------------------


@router.get("/item/{cote}", response_class=HTMLResponse)
def page_item(
    cote: str,
    request: Request,
    fonds: str = Query(
        ...,
        description="Cote du fonds (obligatoire : les cotes d'items ne sont uniques que par fonds).",
    ),
    db: Session = Depends(get_db),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse:
    """Affiche un item (titre + cote ; visionneuse + métadonnées à venir)."""
    try:
        fonds_obj = lire_fonds_par_cote(db, fonds)
    except FondsIntrouvable as e:
        raise HTTPException(
            status_code=404, detail=f"Fonds {fonds!r} introuvable."
        ) from e
    try:
        item = lire_item_par_cote(db, cote, fonds_id=fonds_obj.id)
    except ItemIntrouvable as e:
        raise HTTPException(
            status_code=404, detail=f"Item {cote!r} introuvable."
        ) from e
    return templates.TemplateResponse(
        request,
        "pages/_placeholder_item.html",
        _contexte_base(
            nom_base, utilisateur, item=item, fonds_cote=fonds_obj.cote
        ),
    )


# ---------------------------------------------------------------------------
# Collaborateurs d'un fonds (CRUD HTMX-friendly)
# ---------------------------------------------------------------------------


def _charger_fonds_ou_404(db: Session, cote: str) -> Fonds:
    try:
        return lire_fonds_par_cote(db, cote)
    except FondsIntrouvable as e:
        raise HTTPException(
            status_code=404, detail=f"Fonds {cote!r} introuvable."
        ) from e


def _collaborateur_fonds_appartenant(
    db: Session, collaborateur_id: int, fonds_id: int
) -> CollaborateurFonds:
    c = db.get(CollaborateurFonds, collaborateur_id)
    if c is None or c.fonds_id != fonds_id:
        raise HTTPException(
            status_code=404, detail="Collaborateur introuvable dans ce fonds."
        )
    return c


def _re_rendre_fonds_avec_erreurs_collab(
    request: Request,
    db: Session,
    cote: str,
    formulaire: FormulaireCollaborateurFonds,
    erreurs: dict[str, str],
    nom_base: str,
    utilisateur: str,
    *,
    collaborateur_en_modification: int | None = None,
) -> HTMLResponse:
    """Ré-affiche la page fonds avec les erreurs de validation et le
    formulaire pré-rempli pour que l'utilisateur corrige. Pattern
    PRG-friendly : status 400 ; pas de redirect."""
    detail = composer_page_fonds(db, cote)
    return templates.TemplateResponse(
        request,
        "pages/fonds_lecture.html",
        _contexte_base(
            nom_base,
            utilisateur,
            detail=detail,
            roles_options=ROLES_OPTIONS,
            libelles_roles=LIBELLES_ROLE,
            erreurs_collab=erreurs,
            formulaire_collab=formulaire,
            collaborateur_en_modification=collaborateur_en_modification,
        ),
        status_code=400,
    )


@router.post("/fonds/{cote}/collaborateurs", response_class=HTMLResponse, response_model=None)
def ajouter_collaborateur_fonds_route(
    cote: str,
    request: Request,
    formulaire: Annotated[FormulaireCollaborateurFonds, Form()],
    db: Session = Depends(get_db),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse | RedirectResponse:
    fonds = _charger_fonds_ou_404(db, cote)
    try:
        ajouter_collaborateur_fonds(db, fonds.id, formulaire)
    except CollaborateurFondsInvalide as e:
        return _re_rendre_fonds_avec_erreurs_collab(
            request, db, cote, formulaire, e.erreurs, nom_base, utilisateur
        )
    return RedirectResponse(f"/fonds/{cote}", status_code=303)


@router.post(
    "/fonds/{cote}/collaborateurs/{collaborateur_id}",
    response_class=HTMLResponse,
    response_model=None,
)
def modifier_collaborateur_fonds_route(
    cote: str,
    collaborateur_id: int,
    request: Request,
    formulaire: Annotated[FormulaireCollaborateurFonds, Form()],
    db: Session = Depends(get_db),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse | RedirectResponse:
    fonds = _charger_fonds_ou_404(db, cote)
    _collaborateur_fonds_appartenant(db, collaborateur_id, fonds.id)
    try:
        modifier_collaborateur_fonds(db, collaborateur_id, formulaire)
    except CollaborateurFondsInvalide as e:
        return _re_rendre_fonds_avec_erreurs_collab(
            request,
            db,
            cote,
            formulaire,
            e.erreurs,
            nom_base,
            utilisateur,
            collaborateur_en_modification=collaborateur_id,
        )
    except CollaborateurFondsIntrouvable as e:
        raise HTTPException(
            status_code=404, detail="Collaborateur introuvable."
        ) from e
    return RedirectResponse(f"/fonds/{cote}", status_code=303)


@router.post(
    "/fonds/{cote}/collaborateurs/{collaborateur_id}/supprimer",
    response_class=HTMLResponse,
    response_model=None,
)
def supprimer_collaborateur_fonds_route(
    cote: str,
    collaborateur_id: int,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    fonds = _charger_fonds_ou_404(db, cote)
    _collaborateur_fonds_appartenant(db, collaborateur_id, fonds.id)
    supprimer_collaborateur_fonds(db, collaborateur_id)
    return RedirectResponse(f"/fonds/{cote}", status_code=303)
