"""Service de versioning fichiers Nakala (palier P3+, cf.
`docs/developpeurs/nakala-depot-future.md` difficulté #4).

- **P3+a** : fondation `Fichier.sha1_nakala` (colonne + migration +
  capture upload + capture pull).
- **P3+b** : ``comparer_fichiers_item`` — détection (lecture seule).
- **P3+c** : ``pousser_fichiers_item`` — push effectif (upload des
  nouveaux/modifies + ``PUT /datas/{id}`` avec ``files[]`` cible +
  mise à jour ``sha1_nakala``).

Les hypothèses Nakala validées contre apitest (script
``scripts/explorer_put_files_nakala.py`` 2026-06-14) sont :

- **H1** : ``PUT files=[...]`` remplace intégralement la liste.
- **H2A** : ``PUT`` sans clé ``metas`` préserve les metas distantes.
- **H3** : ``PUT files=[]`` est silencieusement ignoré → garde-fou
  `PushImpossible` si la liste cible est vide.
- **H4** : ``PUT`` avec un sha1 inconnu lève HTTP 404 explicite →
  cleanup des uploads orphelins en cas d'échec.
- **H5** : ordre ``files[]`` préservé (envoyé = restitué).
- **H6** : idempotence du PUT (re-push identique = no-op silencieux).
- **H7** : ``PUT {sha1: existant, name: nouveau}`` renomme côté Nakala
  sans re-upload (gratuit pour les ``inchanges`` dont l'utilisateur a
  changé le ``nom_fichier`` local).
- **H10** : ``lire_depot`` immédiat post-PUT reflète les changements
  (pas d'eventual consistency à gérer).
- **H11** : champ ``description`` par fichier accepté et préservé.
  **Intégration push S7 livrée** : `Fichier.description_externe` est capturé
  au pull (``materialiser_fichiers_nakala``), porté au dépôt
  (``deposer_item`` → ``POST /datas``) ET au push (``_reordonner_files`` →
  ``PUT /datas/{id}``). **Règle anti-wipe indépendante de la sonde** : le
  PUT émet la transcription LOCALE si elle existe, **sinon préserve la
  valeur distante re-lue** — donc un push ne peut jamais effacer une
  description distante, que Nakala efface ou préserve les clés ``files[i]``
  omises. ``comparer_fichiers_item`` détecte une divergence
  description-seule (sha1 identique) pour qu'une édition de transcription
  seule soit poussable. **Corollaire** : un **effacement** local (vider une
  transcription qui existe côté distant) n'est PAS propageable par ce design
  (préserver = garder la distante) — il n'est donc pas classé en divergence
  (sinon faux signal + non-convergence). Effacer une description distante
  attend la sonde omit-vs-wipe. **Reste à confirmer en live** (sonde différée, cf.
  ticket S7 `backlog-nakala-api.md`) : le comportement exact de Nakala sur
  une clé ``files[i]`` omise — confirmation, pas prérequis (le design ne
  dépend pas de la réponse).
"""

from __future__ import annotations

import hashlib
import logging
from collections import defaultdict, deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from archives_tool.external.nakala.client import ClientLectureNakala
from archives_tool.external.nakala.mapper import mapper_depot
from archives_tool.external.nakala.write_client import NakalaEcritureClient
from archives_tool.models import Fichier, Item, normaliser_transcription
from archives_tool.models.enums import EtatFichier

#: Logger structure pour le service push fichiers. Le service mute un
#: etat distant (Nakala) ET local (DB) — sans logging, un push qui
#: foire en prod laisse zero trace. INFO sur les events metiers
#: (debut, PUT, commit, cleanup), DEBUG sur le detail upload/file.
logger = logging.getLogger(__name__)

#: Taille de chunk pour le streaming SHA-1 — 8 KiB.
_TAILLE_CHUNK_SHA1 = 8192

#: Longueur exacte d'un SHA-1 en hex lowercase (160 bits / 4 bits par
#: caractère = 40). Sert à valider les sha1 retournés par
#: `uploader_fichier` avant de les envoyer au `PUT /datas/{id}`.
_LONGUEUR_SHA1_HEX = 40
#: Caractères valides pour un sha1 hex après normalisation lowercase.
_HEX_LOWERCASE = frozenset("0123456789abcdef")


def _valider_depot_lu(depot: object, contexte: str) -> dict[str, Any]:
    """Valide la réponse d'``lire_depot`` et la renvoie typée comme
    dict.

    Lève ``ReponseLectureInvalide`` si le retour n'est pas un dict.
    Le contexte (DOI ou opération) est inclus dans le message pour
    aider au diagnostic — sans ce filet, le code aval planterait avec
    un ``AttributeError`` sans contexte sur la commande en cours.

    Symétrie avec ``_valider_sha1_uploade`` (Trou P passe 7).
    """
    if not isinstance(depot, dict):
        raise ReponseLectureInvalide(
            f"lire_depot({contexte!r}) a retourné "
            f"{type(depot).__name__} au lieu d'un dict."
        )
    return depot


def _valider_sha1_uploade(desc: object, contexte: str) -> str:
    """Valide la réponse d'`uploader_fichier` et renvoie le sha1
    normalisé.

    Lève `UploadInvalide` si la réponse est inexploitable. Le contexte
    (nom du fichier qu'on uploadait) est inclus dans le message pour
    aider au diagnostic — un upload réussi techniquement mais avec un
    sha1 invalide n'est pas immédiatement visible côté logs sinon.
    """
    if not isinstance(desc, dict):
        raise UploadInvalide(
            f"uploader_fichier({contexte!r}) a retourné "
            f"{type(desc).__name__} au lieu d'un dict."
        )
    sha1_brut = desc.get("sha1")
    if not isinstance(sha1_brut, str):
        raise UploadInvalide(
            f"uploader_fichier({contexte!r}) : champ 'sha1' absent ou "
            f"non-string (type={type(sha1_brut).__name__})."
        )
    sha1_norm = sha1_brut.strip().lower()
    if len(sha1_norm) != _LONGUEUR_SHA1_HEX:
        raise UploadInvalide(
            f"uploader_fichier({contexte!r}) : sha1 de longueur "
            f"{len(sha1_norm)} (attendu {_LONGUEUR_SHA1_HEX})."
        )
    if not all(c in _HEX_LOWERCASE for c in sha1_norm):
        raise UploadInvalide(
            f"uploader_fichier({contexte!r}) : sha1 contient des caractères non-hex."
        )
    return sha1_norm


class ComparaisonImpossible(Exception):
    """Item sans `doi_nakala` : pas de dépôt distant à comparer."""


class OrphelinsDetectes(Exception):
    """Refus du push : des fichiers Nakala existent sans pendant local.

    Le ``PUT /datas/{id}`` retirerait automatiquement ces fichiers
    côté distant (catastrophique pour items publiés). L'appelant doit
    repasser avec ``retirer_orphelins=True`` pour confirmer l'intention.

    Attribut ``orphelins`` : liste ``FichierOrphelin`` pour permettre à
    l'appelant (CLI / route) d'afficher la liste à l'utilisateur.
    """

    def __init__(self, orphelins: list["FichierOrphelin"]) -> None:
        self.orphelins = orphelins
        noms = ", ".join(
            f"{o.nom_fichier} (sha1: {o.sha1[:12]}…)" for o in orphelins[:5]
        )
        suffixe = "" if len(orphelins) <= 5 else f" (+ {len(orphelins) - 5} autres)"
        super().__init__(
            f"{len(orphelins)} orphelin(s) distant(s) détecté(s) : {noms}{suffixe}. "
            "Repasser avec retirer_orphelins=True pour confirmer."
        )


class PushImpossible(Exception):
    """Refus du push pour un cas non supporté côté Nakala.

    Cas principal : ``files_cible == []`` (tous les fichiers locaux
    retirés ET ``retirer_orphelins=True``). L'hypothèse H3 confirme
    que ``PUT files=[]`` est silencieusement ignoré côté Nakala —
    la liste cible ne peut pas être vide. Pour vider un dépôt, passer
    par ``supprimer_depot`` puis re-déposer.
    """


class ContenuDuplique(Exception):
    """Refus pré-vol : le set de fichiers final contient deux sha1
    identiques (deux fichiers de même contenu binaire).

    Nakala **rejette** un dépôt avec un sha1 dupliqué (sondé live
    2026-06-15 : `POST /datas` avec `files=[{X,a},{X,b}]` → 422 ; re-POST
    d'un sha1 déjà attaché → 409/500). En push granulaire (T2), sans ce
    garde-fou amont l'échec surviendrait **mi-parcours** (409 au 2ᵉ POST)
    en laissant le dépôt dans un état partiel. On refuse donc **avant
    toute mutation distante**, proprement, en nommant les fichiers
    fautifs — c'est presque toujours une erreur de catalogage (deux
    Fichier pointant le même binaire).
    """

    def __init__(self, doublons: dict[str, list[str]]) -> None:
        #: sha1 (tronqué) → noms des Fichier partageant ce contenu.
        self.doublons = doublons
        details = "; ".join(
            f"{sha1[:12]}… : {', '.join(noms)}" for sha1, noms in doublons.items()
        )
        super().__init__(
            "Contenu dupliqué — Nakala refuse deux fichiers de même sha1 dans "
            f"un dépôt. Fichiers concernés : {details}. Dé-dupliquer côté "
            "ColleC (probable erreur de catalogage) avant de pousser."
        )


class FichierFantomeDistant(Exception):
    """Refus du push : un ou plusieurs Fichier ColleC sans binaire local
    portent un ``sha1_nakala`` qui ne matche plus aucun sha1 distant
    actuel.

    Causes plausibles :

    - **Désynchronisation cache** : un autre opérateur a modifié le
      dépôt côté Nakala (push, suppression de fichier, versioning)
      sans que ColleC ait re-pull entre-temps.
    - **Maintenance Nakala** : opération côté Huma-Num qui re-hashe
      les fichiers (rare mais possible).
    - **Push précédent partiellement échoué** : le ``sha1_nakala``
      d'un Fichier a été mis à jour avant que le PUT distant ne soit
      effectivement appliqué (race condition ou commit DB sans PUT
      réussi).

    Sans refus, le service inclurait ce sha1 fantôme dans ``files[]``
    cible → ``PUT`` retourne HTTP 404 cryptique (H4 : sha1 inconnu)
    sans contexte côté user.

    Workaround : re-rapatrier l'item (``archives-tool nakala
    rapatrier <doi> --no-dry-run`` re-pulle l'état distant courant et
    met à jour les ``sha1_nakala``) ou nettoyer manuellement le
    Fichier ColleC concerné.

    L'attribut ``fichiers`` liste les Fichier concernés (avec leur
    ``sha1_distant`` fantôme).
    """

    def __init__(self, fichiers: list["FichierCompare"]) -> None:
        self.fichiers = fichiers
        noms = ", ".join(
            f"{f.nom_fichier} (sha1: {(f.sha1_distant or '')[:12]}…)"
            for f in fichiers[:5]
        )
        suffixe = "" if len(fichiers) <= 5 else f" (+ {len(fichiers) - 5} autres)"
        super().__init__(
            f"{len(fichiers)} Fichier(s) ColleC pointant vers un sha1 "
            f"fantôme côté Nakala : {noms}{suffixe}. Re-rapatrier l'item "
            "(`archives-tool nakala rapatrier`) pour resynchroniser, ou "
            "nettoyer manuellement le Fichier ColleC."
        )


#: `DepotPublie` est defini dans `nakala_depot.py` (couche plus basse).
#: Re-exporte ici pour preserver les imports existants
#: (`from archives_tool.api.services.nakala_fichiers import DepotPublie`).
from archives_tool.api.services.nakala_depot import DepotPublie  # noqa: E402, F401


class IncoherenceFichierORM(Exception):
    """Le Fichier ORM attendu pour un upload a été muté ou supprimé
    entre la phase ``comparer_fichiers_item`` et la phase de push.

    Race condition typique : une autre session a supprimé le Fichier,
    a basculé son ``etat`` en CORBEILLE, a effacé sa ``racine`` /
    ``chemin_relatif``, ou a déplacé le binaire. Le re-fetch
    ``db.get(Fichier, id)`` au moment de l'upload détecte ces cas.

    Le service catche au niveau du ``try`` global et déclenche le
    cleanup best-effort des uploads précédemment réussis.

    **Pourquoi pas une simple `AssertionError`** : les `assert` Python
    sont supprimés sous `python -O` (rare en prod mais possible) et
    leur message est minimal ; pour un chemin destructif (modifie
    Nakala), on veut une exception explicite quel que soit le mode
    d'exécution.
    """


class ReponseLectureInvalide(Exception):
    """``client_lecture.lire_depot`` a retourné une réponse inexploitable
    (None, non-dict, ou type inattendu).

    Cause typique : bug d'un proxy entre ColleC et Nakala qui munge la
    réponse JSON ; changement non documenté du format Nakala ; ou bug
    d'implémentation d'un client mock dans les tests.

    Sans cette validation explicite, le code aval planterait avec un
    ``AttributeError: 'NoneType' object has no attribute 'get'`` au
    moment d'accéder à ``depot.get("files")`` — message cryptique
    sans contexte sur le DOI ou la commande en cours.

    Symétrie avec ``_valider_sha1_uploade`` (Trou P passe 7) :
    défense en profondeur sur les contrats de retour client.
    """


class UploadInvalide(Exception):
    """`client_ecriture.uploader_fichier` a retourné une réponse
    inexploitable (sha1 absent / vide / non-string / longueur ≠ 40 /
    caractères non-hex).

    Cause typique : bug d'un proxy entre ColleC et Nakala qui munge la
    réponse JSON ; ou changement non documenté du format Nakala ; ou
    bug d'implémentation d'un client mock dans les tests.

    Pourquoi loud : sans validation, on enverrait ce sha1 invalide tel
    quel au ``PUT /datas/{id}`` → Nakala lèverait HTTP 404 (H4 : sha1
    inconnu), le cleanup des uploads précédents pourrait à son tour
    planter sur ``supprimer_upload("")`` selon l'implémentation client
    → fuite d'uploads orphelins côté Nakala et état incohérent local.

    Le service catche l'exception au niveau du ``try`` global et
    déclenche le cleanup best-effort des uploads précédemment réussis.
    """


class BackfillIncomplet(Exception):
    """Refus du push : un ou plusieurs Fichier en `nakala_only_sans_local`
    n'ont pas de ``sha1_nakala`` peuplé (legacy pré-P3+a, ou backfill
    qui a échoué pour certaines URLs IIIF).

    Sans ``sha1_nakala``, le service ne peut pas distinguer un Fichier
    ColleC réellement apparié à un fichier distant d'un Fichier
    orphelin. Si on poussait quand même, le fichier distant
    correspondant serait retiré silencieusement (perte de donnée).

    Workaround : relancer le backfill (``alembic upgrade head`` rejoue
    `appliquer_backfill`) ou éditer manuellement le Fichier ColleC.
    """

    def __init__(self, fichiers: list["FichierCompare"]) -> None:
        self.fichiers = fichiers
        noms = ", ".join(f"{f.nom_fichier}" for f in fichiers[:5])
        suffixe = "" if len(fichiers) <= 5 else f" (+ {len(fichiers) - 5} autres)"
        super().__init__(
            f"{len(fichiers)} Fichier(s) en nakala_only_sans_local sans "
            f"sha1_nakala : {noms}{suffixe}. Relancer le backfill ou nettoyer "
            "manuellement avant de pousser."
        )


@dataclass(frozen=True)
class FichierCompare:
    """Vue figée d'un Fichier ColleC dans une comparaison.

    - ``fichier_id`` : id du Fichier ORM (pour le palier c qui mutera
      ``sha1_nakala`` après le push).
    - ``sha1_local`` : SHA-1 du binaire local recalculé on the fly,
      ou ``None`` si pas de binaire local (cas Nakala-only).
    - ``sha1_distant`` : valeur de ``Fichier.sha1_nakala`` côté local
      (snapshot Nakala connu par ColleC) — la vérité distante actuelle
      vient du ``lire_depot``, pas de cette colonne.
    """

    fichier_id: int
    cote_item: str
    nom_fichier: str
    ordre: int
    sha1_local: str | None
    sha1_distant: str | None


@dataclass(frozen=True)
class FichierOrphelin:
    """Entrée distante (`files[i]` du dépôt) sans Fichier ColleC apparié.

    Risque potentiel au push : un `PUT /datas/{id}` avec une liste cible
    omettant cet orphelin le retire côté Nakala (politique Nakala). Le
    palier c devra refuser sans flag `--retirer-orphelins`.
    """

    sha1: str
    nom_fichier: str


@dataclass
class RapportComparaisonFichiers:
    """Résultat d'un ``comparer_fichiers_item``.

    Classement complet de la confrontation locale vs distante :

    - **nouveaux** : binaire local, sha1_local absent côté distant
      ET pas de sha1_nakala connu pointant ailleurs. Au push, sera
      uploadé + ajouté.
    - **modifies** : binaire local, sha1_local ≠ sha1_distant connu
      qui est encore présent côté Nakala. Au push, sera ré-uploadé
      en remplacement.
    - **inchanges** : sha1_local matche directement un sha1 distant
      présent. Au push, conservé tel quel (juste passer dans `files[]`).
    - **nakala_only_sans_local** : Fichier ColleC pullé depuis Nakala
      mais sans binaire local résolvable. **Préservés par défaut au
      push** (P3+c.1) : `pousser_fichiers_item` les inclut dans
      `files[]` cible avec leur `sha1_nakala` connu, évitant qu'ils
      soient retirés côté distant.
    - **orphelins_distants** : sha1 côté Nakala sans Fichier ColleC
      correspondant. Cas typique : fichier supprimé localement. Au
      push, **refusés par défaut** ; flag `retirer_orphelins=True`
      requis pour confirmer leur retrait côté Nakala.
    - **fichiers_fantomes** : Fichier ColleC sans binaire local dont le
      ``sha1_nakala`` était posé mais ne matche plus aucun fichier
      distant actuel. Cas typique : désynchronisation cache (le distant
      a été modifié hors ColleC, ou Nakala maintenance a re-hashé), ou
      `sha1_nakala` ancien restant après un push partiellement échoué
      (le sha1 distant a changé sans que ColleC l'apprenne). **Refus
      au push** : `pousser_fichiers_item` lève `FichierFantomeDistant`
      car inclure un sha1 fantôme dans `files[]` cible cause une
      HTTP 404 cryptique côté Nakala (H4 : sha1 inconnu). User doit
      re-rapatrier l'item ou nettoyer le Fichier ColleC manuellement.
    - **non_actifs_a_retirer** : Fichier ColleC en `etat != ACTIF`
      (REMPLACE ou CORBEILLE) dont le `sha1_nakala` matche un sha1
      distant. Le filtre `etat != ACTIF` exclut ces Fichier du plan
      de push → au PUT, Nakala les retire (H1 — `files[]` remplace
      intégralement). **Distinct des orphelins** : le user a une trace
      ColleC explicite de l'intention de retrait (Fichier en corbeille),
      contrairement à un vrai orphelin (juste un sha1 distant inconnu).
      Surfacé séparément pour que la CLI/UI puisse l'expliciter au lieu
      du silence. **Sémantique CORBEILLE en attente** : le mécanisme
      « mettre à la corbeille » n'est pas encore implémenté côté UI
      (V1.x). Tant qu'il dort, cette catégorie reste vide. Quand il
      arrivera, il faudra trancher : (a) refuser le push tant que
      des Fichier corbeille existent, ou (b) garder le comportement
      consultatif actuel. Pour l'instant : signaler sans bloquer.
    """

    cote_item: str
    doi: str
    nouveaux: list[FichierCompare] = field(default_factory=list)
    modifies: list[FichierCompare] = field(default_factory=list)
    inchanges: list[FichierCompare] = field(default_factory=list)
    nakala_only_sans_local: list[FichierCompare] = field(default_factory=list)
    orphelins_distants: list[FichierOrphelin] = field(default_factory=list)
    non_actifs_a_retirer: list[FichierCompare] = field(default_factory=list)
    fichiers_fantomes: list[FichierCompare] = field(default_factory=list)
    #: **descriptions_divergentes** : Fichier dont le contenu (sha1) est
    #: inchangé côté distant mais dont la transcription locale **non vide**
    #: (`description_externe`) diffère de la `description` distante (S7).
    #: Sous-ensemble de ``inchanges`` ∪ ``nakala_only_sans_local`` (mêmes
    #: objets). Compte comme un changement (`aucun_changement` → False) :
    #: au PUT, ``_reordonner_files`` propage la nouvelle transcription. Sans
    #: cette détection, une édition de transcription seule serait classée
    #: no-op et jamais poussée. **N'inclut PAS un effacement** (locale vidée,
    #: distante non vide) : non propageable par le design actuel (cf.
    #: `_transcription_a_propager`), donc pas signalé comme « à pousser ».
    descriptions_divergentes: list[FichierCompare] = field(default_factory=list)
    #: Snapshot brut des `files[]` distants (filtré via isinstance dict).
    #: Préservé pour la journalisation `OperationPushNakala` (passe 24)
    #: — snapshot AVANT le PUT. Pas re-lu par le service push (qui
    #: utilise les catégories ci-dessus).
    files_distants_snapshot: list[dict[str, Any]] = field(default_factory=list)
    # `modDate` distant capturé pendant le `lire_depot` initial. Permet
    # au caller (`pousser_fichiers_item`) de détecter une dérive sans
    # rejouer un second `lire_depot` (le client httpx n'a pas de cache
    # LRU — chaque appel = un round-trip HTTP réel).
    mod_date_distant: str | None = None
    # Statut distant ("pending" / "published"). Capturé pour permettre
    # au caller de refuser un push destructif sur un item publié sans
    # un 2e appel (cf. Trou T passe 9 : DOIs DataCite mintés sur les
    # fichiers d'un item publié → toute modification rompt l'intégrité
    # des citations externes).
    statut_distant: str | None = None

    @property
    def aucun_changement(self) -> bool:
        """Vrai si pousser serait un no-op propre : pas de nouveaux,
        pas de modifs, pas d'orphelins à retirer, pas de Fichier
        non-ACTIF avec pendant distant, **pas de fantôme**, **pas de
        divergence de transcription** (S7 : une description éditée
        localement doit pouvoir être poussée même sans changement de
        binaire).

        Les ``nakala_only_sans_local`` ne comptent pas comme un
        changement — ils sont seulement un signal d'attention pour
        le palier c (préservés au PUT avec leur sha1 connu).

        Les ``fichiers_fantomes`` comptent comme un état non-no-op :
        il y a un problème à fixer (désynchronisation DB ↔ Nakala),
        donc le push doit refuser loud plutôt que return early en
        no-op silencieux."""
        return (
            not self.nouveaux
            and not self.modifies
            and not self.orphelins_distants
            and not self.non_actifs_a_retirer
            and not self.fichiers_fantomes
            and not self.descriptions_divergentes
        )


def _sha1_du_binaire(chemin: Path) -> str:
    """SHA-1 streaming d'un fichier sur disque (chunks 8 KiB)."""
    h = hashlib.sha1(usedforsecurity=False)  # noqa: S324 — interop Nakala
    with chemin.open("rb") as fh:
        for chunk in iter(lambda: fh.read(_TAILLE_CHUNK_SHA1), b""):
            h.update(chunk)
    return h.hexdigest()


def _transcription_a_propager(locale: str | None, distante: str | None) -> bool:
    """Vrai si pousser changerait la description distante.

    Le push n'émet la transcription LOCALE que si elle est **non vide**
    (`_reordonner_files`, règle local-sinon-distante). Une divergence n'est
    donc « poussable » que si la locale est non vide **et** diffère de la
    distante (après normalisation None ≡ ""). Sert à classer un changement
    *description-seule* (sha1 identique) en `descriptions_divergentes`.

    Conséquence **assumée** : un **effacement** local (locale vidée alors que
    la distante porte un texte) n'est PAS propageable par le design actuel —
    `_reordonner_files` préserverait la distante. On ne le classe donc pas en
    divergence : sinon faux signal « à pousser » + non-convergence (le PUT
    ré-émettrait la valeur distante, le comparer la re-signalerait à l'infini).
    Effacer une transcription distante nécessitera la sonde omit-vs-wipe
    (différée, apitest down) — cf. note de module + backlog S7."""
    loc = normaliser_transcription(locale)
    return loc is not None and loc != normaliser_transcription(distante)


def comparer_fichiers_item(
    db: Any,
    client: ClientLectureNakala,
    item: Item,
    *,
    racines: Mapping[str, Path],
) -> RapportComparaisonFichiers:
    """Classe les fichiers de ``item`` par rapport au dépôt Nakala distant.

    Pull ``GET /datas/{doi}``, recalcule le SHA-1 de chaque binaire local
    présent, et confronte aux ``files[i].sha1`` distants. Pure lecture
    (aucune écriture base ni distante).

    Stratégie de réconciliation :

    1. Match prioritaire par **sha1 calculé local ↔ sha1 distant** —
       robuste aux renommages.
    2. Fallback par ``sha1_nakala`` connu de ColleC pour détecter une
       **modification** d'un fichier déjà déposé (sha1 a changé en local,
       mais on retrouve l'ancien sha1 côté distant).

    Args:
        db: Session SQLAlchemy (non utilisée directement — ``item`` est
            déjà chargé avec ses fichiers ; argument gardé pour la
            symétrie avec les autres services du module et un éventuel
            usage futur).
        client: Client lecture Nakala (déjà ouvert par l'appelant).
        item: Item ORM avec ``doi_nakala`` non null.
        racines: Mapping racine logique → chemin physique (cf. config
            locale) pour résoudre les binaires locaux.

    Raises:
        ComparaisonImpossible: ``item.doi_nakala`` est None.
        ReponseLectureInvalide: ``lire_depot`` retourne un non-dict.
        ErreurNakala: échec du ``lire_depot`` distant (propagé tel quel).
    """
    if not item.doi_nakala:
        raise ComparaisonImpossible(
            f"Item {item.cote!r} sans doi_nakala — comparaison impossible."
        )

    # Pull distant (peut lever ErreurNakala, on laisse propager).
    # Defense en profondeur (Trou Y passe 13) : valider le dict retourne
    # AVANT d'acceder a ses cles - sinon AttributeError cryptique si
    # le client mock / proxy bogue retourne None.
    depot_brut = client.lire_depot(item.doi_nakala)
    depot = _valider_depot_lu(depot_brut, item.doi_nakala)
    # Validation defensive : Nakala doit retourner un dict avec `files`
    # en list de dicts. Si bug API ou proxy qui munge la reponse (vu
    # `{"files": "not_a_list"}` ou `{"files": {"k": "v"}}`), un truthy-or-
    # default `or []` ne suffit pas : la boucle itererait sur les chars
    # / keys et `fd.get` planterait en AttributeError. On normalise a
    # `[]` toute valeur non-list.
    files_brut = depot.get("files")
    files_distants = files_brut if isinstance(files_brut, list) else []
    # Index sha1 → **liste** d'entrées distantes. On filtre les sha1
    # vides (cas dégénéré côté Nakala, ne devrait pas arriver).
    # **Normalise en lowercase** : `hexdigest()` côté ColleC produit
    # toujours du lowercase, et Nakala renvoie le sha1 en lowercase
    # aujourd'hui. La normalisation est défensive — si Nakala bascule
    # un jour vers uppercase, le matching continue de fonctionner. On
    # normalise aussi `f.sha1_nakala` à la comparaison plus bas pour
    # la même raison.
    #
    # **Pourquoi `list[dict]` et pas `dict` simple** : cas légitime des
    # doublons sha1 distants (deux pages blanches scannées avec contenu
    # binaire identique, deux planches vides, deux vignettes…). Sans
    # liste, le 2e doublon était silencieusement écrasé de l'index, son
    # appariement ne pouvait pas être tracé → au PUT, il était retiré
    # côté Nakala (cohérent avec H1) parce qu'absent de `files_cible`.
    # Avec consommation par `pop(0)` au matching, chaque entrée distante
    # est utilisée au plus une fois ; les restants en fin de boucle sont
    # de vrais orphelins.
    sha1_index: dict[str, list[dict[str, Any]]] = {}
    for fd in files_distants:
        # Double couche : skip toute entree non-dict (defense vs liste
        # heterogene `[{...}, "str_in_middle", null]`).
        if not isinstance(fd, dict):
            continue
        sha1 = (fd.get("sha1") or "").strip().lower()
        if sha1:
            sha1_index.setdefault(sha1, []).append(fd)

    # Snapshot brut filtré (uniquement les dicts, sha1 vide écarté) —
    # utilisé pour le journal `OperationPushNakala` au push (passe 24).
    # On réduit aux 4 champs identifiants utiles pour audit (sha1, name,
    # size, mime) sans embedder embargo / puid (bruit pour la traçabilité).
    snapshot_distants: list[dict[str, Any]] = [
        {
            "sha1": (fd.get("sha1") or "").strip().lower(),
            "name": fd.get("name"),
            "size": fd.get("size"),
            "mime": fd.get("mime"),
        }
        for fd in files_distants
        if isinstance(fd, dict) and (fd.get("sha1") or "").strip()
    ]

    rapport = RapportComparaisonFichiers(
        cote_item=item.cote,
        doi=item.doi_nakala,
        mod_date_distant=depot.get("modDate"),
        statut_distant=depot.get("status"),
        files_distants_snapshot=snapshot_distants,
    )

    # Import paresseux : `resoudre_chemin` charge la config, on évite
    # le coût si on n'a aucun fichier local à classer.
    from archives_tool.files.paths import resoudre_chemin

    for f in sorted(item.fichiers, key=lambda x: x.ordre):
        # Filtre `etat=ACTIF` : un Fichier en `REMPLACE` ou `CORBEILLE`
        # ne participe pas à la comparaison principale (cohérence avec
        # `derivatives/generateur.py:166` et `renamer/plan.py:108`).
        # Au push (palier c), ces Fichier ne seront pas envoyés dans
        # `files[]` → le PUT Nakala les retire côté distant (H1 —
        # remplace intégralement).
        #
        # Si le Fichier a un `sha1_nakala` qui matche un sha1 distant,
        # on **consomme l'entrée distante** dans `sha1_index` (pour
        # qu'elle ne ressorte pas en orphelin anonyme sans contexte)
        # et on l'ajoute à `non_actifs_a_retirer` pour traçabilité
        # explicite. Le push pourra ainsi expliciter le retrait dans
        # son rapport (au lieu du silence).
        if f.etat != EtatFichier.ACTIF.value:
            sha1_nakala_norm_na = f.sha1_nakala.lower() if f.sha1_nakala else None
            if sha1_nakala_norm_na and sha1_index.get(sha1_nakala_norm_na):
                sha1_index[sha1_nakala_norm_na].pop(0)
                rapport.non_actifs_a_retirer.append(
                    FichierCompare(
                        fichier_id=f.id,
                        cote_item=item.cote,
                        nom_fichier=f.nom_fichier,
                        ordre=f.ordre,
                        sha1_local=None,
                        sha1_distant=f.sha1_nakala,
                    )
                )
            continue

        # Binaire local résolvable et lisible ?
        # On élargit le try/except au calcul SHA-1 lui-même :
        # - `KeyError` : racine absente du dict de config
        # - `ValueError` : `resoudre_chemin` rejette le chemin (path
        #   traversal, racine vide, etc.)
        # - `OSError` (parent de FileNotFoundError, PermissionError,
        #   IsADirectoryError) : TOCTOU entre `is_file()` et `open()`,
        #   ou permissions refusées, ou NFS down. Le fichier n'est pas
        #   utilisable → on le traite comme Nakala-only sans local
        #   (sémantique correcte : pas de binaire local exploitable).
        chemin: Path | None = None
        sha1_local: str | None = None
        if f.racine and f.chemin_relatif:
            try:
                resolu = resoudre_chemin(racines, f.racine, f.chemin_relatif)
                if resolu.is_file():
                    sha1_local = _sha1_du_binaire(resolu)
                    chemin = resolu
            except (KeyError, ValueError, OSError):
                pass

        compare = FichierCompare(
            fichier_id=f.id,
            cote_item=item.cote,
            nom_fichier=f.nom_fichier,
            ordre=f.ordre,
            sha1_local=sha1_local,
            sha1_distant=f.sha1_nakala,
        )

        # Normalise `f.sha1_nakala` en lowercase pour le matching
        # (défensif vs. base legacy avec sha1 uppercase ; cf. note
        # ci-dessus sur l'index distant).
        sha1_nakala_norm = f.sha1_nakala.lower() if f.sha1_nakala else None

        if chemin is None:
            # Nakala-only (ou perdu sur disque) : signal d'attention.
            # Trois cas distinguer (Trou U passe 10) :
            # 1. sha1_nakala posé ET matche le distant → cas légitime
            #    (consomme du sha1_index, classe en nakala_only_sans_local).
            # 2. sha1_nakala posé MAIS absent du distant → fantôme
            #    (désynchro DB ↔ Nakala). Inclure dans `files[]` au
            #    push ferait planter avec H4 (404 sha1 inconnu).
            #    Catégorie dédiée + refus loud côté push.
            # 3. sha1_nakala absent ET binaire local absent → backfill
            #    incomplet (Trou J), catégorie `nakala_only_sans_local`
            #    avec sha1_distant=None, garde-fou `BackfillIncomplet`
            #    au push.
            if sha1_nakala_norm:
                if sha1_index.get(sha1_nakala_norm):
                    fd_match = sha1_index[sha1_nakala_norm].pop(0)
                    rapport.nakala_only_sans_local.append(compare)
                    # S7 : transcription éditée localement sur un fichier
                    # Nakala-only (pas de binaire local) → divergence
                    # poussable via `_reordonner_files`.
                    if _transcription_a_propager(
                        f.description_externe, fd_match.get("description")
                    ):
                        rapport.descriptions_divergentes.append(compare)
                else:
                    rapport.fichiers_fantomes.append(compare)
            else:
                rapport.nakala_only_sans_local.append(compare)
            continue

        # Binaire local présent — `sha1_local` est garanti non-None.
        assert compare.sha1_local is not None
        if sha1_index.get(compare.sha1_local):
            fd_match = sha1_index[compare.sha1_local].pop(0)
            rapport.inchanges.append(compare)
            # S7 : binaire identique mais transcription locale éditée →
            # divergence description-seule, poussable via le PUT de
            # réordonnancement (`_reordonner_files`, local gagne).
            if _transcription_a_propager(
                f.description_externe, fd_match.get("description")
            ):
                rapport.descriptions_divergentes.append(compare)
        elif sha1_nakala_norm and sha1_index.get(sha1_nakala_norm):
            # Modifié : on retrouve l'ancien sha1 côté distant, mais
            # le binaire local en porte un nouveau.
            sha1_index[sha1_nakala_norm].pop(0)
            rapport.modifies.append(compare)
        else:
            # Nouveau : ni sha1_local ni sha1_nakala (s'il existe) n'est
            # côté distant — ce binaire n'est pas encore connu de Nakala.
            rapport.nouveaux.append(compare)

    # Orphelins : entrées distantes restantes après consommation. Chaque
    # élément résiduel des listes par sha1 est un orphelin distinct
    # (préserve les doublons sha1 distants : si 2 fichiers distants
    # partageaient le même sha1 et qu'un seul Fichier ColleC s'y
    # appariait, le 2e ressort en orphelin propre).
    for sha1, fd_list in sha1_index.items():
        for fd in fd_list:
            rapport.orphelins_distants.append(
                FichierOrphelin(sha1=sha1, nom_fichier=fd.get("name") or "")
            )

    return rapport


# ---------------------------------------------------------------------------
# P3+c — Push fichiers (écriture)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PlanPushFichier:
    """Une entrée du `files[]` cible envoyée au `PUT /datas/{id}`.

    Concentre les 3 sources possibles : un Fichier déjà connu de Nakala
    (inchangé, ou inchangé renommé via H7), un fichier uploadé pendant
    le push (nouveau ou modifié), un Fichier Nakala-only sans local.

    L'attribut ``ordre`` (depuis ``Fichier.ordre`` de ColleC) est utilisé
    pour trier le plan avant le PUT — H5 confirme que Nakala préserve
    l'ordre envoyé. Cohérence d'affichage ColleC ↔ Nakala garantie.
    """

    fichier_id: int | None  # None pour Nakala-only et orphelins préservés
    nom_fichier: str
    sha1: str
    # Catégories émises par `_construire_plan` (depuis `RapportComparaison
    # Fichiers`). Le rename gratuit (H7) n'a PAS de catégorie dédiée :
    # un Fichier inchangé dont `nom_fichier` local diffère du nom distant
    # tombe en "inchange" et son nouveau nom est propagé via le `name`
    # du `files[i]` envoyé au PUT.
    categorie: str  # "inchange" | "nouveau" | "modifie" | "nakala_only"
    ordre: int  # rang d'affichage cohérent ColleC ↔ Nakala


@dataclass
class RapportPushFichiers:
    """Résultat d'un ``pousser_fichiers_item``."""

    cote_item: str
    doi: str
    dry_run: bool
    applique: bool = False
    raison: str | None = None  # "aucun_changement" | "orphelins_refuses" | ...
    compare: RapportComparaisonFichiers | None = None
    # Plan d'exécution rendu lisible pour l'utilisateur (dry-run et réel).
    plan: list[PlanPushFichier] = field(default_factory=list)
    # Listes des sha1 effectivement uploadés (vide en dry-run).
    sha1s_uploades: list[str] = field(default_factory=list)
    # Listes des sha1 distants retirés via PUT (= orphelins exclus).
    sha1s_retires: list[str] = field(default_factory=list)
    # Drift detection : le `modDate` distant a-t-il avancé depuis le
    # dernier cache `mettre_en_cache_depot` ? Indicateur consultatif
    # (n'empêche pas le push), aligné sur `RapportPush.derive` de
    # `pousser_item` (P3). Vrai = quelqu'un d'autre a poussé entre
    # notre dernier pull et maintenant — l'utilisateur devrait
    # re-comparer avant de confirmer.
    derive: bool = False


def _construire_plan(
    rapport_cmp: RapportComparaisonFichiers,
) -> list[PlanPushFichier]:
    """Calcule le plan d'exécution (hors uploads) à partir du rapport
    de comparaison. Les entrées `nouveau` et `modifie` portent le
    `sha1_local` (recalculé local) comme sha1 prévisionnel — il sera
    remplacé par le sha1 retourné par `uploader_fichier` au moment de
    l'application réelle.

    Les `orphelins_distants` sont **toujours** exclus du plan : ne pas
    les inclure dans `files[]` cible les retire automatiquement
    (cohérent avec H1). Le garde-fou métier (`retirer_orphelins`
    requis) est appliqué en amont par l'appelant — ce helper ne
    re-vérifie pas.
    """
    plan: list[PlanPushFichier] = []
    for fc in rapport_cmp.inchanges:
        plan.append(
            PlanPushFichier(
                fichier_id=fc.fichier_id,
                nom_fichier=fc.nom_fichier,
                sha1=fc.sha1_local or "",  # garanti non-None côté inchanges
                categorie="inchange",
                ordre=fc.ordre,
            )
        )
    for fc in rapport_cmp.modifies:
        plan.append(
            PlanPushFichier(
                fichier_id=fc.fichier_id,
                nom_fichier=fc.nom_fichier,
                sha1=fc.sha1_local or "",  # sera ré-uploadé
                categorie="modifie",
                ordre=fc.ordre,
            )
        )
    for fc in rapport_cmp.nouveaux:
        plan.append(
            PlanPushFichier(
                fichier_id=fc.fichier_id,
                nom_fichier=fc.nom_fichier,
                sha1=fc.sha1_local or "",  # sera uploadé
                categorie="nouveau",
                ordre=fc.ordre,
            )
        )
    for fc in rapport_cmp.nakala_only_sans_local:
        # Préservés : on les inclut avec leur sha1_nakala connu.
        if fc.sha1_distant:
            plan.append(
                PlanPushFichier(
                    fichier_id=fc.fichier_id,
                    nom_fichier=fc.nom_fichier,
                    sha1=fc.sha1_distant,
                    categorie="nakala_only",
                    ordre=fc.ordre,
                )
            )
    # Tri par `Fichier.ordre` : Nakala respecte l'ordre du `files[]`
    # envoyé (H5 validée). Sans ce tri, le PUT mettrait inchanges en
    # premier puis modifies puis nouveaux puis nakala_only, perdant
    # la cohérence d'affichage entre ColleC et Nakala.
    plan.sort(key=lambda p: p.ordre)
    return plan


def _reordonner_files(
    files_distants: list[dict[str, Any]],
    plan: list[PlanPushFichier],
    uploades_par_fichier: Mapping[int, str],
    descriptions_locales: Mapping[int, str | None] | None = None,
) -> list[dict[str, Any]]:
    """Construit le `files[]` canonique pour le PUT de réordonnancement
    (T2 — palier granulaire) à partir de l'**état distant réel relu**
    après les opérations POST/DELETE, pas du plan ColleC.

    Garantie de sûreté : on réémet **exactement les sha1 réellement
    présents** côté Nakala (un par entrée de `files_distants`), jamais une
    liste reconstruite qui pourrait omettre un fichier (≠ ancien push par
    `PUT files[]` qui droppait silencieusement les omissions, H1). On se
    contente de **réordonner** par `Fichier.ordre` et d'appliquer le nom
    ColleC (renommage gratuit H7) pour les fichiers connus ; un fichier
    distant inconnu du plan est **conservé** (jamais droppé) et placé en
    fin, dans son ordre d'origine.

    ``descriptions_locales`` : map ``fichier_id → description_externe`` (S7).
    Pour chaque entrée, la ``description`` émise est la valeur **locale** si
    l'utilisateur en a une (édition = source de vérité), **sinon** la valeur
    **distante re-lue** est préservée. Règle anti-wipe **indépendante de la
    sonde omit-vs-wipe** : un PUT ne peut jamais effacer une transcription
    distante, que Nakala efface ou préserve les clés ``files[i]`` omises.
    """
    # sha1 → FILE de (ordre, nom ColleC) consommée dans l'ordre du plan.
    # Une file (pas un scalaire) car deux Fichier ColleC peuvent porter le
    # MÊME sha1 (cas archivistique légitime : pages blanches, planches
    # vides) — chaque entrée distante consomme un cran du plan, sans
    # collision. Les nouveaux/modifies portent leur sha1 fraîchement
    # uploadé (le plan ne connaît que le sha1 prévisionnel local).
    descriptions_locales = descriptions_locales or {}
    # sha1 → FILE de (ordre, nom ColleC, fichier_id) consommée dans l'ordre
    # du plan. `fichier_id` sert à retrouver la transcription locale (S7).
    desire: dict[str, deque[tuple[int, str, int | None]]] = defaultdict(deque)
    for entree in plan:
        sha1 = entree.sha1
        if entree.categorie in ("nouveau", "modifie") and entree.fichier_id is not None:
            sha1 = uploades_par_fichier.get(entree.fichier_id, sha1)
        desire[sha1].append((entree.ordre, entree.nom_fichier, entree.fichier_id))

    _FIN = 10**9  # un fichier distant inconnu du plan est conservé, en fin
    # (ordre, index distant, sha1, nom, fichier_id|None). `index distant`
    # permet de retrouver l'entrée distante d'origine (et sa `description`).
    annotes: list[tuple[int, int, str | None, str | None, int | None]] = []
    for i, f in enumerate(files_distants):
        sha1 = f.get("sha1")
        file_attente = desire.get(sha1)
        if file_attente:
            ordre, nom, fid = file_attente.popleft()
            annotes.append((ordre, i, sha1, nom, fid))
        else:
            annotes.append((_FIN, i, sha1, f.get("name"), None))
    annotes.sort(key=lambda t: (t[0], t[1]))

    # S7 — `description` (transcription) par fichier : valeur LOCALE
    # (`description_externe`) si l'utilisateur en a une (édition = source de
    # vérité), SINON on PRÉSERVE la valeur distante re-lue. Anti-wipe,
    # indépendant de la sonde omit-vs-wipe. `embargoed` (non modélisé par
    # ColleC) est préservé tel quel depuis le distant — même principe.
    result: list[dict[str, Any]] = []
    for _, i, s, n, fid in annotes:
        fd = files_distants[i]
        entry: dict[str, Any] = {"sha1": s, "name": n}
        # Transcription locale non vide → gagne (normalisée comme à la
        # détection, cf. `_transcription_a_propager`) ; sinon on PRÉSERVE la
        # distante re-lue (anti-wipe). Un effacement local ne peut donc pas
        # écraser la distante (limite assumée, cf. note de module).
        desc_local = (
            normaliser_transcription(descriptions_locales.get(fid))
            if fid is not None
            else None
        )
        description = desc_local if desc_local else (fd.get("description") or None)
        if description:
            entry["description"] = description
        # `embargoed` : non modélisé par ColleC. Datetime+TZ distant opaque,
        # ré-émis tel quel pour ne pas lever un embargo par omission (H1
        # remplace tout). Toujours présent côté distant pour un fichier réel.
        embargoed = fd.get("embargoed")
        if embargoed:
            entry["embargoed"] = embargoed
        result.append(entry)
    return result


def pousser_fichiers_item(
    db: Any,
    client_lecture: ClientLectureNakala,
    client_ecriture: NakalaEcritureClient,
    item: Item,
    *,
    racines: Mapping[str, Path],
    dry_run: bool = True,
    retirer_orphelins: bool = False,
    forcer_publie: bool = False,
    modifie_par: str | None = None,
) -> RapportPushFichiers:
    """Pousse les fichiers locaux d'un Item vers son dépôt Nakala existant.

    Pipeline :

    1. Comparer (réutilise ``comparer_fichiers_item``).
    2. Garde-fous :
       - ``aucun_changement`` → return early, ``applique=False``.
       - ``orphelins_distants > 0`` et ``not retirer_orphelins`` →
         ``OrphelinsDetectes``.
    3. Construire le plan (``inchanges`` + ``modifies`` + ``nouveaux`` +
       ``nakala_only_sans_local``, les orphelins étant exclus).
    4. Garde-fou H3 : ``len(plan) == 0`` → ``PushImpossible``.
    5. Si ``dry_run`` : return avec le plan, sans écriture distante.
    6. Réel : upload des ``nouveaux + modifies`` via ``uploader_fichier``
       (sha1 capturé).
    7. **Opérations granulaires (T2)** :
       a. ``POST /datas/{id}/files`` pour chaque sha1 uploadé (additif) —
          *avant* toute suppression (évite le 403 « dernier fichier »).
       b. ``DELETE /datas/{id}/files/{sha1}`` pour l'ancien sha1 des
          ``modifies``, les ``orphelins`` (sous flag) et les ``non_actifs``.
       c. **Réordonnancement** : relit l'état distant réel et réémet ces
          sha1 triés par ``Fichier.ordre`` via un ``PUT /datas/{id}``
          (le ``POST`` est LIFO ; le ``PUT`` réémettant la vérité distante
          ne peut rien dropper, ≠ ancien push par ``PUT files[]``).
    8. Met à jour ``Fichier.sha1_nakala`` pour ``modifies + nouveaux``,
       journalise, rafraîchit le cache, commit.

    En cas d'erreur : cleanup ``supprimer_upload`` des seuls uploads **pas
    encore attachés** (les sha1 déjà ``POST``és sont consommés). Les
    écritures DB ne sont commitées qu'**après** les opérations distantes
    réussies. ⚠️ **Atomicité partielle** (T2) : N appels au lieu d'1 → un
    échec mid-parcours peut laisser un état distant partiel (fichiers
    ajoutés mais ordre non fixé, ou anciens non retirés). Non destructif
    (ajout avant suppression). **Reprise** : un re-``comparer`` reclasse les
    fichiers déjà attachés en ``inchange`` (leur contenu est désormais
    distant) et les opérations se rejouent — mais un ancien sha1 non retiré
    peut ressortir en **orphelin distant** (à confirmer via
    ``--retirer-orphelins``). Vérifier le diff avant de re-pousser ; ce
    n'est pas une reprise « transparente ».

    Args:
        retirer_orphelins: requis pour confirmer le retrait silencieux
            de fichiers présents côté Nakala mais absents en local.
            Sans ce flag, lève ``OrphelinsDetectes``.
        forcer_publie: requis pour confirmer une modification de
            ``files[]`` sur un item ``status=published`` côté Nakala.
            Sans ce flag, lève ``DepotPublie``. Cas à risque :
            modifier un fichier publié casse l'intégrité des citations
            externes (DOIs DataCite mintés).
        modifie_par: propagé à ``mettre_en_cache_depot`` (champ
            ``cree_par`` de la ressource cachée) après le PUT réussi.
            Non propagé au format ``files[]`` (Nakala n'a pas de champ
            par-fichier pour l'auteur de la modification).

    Returns:
        ``RapportPushFichiers`` — riche en métadonnées d'exécution
        (plan, sha1s uploadés, raison de no-op…).

    Raises:
        DepotImpossible: ``item.doi_nakala`` est None.
        ComparaisonImpossible: propagé depuis ``comparer_fichiers_item``.
        DepotPublie: item ``status=published`` côté Nakala sans flag
            ``forcer_publie`` (risque de casser des citations externes).
        FichierFantomeDistant: au moins un Fichier ColleC pointe vers
            un ``sha1_nakala`` qui n'est plus côté distant (désynchro
            cache ou push partiellement échoué) — éviterait une 404
            cryptique au PUT.
        BackfillIncomplet: au moins un Fichier ``nakala_only_sans_local``
            n'a pas de ``sha1_nakala`` peuplé — risque de perte
            silencieuse de fichier distant au PUT.
        OrphelinsDetectes: orphelins distants sans flag.
        PushImpossible: ``files_cible == []`` (cas H3).
        ContenuDuplique: le set final contient deux sha1 identiques (Nakala
            refuse les doublons de contenu dans un dépôt — refus pré-vol).
        UploadInvalide: ``uploader_fichier`` retourne une réponse
            inexploitable (sha1 vide / malformé / non-string). Cleanup
            best-effort des uploads précédents avant propagation.
        ReponseLectureInvalide: ``lire_depot`` retourne un non-dict
            (au pull initial ou au refresh post-PUT du cache).
        ErreurNakala: échec du ``lire_depot``, ``uploader_fichier`` ou
            ``modifier_depot`` (propagé).
    """
    if not item.doi_nakala:
        from archives_tool.api.services.nakala_depot import DepotImpossible

        raise DepotImpossible(
            f"Item {item.cote!r} sans doi_nakala — utiliser `deposer` d'abord."
        )

    # 1. Comparer
    rapport_cmp = comparer_fichiers_item(
        db,
        client_lecture,
        item,
        racines=racines,
    )

    rapport = RapportPushFichiers(
        cote_item=item.cote,
        doi=item.doi_nakala,
        dry_run=dry_run,
        compare=rapport_cmp,
    )

    # Drift detection (consultatif, n'empêche pas le push) — symétrie avec
    # `pousser_item` P3. Compare `modDate` distant (capturé par
    # `comparer_fichiers_item`, pas de 2e lire_depot) vs baseline cachée :
    # si quelqu'un a poussé entre notre dernier pull et maintenant, on
    # signale. L'utilisateur peut décider de re-comparer ou de pousser
    # quand même par-dessus.
    from archives_tool.api.services.nakala_depot import _baseline_moddate

    baseline = _baseline_moddate(db, item.doi_nakala)
    distant_mod = rapport_cmp.mod_date_distant
    rapport.derive = bool(baseline and distant_mod and str(distant_mod) > str(baseline))

    # 2. Garde-fous métier
    if rapport_cmp.aucun_changement:
        rapport.raison = "aucun_changement"
        return rapport

    # Ordre des garde-fous (Trou Z passe 14) : DIAGNOSTICS d'abord
    # (problemes a fixer, sans opt-in possible), puis CONSENTS
    # (actions a risque a confirmer via flag).
    #
    # Sans cet ordre, un item publie avec un fantome aurait leve
    # `DepotPublie` en premier - le user aurait passe `--force-published`
    # avant de decouvrir que le vrai probleme etait le fantome.
    # Diagnostic d'abord = un seul aller-retour user.

    # DIAGNOSTIC : sha1_nakala pointant vers du fantome distant.
    # Inclure ce sha1 dans `files[]` ferait planter le PUT en H4
    # (404 sha1 inconnu). Refus loud. Cf. Trou U passe 10.
    if rapport_cmp.fichiers_fantomes:
        raise FichierFantomeDistant(list(rapport_cmp.fichiers_fantomes))

    # DIAGNOSTIC : Fichier `nakala_only_sans_local` sans `sha1_nakala`
    # peuple (legacy pre-P3+a ou backfill echoue) → impossible de
    # reconcilier. Le `_construire_plan` le skipperait silencieusement
    # → au PUT, le fichier distant correspondant serait retire sans
    # avertissement. Refus loud. Cf. Trou J passe 4.
    sans_sha1 = [
        fc for fc in rapport_cmp.nakala_only_sans_local if fc.sha1_distant is None
    ]
    if sans_sha1:
        raise BackfillIncomplet(sans_sha1)

    # CONSENT : item published → opt-in via `forcer_publie` car
    # modifier les fichiers casse les citations externes (DOIs
    # DataCite mintes). Cf. Trou T passe 9.
    statut = rapport_cmp.statut_distant
    if statut == "published" and not forcer_publie:
        raise DepotPublie(item.cote, item.doi_nakala, statut)

    # CONSENT : orphelins distants → opt-in via `retirer_orphelins`.
    if rapport_cmp.orphelins_distants and not retirer_orphelins:
        raise OrphelinsDetectes(list(rapport_cmp.orphelins_distants))

    # 3. Plan d'exécution (hors uploads)
    rapport.plan = _construire_plan(rapport_cmp)

    # 4. Garde-fou : plan vide = on retirerait TOUS les fichiers. Nakala
    # refuse de vider un dépôt (DELETE du dernier fichier → 403, sonde E ;
    # `PUT files=[]` ignoré, H3). On bloque en amont plutôt que d'enchaîner
    # des DELETE jusqu'au 403.
    if not rapport.plan:
        raise PushImpossible(
            f"Item {item.cote!r} : files_cible vide après garde-fous "
            "(tous les fichiers seraient retirés). Nakala refuse un dépôt "
            "sans fichier (403 sur le dernier, H3). Pour vider un dépôt, "
            "utiliser `supprimer_depot` + redéposer."
        )

    # Garde-fou pré-vol : contenu dupliqué. Nakala refuse deux fichiers de
    # même sha1 dans un dépôt (sondé live : POST /datas dup → 422, re-POST
    # → 409). En granulaire, sans ce contrôle l'échec arriverait au 2ᵉ POST,
    # mi-parcours, laissant un état distant partiel. On refuse avant toute
    # mutation. Le sha1 prévisionnel du plan = sha1_local (nouveau/modifie/
    # inchange) ou sha1_distant (nakala_only) — c'est exactement le contenu
    # qui coexistera côté Nakala.
    _par_sha1: dict[str, list[str]] = defaultdict(list)
    for entree in rapport.plan:
        if entree.sha1:
            _par_sha1[entree.sha1].append(entree.nom_fichier)
    _doublons = {s: noms for s, noms in _par_sha1.items() if len(noms) > 1}
    if _doublons:
        raise ContenuDuplique(_doublons)

    # Pré-calcul des sha1 distants retirés au PUT. Deux origines :
    # 1. orphelins distants (sha1 connu de Nakala mais sans Fichier
    #    ColleC apparié, retrait sous `--retirer-orphelins`),
    # 2. Fichier ColleC non-ACTIF (corbeille/remplacé) dont le
    #    `sha1_nakala` matchait un sha1 distant — retrait acté par
    #    l'état du Fichier (cf. Trou O passe 6 : explicite au lieu
    #    de silencieux).
    rapport.sha1s_retires = [o.sha1 for o in rapport_cmp.orphelins_distants] + [
        (nac.sha1_distant or "").strip().lower()
        for nac in rapport_cmp.non_actifs_a_retirer
        if nac.sha1_distant
    ]

    # 5. Dry-run : on ne touche pas au distant.
    if dry_run:
        logger.info(
            "push fichiers dry-run cote=%s doi=%s plan=%d nouveaux=%d "
            "modifies=%d inchanges=%d nakala_only=%d orphelins=%d "
            "non_actifs=%d derive=%s",
            item.cote,
            item.doi_nakala,
            len(rapport.plan),
            len(rapport_cmp.nouveaux),
            len(rapport_cmp.modifies),
            len(rapport_cmp.inchanges),
            len(rapport_cmp.nakala_only_sans_local),
            len(rapport_cmp.orphelins_distants),
            len(rapport_cmp.non_actifs_a_retirer),
            rapport.derive,
        )
        return rapport

    # 6. Réel : upload des nouveaux + modifies.
    logger.info(
        "push fichiers START cote=%s doi=%s plan=%d nouveaux=%d "
        "modifies=%d retraits=%d derive=%s",
        item.cote,
        item.doi_nakala,
        len(rapport.plan),
        len(rapport_cmp.nouveaux),
        len(rapport_cmp.modifies),
        len(rapport.sha1s_retires),
        rapport.derive,
    )
    # Map fichier_id → sha1 fraîchement uploadé, pour mettre à jour
    # `Fichier.sha1_nakala` après le push réussi.
    nouveaux_sha1_par_fichier: dict[int, str] = {}
    sha1s_uploades: list[str] = []
    # sha1 déjà attachés via `POST .../files` : sur échec ultérieur, ils
    # sont consommés (≠ orphelins temp), donc exclus du cleanup
    # `supprimer_upload` (qui ne vise que le stockage temporaire).
    sha1s_postes: set[str] = set()
    from archives_tool.files.paths import resoudre_chemin

    try:
        for fc in list(rapport_cmp.nouveaux) + list(rapport_cmp.modifies):
            if fc.fichier_id is None:
                # Catégories nouveau/modifie ont toujours un fichier_id par
                # construction de `comparer_fichiers_item`. Si on tombe ici,
                # bug du composeur — invariant violé.
                raise IncoherenceFichierORM(
                    f"Fichier {fc.nom_fichier!r} en catégorie "
                    f"nouveau/modifie sans fichier_id — invariant viole."
                )
            # Récupère le Fichier ORM (peut avoir été muté par une autre
            # session entre `comparer` et ici : race condition).
            fichier_orm = db.get(Fichier, fc.fichier_id)
            if fichier_orm is None:
                raise IncoherenceFichierORM(
                    f"Fichier id={fc.fichier_id} ({fc.nom_fichier!r}) "
                    "supprime entre comparer et pousser (race condition)."
                )
            if not (fichier_orm.racine and fichier_orm.chemin_relatif):
                raise IncoherenceFichierORM(
                    f"Fichier id={fc.fichier_id} ({fc.nom_fichier!r}) "
                    "a perdu racine/chemin_relatif entre comparer et "
                    "pousser (race condition ou mutation tierce)."
                )
            chemin = resoudre_chemin(
                racines,
                fichier_orm.racine,
                fichier_orm.chemin_relatif,
            )
            desc = client_ecriture.uploader_fichier(chemin, fc.nom_fichier)
            # Defense en profondeur : valider la reponse avant de
            # l'envoyer au PUT. Sha1 vide / malforme = trou P passe 7.
            sha1_neuf = _valider_sha1_uploade(desc, fc.nom_fichier)
            sha1s_uploades.append(sha1_neuf)
            nouveaux_sha1_par_fichier[fc.fichier_id] = sha1_neuf
            logger.debug(
                "push fichiers upload OK nom=%s sha1=%s…",
                fc.nom_fichier,
                sha1_neuf[:12],
            )

        # 7a. POST additifs (T2) : on ATTACHE les nouveaux + modifies via
        # `POST .../files` AVANT toute suppression — si tous les anciens
        # fichiers sont retirés, ajouter d'abord évite le 403 « dernier
        # fichier » (Nakala refuse un dépôt à 0 fichier, sonde E). On itère
        # la map des sha1 uploadés (ordre d'insertion = nouveaux puis
        # modifies, cf. boucle 6a).
        for sha1_neuf in nouveaux_sha1_par_fichier.values():
            client_ecriture.ajouter_fichier(item.doi_nakala, sha1_neuf)
            sha1s_postes.add(sha1_neuf)
            logger.debug("push fichiers POST add sha1=%s…", sha1_neuf[:12])

        # 7b. DELETE ciblés (T2) par sha1 (= fileIdentifier, sonde B) :
        # ancien sha1 des modifies, puis orphelins (sous flag), puis
        # Fichier non-ACTIF (corbeille/remplacé).
        for fc in rapport_cmp.modifies:
            if fc.sha1_distant:
                client_ecriture.supprimer_fichier_donnee(
                    item.doi_nakala,
                    fc.sha1_distant,
                )
        if retirer_orphelins:
            for orph in rapport_cmp.orphelins_distants:
                client_ecriture.supprimer_fichier_donnee(item.doi_nakala, orph.sha1)
        for nac in rapport_cmp.non_actifs_a_retirer:
            if nac.sha1_distant:
                client_ecriture.supprimer_fichier_donnee(
                    item.doi_nakala,
                    nac.sha1_distant,
                )

        # 7c. Réordonnancement (T2) : relit l'état distant RÉEL après les
        # mutations et réémet exactement ces sha1, triés par `Fichier.ordre`
        # (le POST est LIFO et ne contrôle pas l'ordre, sonde C). Le PUT
        # réémettant la vérité distante ne peut rien dropper (≠ ancien push).
        apres_ops = _valider_depot_lu(
            client_lecture.lire_depot(item.doi_nakala),
            item.doi_nakala,
        )
        files_cible = _reordonner_files(
            apres_ops.get("files") or [],
            rapport.plan,
            nouveaux_sha1_par_fichier,
            {f.id: f.description_externe for f in item.fichiers},
        )
        client_ecriture.modifier_depot(item.doi_nakala, files=files_cible)
        logger.info(
            "push fichiers granulaire OK cote=%s doi=%s ajouts=%d "
            "suppressions=%d files_final=%d",
            item.cote,
            item.doi_nakala,
            len(sha1s_postes),
            len(rapport.sha1s_retires) + len(rapport_cmp.modifies),
            len(files_cible),
        )

    except Exception:
        # Cleanup best-effort : seuls les uploads PAS encore attachés
        # (`POST .../files`) sont des orphelins du stockage temporaire.
        # Les sha1 déjà POSTés sont consommés/attachés → `supprimer_upload`
        # échouerait et ne les retirerait pas du dépôt (état partiel — la
        # reprise idempotente réconcilie, cf. backlog T2 piège atomicité).
        non_attaches = [s for s in sha1s_uploades if s not in sha1s_postes]
        logger.warning(
            "push fichiers ECHEC cote=%s doi=%s uploads=%d attaches=%d "
            "cleanup_temp=%d (etat distant possiblement partiel)",
            item.cote,
            item.doi_nakala,
            len(sha1s_uploades),
            len(sha1s_postes),
            len(non_attaches),
        )
        for sha1 in non_attaches:
            try:
                client_ecriture.supprimer_upload(sha1)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "push fichiers cleanup KO sha1=%s… : %s",
                    sha1[:12],
                    exc,
                )
        raise

    rapport.sha1s_uploades = sha1s_uploades

    # 8. Met à jour Fichier.sha1_nakala pour modifies + nouveaux.
    # Re-caracterisation binaire (passe 25, dette signalee passe 12) :
    # recalcule hash_sha256 (SHA-256 distinct du sha1 Nakala) et
    # taille_octets pour les fichiers dont le binaire a change.
    # `format`/`largeur_px`/`hauteur_px` (PIL) restent obsoletes — V2+
    # avec calcul asynchrone si dimensions deviennent un blocage UX.
    # Pose `modifie_le` pour tracer la mutation et incrémente `version`
    # (sans verrou optimiste actif sur Fichier — cf. dette signalee
    # CLAUDE.md, mais on respecte le pattern).
    #
    # Plusieurs champs dépendent du sha — sans propagation, désync
    # silencieuse à mille endroits :
    #
    # - **Trou V** (passe 11) : `iiif_url_nakala` contient le sha dans
    #   son chemin (`/iiif/<doi>/<sha>/info.json`). Recale via
    #   `remplacer_sha` qui preserve scheme/host/DOI/endpoint/suffixe.
    # - **Trou W** (passe 12) : `metadonnees["sha1"]` est ecrit en miroir
    #   par `materialiser_fichiers_nakala` (rapatrier) en compat retro
    #   pour les consommateurs qui le lisaient la (exports, scripts
    #   ad-hoc). Apres push, sans propagation, `sha1_nakala`
    #   (canonique) et `metadonnees["sha1"]` (miroir) divergent. Sync
    #   defensif si la cle existe (sinon on ne l'invente pas).
    # - **Trou X** (passe 12) : `derive_genere` + `apercu_chemin` +
    #   `vignette_chemin` + `dzi_chemin` sont les derives LOCAUX du
    #   binaire. Le binaire a change (categorie `modifie`), donc les
    #   derives generes precedemment correspondent a l'ancien
    #   contenu → vignette desynchro affichee dans l'UI. Pattern de
    #   `renamer/execution._invalider_derives` (deja teste).
    from archives_tool.files.nakala import remplacer_sha
    from archives_tool.files.paths import hash_sha256, resoudre_chemin as _rc

    maintenant = datetime.now()
    for fichier_id, sha1_neuf in nouveaux_sha1_par_fichier.items():
        fichier = db.get(Fichier, fichier_id)
        if fichier is not None:
            fichier.sha1_nakala = sha1_neuf
            if fichier.iiif_url_nakala:
                fichier.iiif_url_nakala = remplacer_sha(
                    fichier.iiif_url_nakala,
                    sha1_neuf,
                )
            # Re-caracterisation binaire (passe 25, dette pass 12)
            # Recalcule sur le chemin local actuel : hash_sha256 +
            # taille. Defense en profondeur : si le chemin n'est plus
            # resolvable (binaire deplace entre upload et commit),
            # on swallow et garde les valeurs precedentes (legerement
            # obsoletes mais pas critique - le sha1_nakala canonique
            # est correct).
            if fichier.racine and fichier.chemin_relatif:
                try:
                    chemin_local = _rc(
                        racines,
                        fichier.racine,
                        fichier.chemin_relatif,
                    )
                    if chemin_local.is_file():
                        fichier.hash_sha256 = hash_sha256(chemin_local)
                        fichier.taille_octets = chemin_local.stat().st_size
                except (KeyError, ValueError, OSError):
                    pass
            # Trou W : metadonnees["sha1"] miroir
            if isinstance(fichier.metadonnees, dict) and "sha1" in fichier.metadonnees:
                # SQLAlchemy ne detecte pas les mutations in-place sur JSON :
                # copier + reassigner pour declencher le flush.
                meta = dict(fichier.metadonnees)
                meta["sha1"] = sha1_neuf
                fichier.metadonnees = meta
            # Trou X : invalider les derives locaux du binaire
            if fichier.derive_genere:
                fichier.derive_genere = False
            if fichier.apercu_chemin is not None:
                fichier.apercu_chemin = None
            if fichier.vignette_chemin is not None:
                fichier.vignette_chemin = None
            if fichier.dzi_chemin is not None:
                fichier.dzi_chemin = None
            fichier.modifie_le = maintenant
            fichier.version = (fichier.version or 1) + 1

    # 9. Journal `OperationPushNakala` (passe 24, dette principe
    # directeur n°4 bouclee) : snapshot avant/apres + sha1 uploades
    # /retires. Insertion DANS la meme transaction que les mutations
    # ci-dessus → atomique avec le commit final.
    #
    # On determine `fonds_cote` defensivement : si l'Item est detaché
    # de sa session ou si `item.fonds` n'a pas ete eager-loaded, on
    # met None plutot que de planter (l'audit fonctionne sans le
    # contexte fonds, juste moins lisible).
    from archives_tool.api.services.operations_push_nakala import (
        journaliser_push_fichiers,
        nouveau_batch_id,
    )

    try:
        fonds_cote_journal = item.fonds.cote if item.fonds else None
    except Exception:  # noqa: BLE001 — defensif sur session detachée
        fonds_cote_journal = None
    journaliser_push_fichiers(
        db,
        batch_id=nouveau_batch_id(),
        cote_item=item.cote,
        fonds_cote=fonds_cote_journal,
        doi=item.doi_nakala,
        snapshot_avant=rapport_cmp.files_distants_snapshot,
        snapshot_apres=files_cible,
        sha1s_uploades=sha1s_uploades,
        sha1s_retires=list(rapport.sha1s_retires),
        execute_par=modifie_par,
    )

    # 10. Cache invalidation : rafraichir `RessourceExterne.metadonnees
    # _brutes` + `LienExterneItem.recupere_le` pour que les autres
    # consommateurs (route web, autres CLI) ne lisent pas un cache stale
    # apres le PUT. Pattern aligne sur `pousser_item` (P3).
    from archives_tool.api.services.nakala import mettre_en_cache_depot

    brut2 = _valider_depot_lu(
        client_lecture.lire_depot(item.doi_nakala),
        item.doi_nakala,
    )
    mettre_en_cache_depot(db, mapper_depot(brut2), brut2, cree_par=modifie_par)

    db.commit()
    logger.info(
        "push fichiers COMMIT cote=%s doi=%s uploades=%d retires=%d",
        item.cote,
        item.doi_nakala,
        len(sha1s_uploades),
        len(rapport.sha1s_retires),
    )

    rapport.applique = True
    return rapport
