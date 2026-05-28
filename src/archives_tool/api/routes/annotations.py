"""Routes REST pour les annotations W3C (V0.9.7).

4 endpoints pour le CRUD :

- `GET    /api/fichiers/{id}/annotations` → AnnotationPage W3C
- `POST   /api/fichiers/{id}/annotations` → création
- `PUT    /api/annotations/{id}`         → modification (verrou optimiste)
- `DELETE /api/annotations/{id}`         → suppression (idempotente)

Format de payload (POST / PUT) : forme W3C simplifiée acceptant
`target.selector` ou directement `selecteur` + `selecteur_type`. La
sortie GET est toujours en JSON-LD W3C complet (réversibilité).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from archives_tool.api.deps import get_db, get_utilisateur_courant
from archives_tool.api.services.annotations import (
    AnnotationIntrouvable,
    AnnotationInvalide,
    FormulaireAnnotation,
    creer_annotation,
    lire_annotation,
    lister_annotations_fichier,
    modifier_annotation,
    serialiser_collection_w3c,
    serialiser_w3c,
    supprimer_annotation,
)
from archives_tool.api.services.conflits import ConflitVersion
from archives_tool.models import Fichier, ValeurControlee, Vocabulaire

router = APIRouter(prefix="/api", tags=["annotations"])


def _formulaire_depuis_payload(payload: dict[str, Any]) -> FormulaireAnnotation:
    """Convertit un payload JSON (POST/PUT) en `FormulaireAnnotation`.

    Accepte deux formes :

    - **Forme simple** (recommandée pour API client) : champs plats
      `selecteur`, `selecteur_type`, `corps`, `motivation`, `version`.
    - **Forme W3C complète** : `{target: {selector: {type, value}},
      body: [...], motivation: ..., version: ...}`. Utile si un client
      Annotorious envoie directement son JSON-LD natif.

    Validation Pydantic appliquée à la fin (selecteur_type, motivation).
    """
    # Détection forme W3C : présence de `target` ou `body`.
    if "target" in payload or "body" in payload:
        target = payload.get("target") or {}
        selector = target.get("selector") or {}
        sel_value = selector.get("value", "")
        sel_type_w3c = selector.get("type", "FragmentSelector")
        # Mapping W3C type → notre type interne court.
        sel_type = "svg" if sel_type_w3c == "SvgSelector" else "fragment"
        return FormulaireAnnotation(
            selecteur=sel_value,
            selecteur_type=sel_type,
            corps=list(payload.get("body") or []),
            motivation=payload.get("motivation", "tagging"),
            version=payload.get("version"),
        )
    # Forme simple.
    return FormulaireAnnotation(
        selecteur=payload.get("selecteur", ""),
        selecteur_type=payload.get("selecteur_type", "fragment"),
        corps=list(payload.get("corps") or []),
        motivation=payload.get("motivation", "tagging"),
        version=payload.get("version"),
    )


def _erreurs_response(erreurs: dict[str, str], status: int = 400) -> JSONResponse:
    return JSONResponse(
        {"detail": "Validation refusée.", "erreurs": erreurs},
        status_code=status,
    )


# ---------------------------------------------------------------------------
# GET liste — sortie AnnotationPage W3C
# ---------------------------------------------------------------------------


@router.get("/fichiers/{fichier_id}/annotations")
def get_annotations_fichier(
    fichier_id: int,
    request: Request,
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Liste les annotations W3C d'un fichier (AnnotationPage)."""
    fichier = db.get(Fichier, fichier_id)
    if fichier is None:
        raise HTTPException(status_code=404, detail=f"Fichier {fichier_id} introuvable.")
    annotations = lister_annotations_fichier(db, fichier_id)
    # base_url : URL du serveur pour URIs absolues. None ou vide
    # = URIs relatives (acceptables côté Annotorious local).
    base_url = str(request.base_url).rstrip("/")
    page = serialiser_collection_w3c(
        list(annotations), fichier_id=fichier_id, base_url=base_url
    )
    return JSONResponse(page)


# ---------------------------------------------------------------------------
# POST création
# ---------------------------------------------------------------------------


@router.post("/fichiers/{fichier_id}/annotations")
async def post_annotation_fichier(
    fichier_id: int,
    request: Request,
    db: Session = Depends(get_db),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> JSONResponse:
    """Crée une annotation sur un fichier. Renvoie le JSON-LD W3C
    de l'annotation créée (avec son ID neuf)."""
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Corps JSON invalide.")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Le corps doit être un objet JSON.")

    try:
        formulaire = _formulaire_depuis_payload(payload)
    except Exception as e:
        return _erreurs_response({"payload": str(e)}, status=400)

    try:
        annotation = creer_annotation(
            db, fichier_id, formulaire, cree_par=utilisateur
        )
    except AnnotationIntrouvable as e:
        raise HTTPException(status_code=404, detail=str(e))
    except AnnotationInvalide as e:
        return _erreurs_response(e.erreurs, status=400)

    base_url = str(request.base_url).rstrip("/")
    return JSONResponse(
        serialiser_w3c(annotation, base_url=base_url),
        status_code=201,
    )


# ---------------------------------------------------------------------------
# PUT modification — verrou optimiste via `version` dans le payload
# ---------------------------------------------------------------------------


@router.put("/annotations/{annotation_id}")
async def put_annotation(
    annotation_id: int,
    request: Request,
    db: Session = Depends(get_db),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> JSONResponse:
    """Modifie une annotation. Le payload doit contenir `version`
    (lue par un précédent GET) — sinon 409 Conflict si la version
    en base diffère."""
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Corps JSON invalide.")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Le corps doit être un objet JSON.")

    try:
        formulaire = _formulaire_depuis_payload(payload)
    except Exception as e:
        return _erreurs_response({"payload": str(e)}, status=400)

    try:
        annotation = modifier_annotation(
            db, annotation_id, formulaire, modifie_par=utilisateur
        )
    except AnnotationIntrouvable as e:
        raise HTTPException(status_code=404, detail=str(e))
    except AnnotationInvalide as e:
        return _erreurs_response(e.erreurs, status=400)
    except ConflitVersion as e:
        return JSONResponse(
            {
                "detail": "Conflit de version (l'annotation a été modifiée ailleurs).",
                "version_actuelle": e.version_actuelle,
                "version_attendue": e.version_attendue,
            },
            status_code=409,
        )

    base_url = str(request.base_url).rstrip("/")
    return JSONResponse(serialiser_w3c(annotation, base_url=base_url))


# ---------------------------------------------------------------------------
# DELETE — idempotent
# ---------------------------------------------------------------------------


@router.delete("/annotations/{annotation_id}", status_code=204)
def delete_annotation(
    annotation_id: int,
    db: Session = Depends(get_db),
) -> None:
    """Supprime une annotation. Idempotent — 204 même si l'annotation
    n'existait pas (cohérent avec REST DELETE)."""
    supprimer_annotation(db, annotation_id)


# ---------------------------------------------------------------------------
# GET unitaire (bonus — utile au client Annotorious pour rafraîchir
# une annotation après création / modification)
# ---------------------------------------------------------------------------


@router.get("/annotations/{annotation_id}")
def get_annotation(
    annotation_id: int,
    request: Request,
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Lookup unitaire d'une annotation par ID."""
    try:
        annotation = lire_annotation(db, annotation_id)
    except AnnotationIntrouvable as e:
        raise HTTPException(status_code=404, detail=str(e))
    base_url = str(request.base_url).rstrip("/")
    return JSONResponse(serialiser_w3c(annotation, base_url=base_url))


# ---------------------------------------------------------------------------
# Autocomplete vocabulaires (V0.9.7 γ.3)
# ---------------------------------------------------------------------------


@router.get("/vocabulaires/autocomplete")
def get_autocomplete_vocabulaires(
    fichier_id: int | None = None,
    db: Session = Depends(get_db),
) -> JSONResponse:
    """Liste les ValeurControlee actives pour l'autocomplete Annotorious.

    Sans `fichier_id` : retourne tout (cas d'usage hors annotation,
    ex. édition d'un champ personnalisé sur la fiche item — voir
    `vocabulaire-scoping-future.md` T2 paragraphe « Sans fichier_id »).

    Avec `fichier_id` : résout fichier → item → fonds, et filtre les
    valeurs selon le rattachement vocab ↔ fonds (cf.
    `vocabulaire-scoping-future.md` T2) :
      - vocab sans rattachement → visible partout (global)
      - vocab rattaché à au moins un fonds → visible uniquement sur
        les fichiers des fonds rattachés
    Si le fichier est introuvable, on retombe sur le comportement
    sans filtre (pas de crash, pas d'info utilisateur).

    Sortie : `{valeurs: [{vocabulaire, vocabulaire_code, code, libelle, uri}]}`.
    Le client construit un datalist HTML5 + au save, si le libellé
    matche, ajoute un body SpecificResource avec l'URI (pivot
    Wikidata/VIAF).
    """
    from sqlalchemy import or_, select

    from archives_tool.models import Item
    from archives_tool.models.profil import vocabulaire_fonds

    # Résolution fichier → fonds quand possible. Si le fichier n'existe
    # pas, on bascule en mode « tout retourné » (défaut le plus permissif,
    # cohérent avec la stratégie « global = visible partout »).
    fonds_courant_id: int | None = None
    if fichier_id is not None:
        fonds_courant_id = db.scalar(
            select(Item.fonds_id)
            .join(Fichier, Fichier.item_id == Item.id)
            .where(Fichier.id == fichier_id)
        )

    stmt = (
        select(
            Vocabulaire.code.label("vocab_code"),
            Vocabulaire.libelle.label("vocab_libelle"),
            ValeurControlee.code,
            ValeurControlee.libelle,
            ValeurControlee.uri,
        )
        .join(ValeurControlee, ValeurControlee.vocabulaire_id == Vocabulaire.id)
        .where(ValeurControlee.actif.is_(True))
    )

    if fonds_courant_id is not None:
        # Convention : un vocab sans aucune ligne dans `vocabulaire_fonds`
        # est global. Un vocab avec ≥1 ligne est visible uniquement sur
        # ses fonds rattachés.
        #
        # Sous-requêtes :
        # - `vocab_a_rattachement` : vocabs qui ont au moins un fonds.
        # - `vocab_rattache_au_fonds` : vocabs rattachés au fonds courant.
        sub_a_rattachement = (
            select(vocabulaire_fonds.c.vocabulaire_id).distinct().subquery()
        )
        sub_rattache_au_fonds = (
            select(vocabulaire_fonds.c.vocabulaire_id)
            .where(vocabulaire_fonds.c.fonds_id == fonds_courant_id)
            .subquery()
        )
        stmt = stmt.where(
            or_(
                # Vocab global (pas dans la junction du tout)
                Vocabulaire.id.notin_(select(sub_a_rattachement.c.vocabulaire_id)),
                # OU vocab rattaché au fonds courant
                Vocabulaire.id.in_(select(sub_rattache_au_fonds.c.vocabulaire_id)),
            )
        )

    stmt = stmt.order_by(Vocabulaire.libelle, ValeurControlee.libelle)

    rows = db.execute(stmt).all()

    valeurs = [
        {
            "vocabulaire": row.vocab_libelle,
            "vocabulaire_code": row.vocab_code,
            "code": row.code,
            "libelle": row.libelle,
            "uri": row.uri,
        }
        for row in rows
    ]
    return JSONResponse({"valeurs": valeurs})
