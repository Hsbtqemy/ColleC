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

import threading
from dataclasses import dataclass
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
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
from archives_tool.api.routes._helpers import contexte_base as _contexte_base
from archives_tool.api.services import sharedocs_jobs, sharedocs_session
from archives_tool.api.services.sharedocs_jobs import (
    JobConcurrent,
    demander_annulation,
    est_job_actif,
    executer_import_sharedocs,
    lire_etat_job,
    reserver_job,
)
from archives_tool.api.services.fonds import (
    FondsIntrouvable,
    FondsInvalide,
    FormulaireFonds,
    creer_fonds,
    lire_fonds_par_cote,
    lister_fonds,
)
from archives_tool.api.services.items import (
    FormulaireItem,
    ItemIntrouvable,
    ItemInvalide,
    OperationItemInterdite,
    creer_item,
    lire_item_par_cote,
    lister_items_fonds,
)
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


def _client_session_ou_none(
    config: ConfigLocale, owner: str
) -> ClientShareDocs | None:
    """Construit le client depuis les identifiants en RAM de l'owner, ou
    None si non connecté (ou base_url devenue hors allowlist — dérive de
    config)."""
    ids = sharedocs_session.identifiants(owner=owner)
    if ids is None:
        return None
    try:
        return ClientShareDocs(ids[0], ids[1], ids[2], hotes_autorises=_hotes(config))
    except ShareDocsHoteInterdit:
        return None


#: Valeur sentinelle des <select> fonds / item signalant « créer une
#: nouvelle entité » (B/C) — au lieu de sélectionner une cote existante.
_SENTINELLE_NOUVEAU = "__nouveau__"


class _CibleErreur(Exception):
    """Message d'erreur de résolution de cible, prêt à rediriger."""


@dataclass
class _Cible:
    """Cible résolue d'un import ShareDocs.

    ``item`` est l'item existant (résolu), ou un item **transitoire**
    non persisté (aperçu d'une création à venir), ou l'item fraîchement
    créé (confirmation). ``fonds_cree`` / ``item_cree`` indiquent ce qui
    a été (ou serait) créé — pour le message et l'aperçu.
    """

    item: Item
    fonds_cote: str
    item_cote: str
    fonds_cree: bool
    item_cree: bool


def _cote_effective(selection: str, nouvelle: str) -> tuple[str, bool]:
    """``(cote, est_nouveau)``. La sentinelle « __nouveau__ » bascule sur la
    cote saisie dans le champ de création ; sinon c'est la cote sélectionnée."""
    if selection == _SENTINELLE_NOUVEAU:
        return (nouvelle or "").strip(), True
    return (selection or "").strip(), False


def _resoudre_cible(
    db: Session,
    *,
    fonds: str,
    nouveau_fonds_cote: str,
    nouveau_fonds_titre: str,
    item: str,
    nouveau_item_cote: str,
    nouveau_item_titre: str,
    creer: bool,
    cree_par: str | None,
) -> _Cible:
    """Résout (ou crée si ``creer``) le fonds + l'item cibles.

    ``creer=False`` (aperçu) ne touche jamais la base : une cible neuve
    donne un item **transitoire** pour piloter le dry-run. ``creer=True``
    (confirmation) crée réellement via les services métier (qui posent
    les invariants : miroir auto, rattachement). Lève ``_CibleErreur``
    avec un message prêt à afficher.
    """
    fonds_cote, fonds_nouveau = _cote_effective(fonds, nouveau_fonds_cote)
    item_cote, item_nouveau = _cote_effective(item, nouveau_item_cote)
    # Un fonds neuf n'a aucun item : l'item est alors forcément neuf aussi.
    if fonds_nouveau:
        item_nouveau = True
    if not fonds_cote:
        raise _CibleErreur("Cote du fonds manquante.")
    if not item_cote:
        raise _CibleErreur("Cote de l'item manquante.")

    # --- Fonds ---
    if fonds_nouveau:
        if creer:
            try:
                fonds_obj = creer_fonds(
                    db,
                    FormulaireFonds(cote=fonds_cote, titre=nouveau_fonds_titre),
                    cree_par=cree_par,
                )
            except FondsInvalide as e:
                raise _CibleErreur(f"Fonds invalide : {e}") from e
        else:
            fonds_obj = None  # aperçu : aucune écriture
    else:
        try:
            fonds_obj = lire_fonds_par_cote(db, fonds_cote)
        except FondsIntrouvable:
            raise _CibleErreur(f"Fonds {fonds_cote!r} introuvable.") from None

    # --- Item ---
    if item_nouveau:
        if creer:
            try:
                item_obj = creer_item(
                    db,
                    FormulaireItem(
                        cote=item_cote,
                        titre=nouveau_item_titre,
                        fonds_id=fonds_obj.id,
                    ),
                    cree_par=cree_par,
                )
            except (ItemInvalide, OperationItemInterdite) as e:
                raise _CibleErreur(f"Item invalide : {e}") from e
        else:
            # Item transitoire (jamais persisté) : .fichiers == [] → le
            # dry-run voit un item vierge, tous les fichiers sont « nouveaux ».
            item_obj = Item(cote=item_cote, fonds_id=fonds_obj.id if fonds_obj else 0)
    else:
        try:
            item_obj = lire_item_par_cote(db, item_cote, fonds_id=fonds_obj.id)
        except ItemIntrouvable:
            raise _CibleErreur(
                f"Item {item_cote!r} introuvable dans le fonds {fonds_cote!r}."
            ) from None

    return _Cible(
        item=item_obj,
        fonds_cote=fonds_cote,
        item_cote=item_cote,
        fonds_cree=fonds_nouveau,
        item_cree=item_nouveau,
    )


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
    db: Session = Depends(get_db),
    config: ConfigLocale = Depends(get_config),
    racines=Depends(get_racines),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
    owner: str = Depends(get_owner_key),
) -> HTMLResponse:
    """Page ShareDocs : formulaire de connexion si déconnecté, sinon le
    contenu du dossier `chemin` (navigation)."""
    etat = sharedocs_session.etat_public(owner=owner)
    # `identifiants()` est l'autorité (lecture atomique) : si une déconnexion
    # concurrente survient, `ids` est None → on retombe gracieusement sur le
    # formulaire (pas d'`assert` qui crasherait en 500, ni ne saute sous -O).
    ids = sharedocs_session.identifiants(owner=owner)
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
            sharedocs_session.deconnecter(owner=owner)
            etat = sharedocs_session.etat_public(owner=owner)
            erreur = erreur or "Identifiants ShareDocs refusés — reconnectez-vous."
        except ShareDocsInjoignable:
            erreur = erreur or "ShareDocs injoignable (réseau / timeout)."
        except (ShareDocsCheminInvalide, ErreurShareDocs) as e:
            erreur = erreur or f"Erreur ShareDocs : {e}"

    # Cibles d'import (B/C) : liste des fonds + items du 1er fonds (celui
    # présélectionné dans le <select>). Inutile si déconnecté (le formulaire
    # d'import n'est pas rendu) → on évite les requêtes.
    fonds_list = lister_fonds(db) if ids is not None else []
    items_initiaux = (
        lister_items_fonds(db, fonds_list[0].id, par_page=0).items if fonds_list else []
    )
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
            fonds_list=fonds_list,
            items_initiaux=items_initiaux,
            erreur=erreur,
            message=message,
        ),
    )


@router.get("/sharedocs/cible-items", response_class=HTMLResponse)
def cible_items(
    request: Request,
    fonds: str = Query(""),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    """Fragment HTMX : ``<select>`` des items du fonds choisi (+ option de
    création). Rechargé au changement de fonds. Un fonds neuf (sentinelle)
    ou introuvable ne propose que la création d'un item."""
    items: list = []
    if fonds and fonds != _SENTINELLE_NOUVEAU:
        try:
            fonds_obj = lire_fonds_par_cote(db, fonds)
            items = lister_items_fonds(db, fonds_obj.id, par_page=0).items
        except FondsIntrouvable:
            items = []
    return templates.TemplateResponse(
        request,
        "partials/_sharedocs_cible_items.html",
        {"items": items},
    )


@router.get("/sharedocs/importer", response_class=HTMLResponse, response_model=None)
def apercu_importer(
    request: Request,
    fonds: str = Query(...),
    item: str = Query(...),
    nouveau_fonds_cote: str = Query(""),
    nouveau_fonds_titre: str = Query(""),
    nouveau_item_cote: str = Query(""),
    nouveau_item_titre: str = Query(""),
    racine: str = Query(...),
    fichiers: list[str] = Query(default=[]),
    chemin: str = Query(""),
    db: Session = Depends(get_db),
    config: ConfigLocale = Depends(get_config),
    racines=Depends(get_racines),
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
    owner: str = Depends(get_owner_key),
) -> HTMLResponse | RedirectResponse:
    """Aperçu (dry-run) de l'import des fichiers cochés vers un item.

    N'écrit jamais : une cible neuve (fonds/item à créer) est résolue en
    item transitoire, et l'aperçu signale ce qui sera créé. La création
    réelle n'a lieu qu'à la confirmation (POST)."""
    if not fichiers:
        return _redirect_erreur("Aucun fichier sélectionné.")
    if racine not in racines:
        return _redirect_erreur(f"Racine {racine!r} inconnue.")
    client = _client_session_ou_none(config, owner)
    if client is None:
        return _redirect_erreur("Non connecté à ShareDocs.")
    try:
        try:
            cible = _resoudre_cible(
                db,
                fonds=fonds,
                nouveau_fonds_cote=nouveau_fonds_cote,
                nouveau_fonds_titre=nouveau_fonds_titre,
                item=item,
                nouveau_item_cote=nouveau_item_cote,
                nouveau_item_titre=nouveau_item_titre,
                creer=False,
                cree_par=None,
            )
        except _CibleErreur as e:
            return _redirect_erreur(str(e))
        try:
            rapport = importer_depuis_sharedocs(
                db,
                client,
                fichiers,
                cible.item,
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
            nouveau_fonds_cote=nouveau_fonds_cote,
            nouveau_fonds_titre=nouveau_fonds_titre,
            nouveau_item_cote=nouveau_item_cote,
            nouveau_item_titre=nouveau_item_titre,
            racine=racine,
            chemin=chemin,
            fonds_cote=cible.fonds_cote,
            item_cote=cible.item_cote,
            fonds_sera_cree=cible.fonds_cree,
            item_sera_cree=cible.item_cree,
        ),
    )


@router.post("/sharedocs/importer")
def executer_importer(
    fonds: str = Form(...),
    item: str = Form(...),
    nouveau_fonds_cote: str = Form(""),
    nouveau_fonds_titre: str = Form(""),
    nouveau_item_cote: str = Form(""),
    nouveau_item_titre: str = Form(""),
    racine: str = Form(...),
    fichiers: list[str] = Form(default=[]),
    chemin: str = Form(""),
    db: Session = Depends(get_db),
    config: ConfigLocale = Depends(get_config),
    racines=Depends(get_racines),
    utilisateur: str = Depends(get_utilisateur_courant),
    owner: str = Depends(get_owner_key),
) -> RedirectResponse:
    """Crée le fonds/item cible si besoin (synchrone, rapide), puis **lance
    le téléchargement en tâche de fond** et redirige vers la page de suivi.

    Le download de gros scans est lent : on ne bloque plus la requête. La
    racine est validée **avant** toute création (pas d'entité orpheline) ;
    le thread reçoit les identifiants ShareDocs explicitement (jamais lus
    d'un global). Bloqué 423 en lecture seule par le middleware."""
    if not fichiers:
        return _redirect_erreur("Aucun fichier sélectionné.")
    if racine not in racines:
        return _redirect_erreur(f"Racine {racine!r} inconnue.")
    ids = sharedocs_session.identifiants(owner=owner)
    if ids is None:
        return _redirect_erreur("Non connecté à ShareDocs.")
    # Garde anti-concurrent AVANT toute création : si un import tourne déjà
    # pour cet owner, on refuse tout de suite (sinon `_resoudre_cible`
    # créerait un fonds/item qui resterait orphelin quand `reserver_job`
    # lèverait `JobConcurrent`). `reserver_job` reste l'autorité atomique
    # ci-dessous (fenêtre TOCTOU négligeable).
    if est_job_actif(owner=owner):
        return _redirect_erreur("Un import ShareDocs est déjà en cours.")
    # Cible créée/résolue dans la requête (rapide) ; le thread ne fait que
    # le download (lent). On capture la cote/id avant de quitter la session.
    try:
        cible = _resoudre_cible(
            db,
            fonds=fonds,
            nouveau_fonds_cote=nouveau_fonds_cote,
            nouveau_fonds_titre=nouveau_fonds_titre,
            item=item,
            nouveau_item_cote=nouveau_item_cote,
            nouveau_item_titre=nouveau_item_titre,
            creer=True,
            cree_par=utilisateur,
        )
    except _CibleErreur as e:
        return _redirect_erreur(str(e))
    item_id = cible.item.id

    try:
        job_id = reserver_job(
            item_cote=cible.item_cote,
            fonds_cote=cible.fonds_cote,
            racine=racine,
            chemin_retour=chemin,
            chemins_distants=fichiers,
            fonds_cree=cible.fonds_cree,
            item_cree=cible.item_cree,
            owner=owner,
        )
    except JobConcurrent as e:
        return _redirect_erreur(str(e))

    thread = threading.Thread(
        target=executer_import_sharedocs,
        args=(job_id,),
        kwargs={
            "chemin_db": chemin_base_courant(),
            "item_id": item_id,
            "chemins_distants": list(fichiers),
            "racine_cible": racine,
            "racines": dict(racines),
            "base_url": ids[0],
            "user": ids[1],
            "password": ids[2],
            "hotes_autorises": _hotes(config),
            "importe_par": utilisateur,
        },
        daemon=True,
        name=f"import-sharedocs-{job_id[:8]}",
    )
    try:
        thread.start()
    except RuntimeError as exc:
        # Défense en profondeur : libérer la garde + marquer le job en échec.
        with sharedocs_jobs._lock:
            etat = sharedocs_jobs._JOBS.get(job_id)
            if etat is not None:
                etat.statut = "echec"
                etat.erreur_globale = f"Démarrage du thread impossible : {exc}"
            sharedocs_jobs._id_actuel.pop(owner, None)
        return _redirect_erreur(f"Démarrage de l'import échoué : {exc}")

    return RedirectResponse(f"/sharedocs/importer/suivi/{job_id}", status_code=303)


@router.get(
    "/sharedocs/importer/suivi/{job_id}",
    response_class=HTMLResponse,
    response_model=None,
)
def page_suivi_import(
    job_id: str,
    request: Request,
    nom_base: str = Depends(get_nom_base),
    utilisateur: str = Depends(get_utilisateur_courant),
    owner: str = Depends(get_owner_key),
) -> HTMLResponse | RedirectResponse:
    """Page de suivi de l'import — barre de progression (HTMX every 2s).

    Si le job est inconnu (serveur redémarré → registre vidé) **ou
    appartient à un autre owner** (IDOR), retour au parcours avec un
    message — un job d'autrui est indiscernable d'un job inexistant."""
    etat = lire_etat_job(job_id, owner=owner)
    if etat is None:
        return _redirect_erreur(
            f"Import {job_id[:8]}… introuvable (serveur redémarré ou job "
            "nettoyé). Relancer l'import depuis le parcours."
        )
    return templates.TemplateResponse(
        request,
        "pages/sharedocs_import_suivi.html",
        _contexte_base(nom_base, utilisateur, etat=etat, job_id=job_id),
    )


@router.get(
    "/sharedocs/importer/statut/{job_id}",
    response_class=HTMLResponse,
    response_model=None,
)
def fragment_statut_import(
    job_id: str,
    request: Request,
    owner: str = Depends(get_owner_key),
) -> HTMLResponse:
    """Fragment HTMX (every 2s) — barre + fichier courant. 404 si inconnu
    ou appartenant à un autre owner (IDOR)."""
    etat = lire_etat_job(job_id, owner=owner)
    if etat is None:
        return HTMLResponse("<p>Import introuvable.</p>", status_code=404)
    return templates.TemplateResponse(
        request,
        "partials/sharedocs_import_statut.html",
        {"etat": etat, "request": request},
    )


@router.post("/sharedocs/importer/annuler/{job_id}")
def annuler_import(
    job_id: str,
    owner: str = Depends(get_owner_key),
) -> RedirectResponse:
    """Demande l'annulation coopérative d'un import en cours, puis revient à
    la page de suivi (le runner s'arrête après le fichier courant ; les
    fichiers déjà importés sont conservés). Bloqué 423 en lecture seule.

    ``owner`` : l'annulation est refusée pour un job d'un autre owner —
    sans ce filtre on pourrait saboter l'import d'autrui via son job_id
    (revue sécurité, IDOR)."""
    demander_annulation(job_id, owner=owner)
    return RedirectResponse(f"/sharedocs/importer/suivi/{job_id}", status_code=303)


@router.post("/sharedocs/connexion")
def connexion(
    base_url: str = Form(...),
    user: str = Form(...),
    password: str = Form(...),
    config: ConfigLocale = Depends(get_config),
    owner: str = Depends(get_owner_key),
) -> RedirectResponse:
    """Valide les identifiants par un PROPFIND racine puis les mémorise en
    RAM (pour cet owner). Bloqué 423 en lecture seule par le middleware."""
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
    sharedocs_session.connecter(base_url, user, password, owner=owner)
    return RedirectResponse("/sharedocs", status_code=303)


@router.post("/sharedocs/deconnexion")
def deconnexion(owner: str = Depends(get_owner_key)) -> RedirectResponse:
    """Oublie les identifiants ShareDocs (RAM) de cet owner. Bloqué 423 en
    lecture seule."""
    sharedocs_session.deconnecter(owner=owner)
    return RedirectResponse("/sharedocs", status_code=303)
