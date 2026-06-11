"""Routes web Nakala (Lot 3) — page autonome `/nakala`.

Trois opérations sur une collection Nakala (DOI ou URL collée) :

- **Exporter** un tableur CSV/xlsx (téléchargement, lecture seule OK) ;
- **Rapatrier** la collection en base (aperçu dry-run en GET, puis exécution
  en POST — bloquée en lecture seule par le middleware) ;
- **Rafraîchir** les items déjà liés (même schéma aperçu → exécution).

Pas d'infra de tâches d'arrière-plan dans ColleC (app locale mono-utilisateur) :
le rapatriement/rafraîchissement réel est **synchrone**. L'aperçu dry-run +
un avertissement de durée + un bouton de confirmation qui se désactive au
submit couvrent l'attente. `ClientLectureNakala` est importé au niveau module
pour être monkeypatchable en test (comme la CLI).
"""

from __future__ import annotations

from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from archives_tool.api.deps import (
    get_config,
    get_db,
    get_nom_base,
    get_utilisateur_courant,
)
from archives_tool.api.routes._helpers import contexte_base as _contexte_base
from archives_tool.api.services.fonds import FondsIntrouvable
from archives_tool.api.services.nakala import (
    rafraichir_collection,
    rapatrier_collection,
    titre_collection_nakala,
)
from archives_tool.api.templating import templates
from archives_tool.config import ConfigLocale
from archives_tool.external.nakala.client import (
    ClientLectureNakala,
    ErreurNakala,
    NakalaAccesInterdit,
    NakalaAuthRefusee,
    NakalaInjoignable,
    NakalaIntrouvable,
    normaliser_identifiant_nakala,
)
from archives_tool.external.nakala.collection import iterer_donnees_collection
from archives_tool.external.nakala.tableur import (
    lignes_niveau_donnee,
    lignes_niveau_fichier,
)
from archives_tool.external.nakala.tableur_io import (
    MIME_CSV,
    MIME_XLSX,
    vers_csv_bytes,
    vers_xlsx_bytes,
)

router = APIRouter()

_GRANULARITES = {"donnee", "fichier"}
_FORMATS = {"csv", "xlsx"}


def _client_ou_none(config: ConfigLocale) -> ClientLectureNakala | None:
    """Construit le client depuis la config, ou `None` si `nakala:` absent."""
    if config.nakala is None:
        return None
    n = config.nakala
    return ClientLectureNakala(
        n.base_url, n.api_key, timeout=n.timeout, verify_ssl=n.verify_ssl
    )


def _fermer(client: ClientLectureNakala) -> None:
    fermer = getattr(client, "fermer", None)
    if callable(fermer):
        fermer()


def _redirect_erreur(message: str) -> RedirectResponse:
    return RedirectResponse(f"/nakala?erreur={quote(message)}", status_code=303)


def _message_erreur_nakala(exc: Exception, doi: str) -> str:
    if isinstance(exc, NakalaIntrouvable):
        return f"Collection {doi} introuvable sur Nakala."
    if isinstance(exc, (NakalaAuthRefusee, NakalaAccesInterdit)):
        return f"Accès refusé à {doi} — clé API manquante ou invalide."
    if isinstance(exc, NakalaInjoignable):
        return "Nakala est injoignable (réseau / timeout)."
    return f"Erreur Nakala : {exc}"


def _slug_doi(doi: str) -> str:
    return doi.replace("/", "_").replace(".", "_")


# ---------------------------------------------------------------------------
# Page d'accueil
# ---------------------------------------------------------------------------


@router.get("/nakala", response_class=HTMLResponse)
def page_nakala(
    request: Request,
    db: Session = Depends(get_db),
    config: ConfigLocale = Depends(get_config),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse:
    """Page autonome Nakala : formulaires export / rapatrier / rafraîchir."""
    return templates.TemplateResponse(
        request,
        "pages/nakala.html",
        _contexte_base(
            nom_base,
            utilisateur,
            nakala_configure=config.nakala is not None,
            base_url=config.nakala.base_url if config.nakala else None,
        ),
    )


# ---------------------------------------------------------------------------
# Export tableur (téléchargement) — GET, autorisé en lecture seule
# ---------------------------------------------------------------------------


@router.get("/nakala/tableur")
def exporter_tableur(
    doi: str = Query(..., description="DOI ou URL de la collection Nakala."),
    granularite: str = Query("donnee"),
    format_sortie: str = Query("csv", alias="format"),
    sep: str = Query(";"),
    config: ConfigLocale = Depends(get_config),
) -> Response:
    """Construit et renvoie le tableur de la collection en téléchargement."""
    doi = normaliser_identifiant_nakala(doi)
    granularite = granularite if granularite in _GRANULARITES else "donnee"
    format_sortie = format_sortie if format_sortie in _FORMATS else "csv"

    client = _client_ou_none(config)
    if client is None:
        return _redirect_erreur("Section `nakala:` absente de la config locale.")
    try:
        meta = client.lire_collection(doi)
        titre = titre_collection_nakala(meta)
        donnees = list(iterer_donnees_collection(client, doi))
    except ErreurNakala as exc:
        return _redirect_erreur(_message_erreur_nakala(exc, doi))
    finally:
        _fermer(client)

    tableur = (
        lignes_niveau_fichier(donnees)
        if granularite == "fichier"
        else lignes_niveau_donnee(donnees)
    )
    nom = f"{_slug_doi(doi)}_{granularite}.{format_sortie}"
    if format_sortie == "xlsx":
        contenu = vers_xlsx_bytes(tableur, titre_collection=titre)
        media = MIME_XLSX
    else:
        contenu = vers_csv_bytes(tableur, sep=sep)
        media = MIME_CSV
    return Response(
        content=contenu,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{nom}"'},
    )


# ---------------------------------------------------------------------------
# Rapatrier — aperçu (GET, dry-run) + exécution (POST, bloqué lecture seule)
# ---------------------------------------------------------------------------


@router.get("/nakala/rapatrier", response_class=HTMLResponse, response_model=None)
def apercu_rapatrier(
    request: Request,
    doi: str = Query(...),
    fonds: str | None = Query(None),
    db: Session = Depends(get_db),
    config: ConfigLocale = Depends(get_config),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse | RedirectResponse:
    """Aperçu (dry-run) du rapatriement d'une collection."""
    doi = normaliser_identifiant_nakala(doi)
    fonds_cote = (fonds or "").strip() or None
    client = _client_ou_none(config)
    if client is None:
        return _redirect_erreur("Section `nakala:` absente de la config locale.")
    try:
        rapport = rapatrier_collection(
            db, client, doi, fonds_cote=fonds_cote,
            cree_par=utilisateur, dry_run=True,
        )
    except FondsIntrouvable:
        return _redirect_erreur(f"Fonds {fonds_cote!r} introuvable.")
    except ErreurNakala as exc:
        return _redirect_erreur(_message_erreur_nakala(exc, doi))
    finally:
        _fermer(client)

    return templates.TemplateResponse(
        request,
        "pages/nakala_rapatrier_apercu.html",
        _contexte_base(
            nom_base, utilisateur, rapport=rapport, doi=doi, fonds=fonds_cote,
        ),
    )


@router.post("/nakala/rapatrier")
def executer_rapatrier(
    doi: Annotated[str, Form()],
    fonds: Annotated[str, Form()] = "",
    db: Session = Depends(get_db),
    config: ConfigLocale = Depends(get_config),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> RedirectResponse:
    """Exécute réellement le rapatriement (bloqué 423 en lecture seule)."""
    doi = normaliser_identifiant_nakala(doi)
    fonds_cote = (fonds or "").strip() or None
    client = _client_ou_none(config)
    if client is None:
        return _redirect_erreur("Section `nakala:` absente de la config locale.")
    try:
        rapport = rapatrier_collection(
            db, client, doi, fonds_cote=fonds_cote,
            cree_par=utilisateur, dry_run=False,
        )
    except FondsIntrouvable:
        return _redirect_erreur(f"Fonds {fonds_cote!r} introuvable.")
    except ErreurNakala as exc:
        return _redirect_erreur(_message_erreur_nakala(exc, doi))
    finally:
        _fermer(client)

    url = (
        f"/fonds/{rapport.fonds_cote}"
        f"?nakala_crees={len(rapport.crees)}"
        f"&nakala_fichiers={rapport.fichiers_crees}"
        f"&nakala_erreurs={len(rapport.erreurs)}"
    )
    return RedirectResponse(url, status_code=303)


# ---------------------------------------------------------------------------
# Rafraîchir — aperçu (GET, dry-run) + exécution (POST)
# ---------------------------------------------------------------------------


@router.get("/nakala/rafraichir", response_class=HTMLResponse, response_model=None)
def apercu_rafraichir(
    request: Request,
    doi: str = Query(...),
    db: Session = Depends(get_db),
    config: ConfigLocale = Depends(get_config),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse | RedirectResponse:
    """Aperçu (dry-run) du rafraîchissement des items liés."""
    doi = normaliser_identifiant_nakala(doi)
    client = _client_ou_none(config)
    if client is None:
        return _redirect_erreur("Section `nakala:` absente de la config locale.")
    try:
        rapport = rafraichir_collection(
            db, client, doi, modifie_par=utilisateur, dry_run=True
        )
    except ErreurNakala as exc:
        return _redirect_erreur(_message_erreur_nakala(exc, doi))
    finally:
        _fermer(client)

    return templates.TemplateResponse(
        request,
        "pages/nakala_rafraichir_apercu.html",
        _contexte_base(nom_base, utilisateur, rapport=rapport, doi=doi),
    )


@router.post("/nakala/rafraichir")
def executer_rafraichir(
    doi: Annotated[str, Form()],
    db: Session = Depends(get_db),
    config: ConfigLocale = Depends(get_config),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> RedirectResponse:
    """Applique les overwrites (bloqué 423 en lecture seule)."""
    doi = normaliser_identifiant_nakala(doi)
    client = _client_ou_none(config)
    if client is None:
        return _redirect_erreur("Section `nakala:` absente de la config locale.")
    try:
        rapport = rafraichir_collection(
            db, client, doi, modifie_par=utilisateur, dry_run=False
        )
    except ErreurNakala as exc:
        return _redirect_erreur(_message_erreur_nakala(exc, doi))
    finally:
        _fermer(client)

    return RedirectResponse(
        f"/nakala?nakala_modifies={len(rapport.modifies)}", status_code=303
    )
