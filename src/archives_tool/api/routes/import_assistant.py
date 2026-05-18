"""Routes de l'assistant d'import web (V0.7).

Wizard multi-pages : chaque étape a son URL `/import/{id}/{etape}`.
`/import/{id}` redirige vers l'étape courante de la session. Une
étape non encore atteinte redirige vers l'étape courante (pas de
saut en avant). L'état est persisté dans `SessionImport` à chaque
POST — l'utilisateur peut fermer et reprendre.

Sous-étape 1 : cycle de vie (accueil, création, abandon).
Sous-étape 2 : upload tableur + saisie des métadonnées du fonds.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from archives_tool.api.deps import get_db, get_nom_base, get_utilisateur_courant
from archives_tool.api.routes._helpers import (
    charger_session_import_ou_404,
    contexte_base as _contexte_base,
)
from archives_tool.api.services.import_web import (
    TAILLE_MAX_TABLEUR,
    TableurInvalide,
    abandonner_session,
    attacher_tableur,
    creer_session,
    enregistrer_fonds,
    lister_sessions_en_cours,
)
from archives_tool.api.templating import templates
from archives_tool.models import ETAPES_IMPORT, SessionImport
from archives_tool.profils.schema import FondsProfil

router = APIRouter()


# ---------------------------------------------------------------------------
# Accueil + cycle de vie
# ---------------------------------------------------------------------------


@router.get("/import", response_class=HTMLResponse)
def page_import(
    request: Request,
    db: Session = Depends(get_db),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse:
    """Accueil de l'assistant : imports en cours + démarrer un import."""
    sessions = lister_sessions_en_cours(db)
    return templates.TemplateResponse(
        request,
        "pages/import_accueil.html",
        _contexte_base(nom_base, utilisateur, sessions=sessions),
    )


@router.post("/import/nouveau", response_class=HTMLResponse, response_model=None)
def nouveau_import(
    db: Session = Depends(get_db),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> RedirectResponse:
    """Crée une session d'import vierge et ouvre sa première étape."""
    session = creer_session(db, utilisateur)
    return RedirectResponse(f"/import/{session.id}", status_code=303)


@router.post(
    "/import/{session_id}/abandonner",
    response_class=HTMLResponse,
    response_model=None,
)
def abandonner_import(
    session_id: int,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Abandonne une session : statut `abandonnee`, tableur temporaire
    supprimé. Idempotent."""
    session = charger_session_import_ou_404(db, session_id)
    abandonner_session(db, session)
    return RedirectResponse("/import", status_code=303)


@router.get("/import/{session_id}", response_class=HTMLResponse, response_model=None)
def page_session_import(
    session_id: int,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    """Ouvre une session sur son étape courante."""
    session = charger_session_import_ou_404(db, session_id)
    return RedirectResponse(
        f"/import/{session.id}/{session.etape}", status_code=303
    )


# ---------------------------------------------------------------------------
# Navigation entre étapes
# ---------------------------------------------------------------------------


def _rediriger_vers_etape_courante(session: SessionImport) -> RedirectResponse:
    return RedirectResponse(
        f"/import/{session.id}/{session.etape}", status_code=303
    )


def _etape_accessible(session: SessionImport, demandee: str) -> bool:
    """Vrai si l'utilisateur peut afficher `demandee` : une étape déjà
    franchie ou l'étape courante, jamais un saut en avant."""
    return ETAPES_IMPORT.index(demandee) <= ETAPES_IMPORT.index(session.etape)


# ---------------------------------------------------------------------------
# Étape 1 — upload du tableur
# ---------------------------------------------------------------------------


@router.get(
    "/import/{session_id}/tableur",
    response_class=HTMLResponse,
    response_model=None,
)
def etape_tableur(
    session_id: int,
    request: Request,
    db: Session = Depends(get_db),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse:
    session = charger_session_import_ou_404(db, session_id)
    return templates.TemplateResponse(
        request,
        "pages/import_etape_tableur.html",
        _contexte_base(nom_base, utilisateur, session=session, erreur=None),
    )


@router.post(
    "/import/{session_id}/tableur",
    response_class=HTMLResponse,
    response_model=None,
)
def soumettre_tableur(
    session_id: int,
    request: Request,
    fichier: UploadFile,
    feuille: Annotated[str, Form()] = "",
    db: Session = Depends(get_db),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse | RedirectResponse:
    session = charger_session_import_ou_404(db, session_id)
    # Lecture bornée : on ne charge jamais plus que la limite + 1 octet
    # en mémoire. `attacher_tableur` rejette si la taille dépasse la
    # limite — un upload géant est ainsi tronqué, pas avalé en entier.
    contenu = fichier.file.read(TAILLE_MAX_TABLEUR + 1)
    try:
        attacher_tableur(
            db,
            session,
            contenu,
            fichier.filename or "tableur",
            feuille=feuille.strip() or None,
        )
    except TableurInvalide as e:
        return templates.TemplateResponse(
            request,
            "pages/import_etape_tableur.html",
            _contexte_base(
                nom_base, utilisateur, session=session, erreur=str(e)
            ),
            status_code=400,
        )
    return RedirectResponse(f"/import/{session.id}/fonds", status_code=303)


# ---------------------------------------------------------------------------
# Étape 2 — métadonnées du fonds
# ---------------------------------------------------------------------------

# Champs de la section `fonds:` exposés par le formulaire, dans l'ordre
# d'affichage. cote + titre sont obligatoires (FondsProfil), le reste
# optionnel.
_CHAMPS_FONDS: tuple[str, ...] = (
    "cote",
    "titre",
    "description",
    "description_interne",
    "editeur",
    "lieu_edition",
    "periodicite",
    "issn",
    "date_debut",
    "date_fin",
    "responsable_archives",
    "personnalite_associee",
)


@router.get(
    "/import/{session_id}/fonds",
    response_class=HTMLResponse,
    response_model=None,
)
def etape_fonds(
    session_id: int,
    request: Request,
    db: Session = Depends(get_db),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse | RedirectResponse:
    session = charger_session_import_ou_404(db, session_id)
    if not _etape_accessible(session, "fonds"):
        return _rediriger_vers_etape_courante(session)
    return templates.TemplateResponse(
        request,
        "pages/import_etape_fonds.html",
        _contexte_base(
            nom_base,
            utilisateur,
            session=session,
            valeurs=session.fonds_data or {},
            champs=_CHAMPS_FONDS,
            erreurs={},
        ),
    )


@router.post(
    "/import/{session_id}/fonds",
    response_class=HTMLResponse,
    response_model=None,
)
def soumettre_fonds(
    session_id: int,
    request: Request,
    cote: Annotated[str, Form()] = "",
    titre: Annotated[str, Form()] = "",
    description: Annotated[str, Form()] = "",
    description_interne: Annotated[str, Form()] = "",
    editeur: Annotated[str, Form()] = "",
    lieu_edition: Annotated[str, Form()] = "",
    periodicite: Annotated[str, Form()] = "",
    issn: Annotated[str, Form()] = "",
    date_debut: Annotated[str, Form()] = "",
    date_fin: Annotated[str, Form()] = "",
    responsable_archives: Annotated[str, Form()] = "",
    personnalite_associee: Annotated[str, Form()] = "",
    db: Session = Depends(get_db),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse | RedirectResponse:
    session = charger_session_import_ou_404(db, session_id)
    # Champs vides → absents du dict : FondsProfil les traitera comme
    # None (valeur par défaut), pas comme chaîne vide.
    brut = {
        "cote": cote,
        "titre": titre,
        "description": description,
        "description_interne": description_interne,
        "editeur": editeur,
        "lieu_edition": lieu_edition,
        "periodicite": periodicite,
        "issn": issn,
        "date_debut": date_debut,
        "date_fin": date_fin,
        "responsable_archives": responsable_archives,
        "personnalite_associee": personnalite_associee,
    }
    fonds_data = {k: v.strip() for k, v in brut.items() if v and v.strip()}

    try:
        FondsProfil.model_validate(fonds_data)
    except ValidationError as e:
        erreurs = {
            str(err["loc"][0]): err["msg"]
            for err in e.errors()
            if err.get("loc")
        }
        return templates.TemplateResponse(
            request,
            "pages/import_etape_fonds.html",
            _contexte_base(
                nom_base,
                utilisateur,
                session=session,
                valeurs=fonds_data,
                champs=_CHAMPS_FONDS,
                erreurs=erreurs,
            ),
            status_code=400,
        )

    enregistrer_fonds(db, session, fonds_data)
    return RedirectResponse(f"/import/{session.id}/mapping", status_code=303)


# ---------------------------------------------------------------------------
# Étape 3 — mapping (stub : livré en sous-étape 3)
# ---------------------------------------------------------------------------


@router.get(
    "/import/{session_id}/mapping",
    response_class=HTMLResponse,
    response_model=None,
)
def etape_mapping(
    session_id: int,
    request: Request,
    db: Session = Depends(get_db),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse | RedirectResponse:
    session = charger_session_import_ou_404(db, session_id)
    if not _etape_accessible(session, "mapping"):
        return _rediriger_vers_etape_courante(session)
    return templates.TemplateResponse(
        request,
        "pages/import_etape_mapping.html",
        _contexte_base(nom_base, utilisateur, session=session),
    )
