"""Gestion des vocabulaires personnalisés (V0.9.4 lot 3a).

Routes web pour CRUD ``Vocabulaire`` + ``ValeurControlee`` depuis l'UI.
Indépendantes des collections : un vocabulaire est partagé par toutes
les collections (un même tag « personnage » peut être référencé par
plusieurs ``ChampPersonnalise`` de fonds différents).

Wire avec ``ChampPersonnalise.valeurs_controlees_id`` : lot 3b.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from archives_tool.api.deps import (
    get_db,
    get_nom_base,
    get_utilisateur_courant,
)
from archives_tool.api.routes._helpers import contexte_base as _contexte_base
from archives_tool.api.services._erreurs import EntiteIntrouvable
from archives_tool.api.services.fonds import lister_fonds
from archives_tool.api.services.vocabulaires_db import (
    FormulaireValeur,
    FormulaireVocabulaire,
    ValeurInvalide,
    VocabulaireInvalide,
    VocabulaireReference,
    ajouter_valeur,
    attacher_vocabulaire_au_fonds,
    creer_vocabulaire,
    deprecier_valeur,
    detacher_vocabulaire_du_fonds,
    lister_vocabulaires,
    modifier_valeur,
    modifier_vocabulaire,
    reactiver_valeur,
    supprimer_valeur,
    supprimer_vocabulaire,
    valeur_par_id,
    vocabulaire_par_id,
)
from archives_tool.api.templating import templates
from archives_tool.models import ValeurControlee

router = APIRouter()


def _valider_appartenance_valeur(
    valeur: ValeurControlee, vocab_id: int
) -> None:
    """Garde anti-confused-deputy : POST sur
    ``/vocabulaires/A/valeurs/<id>/...`` où ``id`` est en réalité dans
    le vocab B doit être rejeté en 404."""
    if valeur.vocabulaire_id != vocab_id:
        raise HTTPException(
            status_code=404,
            detail=f"Valeur {valeur.id} introuvable dans ce vocabulaire.",
        )


def _contexte_detail_vocab(
    db: Session,
    vocab,
    *,
    nom_base: str,
    utilisateur: str,
    **overrides,
) -> dict:
    """Construit le contexte de rendu de `vocabulaire_detail.html`.

    Centralise les variables communes (vocab + tous les fonds pour les
    cases à cocher de rattachement T3 + IDs cochés) pour ne pas
    dupliquer cette logique dans les 5 routes qui rendent ce template
    (page principale + 4 re-render après erreur de validation)."""
    return _contexte_base(
        nom_base,
        utilisateur,
        vocabulaire=vocab,
        tous_les_fonds=lister_fonds(db),
        ids_fonds_rattaches={f.id for f in vocab.fonds_rattaches},
        **overrides,
    )


# ---------------------------------------------------------------------------
# Liste + création vocabulaire
# ---------------------------------------------------------------------------


@router.get("/vocabulaires", response_class=HTMLResponse, response_model=None)
def page_vocabulaires(
    request: Request,
    db: Session = Depends(get_db),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse:
    """Page d'accueil : liste des vocabulaires + formulaire création."""
    vocabs = lister_vocabulaires(db)
    return templates.TemplateResponse(
        request,
        "pages/vocabulaires.html",
        _contexte_base(
            nom_base,
            utilisateur,
            vocabulaires=vocabs,
            formulaire=FormulaireVocabulaire(),
            erreurs={},
        ),
    )


@router.post(
    "/vocabulaires/creer",
    response_class=HTMLResponse,
    response_model=None,
)
def soumettre_creer_vocabulaire(
    request: Request,
    formulaire: Annotated[FormulaireVocabulaire, Form()],
    db: Session = Depends(get_db),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse | RedirectResponse:
    try:
        vocab = creer_vocabulaire(db, formulaire)
    except VocabulaireInvalide as e:
        return templates.TemplateResponse(
            request,
            "pages/vocabulaires.html",
            _contexte_base(
                nom_base,
                utilisateur,
                vocabulaires=lister_vocabulaires(db),
                formulaire=formulaire,
                erreurs=e.erreurs,
            ),
            status_code=400,
        )
    return RedirectResponse(f"/vocabulaires/{vocab.id}", status_code=303)


# ---------------------------------------------------------------------------
# Détail / modifier / supprimer un vocabulaire
# ---------------------------------------------------------------------------


@router.get(
    "/vocabulaires/{vocab_id}",
    response_class=HTMLResponse,
    response_model=None,
)
def page_vocabulaire(
    vocab_id: int,
    request: Request,
    db: Session = Depends(get_db),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse:
    """Page détail : métadonnées du vocabulaire + tableau des valeurs
    + formulaire d'ajout d'une nouvelle valeur."""
    vocab = vocabulaire_par_id(db, vocab_id)
    return templates.TemplateResponse(
        request,
        "pages/vocabulaire_detail.html",
        _contexte_detail_vocab(
            db,
            vocab,
            nom_base=nom_base,
            utilisateur=utilisateur,
            formulaire_vocab=FormulaireVocabulaire(
                code=vocab.code,
                libelle=vocab.libelle,
                description=vocab.description or "",
                description_interne=vocab.description_interne or "",
                uri_base=vocab.uri_base or "",
            ),
            formulaire_valeur=FormulaireValeur(),
            erreurs_vocab={},
            erreurs_valeur={},
        ),
    )


@router.post(
    "/vocabulaires/{vocab_id}/modifier",
    response_class=HTMLResponse,
    response_model=None,
)
def soumettre_modifier_vocabulaire(
    vocab_id: int,
    request: Request,
    formulaire: Annotated[FormulaireVocabulaire, Form()],
    db: Session = Depends(get_db),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse | RedirectResponse:
    try:
        modifier_vocabulaire(db, vocab_id, formulaire)
    except VocabulaireInvalide as e:
        vocab = vocabulaire_par_id(db, vocab_id)
        return templates.TemplateResponse(
            request,
            "pages/vocabulaire_detail.html",
            _contexte_detail_vocab(
                db,
                vocab,
                nom_base=nom_base,
                utilisateur=utilisateur,
                formulaire_vocab=formulaire,
                formulaire_valeur=FormulaireValeur(),
                erreurs_vocab=e.erreurs,
                erreurs_valeur={},
            ),
            status_code=400,
        )
    return RedirectResponse(f"/vocabulaires/{vocab_id}", status_code=303)


@router.post(
    "/vocabulaires/{vocab_id}/supprimer",
    response_class=HTMLResponse,
    response_model=None,
)
def soumettre_supprimer_vocabulaire(
    vocab_id: int,
    request: Request,
    db: Session = Depends(get_db),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse | RedirectResponse:
    try:
        supprimer_vocabulaire(db, vocab_id)
    except VocabulaireReference as e:
        vocab = vocabulaire_par_id(db, vocab_id)
        return templates.TemplateResponse(
            request,
            "pages/vocabulaire_detail.html",
            _contexte_detail_vocab(
                db,
                vocab,
                nom_base=nom_base,
                utilisateur=utilisateur,
                formulaire_vocab=FormulaireVocabulaire(
                    code=vocab.code,
                    libelle=vocab.libelle,
                    description=vocab.description or "",
                    description_interne=vocab.description_interne or "",
                    uri_base=vocab.uri_base or "",
                ),
                formulaire_valeur=FormulaireValeur(),
                erreurs_vocab={
                    "_global": (
                        f"Impossible : vocabulaire référencé par "
                        f"{len(e.champs_referents)} champ(s) "
                        f"personnalisé(s) ({', '.join(e.champs_referents)}). "
                        "Détacher le vocabulaire de ces champs avant de supprimer."
                    )
                },
                erreurs_valeur={},
            ),
            status_code=409,
        )
    return RedirectResponse("/vocabulaires", status_code=303)


# ---------------------------------------------------------------------------
# Valeurs contrôlées (ajout / modif / déprécier / réactiver / supprimer)
# ---------------------------------------------------------------------------


@router.post(
    "/vocabulaires/{vocab_id}/valeurs/ajouter",
    response_class=HTMLResponse,
    response_model=None,
)
def soumettre_ajouter_valeur(
    vocab_id: int,
    request: Request,
    formulaire: Annotated[FormulaireValeur, Form()],
    db: Session = Depends(get_db),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse | RedirectResponse:
    try:
        ajouter_valeur(db, vocab_id, formulaire)
    except ValeurInvalide as e:
        vocab = vocabulaire_par_id(db, vocab_id)
        return templates.TemplateResponse(
            request,
            "pages/vocabulaire_detail.html",
            _contexte_detail_vocab(
                db,
                vocab,
                nom_base=nom_base,
                utilisateur=utilisateur,
                formulaire_vocab=FormulaireVocabulaire(
                    code=vocab.code,
                    libelle=vocab.libelle,
                    description=vocab.description or "",
                    description_interne=vocab.description_interne or "",
                    uri_base=vocab.uri_base or "",
                ),
                formulaire_valeur=formulaire,
                erreurs_vocab={},
                erreurs_valeur=e.erreurs,
            ),
            status_code=400,
        )
    return RedirectResponse(f"/vocabulaires/{vocab_id}", status_code=303)


@router.post(
    "/vocabulaires/{vocab_id}/valeurs/{valeur_id}/modifier",
    response_class=HTMLResponse,
    response_model=None,
)
def soumettre_modifier_valeur(
    vocab_id: int,
    valeur_id: int,
    request: Request,
    formulaire: Annotated[FormulaireValeur, Form()],
    db: Session = Depends(get_db),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse | RedirectResponse:
    valeur = valeur_par_id(db, valeur_id)
    _valider_appartenance_valeur(valeur, vocab_id)
    try:
        modifier_valeur(db, valeur_id, formulaire)
    except ValeurInvalide as e:
        vocab = vocabulaire_par_id(db, vocab_id)
        return templates.TemplateResponse(
            request,
            "pages/vocabulaire_detail.html",
            _contexte_detail_vocab(
                db,
                vocab,
                nom_base=nom_base,
                utilisateur=utilisateur,
                formulaire_vocab=FormulaireVocabulaire(
                    code=vocab.code,
                    libelle=vocab.libelle,
                    description=vocab.description or "",
                    description_interne=vocab.description_interne or "",
                    uri_base=vocab.uri_base or "",
                ),
                formulaire_valeur=formulaire,
                erreurs_vocab={},
                erreurs_valeur=e.erreurs,
                valeur_en_modification=valeur_id,
            ),
            status_code=400,
        )
    return RedirectResponse(f"/vocabulaires/{vocab_id}", status_code=303)


@router.post(
    "/vocabulaires/{vocab_id}/valeurs/{valeur_id}/deprecier",
    response_class=HTMLResponse,
    response_model=None,
)
def soumettre_deprecier_valeur(
    vocab_id: int,
    valeur_id: int,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    valeur = valeur_par_id(db, valeur_id)
    _valider_appartenance_valeur(valeur, vocab_id)
    deprecier_valeur(db, valeur_id)
    return RedirectResponse(f"/vocabulaires/{vocab_id}", status_code=303)


@router.post(
    "/vocabulaires/{vocab_id}/valeurs/{valeur_id}/reactiver",
    response_class=HTMLResponse,
    response_model=None,
)
def soumettre_reactiver_valeur(
    vocab_id: int,
    valeur_id: int,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    valeur = valeur_par_id(db, valeur_id)
    _valider_appartenance_valeur(valeur, vocab_id)
    reactiver_valeur(db, valeur_id)
    return RedirectResponse(f"/vocabulaires/{vocab_id}", status_code=303)


@router.post(
    "/vocabulaires/{vocab_id}/valeurs/{valeur_id}/supprimer",
    response_class=HTMLResponse,
    response_model=None,
)
def soumettre_supprimer_valeur(
    vocab_id: int,
    valeur_id: int,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    valeur = valeur_par_id(db, valeur_id)
    _valider_appartenance_valeur(valeur, vocab_id)
    supprimer_valeur(db, valeur_id)
    return RedirectResponse(f"/vocabulaires/{vocab_id}", status_code=303)


# ---------------------------------------------------------------------------
# Rattachement vocab ↔ fonds (T3 du chantier scoping)
# ---------------------------------------------------------------------------


def _fonds_par_cote_ou_404(db: Session, cote: str):
    """Lookup fonds + 404 si inconnu (cote vient d'un form/URL utilisateur)."""
    from sqlalchemy import select as sa_select

    from archives_tool.models import Fonds

    fonds = db.scalar(sa_select(Fonds).where(Fonds.cote == cote))
    if fonds is None:
        raise HTTPException(
            status_code=404, detail=f"Fonds « {cote} » introuvable."
        )
    return fonds


@router.post(
    "/vocabulaires/{vocab_id}/fonds/{cote}/attacher",
    response_class=HTMLResponse,
    response_model=None,
)
def soumettre_attacher_fonds(
    vocab_id: int,
    cote: str,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Rattache un vocabulaire à un fonds. Idempotent côté service."""
    # Garde-fou que le vocab existe (sinon service lèvera plus tard).
    vocabulaire_par_id(db, vocab_id)
    fonds = _fonds_par_cote_ou_404(db, cote)
    try:
        attacher_vocabulaire_au_fonds(db, vocab_id, fonds.id)
    except EntiteIntrouvable as e:
        # Course rare : fonds supprimé entre la lecture et le service.
        raise HTTPException(status_code=404, detail=str(e)) from e
    return RedirectResponse(f"/vocabulaires/{vocab_id}", status_code=303)


@router.post(
    "/vocabulaires/{vocab_id}/fonds/{cote}/detacher",
    response_class=HTMLResponse,
    response_model=None,
)
def soumettre_detacher_fonds(
    vocab_id: int,
    cote: str,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Détache un vocabulaire d'un fonds. Idempotent côté service."""
    vocabulaire_par_id(db, vocab_id)
    fonds = _fonds_par_cote_ou_404(db, cote)
    try:
        detacher_vocabulaire_du_fonds(db, vocab_id, fonds.id)
    except EntiteIntrouvable as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return RedirectResponse(f"/vocabulaires/{vocab_id}", status_code=303)


# ---------------------------------------------------------------------------
# Enrichissement rétroactif (T4 scoping)
# ---------------------------------------------------------------------------


@router.get(
    "/vocabulaires/{vocab_id}/fonds/{cote}/enrichir",
    response_class=HTMLResponse,
    response_model=None,
)
def page_enrichissement_preview(
    vocab_id: int,
    cote: str,
    request: Request,
    db: Session = Depends(get_db),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
):
    """Preview (dry-run) de l'enrichissement rétroactif des annotations
    du fonds avec les URIs du vocabulaire.

    Affiche la liste des matches candidats AVANT toute modification.
    L'utilisateur confirme via le POST de cette même URL pour appliquer.
    """
    from archives_tool.api.services.annotations import (
        enrichir_annotations_par_vocab,
    )

    vocab = vocabulaire_par_id(db, vocab_id)
    fonds = _fonds_par_cote_ou_404(db, cote)
    rapport = enrichir_annotations_par_vocab(
        db, vocab_id, fonds.id, dry_run=True,
    )
    contexte = _contexte_base(
        nom_base, utilisateur,
        vocabulaire=vocab,
        fonds=fonds,
        rapport=rapport,
    )
    return templates.TemplateResponse(
        request, "pages/enrichissement_preview.html", contexte,
    )


@router.post(
    "/vocabulaires/{vocab_id}/fonds/{cote}/enrichir",
    response_class=HTMLResponse,
    response_model=None,
)
def soumettre_enrichissement(
    vocab_id: int,
    cote: str,
    db: Session = Depends(get_db),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> RedirectResponse:
    """Applique l'enrichissement rétroactif (sortie du dry-run).

    Idempotent (replay = no-op grâce au service). Redirige vers la page
    du vocabulaire avec un flash de comptage via query string.
    """
    from archives_tool.api.services.annotations import (
        enrichir_annotations_par_vocab,
    )

    vocabulaire_par_id(db, vocab_id)
    fonds = _fonds_par_cote_ou_404(db, cote)
    rapport = enrichir_annotations_par_vocab(
        db, vocab_id, fonds.id,
        dry_run=False,
        modifie_par=utilisateur,
    )
    # Flash léger via query string (pas de session storage). La page
    # vocab pourrait l'afficher en bandeau dans un futur lot ; pour
    # l'instant la redirection suffit (l'utilisateur voit que l'action
    # est terminée).
    return RedirectResponse(
        f"/vocabulaires/{vocab_id}"
        f"?enrichi={rapport.annotations_modifiees}"
        f"&fonds={cote}",
        status_code=303,
    )
