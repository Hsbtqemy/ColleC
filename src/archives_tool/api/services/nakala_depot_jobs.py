"""Runner et registre mémoire pour le dépôt collection en tâche de fond.

D2 du backlog `docs/developpeurs/backlog-nakala-collection.md`.

Architecture :

- ``EtatJobDepot`` : snapshot mutable de l'état d'un job de dépôt,
  alimenté par le runner via le hook de progression D1 et lu par la
  route HTMX every 2s pour rendre une barre de progression.
- ``_JOBS: dict[str, EtatJobDepot]`` : registre en mémoire,
  protégé par ``_lock`` (threading.Lock global).
- ``_id_actuel: str | None`` : garde anti-concurrent (un seul job de
  dépôt actif à la fois — mono-utilisateur).
- ``reserver_job(...)`` : crée atomiquement le job et pose
  ``_id_actuel``. Lève ``JobConcurrent`` si un autre tourne déjà.
- ``executer_depot_collection(job_id, ...)`` : **fonction synchrone**
  (testable directement, sans thread). La route D3 la lance dans un
  ``threading.Thread(daemon=True)`` puis redirige vers la page suivi.
- ``lire_etat_job(job_id)`` / ``est_job_actif()`` : accesseurs
  thread-safe.

Sûreté par reprise idempotente : si le thread meurt (uvicorn restart,
KeyboardInterrupt…), le registre est perdu (in-memory) mais :

- ``Collection.doi_nakala`` et ``Item.doi_nakala`` sont commités au fil
  de l'eau côté ``deposer_collection`` — la donnée est durable.
- Au prochain lancement (« Reprendre »), un nouveau job démarre ; le
  service ``deposer_collection`` saute les items déjà déposés
  (idempotence native, héritée de ``deposer_item``).

Pas de broker (Redis/Celery) : c'est la 1ʳᵉ tâche de fond du projet,
volontairement légère. Un seul job à la fois, mono-utilisateur, et la
reprise couvre les pannes — pas besoin de plus.
"""

from __future__ import annotations

import copy
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from archives_tool.api.services.nakala_depot import (
    LICENCE_DEFAUT,
    RapportDepotCollection,
    deposer_collection,
)
from archives_tool.db import creer_engine, creer_session_factory
from archives_tool.external.nakala.write_client import NakalaEcritureClient
from archives_tool.models import Collection

#: Défaut en mode local — réplique `deps.OWNER_DEFAUT` (ce module n'importe
#: pas `deps` pour éviter un cycle). Garder alignés.
OWNER_DEFAUT = "local"


# ---------------------------------------------------------------------------
# Erreurs publiques
# ---------------------------------------------------------------------------


class JobConcurrent(Exception):
    """Un autre job de dépôt collection est déjà actif.

    Levée par ``reserver_job`` quand ``_id_actuel`` est posé. L'appelant
    (route D3) doit afficher un message d'erreur et rediriger sans
    démarrer de thread.
    """


# ---------------------------------------------------------------------------
# État d'un job
# ---------------------------------------------------------------------------


#: Valeurs autorisées pour ``EtatJobDepot.statut``. Cycle de vie :
#: ``en_cours`` (initial) → ``termine`` (déroulement normal) ou
#: ``echec`` (exception globale interceptée par le runner).
STATUTS_VALIDES: frozenset[str] = frozenset({"en_cours", "termine", "echec"})


@dataclass
class EtatJobDepot:
    """État d'un job de dépôt collection, persistant le temps du run.

    Champs mis à jour par le runner sous ``_lock`` ; lus par la route
    HTMX du suivi. ``cote_courante`` est la cote du **dernier item
    traité** (le hook D1 fire APRÈS traitement) — l'UI peut le rendre
    en « X traité » plutôt que « X en cours », ce qui est plus honnête.
    """

    job_id: str
    fonds_cote: str  # contexte d'affichage (breadcrumb suivi)
    collection_cote: str
    total: int  # nombre d'items à traiter (constant)
    owner: str = OWNER_DEFAUT  # clé d'isolation (garde mono-job per-owner)
    faits: int = 0  # incrémenté à chaque hook progress
    cote_courante: str | None = None  # cote du dernier item traité
    statut: str = "en_cours"
    debut: datetime = field(default_factory=datetime.now)
    fin: datetime | None = None
    # Listes finales, posées au moment où statut passe à `termine` (depuis
    # le rapport renvoyé par ``deposer_collection``). Avant ça, vides.
    deposes: list[str] = field(default_factory=list)  # cotes
    sautes: list[str] = field(default_factory=list)
    non_deposables: list[str] = field(default_factory=list)
    erreurs: list[tuple[str, str]] = field(default_factory=list)
    collection_doi: str | None = None  # connu après le 1er coup de POST /collections
    collection_creee: bool = False
    erreur_globale: str | None = None  # si statut=echec


# ---------------------------------------------------------------------------
# Registre + verrou
# ---------------------------------------------------------------------------


_lock = threading.Lock()
_JOBS: dict[str, EtatJobDepot] = {}
#: owner -> job_id actif. Garde mono-job **per-owner** : un seul dépôt par
#: owner à la fois (en local, un seul owner ``OWNER_DEFAUT``). `_JOBS` reste
#: keyé par UUID (un job_id non devinable n'est pas une fuite cross-owner).
_id_actuel: dict[str, str] = {}


def lire_etat_job(job_id: str) -> EtatJobDepot | None:
    """Lecture thread-safe d'un état de job. ``None`` si inconnu.

    Renvoie un **snapshot deepcopy** pris sous lock, pas l'objet vivant.
    Garantit qu'aucun champ ne peut être muté pendant que l'appelant
    le lit — critique pour la route HTMX every 2s qui rend un template
    avec plusieurs accès aux champs après cette lecture (un writer qui
    set `statut=termine` puis `collection_doi=...` puis `deposes=[...]`
    pourrait laisser le reader voir un état partiellement écrit sinon).

    Le deepcopy couvre les listes (`deposes`, `sautes`, …) — sans cela,
    le reader recevrait une référence au même list object que le writer
    pourrait remplacer en cours d'itération Jinja.
    """
    with _lock:
        etat = _JOBS.get(job_id)
        if etat is None:
            return None
        return copy.deepcopy(etat)


def est_job_actif(*, owner: str = OWNER_DEFAUT) -> bool:
    """True si un job de dépôt est en cours pour cet owner."""
    with _lock:
        return owner in _id_actuel


# ---------------------------------------------------------------------------
# Réservation + lancement
# ---------------------------------------------------------------------------


def reserver_job(
    *,
    fonds_cote: str,
    collection_cote: str,
    total: int,
    owner: str = OWNER_DEFAUT,
) -> str:
    """Réserve un job_id atomiquement et pose la garde anti-concurrent
    **pour cet owner**.

    Lève ``JobConcurrent`` si un dépôt tourne déjà pour ``owner``. Sinon,
    crée l'``EtatJobDepot`` initial dans le registre et renvoie le job_id
    (UUID4 hex). Le runner consommera ce job_id pour mettre à jour l'état
    au fil de l'eau.

    ``total`` doit être ``len(collection.items)`` calculé par l'appelant
    avant la réservation (évite un round-trip DB dans cette fonction
    critique sous lock).
    """
    with _lock:
        actuel = _id_actuel.get(owner)
        if actuel is not None:
            actif = _JOBS.get(actuel)
            raise JobConcurrent(
                f"Un dépôt collection est déjà en cours "
                f"(job {actuel}, statut={actif.statut if actif else '?'})."
            )
        job_id = uuid4().hex
        _JOBS[job_id] = EtatJobDepot(
            job_id=job_id,
            fonds_cote=fonds_cote,
            collection_cote=collection_cote,
            total=total,
            owner=owner,
        )
        _id_actuel[owner] = job_id
    return job_id


# ---------------------------------------------------------------------------
# Runner synchrone
# ---------------------------------------------------------------------------


def _make_progress(job_id: str) -> Callable[[str, int, int], None]:
    """Construit un callback `progress` qui met à jour le registre.

    Capture ``job_id`` par closure. Chaque appel pose ``cote_courante``
    (dernier item traité) et ``faits`` (= index 1-based). ``total`` est
    réaffirmé à chaque appel pour défendre contre une dérive si la
    collection venait à changer (cas théorique).
    """

    def progress(cote: str, index: int, total: int) -> None:
        with _lock:
            etat = _JOBS.get(job_id)
            if etat is None:
                return  # registre nettoyé entre-temps : on ignore silencieusement
            etat.cote_courante = cote
            etat.faits = index
            etat.total = total

    return progress


def _client_ecriture(config_nakala: Any) -> NakalaEcritureClient:
    """Construit un client d'écriture Nakala depuis la config locale.

    Helper interne pour que le runner n'importe pas directement
    ``api/routes/nakala_web.py`` (boucle de dépendance). La config est
    typée ``Any`` car ``ConfigNakala`` est un dataclass interne à
    ``config.py`` qu'on ne veut pas couper en deux pour un import.
    """
    return NakalaEcritureClient(
        config_nakala.base_url,
        config_nakala.api_key,
        timeout=config_nakala.timeout,
        verify_ssl=config_nakala.verify_ssl,
    )


def executer_depot_collection(
    job_id: str,
    *,
    chemin_db: Path,
    collection_id: int,
    config_nakala: Any,
    racines: Mapping[str, Path],
    statut_donnee: str = "pending",
    statut_collection: str = "private",
    cree_par: str | None = None,
    licence_defaut: str = LICENCE_DEFAUT,
) -> None:
    """Exécute synchroniquement le dépôt d'une collection et alimente
    le registre via le hook D1.

    **Fonction pure** : pas de threading, pas de daemon. La route D3
    appelle ``threading.Thread(target=executer_depot_collection, …,
    daemon=True).start()`` ; les tests appellent directement.

    Gère :
    - ouverture/fermeture de la session DB (engine dédié par job,
      disposé en fin) ;
    - construction/fermeture du client d'écriture ;
    - capture de toute exception et bascule de l'état en ``echec``
      avec ``erreur_globale`` ;
    - libération de ``_id_actuel`` dans le ``finally`` global pour
      qu'un nouveau job soit autorisé même en cas d'exception
      inattendue.

    Pré-conditions :
    - ``job_id`` a été obtenu via ``reserver_job(...)``.
    - ``_JOBS[job_id]`` existe (posé par la réservation).
    """
    rapport: RapportDepotCollection | None = None
    # Owner capturé depuis l'Etat (posé par reserver_job) — sert à libérer
    # la garde du bon owner dans le finally, même si l'Etat est nettoyé
    # entre-temps.
    with _lock:
        _etat0 = _JOBS.get(job_id)
        owner = _etat0.owner if _etat0 is not None else OWNER_DEFAUT
    engine = creer_engine(chemin_db)
    try:
        factory = creer_session_factory(engine)
        with factory() as db:
            collection = db.get(Collection, collection_id)
            if collection is None:
                raise ValueError(
                    f"Collection {collection_id} introuvable dans la base."
                )
            client = _client_ecriture(config_nakala)
            try:
                rapport = deposer_collection(
                    db,
                    client,
                    collection,
                    racines=racines,
                    statut_donnee=statut_donnee,
                    statut_collection=statut_collection,
                    cree_par=cree_par,
                    dry_run=False,
                    licence_defaut=licence_defaut,
                    progress=_make_progress(job_id),
                )
            finally:
                fermer = getattr(client, "fermer", None)
                if callable(fermer):
                    fermer()
        # Finalisation succès (sous lock pour cohérence vis-à-vis des
        # lectures HTMX).
        with _lock:
            etat = _JOBS.get(job_id)
            if etat is not None and rapport is not None:
                etat.statut = "termine"
                etat.fin = datetime.now()
                etat.collection_doi = rapport.collection_doi
                etat.collection_creee = rapport.collection_creee
                etat.deposes = [r.cote for r in rapport.deposes]
                etat.sautes = list(rapport.sautes)
                etat.non_deposables = list(rapport.non_deposables)
                etat.erreurs = list(rapport.erreurs)
    except BaseException as exc:
        # BaseException catch également KeyboardInterrupt/SystemExit
        # — si on est dans un thread daemon, on ne veut pas que le
        # _id_actuel reste bloqué au cas où ça arrive.
        with _lock:
            etat = _JOBS.get(job_id)
            if etat is not None:
                etat.statut = "echec"
                etat.fin = datetime.now()
                etat.erreur_globale = f"{type(exc).__name__}: {exc}"
        # Re-lève uniquement les exceptions normales — KeyboardInterrupt
        # propage pour ne pas masquer un Ctrl-C en mode CLI.
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        # Pour les autres : on a marqué le job en echec, on laisse mourir
        # silencieusement. La trace est dans erreur_globale ; le caller
        # (route D3) ne voit pas l'exception car le thread a démarré et
        # rendu la main.
    finally:
        engine.dispose()
        with _lock:
            if _id_actuel.get(owner) == job_id:
                del _id_actuel[owner]


# ---------------------------------------------------------------------------
# Helpers tests
# ---------------------------------------------------------------------------


def _reset_pour_tests() -> None:
    """Réinitialise le registre + les gardes anti-concurrent (tous owners).

    À appeler dans une fixture pytest pour isoler les tests. Pas
    d'usage en production — préfixé ``_`` pour signaler le scope.
    """
    with _lock:
        _JOBS.clear()
        _id_actuel.clear()
