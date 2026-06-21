"""Runner et registre mémoire pour l'import ShareDocs en tâche de fond.

2ᵉ type de tâche de fond du projet (après le dépôt collection Nakala). Le
téléchargement de fichiers ShareDocs (gros TIFF de scans) est synchrone et
lent : sans tâche de fond, la requête HTTP reste bloquée plusieurs minutes
et la page paraît figée. Ici on **réserve un job, on lance un thread daemon,
et on rend la main immédiatement** ; une page de suivi polle l'état en HTMX
(barre de progression).

Architecture identique à ``nakala_depot_jobs`` (registre mémoire + verrou +
runner synchrone testable). **Garde mono-job indépendante** : ``_id_actuel``
est propre à ce module — un import ShareDocs et un dépôt Nakala peuvent donc
tourner en parallèle (opérations indépendantes), mais deux imports ShareDocs
simultanés sont refusés (``JobConcurrent``). Le jour où l'on multiplie les
types de tâches, factoriser un registre générique (cf. roadmap § Chantier 2).

Sûreté : la cible (fonds/item) est créée **avant** la réservation, côté
requête. Le runner ne fait que télécharger + créer des ``Fichier``. Si le
thread meurt (uvicorn restart), le registre est perdu mais les fichiers déjà
téléchargés sur disque sont **adoptés** au prochain import (idempotence
native de ``importer_depuis_sharedocs``) — pas de re-téléchargement.
"""

from __future__ import annotations

import copy
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from archives_tool.api.services.sharedocs import (
    RapportImportShareDocs,
    importer_depuis_sharedocs,
)
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.external.sharedocs import ClientShareDocs
from archives_tool.models import Item


class JobConcurrent(Exception):
    """Un autre import ShareDocs est déjà actif (``_id_actuel`` posé)."""


#: Cycle de vie d'un job : ``en_cours`` → ``termine`` | ``echec`` |
#: ``annule`` (arrêt coopératif demandé par l'utilisateur).
STATUTS_VALIDES: frozenset[str] = frozenset({"en_cours", "termine", "echec", "annule"})


@dataclass
class EtatJobImport:
    """État d'un job d'import ShareDocs, mis à jour par le runner sous
    ``_lock`` et lu par la route HTMX du suivi (snapshot deepcopy)."""

    job_id: str
    item_cote: str
    fonds_cote: str
    racine: str
    chemin_retour: str  # dossier ShareDocs d'où l'import a été lancé
    total: int  # nombre de fichiers à importer (constant)
    chemins_distants: list[str] = field(default_factory=list)  # pour « Reprendre »
    fonds_cree: bool = False  # le fonds cible a été créé à la volée
    item_cree: bool = False  # l'item cible a été créé à la volée
    faits: int = 0  # index du fichier courant (1-based)
    fichier_courant: str | None = None
    annule: bool = False  # annulation demandée (drapeau coopératif)
    statut: str = "en_cours"
    debut: datetime = field(default_factory=datetime.now)
    fin: datetime | None = None
    # Bilan final, posé quand statut → termine (depuis le rapport).
    retenus: int = 0
    sautes: int = 0
    details_sautes: list[tuple[str, str]] = field(default_factory=list)
    erreur_globale: str | None = None  # si statut=echec


_lock = threading.Lock()
_JOBS: dict[str, EtatJobImport] = {}
_id_actuel: str | None = None


def lire_etat_job(job_id: str) -> EtatJobImport | None:
    """Snapshot deepcopy thread-safe d'un job (``None`` si inconnu).

    Le deepcopy (pris sous lock) garantit que la route HTMX lit un état
    cohérent même si le runner mute les champs entre deux accès Jinja.
    """
    with _lock:
        etat = _JOBS.get(job_id)
        return copy.deepcopy(etat) if etat is not None else None


def est_job_actif() -> bool:
    """True si un import ShareDocs est actuellement en cours."""
    with _lock:
        return _id_actuel is not None


def reserver_job(
    *,
    item_cote: str,
    fonds_cote: str,
    racine: str,
    chemin_retour: str,
    chemins_distants: Sequence[str],
    fonds_cree: bool = False,
    item_cree: bool = False,
) -> str:
    """Réserve atomiquement un job_id et pose la garde anti-concurrent.

    Lève ``JobConcurrent`` si un import ShareDocs tourne déjà.
    """
    global _id_actuel
    with _lock:
        if _id_actuel is not None:
            actif = _JOBS.get(_id_actuel)
            raise JobConcurrent(
                f"Un import ShareDocs est déjà en cours "
                f"(job {_id_actuel}, statut={actif.statut if actif else '?'})."
            )
        job_id = uuid4().hex
        _JOBS[job_id] = EtatJobImport(
            job_id=job_id,
            item_cote=item_cote,
            fonds_cote=fonds_cote,
            racine=racine,
            chemin_retour=chemin_retour,
            total=len(chemins_distants),
            chemins_distants=list(chemins_distants),
            fonds_cree=fonds_cree,
            item_cree=item_cree,
        )
        _id_actuel = job_id
    return job_id


def demander_annulation(job_id: str) -> bool:
    """Pose le drapeau d'annulation sur un job **en cours** (thread-safe).

    Renvoie True si l'annulation a été enregistrée (job connu et en cours),
    False sinon (inconnu ou déjà terminé/échoué/annulé). L'arrêt est
    coopératif : le runner le constate avant le fichier suivant.
    """
    with _lock:
        etat = _JOBS.get(job_id)
        if etat is None or etat.statut != "en_cours":
            return False
        etat.annule = True
        return True


def _make_progress(job_id: str) -> Callable[[int, int, str], None]:
    """Callback de progression qui met à jour le registre (closure job_id)."""

    def progress(index: int, total: int, nom: str) -> None:
        with _lock:
            etat = _JOBS.get(job_id)
            if etat is None:
                return
            etat.faits = index
            etat.total = total
            etat.fichier_courant = nom

    return progress


def _make_should_cancel(job_id: str) -> Callable[[], bool]:
    """Sonde d'annulation : lit le drapeau ``annule`` du job (closure)."""

    def should_cancel() -> bool:
        with _lock:
            etat = _JOBS.get(job_id)
            return bool(etat and etat.annule)

    return should_cancel


def executer_import_sharedocs(
    job_id: str,
    *,
    chemin_db: Path,
    item_id: int,
    chemins_distants: Sequence[str],
    racine_cible: str,
    racines: Mapping[str, Path],
    base_url: str,
    user: str,
    password: str,
    hotes_autorises: frozenset[str] | None = None,
    importe_par: str | None = None,
) -> None:
    """Exécute synchroniquement l'import ShareDocs et alimente le registre.

    **Fonction pure** (pas de thread) : la route la lance dans un
    ``threading.Thread(daemon=True)`` ; les tests l'appellent directement.
    Ouvre une session DB et un client ShareDocs dédiés au thread (creds
    passés explicitement — jamais lus d'un global), capture toute exception
    en ``echec``, et libère ``_id_actuel`` dans le ``finally``.
    """
    global _id_actuel
    rapport: RapportImportShareDocs | None = None
    engine = creer_engine(chemin_db)
    try:
        factory = creer_session_factory(engine)
        with factory() as db:
            item = db.get(Item, item_id)
            if item is None:
                raise ValueError(f"Item {item_id} introuvable dans la base.")
            client = ClientShareDocs(
                base_url, user, password, hotes_autorises=hotes_autorises
            )
            try:
                rapport = importer_depuis_sharedocs(
                    db,
                    client,
                    chemins_distants,
                    item,
                    racine_cible=racine_cible,
                    racines=racines,
                    dry_run=False,
                    importe_par=importe_par,
                    on_progress=_make_progress(job_id),
                    should_cancel=_make_should_cancel(job_id),
                )
            finally:
                client.fermer()
        with _lock:
            etat = _JOBS.get(job_id)
            if etat is not None and rapport is not None:
                # Annulation demandée → statut `annule` (le partiel déjà
                # téléchargé est conservé) ; sinon déroulement normal.
                etat.statut = "annule" if etat.annule else "termine"
                etat.fin = datetime.now()
                if not etat.annule:
                    etat.faits = etat.total
                etat.retenus = rapport.nb_retenus
                etat.sautes = rapport.nb_sautes
                etat.details_sautes = [
                    (f.nom_fichier, f.raison or "")
                    for f in rapport.fichiers
                    if not f.retenu
                ]
    except BaseException as exc:
        with _lock:
            etat = _JOBS.get(job_id)
            if etat is not None:
                etat.statut = "echec"
                etat.fin = datetime.now()
                etat.erreur_globale = f"{type(exc).__name__}: {exc}"
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
    finally:
        engine.dispose()
        with _lock:
            if _id_actuel == job_id:
                _id_actuel = None


def _reset_pour_tests() -> None:
    """Réinitialise le registre + la garde (isolation des tests)."""
    global _id_actuel
    with _lock:
        _JOBS.clear()
        _id_actuel = None
