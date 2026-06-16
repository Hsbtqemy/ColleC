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

from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from archives_tool.api.deps import (
    get_db,
    get_nom_base,
    get_racines,
    get_utilisateur_courant,
)
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
    OperationCollectionInterdite,
    ajouter_items_a_collection,
    creer_collection_libre,
    formulaire_depuis_collection,
    items_disponibles_pour_collection,
    lire_collection_par_cote,
    modifier_collection,
    retirer_item_de_collection,
    supprimer_collection_libre,
)
from archives_tool.api.routes._helpers import (
    charger_fonds_ou_404 as _charger_fonds_ou_404,
    contexte_base as _contexte_base,
    resoudre_item_ou_404 as _resoudre_item_ou_404,
)
from archives_tool.api.services.dashboard import (
    composer_dashboard,
    composer_fiche_item,
    composer_page_collection,
    composer_synthese_collection,
    composer_synthese_fonds,
    composer_page_fonds,
    composer_page_item,
    parser_filtres_collection,
)
from archives_tool.api.services.fonds import (
    FondsIntrouvable,
    FondsInvalide,
    FormulaireFonds,
    formulaire_depuis_fonds,
    lire_fonds_par_cote,
    lister_fonds,
    modifier_fonds,
    supprimer_fonds,
)
from archives_tool.api.services.conflits import ConflitVersion
from archives_tool.api.services.items import (
    FormulaireItem,
    ItemIntrouvable,
    ItemInvalide,
    OperationItemInterdite,
    formulaire_depuis_item,
    lire_item_par_cote,
    lister_items_collection,
    modifier_item,
    supprimer_item,
)
from archives_tool.api.services.champs_personnalises import (
    lister_champs_actifs_pour_item,
)
from archives_tool.api.services.preferences import charger_colonnes_actives
from archives_tool.api.services.vocabulaires import (
    LANGUES_OPTIONS,
    PHASES_OPTIONS,
    TYPES_COAR_OPTIONS,
)
from archives_tool.api.services.vocabulaires_db import (
    options_depuis_vocabulaire,
)
from archives_tool.api.templating import templates
from archives_tool.models import (
    CollaborateurFonds,
    EtatCatalogage,
    Fichier,
    Fonds,
    LIBELLES_ROLE,
    PhaseChantier,
    RoleCollaborateur,
    TypeCollection,
)

router = APIRouter()

ROLES_OPTIONS: list[str] = [r.value for r in RoleCollaborateur]


def _annee_int_ou_none(v: str | None) -> int | None:
    """Coerce une valeur de champ annee (chaine ou None) en `int | None`.

    Le drawer Filtrer envoie `annee_de=&annee_a=` quand les inputs sont
    vides, et l'utilisateur peut taper n'importe quoi. On accepte
    silencieusement et on retombe sur None pour tout ce qui n'est pas
    un entier dans [1000, 2100] — coherent avec la philosophie de
    validation silencieuse des filtres collection.
    """
    if v is None or v.strip() == "":
        return None
    try:
        n = int(v.strip())
    except ValueError:
        return None
    return n if 1000 <= n <= 2100 else None


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


@router.get("/recherche", response_class=HTMLResponse)
def page_recherche(
    request: Request,
    q: str = Query("", description="Requête full-text"),
    fonds_id: int | None = Query(None, description="Limite au fonds (ID)"),
    collection_id: int | None = Query(None, description="Limite à la collection (ID)"),
    types: list[str] | None = Query(
        None, description="Types entité (item/fonds/collection). Tous si vide.",
    ),
    # Filtres avancés (items only sauf q2 qui raffine tout).
    etat: list[str] | None = Query(None, description="Filtre par état (items)."),
    langue: list[str] | None = Query(None, description="Filtre par langue (items)."),
    type_coar: list[str] | None = Query(
        None, description="Filtre par type COAR (items)."
    ),
    annee_min: str | None = Query(None, description="Année min EDTF (items)."),
    annee_max: str | None = Query(None, description="Année max EDTF (items)."),
    q2: str = Query(
        "", description="Raffinement query (concaténé à q avec AND FTS5).",
    ),
    page: int = Query(1, ge=1, description="Numéro de page (1-based)."),
    par_page: int = Query(
        50, ge=10, le=200,
        description="Résultats par page (cap 200).",
    ),
    db: Session = Depends(get_db),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse:
    """Page de résultats de recherche full-text (Lot B V0.9.x).

    - `q` : requête utilisateur libre. Vide → page sans résultats
      (affiche juste la barre + filtres).
    - `fonds_id` / `collection_id` : scope géographique (mutuellement
      exclusifs, le `collection_id` prime si les 2 sont posés).
    - `types` : filtre les entités à inclure. Valeurs reconnues :
      `item`, `fonds`, `collection`. Casse silencieusement les
      invalides.
    - `etat` / `langue` / `type_coar` / `annee_min` / `annee_max` :
      filtres avancés items-only (les fonds/collections passent à
      travers). Validés silencieusement contre les options dynamiques
      de la base (scope-aware).
    - `q2` : raffinement de la query principale, appliqué aux 3 types
      via AND FTS5 implicite.
    - `page` / `par_page` : pagination de la liste plate triée par
      pertinence (BM25). Défaut 50/page, cap 200/page.
    """
    from archives_tool.api.services.recherche import (
        Scope, TypeEntite, calculer_options_filtres_recherche,
        parser_filtres_recherche, rechercher,
    )
    from archives_tool.models import Collection, Fonds

    types_valides: set[TypeEntite] = {"item", "fonds", "collection"}
    types_filtres: set[TypeEntite] | None = None
    if types is not None:
        types_filtres = {t for t in types if t in types_valides} or None

    scope = Scope(
        fonds_id=fonds_id if collection_id is None else None,
        collection_id=collection_id,
    )

    # Options dynamiques scope-aware (limite aux valeurs effectivement
    # présentes dans le périmètre — un fonds en français n'affiche pas
    # « polonais » dans la liste).
    options_filtres = calculer_options_filtres_recherche(db, scope)
    filtres = parser_filtres_recherche(
        etat=etat,
        langue=langue,
        type_coar=type_coar,
        annee_min=_annee_int_ou_none(annee_min),
        annee_max=_annee_int_ou_none(annee_max),
        q_dans_resultats=q2,
        options=options_filtres,
    )

    # `rechercher` retourne ResultatsRecherche avec la page courante
    # ET les totaux exacts par type (COUNT séparé sans LIMIT — utile
    # pour le compteur principal et le calcul de nb_pages).
    res = rechercher(
        db, q, scope=scope, types=types_filtres,
        filtres=filtres, page=page, par_page=par_page,
    )

    fonds_scope = None
    collection_scope = None
    if fonds_id is not None:
        fonds_scope = db.get(Fonds, fonds_id)
    if collection_id is not None:
        collection_scope = db.get(Collection, collection_id)

    return templates.TemplateResponse(
        request,
        "pages/recherche.html",
        _contexte_base(
            nom_base,
            utilisateur,
            q=q,
            resultats=res.resultats,
            total_par_type=res.total_par_type,
            total_global=res.total,
            cap_atteint=res.cap_atteint,
            page=res.page,
            par_page=res.par_page,
            nb_pages=res.nb_pages,
            premier_index=res.premier_index,
            dernier_index=res.dernier_index,
            fonds_scope=fonds_scope,
            collection_scope=collection_scope,
            types_filtres=types_filtres or set(),
            tous_types=list(types_valides),
            filtres=filtres,
            options_filtres=options_filtres,
            etats_disponibles=list(EtatCatalogage),
        ),
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
    q: str = Query(
        "",
        description=(
            "Termes à surligner — propagé depuis la page de recherche "
            "via le filtre `surligner_q`."
        ),
    ),
    modifier_collab: int | None = Query(
        None,
        description=(
            "Si fourni et appartient à ce fonds, bascule la ligne du "
            "collaborateur en mode édition inline (pattern identique au "
            "?modifier=<vid> de la page vocabulaire détail)."
        ),
    ),
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
    # Synthèse fonds : aggrégats cross-collection + temporel + vignettes.
    # Auto-masqué côté template si `synthese.vide`.
    synthese = composer_synthese_fonds(db, detail.fonds)
    # Premier item du fonds (cote ASC) pour le bouton « Mode consultation »
    # du header — entrée naturelle pour parcourir le fonds en mode liseuse.
    from archives_tool.models import Item

    premier_item_cote = db.scalar(
        select(Item.cote)
        .where(Item.fonds_id == detail.fonds.id)
        .order_by(Item.cote)
        .limit(1)
    )
    consultation_url = (
        f"/lire/{detail.fonds.cote}/{premier_item_cote}"
        if premier_item_cote
        else None
    )

    # Mode édition inline d'un collaborateur (cf. ?modifier_collab=<id>).
    # Pré-remplit le formulaire depuis les valeurs en base. Si l'id ne
    # pointe pas sur un collaborateur de ce fonds, on ignore silencieusement
    # (anti-confused-deputy léger — pas de 404 brutal pour un id taquiné
    # via URL).
    collaborateur_en_modification: int | None = None
    formulaire_collab = None
    if modifier_collab is not None:
        cible = next(
            (c for c in detail.collaborateurs if c.id == modifier_collab),
            None,
        )
        if cible is not None:
            collaborateur_en_modification = cible.id
            formulaire_collab = FormulaireCollaborateurFonds(
                nom=cible.nom,
                roles=[r.value for r in cible.roles],
                periode=cible.periode or "",
                notes=cible.notes or "",
            )

    return templates.TemplateResponse(
        request,
        "pages/fonds_lecture.html",
        _contexte_base(
            nom_base,
            utilisateur,
            detail=detail,
            synthese=synthese,
            roles_options=ROLES_OPTIONS,
            libelles_roles=LIBELLES_ROLE,
            consultation_url=consultation_url,
            q_surligne=q,
            collaborateur_en_modification=collaborateur_en_modification,
            formulaire_collab=formulaire_collab,
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
    except ConflitVersion as e:
        formulaire.version = fonds.version
        if e.version_actuelle is None:
            detail = (
                "modification cross-process détectée — la version "
                "actuelle ne peut pas être lue depuis la transaction "
                "courante"
            )
        else:
            detail = (
                f"version {e.version_actuelle} en base, "
                f"vous avez {e.version_attendue}"
            )
        return templates.TemplateResponse(
            request,
            "pages/fonds_modifier.html",
            _contexte_base(
                nom_base,
                utilisateur,
                fonds=fonds,
                formulaire=formulaire,
                erreurs={
                    "_version": (
                        f"Ce fonds a été modifié entre-temps ({detail}). "
                        "Vérifiez les valeurs et resoumettez si vous "
                        "souhaitez écraser."
                    )
                },
                phases=list(PhaseChantier),
            ),
            status_code=409,
        )
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


def _resoudre_collection_mutable(db: Session, cote: str, fonds: str | None):
    """Pour les routes qui mutent une collection : résout + refuse 403
    si miroir. Centralise la paire `_resoudre_collection` +
    `_refuser_si_miroir`."""
    collection = _resoudre_collection(db, cote, fonds)
    _refuser_si_miroir(collection)
    return collection


def _url_collection(cote: str, fonds: str | None) -> str:
    return f"/collection/{cote}" + (f"?fonds={fonds}" if fonds else "")


# ---------------------------------------------------------------------------
# Création d'une collection libre depuis l'UI
#
# L'URL `/collections/nouvelle` (pluriel) est référencée depuis le menu
# Importer global (`menu_importer.html`) et le bouton « + Créer une
# collection libre » sur la page fonds. Le service `creer_collection_libre`
# existait depuis V0.7-alpha (UI livrée) mais la route web a disparu lors
# du refactor V0.9.0-alpha — les deux liens menaient à un 404 pendant
# longtemps. Restauration ici.
#
# Pour les transversales (collection sans fonds parent), passer par la CLI
# `archives-tool collections creer-libre` — la valeur d'usage côté UI est
# limitée et l'ajout d'une option « Aucun fonds » au selector compliquerait
# le formulaire pour un cas marginal.
# ---------------------------------------------------------------------------


@router.get(
    "/collections/nouvelle",
    response_class=HTMLResponse,
    response_model=None,
)
def page_collection_nouvelle(
    request: Request,
    fonds: str | None = Query(
        None,
        description=(
            "Cote du fonds parent. Si fournie, la libre sera rattachée à "
            "ce fonds et le champ sera verrouillé dans le formulaire. "
            "Sinon, un sélecteur listera tous les fonds existants."
        ),
    ),
    db: Session = Depends(get_db),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse:
    """Formulaire de création d'une collection libre."""
    fonds_locked = None
    if fonds is not None:
        try:
            fonds_locked = lire_fonds_par_cote(db, fonds)
        except FondsIntrouvable as e:
            raise HTTPException(status_code=404, detail=str(e)) from e

    # Liste tous les fonds pour le sélecteur si pas de fonds pré-imposé.
    tous_fonds = lister_fonds(db) if fonds_locked is None else []

    formulaire = FormulaireCollection(
        fonds_id=fonds_locked.id if fonds_locked else None,
    )
    return templates.TemplateResponse(
        request,
        "pages/collection_nouvelle.html",
        _contexte_base(
            nom_base,
            utilisateur,
            fonds_locked=fonds_locked,
            tous_fonds=tous_fonds,
            formulaire=formulaire,
            erreurs={},
            phases=list(PhaseChantier),
        ),
    )


@router.post(
    "/collections/nouvelle",
    response_class=HTMLResponse,
    response_model=None,
)
def soumettre_collection_nouvelle(
    request: Request,
    formulaire: Annotated[FormulaireCollection, Form()],
    fonds: str | None = Query(
        None,
        description=(
            "Cote du fonds locked depuis l'arrivée GET. Sert à reproduire "
            "le mode (locked vs sélecteur) en cas d'erreur de validation. "
            "Absent = mode sélecteur (l'utilisateur peut re-choisir le "
            "fonds au prochain submit)."
        ),
    ),
    db: Session = Depends(get_db),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse | RedirectResponse:
    """Crée la collection libre et redirige vers sa page lecture.

    Erreurs de validation (cote / titre vide, cote en collision) : 400
    avec le formulaire ré-affiché et les erreurs surlignées. Le mode
    (locked vs sélecteur) est porté par `?fonds=<cote>` sur l'URL de
    soumission — sans ça, un utilisateur venu en mode sélecteur qui se
    trompe de cote se retrouverait bloqué sur le fonds qu'il a choisi.
    """
    try:
        col = creer_collection_libre(db, formulaire, cree_par=utilisateur)
    except CollectionInvalide as e:
        # Mode locked (?fonds=X) → on relit X depuis la base. Mode
        # sélecteur (pas de query) → on liste tous les fonds, l'utilisateur
        # peut changer son rattachement avant de resoumettre.
        fonds_locked = None
        if fonds is not None:
            try:
                fonds_locked = lire_fonds_par_cote(db, fonds)
            except FondsIntrouvable:
                # Mode locked sur un fonds qui aurait disparu entre-temps :
                # on retombe en mode sélecteur plutôt que 404 brutal.
                fonds_locked = None
        tous_fonds = lister_fonds(db) if fonds_locked is None else []
        return templates.TemplateResponse(
            request,
            "pages/collection_nouvelle.html",
            _contexte_base(
                nom_base,
                utilisateur,
                fonds_locked=fonds_locked,
                tous_fonds=tous_fonds,
                formulaire=formulaire,
                erreurs=e.erreurs,
                phases=list(PhaseChantier),
            ),
            status_code=400,
        )

    # Redirige vers la lecture de la collection créée. ?fonds=... pour
    # désambiguïser si la cote pourrait coïncider avec d'autres.
    fonds_query = col.fonds.cote if col.fonds else None
    return RedirectResponse(
        _url_collection(col.cote, fonds_query), status_code=303
    )


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
    etat: list[str] | None = Query(
        None,
        description=(
            "Filtre par état. Accepte les clés répétées "
            "(`?etat=brouillon&etat=valide`, format envoyé par les "
            "`<select multiple>`) et la CSV (`?etat=brouillon,valide`)."
        ),
    ),
    langue: list[str] | None = Query(
        None, description="Filtre par langue (mêmes formats que `etat`)."
    ),
    type_coar: list[str] | None = Query(
        None, description="Filtre par type COAR (mêmes formats que `etat`)."
    ),
    # `str | None` plutot que `int | None` : le drawer Filtrer soumet
    # `annee_de=&annee_a=` quand les champs sont vides, ce que la
    # validation int rejette en 422. On parse + filtre les valeurs
    # invalides en silence (coherent avec `parser_filtres_collection`
    # qui ignore les filtres hors options).
    annee_de: str | None = Query(None),
    annee_a: str | None = Query(None),
    q: str = Query(
        "",
        description=(
            "Termes à surligner — propagé depuis la page de recherche "
            "via le filtre `surligner_q`."
        ),
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
    # Parsing + validation des filtres contre les options dynamiques.
    # Synthèse : seulement pour le rendu pleine page (pas pour les
    # swaps HTMX qui ne rendent que le partial du tableau).
    synthese = None
    if request.headers.get("HX-Request") != "true":
        synthese = composer_synthese_collection(db, collection, fonds_query=fonds)
    filtres = parser_filtres_collection(
        etat=etat,
        langue=langue,
        type_coar=type_coar,
        annee_de=_annee_int_ou_none(annee_de),
        annee_a=_annee_int_ou_none(annee_a),
        options=detail.options_filtres,
    )
    listage = lister_items_collection(
        db,
        collection.id,
        tri=tri,
        ordre=ordre if ordre in ("asc", "desc") else "asc",
        page=page,
        par_page=par_page,
        etats=filtres.etats,
        langues=filtres.langues,
        types_coar=filtres.types_coar,
        annee_de=filtres.annee_de,
        annee_a=filtres.annee_a,
    )
    resolu = charger_colonnes_actives(db, utilisateur, collection.id, "items")
    # HTMX swap (tri colonne, pagination) : on ne renvoie que le partial
    # du tableau, pas la page entiere. Sinon HTMX injecte la page complete
    # dans #tableau-items et tout s'imbrique.
    if request.headers.get("HX-Request") == "true":
        return templates.TemplateResponse(
            request,
            "partials/collection_items.html",
            _contexte_base(
                nom_base,
                utilisateur,
                items=listage,
                cote=collection.cote,
                colonnes_actives=resolu.actives,
                collection_id=collection.id,
                fonds_query=fonds,
                filtres=filtres,
            ),
        )
    # Premier item de la collection (cote ASC) pour le bouton « Mode
     # consultation » du header. Transversale : pas de fonds parent
     # → liseuse pas applicable (la liseuse exige un fonds dans l'URL).
    consultation_url: str | None = None
    if collection.fonds_id is not None and listage.items:
        # On a déjà la 1ère page d'items via `listage` — autant la
        # réutiliser plutôt qu'une requête de plus.
        premier = min(listage.items, key=lambda i: i.cote)
        fonds_obj = db.scalar(
            select(Fonds.cote).where(Fonds.id == collection.fonds_id)
        )
        if fonds_obj:
            consultation_url = f"/lire/{fonds_obj}/{premier.cote}"

    return templates.TemplateResponse(
        request,
        "pages/collection_lecture.html",
        _contexte_base(
            nom_base,
            utilisateur,
            detail=detail,
            synthese=synthese,
            listage=listage,
            colonnes_actives=resolu.actives,
            fonds_query=fonds,
            filtres=filtres,
            etats_disponibles=list(EtatCatalogage),
            consultation_url=consultation_url,
            q_surligne=q,
            phases_options=PHASES_OPTIONS,
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
    collection = _resoudre_collection_mutable(db, cote, fonds)
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
    collection = _resoudre_collection_mutable(db, cote, fonds)
    # La cote est verrouillée : on impose la valeur du chemin.
    formulaire.cote = collection.cote
    # `fonds_id` est immuable côté UI (cf. décision V0.9.0-alpha.1).
    formulaire.fonds_id = collection.fonds_id
    try:
        modifier_collection(db, collection.id, formulaire, modifie_par=utilisateur)
    except ConflitVersion as e:
        formulaire.version = collection.version
        if e.version_actuelle is None:
            detail = (
                "modification cross-process détectée — la version "
                "actuelle ne peut pas être lue depuis la transaction "
                "courante"
            )
        else:
            detail = (
                f"version {e.version_actuelle} en base, "
                f"vous avez {e.version_attendue}"
            )
        return templates.TemplateResponse(
            request,
            "pages/collection_modifier.html",
            _contexte_base(
                nom_base,
                utilisateur,
                collection=collection,
                formulaire=formulaire,
                erreurs={
                    "_version": (
                        f"Cette collection a été modifiée entre-temps "
                        f"({detail}). Vérifiez les valeurs et resoumettez "
                        "si vous souhaitez écraser."
                    )
                },
                fonds_query=fonds,
                phases=list(PhaseChantier),
            ),
            status_code=409,
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
    collection = _resoudre_collection_mutable(db, cote, fonds)

    # Détermine le filtre fonds par défaut : si la collection est
    # rattachée et qu'aucun filtre n'est explicite, on propose les
    # items du fonds parent. On charge le `Fonds` au plus une fois.
    fonds_filter_obj: Fonds | None = None
    if fonds_filter:
        try:
            fonds_filter_obj = lire_fonds_par_cote(db, fonds_filter)
        except FondsIntrouvable as e:
            raise HTTPException(
                status_code=404,
                detail=f"Fonds {fonds_filter!r} introuvable.",
            ) from e
    elif collection.fonds_id is not None:
        fonds_filter_obj = db.get(Fonds, collection.fonds_id)

    disponibles = items_disponibles_pour_collection(
        db,
        collection.id,
        fonds_id=fonds_filter_obj.id if fonds_filter_obj else None,
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
            fonds_filter_effectif=fonds_filter_obj,
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
    item_ids: Annotated[list[int], Form()] = [],  # noqa: B006 — FastAPI lit Form() à chaque requête.
    fonds: str | None = Query(None),
    db: Session = Depends(get_db),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> RedirectResponse:
    """Ajoute la sélection (multi-id) à la collection. Idempotent."""
    collection = _resoudre_collection_mutable(db, cote, fonds)
    ajouter_items_a_collection(db, collection.id, item_ids, ajoute_par=utilisateur)
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
# Collection : creation en serie d'items (V0.9.7)
# ---------------------------------------------------------------------------


@router.get(
    "/collection/{cote}/items/serie",
    response_class=HTMLResponse,
)
def page_serie_items_formulaire(
    cote: str,
    request: Request,
    fonds: str | None = Query(None),
    db: Session = Depends(get_db),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse:
    """Formulaire de creation en serie d'items dans une collection.

    Accepte miroir et libre rattachee (transversale refusee : il
    faudrait choisir un fonds explicite — flux a part).
    """
    collection = _resoudre_collection(db, cote, fonds)
    if collection.fonds_id is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "Creation en serie indisponible sur les transversales "
                "(necessite un fonds explicite). Creer dans une collection "
                "rattachee a un fonds et ajouter manuellement a la "
                "transversale."
            ),
        )
    fonds_obj = db.get(Fonds, collection.fonds_id)
    return templates.TemplateResponse(
        request,
        "pages/items_serie.html",
        _contexte_base(
            nom_base,
            utilisateur,
            collection=collection,
            fonds=fonds_obj,
            fonds_query=fonds,
            etats_disponibles=list(EtatCatalogage),
            erreurs={},
            valeurs={},
        ),
    )


@router.post(
    "/collection/{cote}/items/serie",
    response_class=HTMLResponse,
    response_model=None,
)
def soumettre_serie_items(
    cote: str,
    request: Request,
    pattern_cote: Annotated[str, Form()],
    de_n: Annotated[int, Form()],
    a_n: Annotated[int, Form()],
    titre_template: Annotated[str, Form()] = "",
    etat: Annotated[str, Form()] = "brouillon",
    type_coar: Annotated[str, Form()] = "",
    langue: Annotated[str, Form()] = "",
    ignorer_existants: Annotated[bool, Form()] = False,
    fonds: str | None = Query(None),
    db: Session = Depends(get_db),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse | RedirectResponse:
    """Crée une serie d'items via le formulaire. Redirige vers la
    collection si succes, re-rend le form avec erreurs sinon."""
    from archives_tool.api.services.items import (
        ItemInvalide,
        creer_items_en_serie,
    )

    collection = _resoudre_collection(db, cote, fonds)
    if collection.fonds_id is None:
        raise HTTPException(
            status_code=400,
            detail="Creation en serie indisponible sur les transversales.",
        )
    fonds_obj = db.get(Fonds, collection.fonds_id)
    # On choisit la miroir comme cible defaut si la collection courante
    # est la miroir, sinon la libre courante. Le service rattachera
    # automatiquement a la miroir (invariant 6) si on cible une libre.
    cible_id = collection.id

    valeurs = {
        "pattern_cote": pattern_cote,
        "de_n": de_n,
        "a_n": a_n,
        "titre_template": titre_template,
        "etat": etat,
        "type_coar": type_coar,
        "langue": langue,
        "ignorer_existants": ignorer_existants,
    }

    try:
        rapport = creer_items_en_serie(
            db,
            fonds_id=fonds_obj.id,
            pattern_cote=pattern_cote,
            de_n=de_n,
            a_n=a_n,
            titre_template=titre_template,
            collection_id=cible_id,
            etat=etat,
            type_coar=type_coar or None,
            langue=langue or None,
            ignorer_existants=ignorer_existants,
            cree_par=utilisateur,
        )
    except ItemInvalide as e:
        return templates.TemplateResponse(
            request,
            "pages/items_serie.html",
            _contexte_base(
                nom_base,
                utilisateur,
                collection=collection,
                fonds=fonds_obj,
                fonds_query=fonds,
                etats_disponibles=list(EtatCatalogage),
                erreurs=e.erreurs,
                valeurs=valeurs,
            ),
            status_code=400,
        )

    # Succes : redirige vers la collection avec un flash dans la query
    # string (lu par le template).
    url = _url_collection(cote, fonds)
    sep = "&" if "?" in url else "?"
    flash = (
        f"{sep}serie_crees={rapport.nb_crees}"
        f"&serie_ignores={rapport.nb_ignores}"
    )
    return RedirectResponse(url + flash, status_code=303)


# ---------------------------------------------------------------------------
# Item : lecture, modification, service de fichier
# ---------------------------------------------------------------------------


@router.get("/item/{cote}", response_class=HTMLResponse)
def page_item_fiche(
    cote: str,
    request: Request,
    fonds: str = Query(
        ...,
        description=(
            "Cote du fonds (obligatoire : les cotes d'items ne sont "
            "uniques que par fonds)."
        ),
    ),
    q: str = Query(
        "",
        description=(
            "Termes à surligner dans la page — propagé depuis la page "
            "de résultats de recherche pour aider à localiser les matches."
        ),
    ),
    db: Session = Depends(get_db),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse:
    """Fiche item (V0.9.5) : notice complète sans visionneuse —
    landing par défaut pour comprendre un item. Layout 3 colonnes :
    métadonnées item, agrégats fichier + liste compacte, grille de
    vignettes scrollable.

    Pour l'ancien layout (cartouche + visionneuse), passer par
    ``/item/<cote>/visionneuse?fonds=X``.
    """
    fonds_obj = _charger_fonds_ou_404(db, fonds)
    try:
        fiche = composer_fiche_item(db, cote, fonds_obj)
    except ItemIntrouvable as e:
        raise HTTPException(
            status_code=404, detail=f"Item {cote!r} introuvable."
        ) from e
    return templates.TemplateResponse(
        request,
        "pages/item_fiche.html",
        _contexte_base(
            nom_base,
            utilisateur,
            fiche=fiche,
            fonds_cote=fonds_obj.cote,
            visionneuse_url=f"/item/{cote}/visionneuse?fonds={fonds_obj.cote}",
            consultation_url=f"/lire/{fonds_obj.cote}/{cote}",
            q_surligne=q,
        ),
    )


@router.get("/item/{cote}/visionneuse", response_class=HTMLResponse)
def page_item_visionneuse(
    cote: str,
    request: Request,
    fonds: str = Query(...),
    fichier_courant: int = Query(1, ge=1),
    q: str = Query(""),
    db: Session = Depends(get_db),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse:
    """Ancien layout V0.9.2-gamma : 3 zones cartouche / visionneuse /
    panneau fichiers. Reste utile pour le catalogage page-par-page —
    ``/item/<cote>`` envoie sur la fiche depuis V0.9.5."""
    fonds_obj = _charger_fonds_ou_404(db, fonds)
    try:
        detail = composer_page_item(
            db, cote, fonds_obj, fichier_courant_pos=fichier_courant
        )
    except ItemIntrouvable as e:
        raise HTTPException(
            status_code=404, detail=f"Item {cote!r} introuvable."
        ) from e
    return templates.TemplateResponse(
        request,
        "pages/item_lecture.html",
        _contexte_base(
            nom_base,
            utilisateur,
            detail=detail,
            fonds_cote=fonds_obj.cote,
            consultation_url=f"/lire/{fonds_obj.cote}/{cote}",
            fiche_url=f"/item/{cote}?fonds={fonds_obj.cote}",
            q_surligne=q,
        ),
    )


@router.get("/lire/{fonds_cote}/{cote}", response_class=HTMLResponse)
def page_lire_item(
    fonds_cote: str,
    cote: str,
    request: Request,
    fichier: int = Query(1, ge=1, description="Position 1-indexée du fichier courant"),
    db: Session = Depends(get_db),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse:
    """Liseuse consultation d'un item (Lot 1 V0.9.x).

    Layout 3 colonnes : métadonnées (gauche) | visionneuse (centre) |
    vignettes (droite). Navigation HTMX swap pour changer de fichier
    sans reload. Navigation reload classique pour changer d'item.
    """
    fonds_obj = _charger_fonds_ou_404(db, fonds_cote)
    try:
        detail = composer_page_item(
            db, cote, fonds_obj, fichier_courant_pos=fichier
        )
    except ItemIntrouvable as e:
        raise HTTPException(
            status_code=404, detail=f"Item {cote!r} introuvable."
        ) from e

    # IDs Fichier pour les boutons Page précédente/suivante du bandeau.
    # Reposent sur la même séquence que le panneau vignettes (ordre
    # `fichier.ordre` ASC). `position_courante` est 1-indexé.
    fichiers = detail.fichiers
    pos = detail.position_courante
    fichier_precedent_id = fichiers[pos - 2].id if pos > 1 else None
    fichier_suivant_id = (
        fichiers[pos].id if pos < len(fichiers) else None
    )

    return templates.TemplateResponse(
        request,
        "pages/lire_item.html",
        _contexte_base(
            nom_base,
            utilisateur,
            detail=detail,
            fonds_cote=fonds_obj.cote,
            fichier_precedent_id=fichier_precedent_id,
            fichier_suivant_id=fichier_suivant_id,
            mode_consultation_actif=True,
        ),
    )


@router.get(
    "/lire/{fonds_cote}/{cote}/visionneuse/{fichier_id}",
    response_class=HTMLResponse,
)
def page_lire_item_visionneuse_partial(
    fonds_cote: str,
    cote: str,
    fichier_id: int,
    request: Request,
    db: Session = Depends(get_db),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse:
    """Partial HTMX : retourne plusieurs fragments à swap simultané :
    - cible principale : `#zone-visionneuse` (nouvelle visionneuse)
    - out-of-band `#bandeau-liseuse` (boutons Page ← →, compteur)
    - out-of-band `#zone-vignettes-liseuse` (highlight de la vignette
      active)

    Sans ces 3 swaps, les boutons Page restent figés sur leurs cibles
    initiales et le clic suivant ne fait rien (cas signalé à l'usage).

    Sécurité : vérifie l'appartenance fichier → item → fonds avant
    rendu (anti-confused-deputy).
    """
    fonds_obj = _charger_fonds_ou_404(db, fonds_cote)
    try:
        item = lire_item_par_cote(db, cote, fonds_id=fonds_obj.id)
    except ItemIntrouvable as e:
        raise HTTPException(status_code=404, detail="Item introuvable.") from e
    fichier = db.get(Fichier, fichier_id)
    if fichier is None or fichier.item_id != item.id:
        raise HTTPException(
            status_code=404,
            detail="Fichier introuvable dans cet item.",
        )

    # Position 1-indexée du fichier dans l'ordre courant. Recompose
    # le detail item pour avoir bandeau + vignettes à jour.
    fichiers_tries = sorted(item.fichiers, key=lambda f: f.ordre)
    position = next(
        (i + 1 for i, f in enumerate(fichiers_tries) if f.id == fichier_id),
        1,
    )
    detail = composer_page_item(db, cote, fonds_obj, fichier_courant_pos=position)
    fichier_precedent_id = (
        detail.fichiers[position - 2].id if position > 1 else None
    )
    fichier_suivant_id = (
        detail.fichiers[position].id if position < len(detail.fichiers) else None
    )
    return templates.TemplateResponse(
        request,
        "partials/_visionneuse_partial.html",
        _contexte_base(
            nom_base,
            utilisateur,
            detail=detail,
            cote=cote,
            fonds_cote=fonds_obj.cote,
            fichier_precedent_id=fichier_precedent_id,
            fichier_suivant_id=fichier_suivant_id,
        ),
    )


@router.post("/item/{cote}/fichiers/{fichier_id}/transcription")
def item_fichier_transcription(
    cote: str,
    fichier_id: int,
    fonds: str = Query(...),
    texte: str = Form(""),
    fichier_courant: int = Form(1),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Enregistre la transcription (description publique) d'un scan (S7).

    Surface d'édition = viewer de catalogage (`/item/<cote>/visionneuse`,
    même page que « Annoter ») ; la liseuse l'affiche en lecture seule.
    Vérifie l'appartenance fichier→item→fonds (anti-confused-deputy) avant
    d'écrire. Texte vide → `None` (pas de transcription). Bloqué 423 en
    lecture seule par le middleware (et le formulaire est masqué côté
    template). PRG : redirige vers le viewer au même scan courant.

    Pas d'auteur enregistré : `Fichier` n'a pas de `modifie_par` (≠ Item/
    Collection/Fonds). Le bump `version` suit le pattern du module Nakala
    (`pousser_fichiers_item`) — sans verrou optimiste actif sur `Fichier`
    (dette projet documentée), c'est last-write-wins en concurrence.
    """
    fonds_obj = _charger_fonds_ou_404(db, fonds)
    try:
        item = lire_item_par_cote(db, cote, fonds_id=fonds_obj.id)
    except ItemIntrouvable as e:
        raise HTTPException(status_code=404, detail="Item introuvable.") from e
    fichier = db.get(Fichier, fichier_id)
    if fichier is None or fichier.item_id != item.id:
        raise HTTPException(
            status_code=404, detail="Fichier introuvable dans cet item.",
        )
    nouvelle = texte.strip() or None
    if nouvelle != fichier.description_externe:
        fichier.description_externe = nouvelle
        fichier.modifie_le = datetime.now()
        fichier.version = (fichier.version or 1) + 1
        db.commit()
    # Redirige avec la cote canonique (item.cote), pas le param de chemin brut.
    return RedirectResponse(
        f"/item/{item.cote}/visionneuse?fonds={fonds_obj.cote}"
        f"&fichier_courant={max(1, fichier_courant)}",
        status_code=303,
    )


@router.get("/item/{cote}/fichiers/{fichier_id}")
def servir_fichier_item(
    cote: str,
    fichier_id: int,
    fonds: str = Query(...),
    db: Session = Depends(get_db),
    racines: dict[str, Path] = Depends(get_racines),
) -> FileResponse:
    """Sert le binaire d'un fichier rattaché à un item.

    Vérifie l'appartenance fichier→item→fonds (anti-confused-deputy)
    avant toute résolution disque. Pour la base de démo où les
    chemins sont fictifs, retourne 404 propre.

    Defense en profondeur path traversal (audit V0.9.x) : valide
    `chemin_relatif` contre `..` / chemin absolu, puis verifie apres
    resolution que la cible reste dans la racine. `racine_path /
    "/etc/passwd"` en pathlib pur reinitialise au root (documente),
    donc une valeur DB malformee (par ex. ecrite via une faille
    ailleurs ou edition manuelle) pourrait sortir de la racine sans
    ces deux gardes. Pattern identique au router `derives` qui les
    a depuis V0.6.
    """
    from archives_tool.files.paths import valider_chemin_relatif

    fonds_obj = _charger_fonds_ou_404(db, fonds)
    try:
        item = lire_item_par_cote(db, cote, fonds_id=fonds_obj.id)
    except ItemIntrouvable as e:
        raise HTTPException(status_code=404, detail="Item introuvable.") from e
    fichier = db.get(Fichier, fichier_id)
    if fichier is None or fichier.item_id != item.id:
        raise HTTPException(
            status_code=404,
            detail="Fichier introuvable dans cet item.",
        )
    if not fichier.racine or not fichier.chemin_relatif:
        raise HTTPException(
            status_code=404,
            detail="Fichier sans source locale (Nakala-only ou non résolu).",
        )
    racine_path = racines.get(fichier.racine)
    if racine_path is None:
        raise HTTPException(
            status_code=404,
            detail=f"Racine {fichier.racine!r} non configurée.",
        )

    # Garde 1 : rejette chemin absolu ou contenant `..`. Detecte les
    # `chemin_relatif` malformes en base avant qu'ils ne sortent de
    # leur racine via `pathlib.Path.__truediv__`. Detail neutre — pas
    # de leak du chemin soumis pour ne pas confirmer une tentative
    # de path traversal (l'attaquant connait deja sa propre saisie
    # mais defense-in-depth = ne pas confirmer).
    try:
        rel = str(valider_chemin_relatif(fichier.chemin_relatif))
    except ValueError:
        raise HTTPException(
            status_code=403,
            detail="Chemin relatif invalide en base.",
        ) from None

    base = racine_path.resolve()
    chemin_local = (base / rel).resolve()

    # Garde 2 : verifie apres resolution que la cible reste dans la
    # racine. Couvre les symlinks pointant hors racine et un
    # eventuel contournement de valider_chemin_relatif.
    if not chemin_local.is_relative_to(base):
        raise HTTPException(
            status_code=403,
            detail="Cible hors de la racine declaree.",
        )
    if not chemin_local.is_file():
        # 404 detail conserve le chemin — c'est un cas legitime de
        # debug (fichier supprime du disque). Pas un vecteur d'attaque
        # car le chemin a deja passe la garde 1.
        raise HTTPException(
            status_code=404,
            detail=f"Fichier absent du disque : {fichier.chemin_relatif}",
        )
    return FileResponse(chemin_local)


def _options_par_champ_perso(
    champs_perso: list,
) -> dict[str, tuple[tuple[str, str], ...]]:
    """Pour chaque ChampPersonnalise lié à un vocabulaire DB, expose
    ses (code, libellé) sous la forme attendue par la macro selecteur.
    Les champs sans vocabulaire sont absents du dict — le template
    rend alors un input libre."""
    options: dict[str, tuple[tuple[str, str], ...]] = {}
    for c in champs_perso:
        if c.vocabulaire is not None:
            options[c.cle] = options_depuis_vocabulaire(c.vocabulaire)
    return options


@router.get("/item/{cote}/modifier", response_class=HTMLResponse)
def formulaire_modifier_item(
    cote: str,
    request: Request,
    fonds: str = Query(...),
    db: Session = Depends(get_db),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse:
    item, fonds_obj = _resoudre_item_ou_404(db, cote, fonds)
    formulaire = formulaire_depuis_item(item)
    champs_perso = lister_champs_actifs_pour_item(db, item.id)
    options_par_champ_perso = _options_par_champ_perso(champs_perso)
    return templates.TemplateResponse(
        request,
        "pages/item_modifier.html",
        _contexte_base(
            nom_base,
            utilisateur,
            item=item,
            fonds=fonds_obj,
            formulaire=formulaire,
            erreurs={},
            etats=list(EtatCatalogage),
            champs_personnalises=champs_perso,
            options_par_champ_perso=options_par_champ_perso,
            langues_options=LANGUES_OPTIONS,
            types_coar_options=TYPES_COAR_OPTIONS,
        ),
    )


@router.post("/item/{cote}/modifier", response_class=HTMLResponse, response_model=None)
async def soumettre_modification_item(
    cote: str,
    request: Request,
    formulaire: Annotated[FormulaireItem, Form()],
    fonds: str = Query(...),
    db: Session = Depends(get_db),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse | RedirectResponse:
    item, fonds_obj = _resoudre_item_ou_404(db, cote, fonds)
    # La cote et le fonds sont verrouillés : on impose les valeurs du
    # chemin / item courant. Tout override venu du POST est silencieux.
    formulaire.cote = item.cote
    formulaire.fonds_id = item.fonds_id
    # V0.9.5 : extrait les valeurs des champs personnalisés (préfixe
    # `meta_<cle>`) et les fusionne dans `formulaire.metadonnees`.
    # Pydantic Form() n'expose pas les noms dynamiques, on relit donc
    # request.form() (cache Starlette → pas de double lecture du body).
    # V0.9.6 : `liste_multiple` → getlist (checkboxes envoient N fois
    # le meme name) ; les autres types restent une seule valeur.
    # V0.9.4-fix : on part de `item.metadonnees` (etat actuel DB) et
    # NON de `formulaire.metadonnees` (qui repart a `{}` car le form
    # n'expose pas la dict en hidden input). Sans ce fix, le POST
    # d'une edition de champ formel ecrasait les cles libres
    # restantes de l'item. Bug introduit dans 14139dc, observe sur
    # PF-002 (5 cles libres -> 1 cle apres test interne).
    form_data = await request.form()
    champs_perso = lister_champs_actifs_pour_item(db, item.id)
    nouvelles_metas = dict(item.metadonnees or {})
    for c in champs_perso:
        cle_form = f"meta_{c.cle}"
        if c.type == "liste_multiple":
            valeurs = [v.strip() for v in form_data.getlist(cle_form) if v.strip()]
            if valeurs:
                nouvelles_metas[c.cle] = valeurs
            else:
                nouvelles_metas.pop(c.cle, None)
        elif cle_form in form_data:
            val = (form_data[cle_form] or "").strip()
            if val:
                nouvelles_metas[c.cle] = val
            else:
                # Saisie vide = effacer la clé (cohérent avec le rendu
                # « non renseigné » et la sémantique import).
                nouvelles_metas.pop(c.cle, None)
    formulaire.metadonnees = nouvelles_metas
    try:
        modifier_item(db, item.id, formulaire, modifie_par=utilisateur)
    except ConflitVersion as e:
        # L'item a été modifié entre le rendu du formulaire et le POST.
        # On re-rend avec un erreur visible et la version actuelle
        # injectée pour que la ressoumission n'échoue plus si l'auteur
        # accepte d'écraser. Le formulaire conserve les saisies de
        # l'utilisateur pour qu'il puisse les ressoumettre sans tout
        # retaper.
        formulaire.version = item.version
        if e.version_actuelle is None:
            detail = (
                "modification cross-process détectée — la version "
                "actuelle ne peut pas être lue depuis la transaction "
                "courante"
            )
        else:
            detail = (
                f"version {e.version_actuelle} en base, "
                f"vous avez {e.version_attendue}"
            )
        return templates.TemplateResponse(
            request,
            "pages/item_modifier.html",
            _contexte_base(
                nom_base,
                utilisateur,
                item=item,
                fonds=fonds_obj,
                formulaire=formulaire,
                erreurs={
                    "_version": (
                        f"Cet item a été modifié entre-temps ({detail}). "
                        "Vérifiez les valeurs et resoumettez si vous "
                        "souhaitez écraser."
                    )
                },
                etats=list(EtatCatalogage),
                champs_personnalises=champs_perso,
                options_par_champ_perso=_options_par_champ_perso(champs_perso),
                langues_options=LANGUES_OPTIONS,
                types_coar_options=TYPES_COAR_OPTIONS,
            ),
            status_code=409,
        )
    except ItemInvalide as e:
        return templates.TemplateResponse(
            request,
            "pages/item_modifier.html",
            _contexte_base(
                nom_base,
                utilisateur,
                item=item,
                fonds=fonds_obj,
                formulaire=formulaire,
                erreurs=e.erreurs,
                etats=list(EtatCatalogage),
                champs_personnalises=champs_perso,
                options_par_champ_perso=_options_par_champ_perso(champs_perso),
                langues_options=LANGUES_OPTIONS,
                types_coar_options=TYPES_COAR_OPTIONS,
            ),
            status_code=400,
        )
    except OperationItemInterdite as e:
        # fonds_id immuable : ne devrait pas arriver vu l'override
        # ci-dessus, mais on rend l'erreur lisible si elle survient.
        raise HTTPException(status_code=400, detail=str(e)) from e
    return RedirectResponse(f"/item/{cote}?fonds={fonds_obj.cote}", status_code=303)


# ---------------------------------------------------------------------------
# Collaborateurs d'un fonds (CRUD HTMX-friendly)
# ---------------------------------------------------------------------------


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
    PRG-friendly : status 400 ; pas de redirect.

    Propage `synthese` + `consultation_url` + `q_surligne` pour que
    le re-render ait le même rendu que le GET nominal (sans, la page
    perd son bloc synthèse et le bouton mode consultation — UX
    incohérente vis-à-vis du GET). Pre-existing gap rattrapé en Lot B.
    """
    from archives_tool.models import Item

    detail = composer_page_fonds(db, cote)
    synthese = composer_synthese_fonds(db, detail.fonds)
    premier_item_cote = db.scalar(
        select(Item.cote)
        .where(Item.fonds_id == detail.fonds.id)
        .order_by(Item.cote)
        .limit(1)
    )
    consultation_url = (
        f"/lire/{detail.fonds.cote}/{premier_item_cote}"
        if premier_item_cote
        else None
    )
    return templates.TemplateResponse(
        request,
        "pages/fonds_lecture.html",
        _contexte_base(
            nom_base,
            utilisateur,
            detail=detail,
            synthese=synthese,
            roles_options=ROLES_OPTIONS,
            libelles_roles=LIBELLES_ROLE,
            consultation_url=consultation_url,
            q_surligne="",
            erreurs_collab=erreurs,
            formulaire_collab=formulaire,
            collaborateur_en_modification=collaborateur_en_modification,
        ),
        status_code=400,
    )


@router.post(
    "/fonds/{cote}/collaborateurs", response_class=HTMLResponse, response_model=None
)
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
        raise HTTPException(status_code=404, detail="Collaborateur introuvable.") from e
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


# ---------------------------------------------------------------------------
# Suppression d'entités (V0.9.7) — fonds / collection libre / item
#
# Sécurité : double-confirmation par recopie de la cote (param `confirmer`).
# Refus si `confirmer != cote` (clic accidentel, formulaire bookmark).
# Mode lecture seule bloqué par le middleware en amont (423). Miroir refusée
# par le service `supprimer_collection_libre`. Fichier individuel non géré
# dans ce premier cut (dette V0.9.7).
# ---------------------------------------------------------------------------


@router.post("/fonds/{cote}/supprimer", response_class=HTMLResponse, response_model=None)
def supprimer_fonds_route(
    cote: str,
    confirmer: Annotated[str, Form()],
    db: Session = Depends(get_db),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> RedirectResponse:
    fonds = _charger_fonds_ou_404(db, cote)
    if confirmer != fonds.cote:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Confirmation invalide : saisir exactement « {fonds.cote} » "
                f"pour confirmer la suppression du fonds."
            ),
        )
    supprimer_fonds(db, fonds.id, execute_par=utilisateur)
    return RedirectResponse("/", status_code=303)


@router.post(
    "/collection/{cote}/supprimer", response_class=HTMLResponse, response_model=None
)
def supprimer_collection_route(
    cote: str,
    confirmer: Annotated[str, Form()],
    fonds: str | None = None,
    db: Session = Depends(get_db),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> RedirectResponse:
    fonds_id: int | None = None
    if fonds is not None:
        fonds_obj = _charger_fonds_ou_404(db, fonds)
        fonds_id = fonds_obj.id
    try:
        col = lire_collection_par_cote(db, cote, fonds_id=fonds_id)
    except CollectionIntrouvable as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except OperationCollectionInterdite as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if confirmer != col.cote:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Confirmation invalide : saisir exactement « {col.cote} » "
                f"pour confirmer la suppression de la collection."
            ),
        )
    # Capture le fonds parent avant la suppression (la relation sera
    # invalidée après commit).
    fonds_parent_cote = col.fonds.cote if col.fonds is not None else None
    try:
        supprimer_collection_libre(db, col.id, execute_par=utilisateur)
    except OperationCollectionInterdite as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if fonds_parent_cote is not None:
        return RedirectResponse(f"/fonds/{fonds_parent_cote}", status_code=303)
    return RedirectResponse("/", status_code=303)


@router.post("/item/{cote}/supprimer", response_class=HTMLResponse, response_model=None)
def supprimer_item_route(
    cote: str,
    confirmer: Annotated[str, Form()],
    fonds: Annotated[str, Query()],
    db: Session = Depends(get_db),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> RedirectResponse:
    fonds_obj = _charger_fonds_ou_404(db, fonds)
    try:
        item = lire_item_par_cote(db, cote, fonds_id=fonds_obj.id)
    except ItemIntrouvable as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    if confirmer != item.cote:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Confirmation invalide : saisir exactement « {item.cote} » "
                f"pour confirmer la suppression de l'item."
            ),
        )
    supprimer_item(db, item.id, execute_par=utilisateur)
    return RedirectResponse(f"/fonds/{fonds_obj.cote}", status_code=303)
