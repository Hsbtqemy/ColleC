"""Routes web ShareDocs (Chantier 1, tranche 3a) — page autonome `/sharedocs`.

Connexion (identifiants en RAM, **validés par un PROPFIND racine**) →
parcourir un partage WebDAV (navigation dossiers + fil d'Ariane). La
sélection + l'import (tranche 3b) viendront ensuite. Identifiants jamais sur
disque ni ré-affichés (cf. `deploiement-future.md`). `ClientShareDocs` est
importé au niveau module pour être monkeypatchable en test (comme la CLI /
`nakala_web`). Les POST (connexion / déconnexion) sont bloqués en lecture
seule par le middleware (423).
"""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from archives_tool.api.deps import (
    get_config,
    get_nom_base,
    get_utilisateur_courant,
)
from archives_tool.api.routes._helpers import contexte_base as _contexte_base
from archives_tool.api.services import sharedocs_session
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

router = APIRouter()


def _hotes(config: ConfigLocale) -> frozenset[str] | None:
    if config.sharedocs and config.sharedocs.hotes_autorises:
        return frozenset(config.sharedocs.hotes_autorises)
    return None


def _redirect_erreur(message: str) -> RedirectResponse:
    return RedirectResponse(f"/sharedocs?erreur={quote(message)}", status_code=303)


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
    config: ConfigLocale = Depends(get_config),
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
            erreur=erreur,
        ),
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
