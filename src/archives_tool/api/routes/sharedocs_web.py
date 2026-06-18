"""Routes web ShareDocs (Chantier 1, tranches 3a + 3b) — page `/sharedocs`.

Connexion (identifiants en RAM, **validés par un PROPFIND racine**) →
parcourir un partage WebDAV (navigation + fil d'Ariane) → **sélectionner des
fichiers et les importer** vers un item (aperçu dry-run GET → confirmation
POST, comme `/nakala`). Identifiants jamais sur disque ni ré-affichés (cf.
`deploiement-future.md`). `ClientShareDocs` est importé au niveau module pour
être monkeypatchable en test. Les POST (connexion / déconnexion / import)
sont bloqués en lecture seule par le middleware (423).
"""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from archives_tool.api.deps import (
    get_config,
    get_db,
    get_nom_base,
    get_racines,
    get_utilisateur_courant,
)
from archives_tool.api.routes._helpers import contexte_base as _contexte_base
from archives_tool.api.services import sharedocs_session
from archives_tool.api.services.fonds import FondsIntrouvable, lire_fonds_par_cote
from archives_tool.api.services.items import ItemIntrouvable, lire_item_par_cote
from archives_tool.api.services.sharedocs import (
    RacineCibleInconnue,
    importer_depuis_sharedocs,
)
from archives_tool.api.templating import templates
from archives_tool.config import ConfigLocale
from archives_tool.external.sharedocs import (
    ClientShareDocs,
    ErreurShareDocs,
    ShareDocsAuthRefusee,
    ShareDocsCheminInvalide,
    ShareDocsHoteInterdit,
    ShareDocsInjoignable,
)
from archives_tool.models import Item

router = APIRouter()


def _hotes(config: ConfigLocale) -> frozenset[str] | None:
    if config.sharedocs and config.sharedocs.hotes_autorises:
        return frozenset(config.sharedocs.hotes_autorises)
    return None


def _redirect_erreur(message: str) -> RedirectResponse:
    return RedirectResponse(f"/sharedocs?erreur={quote(message)}", status_code=303)


def _client_session_ou_none(config: ConfigLocale) -> ClientShareDocs | None:
    """Construit le client depuis les identifiants en RAM, ou None si non
    connecté (ou base_url devenue hors allowlist — dérive de config)."""
    ids = sharedocs_session.identifiants()
    if ids is None:
        return None
    try:
        return ClientShareDocs(ids[0], ids[1], ids[2], hotes_autorises=_hotes(config))
    except ShareDocsHoteInterdit:
        return None


def _resoudre_item(db: Session, fonds: str, item: str) -> Item:
    """Item par cote dans son fonds. Lève FondsIntrouvable / ItemIntrouvable."""
    fonds_obj = lire_fonds_par_cote(db, fonds)
    return lire_item_par_cote(db, item, fonds_id=fonds_obj.id)


def _fil_ariane(chemin: str) -> list[tuple[str, str]]:
    """Fil d'Ariane ``[(label, chemin)]`` : Racine + chaque segment cumulé."""
    crumbs: list[tuple[str, str]] = [("Racine", "")]
    acc = ""
    for seg in (p for p in chemin.split("/") if p):
        acc = f"{acc}/{seg}" if acc else seg
        crumbs.append((seg, acc))
    return crumbs


@router.get("/sharedocs", response_class=HTMLResponse)
def page_sharedocs(
    request: Request,
    chemin: str = Query(""),
    erreur: str | None = Query(None),
    message: str | None = Query(None),
    config: ConfigLocale = Depends(get_config),
    racines=Depends(get_racines),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse:
    """Page ShareDocs : formulaire de connexion si déconnecté, sinon le
    contenu du dossier `chemin` (navigation)."""
    etat = sharedocs_session.etat_public()
    # `identifiants()` est l'autorité (lecture atomique) : si une déconnexion
    # concurrente survient, `ids` est None → on retombe gracieusement sur le
    # formulaire (pas d'`assert` qui crasherait en 500, ni ne saute sous -O).
    ids = sharedocs_session.identifiants()
    entrees = None
    fil = None
    if ids is not None:
        try:
            client = ClientShareDocs(
                ids[0], ids[1], ids[2], hotes_autorises=_hotes(config)
            )
            try:
                entrees = client.lister(chemin)
            finally:
                client.fermer()
            fil = _fil_ariane(chemin)
        except ShareDocsAuthRefusee:
            # Identifiants devenus invalides → on déconnecte et on repropose
            # le formulaire (sinon la page resterait coincée en erreur).
            sharedocs_session.deconnecter()
            etat = sharedocs_session.etat_public()
            erreur = erreur or "Identifiants ShareDocs refusés — reconnectez-vous."
        except ShareDocsInjoignable:
            erreur = erreur or "ShareDocs injoignable (réseau / timeout)."
        except (ShareDocsCheminInvalide, ErreurShareDocs) as e:
            erreur = erreur or f"Erreur ShareDocs : {e}"
    return templates.TemplateResponse(
        request,
        "pages/sharedocs.html",
        _contexte_base(
            nom_base,
            utilisateur,
            etat=etat,
            entrees=entrees,
            chemin=chemin,
            fil=fil,
            base_url_defaut=(config.sharedocs.base_url if config.sharedocs else ""),
            racines=sorted(racines),
            erreur=erreur,
            message=message,
        ),
    )


@router.get("/sharedocs/importer", response_class=HTMLResponse, response_model=None)
def apercu_importer(
    request: Request,
    fonds: str = Query(...),
    item: str = Query(...),
    racine: str = Query(...),
    fichiers: list[str] = Query(default=[]),
    chemin: str = Query(""),
    db: Session = Depends(get_db),
    config: ConfigLocale = Depends(get_config),
    racines=Depends(get_racines),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> HTMLResponse | RedirectResponse:
    """Aperçu (dry-run) de l'import des fichiers cochés vers un item."""
    if not fichiers:
        return _redirect_erreur("Aucun fichier sélectionné.")
    client = _client_session_ou_none(config)
    if client is None:
        return _redirect_erreur("Non connecté à ShareDocs.")
    try:
        item_obj = _resoudre_item(db, fonds, item)
    except (FondsIntrouvable, ItemIntrouvable):
        client.fermer()
        return _redirect_erreur(f"Item {item!r} introuvable dans le fonds {fonds!r}.")
    try:
        rapport = importer_depuis_sharedocs(
            db,
            client,
            fichiers,
            item_obj,
            racine_cible=racine,
            racines=dict(racines),
            dry_run=True,
        )
    except RacineCibleInconnue as e:
        return _redirect_erreur(str(e))
    finally:
        client.fermer()
    return templates.TemplateResponse(
        request,
        "pages/sharedocs_import_apercu.html",
        _contexte_base(
            nom_base,
            utilisateur,
            rapport=rapport,
            fonds=fonds,
            item=item,
            racine=racine,
            chemin=chemin,
        ),
    )


@router.post("/sharedocs/importer")
def executer_importer(
    fonds: str = Form(...),
    item: str = Form(...),
    racine: str = Form(...),
    fichiers: list[str] = Form(default=[]),
    chemin: str = Form(""),
    db: Session = Depends(get_db),
    config: ConfigLocale = Depends(get_config),
    racines=Depends(get_racines),
    utilisateur: str = Depends(get_utilisateur_courant),
) -> RedirectResponse:
    """Importe réellement les fichiers cochés (bloqué 423 en lecture seule)."""
    if not fichiers:
        return _redirect_erreur("Aucun fichier sélectionné.")
    client = _client_session_ou_none(config)
    if client is None:
        return _redirect_erreur("Non connecté à ShareDocs.")
    try:
        item_obj = _resoudre_item(db, fonds, item)
    except (FondsIntrouvable, ItemIntrouvable):
        client.fermer()
        return _redirect_erreur(f"Item {item!r} introuvable dans le fonds {fonds!r}.")
    try:
        rapport = importer_depuis_sharedocs(
            db,
            client,
            fichiers,
            item_obj,
            racine_cible=racine,
            racines=dict(racines),
            dry_run=False,
            importe_par=utilisateur,
        )
    except RacineCibleInconnue as e:
        return _redirect_erreur(str(e))
    finally:
        client.fermer()
    msg = f"{rapport.nb_retenus} fichier(s) importé(s) vers {item}" + (
        f", {rapport.nb_sautes} sauté(s)" if rapport.nb_sautes else ""
    )
    retour = quote(chemin)
    return RedirectResponse(
        f"/sharedocs?chemin={retour}&message={quote(msg)}", status_code=303
    )


@router.post("/sharedocs/connexion")
def connexion(
    base_url: str = Form(...),
    user: str = Form(...),
    password: str = Form(...),
    config: ConfigLocale = Depends(get_config),
) -> RedirectResponse:
    """Valide les identifiants par un PROPFIND racine puis les mémorise en
    RAM. Bloqué 423 en lecture seule par le middleware."""
    base_url = (base_url or "").strip()
    try:
        client = ClientShareDocs(
            base_url, user, password, hotes_autorises=_hotes(config)
        )
    except ShareDocsHoteInterdit as e:
        return _redirect_erreur(str(e))
    try:
        client.lister("")  # validation : PROPFIND racine
    except ShareDocsAuthRefusee:
        return _redirect_erreur("Identifiants refusés par ShareDocs (401/403).")
    except ShareDocsInjoignable as e:
        return _redirect_erreur(f"ShareDocs injoignable ({e}).")
    except ErreurShareDocs as e:
        return _redirect_erreur(f"Erreur ShareDocs : {e}")
    finally:
        client.fermer()
    sharedocs_session.connecter(base_url, user, password)
    return RedirectResponse("/sharedocs", status_code=303)


@router.post("/sharedocs/deconnexion")
def deconnexion() -> RedirectResponse:
    """Oublie les identifiants ShareDocs (RAM). Bloqué 423 en lecture seule."""
    sharedocs_session.deconnecter()
    return RedirectResponse("/sharedocs", status_code=303)
