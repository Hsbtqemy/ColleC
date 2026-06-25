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

import threading
from pathlib import Path
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from archives_tool.api.deps import (
    chemin_base_courant,
    get_config,
    get_db,
    get_nom_base,
    get_owner_key,
    get_racines,
    get_utilisateur_courant,
)
from archives_tool.api.routes._helpers import (
    charger_fonds_ou_404 as _charger_fonds_ou_404,
    contexte_base as _contexte_base,
)
from archives_tool.api.services.collections import (
    CollectionIntrouvable,
    lire_collection_par_cote,
)
from archives_tool.api.services.fonds import FondsIntrouvable
from archives_tool.api.services.items import ItemIntrouvable, lire_item_par_cote
from archives_tool.api.services.nakala import (
    rafraichir_collection,
    rapatrier_collection,
    titre_collection_nakala,
)
from archives_tool.api.services.nakala_depot import (
    DepotImpossible,
    deposer_collection,
    pousser_collection,
    pousser_item,
    publier_collection,
    publier_item,
)
from archives_tool.api.services.nakala_depot_jobs import (
    JobConcurrent,
    executer_depot_collection,
    lire_etat_job,
    reserver_job,
)
from archives_tool.api.services.nakala_fichiers import (
    ComparaisonImpossible,
    ReponseLectureInvalide,
    comparer_fichiers_item,
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
from archives_tool.external.nakala.depot_mapper import MetaInvalide
from archives_tool.external.nakala.write_client import NakalaEcritureClient
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


def _client_ecriture_ou_none(config: ConfigLocale) -> NakalaEcritureClient | None:
    """Client d'écriture, ou `None` si `nakala:` / `api_key` absent."""
    if config.nakala is None or not config.nakala.api_key:
        return None
    n = config.nakala
    return NakalaEcritureClient(
        n.base_url, n.api_key, timeout=n.timeout, verify_ssl=n.verify_ssl
    )


def _fermer(client) -> None:
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
            db,
            client,
            doi,
            fonds_cote=fonds_cote,
            cree_par=utilisateur,
            dry_run=True,
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
            nom_base,
            utilisateur,
            rapport=rapport,
            doi=doi,
            fonds=fonds_cote,
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
            db,
            client,
            doi,
            fonds_cote=fonds_cote,
            cree_par=utilisateur,
            dry_run=False,
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


# ---------------------------------------------------------------------------
# Push (écriture) — item & collection. Aperçu GET (dry-run, lecture seule OK)
# → confirmation POST (bloquée 423 en lecture seule par le middleware).
# ---------------------------------------------------------------------------


def _redirect_item_erreur(cote: str, fonds: str, message: str) -> RedirectResponse:
    return RedirectResponse(
        f"/item/{cote}?fonds={fonds}&nakala_erreur={quote(message)}", status_code=303
    )


def _redirect_fonds_erreur(cote: str, message: str) -> RedirectResponse:
    return RedirectResponse(
        f"/fonds/{cote}?nakala_erreur={quote(message)}", status_code=303
    )


def _config_ecriture_absente() -> str:
    return "Section `nakala:` avec `api_key` requise pour écrire vers Nakala."


def _ecriture_configuree(config: ConfigLocale) -> bool:
    """Vrai si la config permet d'écrire (section `nakala:` + `api_key`).

    Vérifie la config **sans instancier** de client : construire un client
    httpx puis l'abandonner sur un early-return fuirait la connexion (les
    `__init__` des clients ouvrent un `httpx.Client` eagerly)."""
    return config.nakala is not None and bool(config.nakala.api_key)


def _resoudre_item_ou_404(db: Session, cote: str, fonds: str):
    fonds_obj = _charger_fonds_ou_404(db, fonds)
    try:
        return lire_item_par_cote(db, cote, fonds_id=fonds_obj.id)
    except ItemIntrouvable as e:
        from fastapi import HTTPException

        raise HTTPException(404, detail=f"Item {cote!r} introuvable.") from e


def _resoudre_collection_ou_404(db: Session, cote: str, fonds: str | None):
    fonds_id = _charger_fonds_ou_404(db, fonds).id if fonds else None
    try:
        return lire_collection_par_cote(db, cote, fonds_id=fonds_id)
    except CollectionIntrouvable as e:
        from fastapi import HTTPException

        raise HTTPException(404, detail=f"Collection {cote!r} introuvable.") from e


# ---- Item : citation (S4) ----------------------------------------------


@router.get("/nakala/item/{cote}/citation", response_class=HTMLResponse)
def citation_item(
    cote: str,
    request: Request,
    fonds: str = Query(...),
    db: Session = Depends(get_db),
    config: ConfigLocale = Depends(get_config),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse:
    """Partial HTMX : citation Nakala d'un item (S4, lecture seule, lazy).

    Chargé à la demande car Nakala est lent (~3-5 s) — pas à chaque rendu de
    fiche. Best-effort : toute erreur Nakala devient un message dans le
    partial, jamais une 500 (sauf item local inconnu → 404)."""
    item = _resoudre_item_ou_404(db, cote, fonds)  # 404 si item inconnu
    citation: str | None = None
    erreur: str | None = None
    if not item.doi_nakala:
        erreur = "Cet item n'a pas de DOI Nakala."
    else:
        lecture = _client_ou_none(config)
        if lecture is None:
            erreur = "Nakala n'est pas configuré (section `nakala:`)."
        else:
            try:
                citation = lecture.citation(item.doi_nakala)
            except ErreurNakala as exc:
                erreur = _message_erreur_nakala(exc, cote)
            finally:
                _fermer(lecture)
    return templates.TemplateResponse(
        request,
        "partials/nakala_citation.html",
        _contexte_base(nom_base, utilisateur, citation=citation, erreur=erreur),
    )


# ---- Item : diagnostic synchronisation fichiers (P3+b, lecture seule) ---


@router.get("/nakala/item/{cote}/comparer-fichiers", response_class=HTMLResponse)
def comparer_fichiers_web(
    cote: str,
    request: Request,
    fonds: str = Query(...),
    db: Session = Depends(get_db),
    config: ConfigLocale = Depends(get_config),
    racines: dict = Depends(get_racines),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse:
    """Partial HTMX : diagnostic de synchronisation des fichiers d'un item
    avec son dépôt Nakala (lecture seule, lazy — fait un appel réseau).

    Pré-visualise ce qu'un push de fichiers ferait (nouveaux / modifiés /
    orphelins / fantômes…), sans rien modifier. Chargé à la demande car
    le pull Nakala + le recalcul des SHA-1 locaux prennent du temps — pas
    à chaque rendu de fiche. Best-effort : toute erreur Nakala devient un
    message dans le partial, jamais une 500 (sauf item local inconnu → 404).
    """
    item = _resoudre_item_ou_404(db, cote, fonds)  # 404 si item inconnu
    rapport = None
    erreur: str | None = None
    if not item.doi_nakala:
        erreur = "Cet item n'a pas de DOI Nakala."
    else:
        lecture = _client_ou_none(config)
        if lecture is None:
            erreur = "Nakala n'est pas configuré (section `nakala:`)."
        else:
            try:
                rapport = comparer_fichiers_item(db, lecture, item, racines=racines)
            except ErreurNakala as exc:
                erreur = _message_erreur_nakala(exc, cote)
            except (ReponseLectureInvalide, ComparaisonImpossible) as exc:
                erreur = str(exc)
            except ValueError:
                # `lire_depot` ne garde pas `.json()` (≠ `citation()`) : un
                # corps 200 non-JSON lève `json.JSONDecodeError` (⊂ ValueError).
                # Best-effort : message, jamais 500. Les ValueError internes
                # à la comparaison (résolution chemin / sha1) sont déjà avalées
                # dans le service — celle-ci ne peut venir que de `lire_depot`.
                erreur = "Réponse Nakala illisible (corps non-JSON)."
            finally:
                _fermer(lecture)
    return templates.TemplateResponse(
        request,
        "partials/nakala_comparaison.html",
        _contexte_base(
            nom_base,
            utilisateur,
            rapport=rapport,
            erreur=erreur,
            cote=cote,
            fonds=fonds,
        ),
    )


# ---- Item : pousser ----------------------------------------------------


@router.get("/nakala/pousser", response_class=HTMLResponse, response_model=None)
def apercu_pousser_item(
    request: Request,
    cote: str = Query(...),
    fonds: str = Query(...),
    db: Session = Depends(get_db),
    config: ConfigLocale = Depends(get_config),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse | RedirectResponse:
    """Aperçu (dry-run) du push des métadonnées d'un item."""
    if not _ecriture_configuree(config):
        return _redirect_item_erreur(cote, fonds, _config_ecriture_absente())
    item = _resoudre_item_ou_404(db, cote, fonds)  # peut lever 404 — avant tout client
    lecture = _client_ou_none(config)
    ecriture = _client_ecriture_ou_none(config)
    try:
        rapport = pousser_item(
            db, lecture, ecriture, item, dry_run=True, modifie_par=utilisateur
        )
    except DepotImpossible as exc:
        return _redirect_item_erreur(cote, fonds, str(exc))
    except MetaInvalide as exc:
        return _redirect_item_erreur(cote, fonds, f"Métadonnées insuffisantes — {exc}")
    except ErreurNakala as exc:
        return _redirect_item_erreur(cote, fonds, _message_erreur_nakala(exc, cote))
    finally:
        _fermer(lecture)
        _fermer(ecriture)
    return templates.TemplateResponse(
        request,
        "pages/nakala_pousser_apercu.html",
        _contexte_base(nom_base, utilisateur, rapport=rapport, cote=cote, fonds=fonds),
    )


@router.post("/nakala/pousser")
def executer_pousser_item(
    cote: Annotated[str, Form()],
    fonds: Annotated[str, Form()],
    db: Session = Depends(get_db),
    config: ConfigLocale = Depends(get_config),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> RedirectResponse:
    """Pousse réellement (bloqué 423 en lecture seule)."""
    if not _ecriture_configuree(config):
        return _redirect_item_erreur(cote, fonds, _config_ecriture_absente())
    item = _resoudre_item_ou_404(db, cote, fonds)
    lecture = _client_ou_none(config)
    ecriture = _client_ecriture_ou_none(config)
    try:
        rapport = pousser_item(
            db, lecture, ecriture, item, dry_run=False, modifie_par=utilisateur
        )
    except (DepotImpossible, MetaInvalide) as exc:
        return _redirect_item_erreur(cote, fonds, str(exc))
    except ErreurNakala as exc:
        return _redirect_item_erreur(cote, fonds, _message_erreur_nakala(exc, cote))
    finally:
        _fermer(lecture)
        _fermer(ecriture)
    return RedirectResponse(
        f"/item/{cote}?fonds={fonds}&nakala_pousse={len(rapport.diffs)}",
        status_code=303,
    )


# ---- Item : publier (irréversible) -------------------------------------


@router.get("/nakala/publier", response_class=HTMLResponse, response_model=None)
def apercu_publier_item(
    request: Request,
    cote: str = Query(...),
    fonds: str = Query(...),
    db: Session = Depends(get_db),
    config: ConfigLocale = Depends(get_config),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse | RedirectResponse:
    """Aperçu (rouge, irréversible) de la publication d'un item."""
    # Aperçu statique : aucun client réseau nécessaire (juste l'avertissement).
    if not _ecriture_configuree(config):
        return _redirect_item_erreur(cote, fonds, _config_ecriture_absente())
    item = _resoudre_item_ou_404(db, cote, fonds)
    if not item.doi_nakala:
        return _redirect_item_erreur(cote, fonds, "Item non déposé sur Nakala.")
    return templates.TemplateResponse(
        request,
        "pages/nakala_publier_apercu.html",
        _contexte_base(
            nom_base, utilisateur, cote=cote, fonds=fonds, doi=item.doi_nakala
        ),
    )


@router.post("/nakala/publier")
def executer_publier_item(
    cote: Annotated[str, Form()],
    fonds: Annotated[str, Form()],
    db: Session = Depends(get_db),
    config: ConfigLocale = Depends(get_config),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> RedirectResponse:
    """Publie réellement (irréversible ; bloqué 423 en lecture seule)."""
    if not _ecriture_configuree(config):
        return _redirect_item_erreur(cote, fonds, _config_ecriture_absente())
    item = _resoudre_item_ou_404(db, cote, fonds)
    lecture = _client_ou_none(config)
    ecriture = _client_ecriture_ou_none(config)
    try:
        publier_item(
            db, lecture, ecriture, item, dry_run=False, modifie_par=utilisateur
        )
    except (DepotImpossible, MetaInvalide) as exc:
        return _redirect_item_erreur(cote, fonds, str(exc))
    except ErreurNakala as exc:
        return _redirect_item_erreur(cote, fonds, _message_erreur_nakala(exc, cote))
    finally:
        _fermer(lecture)
        _fermer(ecriture)
    return RedirectResponse(
        f"/item/{cote}?fonds={fonds}&nakala_publie=1", status_code=303
    )


# ---- Collection : pousser & publier ------------------------------------


@router.get(
    "/nakala/pousser-collection", response_class=HTMLResponse, response_model=None
)
def apercu_pousser_collection(
    request: Request,
    cote: str = Query(...),
    fonds: str | None = Query(None),
    db: Session = Depends(get_db),
    config: ConfigLocale = Depends(get_config),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse | RedirectResponse:
    """Aperçu (dry-run) du push d'une collection (entité + items)."""
    if not _ecriture_configuree(config):
        return _redirect_fonds_erreur(fonds or cote, _config_ecriture_absente())
    collection = _resoudre_collection_ou_404(db, cote, fonds)
    lecture = _client_ou_none(config)
    ecriture = _client_ecriture_ou_none(config)
    try:
        rapport = pousser_collection(
            db, lecture, ecriture, collection, dry_run=True, modifie_par=utilisateur
        )
    except ErreurNakala as exc:
        return _redirect_fonds_erreur(fonds or cote, _message_erreur_nakala(exc, cote))
    finally:
        _fermer(lecture)
        _fermer(ecriture)
    return templates.TemplateResponse(
        request,
        "pages/nakala_pousser_collection_apercu.html",
        _contexte_base(
            nom_base,
            utilisateur,
            rapport=rapport,
            cote=collection.cote,
            fonds=fonds or "",
        ),
    )


@router.post("/nakala/pousser-collection")
def executer_pousser_collection(
    cote: Annotated[str, Form()],
    fonds: Annotated[str, Form()] = "",
    db: Session = Depends(get_db),
    config: ConfigLocale = Depends(get_config),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> RedirectResponse:
    if not _ecriture_configuree(config):
        return _redirect_fonds_erreur(fonds or cote, _config_ecriture_absente())
    collection = _resoudre_collection_ou_404(db, cote, fonds or None)
    lecture = _client_ou_none(config)
    ecriture = _client_ecriture_ou_none(config)
    try:
        rapport = pousser_collection(
            db, lecture, ecriture, collection, dry_run=False, modifie_par=utilisateur
        )
    except ErreurNakala as exc:
        return _redirect_fonds_erreur(fonds or cote, _message_erreur_nakala(exc, cote))
    finally:
        _fermer(lecture)
        _fermer(ecriture)
    return RedirectResponse(
        f"/fonds/{fonds or cote}?nakala_pousse_items={len(rapport.pousses)}",
        status_code=303,
    )


@router.get(
    "/nakala/publier-collection", response_class=HTMLResponse, response_model=None
)
def apercu_publier_collection(
    request: Request,
    cote: str = Query(...),
    fonds: str | None = Query(None),
    db: Session = Depends(get_db),
    config: ConfigLocale = Depends(get_config),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse | RedirectResponse:
    """Aperçu (rouge, irréversible) de la publication d'une collection."""
    if not _ecriture_configuree(config):
        return _redirect_fonds_erreur(fonds or cote, _config_ecriture_absente())
    collection = _resoudre_collection_ou_404(db, cote, fonds)
    lecture = _client_ou_none(config)
    ecriture = _client_ecriture_ou_none(config)
    try:
        rapport = publier_collection(
            db, lecture, ecriture, collection, dry_run=True, modifie_par=utilisateur
        )
    except ErreurNakala as exc:
        return _redirect_fonds_erreur(fonds or cote, _message_erreur_nakala(exc, cote))
    finally:
        _fermer(lecture)
        _fermer(ecriture)
    return templates.TemplateResponse(
        request,
        "pages/nakala_publier_collection_apercu.html",
        _contexte_base(
            nom_base,
            utilisateur,
            rapport=rapport,
            cote=collection.cote,
            fonds=fonds or "",
        ),
    )


@router.post("/nakala/publier-collection")
def executer_publier_collection(
    cote: Annotated[str, Form()],
    fonds: Annotated[str, Form()] = "",
    db: Session = Depends(get_db),
    config: ConfigLocale = Depends(get_config),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> RedirectResponse:
    if not _ecriture_configuree(config):
        return _redirect_fonds_erreur(fonds or cote, _config_ecriture_absente())
    collection = _resoudre_collection_ou_404(db, cote, fonds or None)
    lecture = _client_ou_none(config)
    ecriture = _client_ecriture_ou_none(config)
    try:
        rapport = publier_collection(
            db, lecture, ecriture, collection, dry_run=False, modifie_par=utilisateur
        )
    except ErreurNakala as exc:
        return _redirect_fonds_erreur(fonds or cote, _message_erreur_nakala(exc, cote))
    finally:
        _fermer(lecture)
        _fermer(ecriture)
    return RedirectResponse(
        f"/fonds/{fonds or cote}?nakala_publie_items={len(rapport.publies)}",
        status_code=303,
    )


# ---------------------------------------------------------------------------
# D3 (backlog dépôt UI) — dépôt collection en tâche de fond
# ---------------------------------------------------------------------------


@router.get(
    "/nakala/deposer-collection",
    response_class=HTMLResponse,
    response_model=None,
)
def apercu_deposer_collection(
    request: Request,
    cote: str = Query(...),
    fonds: str | None = Query(None),
    db: Session = Depends(get_db),
    config: ConfigLocale = Depends(get_config),
    racines: dict[str, Path] = Depends(get_racines),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse | RedirectResponse:
    """Aperçu (dry-run) du dépôt d'une collection.

    Liste : items déposables (avec fichiers), items non-déposables
    (Nakala-only), erreurs préflight. Permet à l'utilisateur de relire
    avant de confirmer.
    """
    if not _ecriture_configuree(config):
        return _redirect_fonds_erreur(fonds or cote, _config_ecriture_absente())
    collection = _resoudre_collection_ou_404(db, cote, fonds or None)
    # Garde défensive : si la miroir a déjà un DOI, le bouton « Déposer »
    # n'aurait pas dû être affiché (cf. fonds_lecture.html), mais on
    # protège contre l'accès direct par URL.
    if collection.doi_nakala:
        return _redirect_fonds_erreur(
            fonds or cote,
            f"Collection {collection.cote} déjà déposée "
            f"(DOI {collection.doi_nakala}). Utiliser « Pousser vers Nakala » "
            "pour les modifications.",
        )
    ecriture = _client_ecriture_ou_none(config)
    try:
        rapport = deposer_collection(
            db,
            ecriture,
            collection,
            racines=racines,
            dry_run=True,
            cree_par=utilisateur,
        )
    except ErreurNakala as exc:
        return _redirect_fonds_erreur(fonds or cote, _message_erreur_nakala(exc, cote))
    finally:
        _fermer(ecriture)
    return templates.TemplateResponse(
        request,
        "pages/nakala_deposer_collection_apercu.html",
        _contexte_base(
            nom_base,
            utilisateur,
            rapport=rapport,
            cote=cote,
            fonds=fonds or "",
            collection_titre=collection.titre,
        ),
    )


@router.post("/nakala/deposer-collection")
def lancer_depot_collection(
    cote: Annotated[str, Form()],
    fonds: Annotated[str, Form()] = "",
    db: Session = Depends(get_db),
    config: ConfigLocale = Depends(get_config),
    racines: dict[str, Path] = Depends(get_racines),
    utilisateur: str = Depends(get_utilisateur_courant),
    owner: str = Depends(get_owner_key),
) -> RedirectResponse:
    """Lance le dépôt en tâche de fond.

    Réserve un job_id (lève `JobConcurrent` si un autre dépôt tourne),
    démarre un `threading.Thread` daemon qui appelle
    `executer_depot_collection(...)`, puis redirige immédiatement vers
    la page de suivi. **Bloqué 423** par le middleware en lecture seule
    (la route est invoquée par le middleware avant ce handler).
    """
    if not _ecriture_configuree(config):
        return _redirect_fonds_erreur(fonds or cote, _config_ecriture_absente())
    collection = _resoudre_collection_ou_404(db, cote, fonds or None)
    if collection.doi_nakala:
        return _redirect_fonds_erreur(
            fonds or cote,
            f"Collection {collection.cote} déjà déposée.",
        )
    total = len(collection.items)
    try:
        job_id = reserver_job(
            fonds_cote=collection.fonds.cote if collection.fonds else "",
            collection_cote=collection.cote,
            total=total,
            owner=owner,
        )
    except JobConcurrent as exc:
        return _redirect_fonds_erreur(fonds or cote, str(exc))

    # Thread daemon : meurt avec le serveur uvicorn. La reprise après
    # restart est gérée côté donnée (DOI commités par item).
    # `racines` et `config.nakala` sont passés par référence — partage
    # mémoire OK puisque le runner ne les mute pas.
    thread = threading.Thread(
        target=executer_depot_collection,
        args=(job_id,),
        kwargs={
            "chemin_db": chemin_base_courant(),
            "collection_id": collection.id,
            "config_nakala": config.nakala,
            "racines": dict(racines),
            "cree_par": utilisateur,
        },
        daemon=True,
        name=f"depot-collection-{job_id[:8]}",
    )
    try:
        thread.start()
    except RuntimeError as exc:
        # `Thread.start()` ne lève quasi-jamais en pratique (RuntimeError
        # uniquement sur thread déjà démarré, ce qui ne peut pas arriver
        # car on instancie un nouveau Thread). Defense en profondeur :
        # relâcher `_id_actuel` pour ne pas bloquer indéfiniment, marquer
        # le job en echec pour qu'il apparaisse dans le suivi avec le
        # bon statut.
        from archives_tool.api.services import nakala_depot_jobs

        with nakala_depot_jobs._lock:
            etat = nakala_depot_jobs._JOBS.get(job_id)
            if etat is not None:
                etat.statut = "echec"
                etat.erreur_globale = (
                    f"Impossible de démarrer le thread de dépôt : {exc}"
                )
            nakala_depot_jobs._id_actuel.pop(owner, None)
        return _redirect_fonds_erreur(
            fonds or cote,
            f"Démarrage du dépôt échoué : {exc}",
        )

    return RedirectResponse(
        f"/nakala/deposer-collection/suivi/{job_id}",
        status_code=303,
    )


@router.get(
    "/nakala/deposer-collection/suivi/{job_id}",
    response_class=HTMLResponse,
    response_model=None,
)
def page_suivi_depot(
    job_id: str,
    request: Request,
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse | RedirectResponse:
    """Page de suivi du dépôt — affiche barre de progression + journal.

    Le fragment HTMX `every 2s` (statut) met à jour la barre. Si le job
    n'existe pas (uvicorn redémarré → registre vidé), retour à `/nakala`
    avec un message d'erreur.
    """
    etat = lire_etat_job(job_id)
    if etat is None:
        return _redirect_erreur(
            f"Job {job_id[:8]}… introuvable "
            "(serveur redémarré ou job nettoyé). "
            "Relancer le dépôt depuis la page du fonds."
        )
    return templates.TemplateResponse(
        request,
        "pages/nakala_deposer_suivi.html",
        _contexte_base(
            nom_base,
            utilisateur,
            etat=etat,
            job_id=job_id,
        ),
    )


@router.get(
    "/nakala/deposer-collection/statut/{job_id}",
    response_class=HTMLResponse,
    response_model=None,
)
def fragment_statut_depot(
    job_id: str,
    request: Request,
) -> HTMLResponse:
    """Fragment HTMX (every 2s) — barre + dernière cote traitée.

    Retourne le markup partiel à injecter dans la page suivi. 404 si
    le job est inconnu — HTMX peut afficher un message côté client.
    """
    etat = lire_etat_job(job_id)
    if etat is None:
        return HTMLResponse(
            "<p>Job introuvable.</p>",
            status_code=404,
        )
    return templates.TemplateResponse(
        request,
        "partials/nakala_deposer_statut.html",
        {"etat": etat, "request": request},
    )
