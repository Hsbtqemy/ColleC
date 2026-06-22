"""Ingestion remote-first depuis ShareDocs (Chantier 1, tranche 2).

Télécharge des fichiers d'un partage WebDAV ShareDocs (via
``ClientShareDocs``) et les matérialise en ``Fichier`` ColleC rattachés à un
``Item``, sous une **racine locale configurée**. Le binaire devient un
intrant local normal (décision « download → racine » de la roadmap, cf.
`docs/developpeurs/roadmap.md` § Chantier 1) : la recherche/indexation reste
possible hors-source.

Garde-fous alignés sur le projet :

- **Dry-run par défaut** (principe directeur n°3) : aperçu **fidèle** du plan
  sans aucun téléchargement ni écriture (disque + DB).
- **Idempotent / reprise auto-réparante** : un fichier déjà rattaché (même
  racine + chemin) est sauté ; un binaire déjà présent sur disque **sans
  pendant en base** (import précédent interrompu) est **adopté** — jamais
  re-téléchargé ni écrasé. Évite l'orphelin disque définitif.
- **Chemin sûr** : la cible passe par ``resoudre_chemin`` (rejette `..`,
  normalise NFC) ; nom NFC ; collisions de basename **intra-lot** détectées.
- **Écriture atomique** (temp + ``replace``) : pas de fichier partiel piégé.
- **Succès partiel** : un échec sur un fichier — **réseau OU disque** — est
  consigné et n'interrompt pas le lot.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from archives_tool.external.sharedocs import ClientShareDocs, ErreurShareDocs
from archives_tool.files.paths import hash_sha256, normaliser_nfc, resoudre_chemin
from archives_tool.models import Fichier, Item

logger = logging.getLogger(__name__)

#: Hook de progression optionnel : appelé **au début** du traitement de
#: chaque fichier avec ``(index_1based, total, nom_fichier)``. Sert à la
#: tâche de fond (barre de progression) — voir ``sharedocs_jobs``. Aucun
#: effet sur la sémantique d'import (lecture seule du point de vue du hook).
ProgressImport = Callable[[int, int, str], None]

#: Sonde d'annulation coopérative optionnelle : interrogée **avant** chaque
#: fichier. Si elle renvoie True, la boucle s'arrête proprement (les fichiers
#: déjà importés sont conservés et commités). On ne coupe jamais un
#: téléchargement en cours — l'arrêt prend effet à la fin du fichier courant.
SondeAnnulation = Callable[[], bool]


class RacineCibleInconnue(Exception):
    """La racine logique cible n'est pas déclarée dans la config locale."""


@dataclass
class FichierImporte:
    """Sort d'un fichier dans le rapport d'ingestion.

    ``retenu`` : True s'il a été importé / rattaché (ou le serait en dry-run) ;
    False s'il a été sauté / en échec. ``raison`` :

    - retenu=True : ``None`` (téléchargé) | ``rattache_disque`` (binaire déjà
      présent sur disque sans pendant en base → adopté, pas re-téléchargé) ;
    - retenu=False : ``deja_en_base`` | ``collision_nom`` (même basename qu'un
      autre fichier du lot pour cet item) | ``nom_invalide`` |
      ``chemin_invalide`` | ``echec_telechargement`` | ``echec_ecriture``."""

    chemin_distant: str
    nom_fichier: str
    chemin_relatif: str
    retenu: bool
    raison: str | None = None
    taille: int | None = None


@dataclass
class RapportImportShareDocs:
    """Résultat d'un ``importer_depuis_sharedocs``."""

    cote_item: str
    racine_cible: str
    dry_run: bool
    fichiers: list[FichierImporte] = field(default_factory=list)

    @property
    def nb_retenus(self) -> int:
        return sum(1 for f in self.fichiers if f.retenu)

    @property
    def nb_sautes(self) -> int:
        return sum(1 for f in self.fichiers if not f.retenu)


def _ecrire_atomique(cible: Path, data: bytes) -> None:
    """Écrit ``data`` dans ``cible`` de façon atomique (temp + ``replace``).

    Évite un fichier **partiel** à ``cible`` en cas d'interruption (disque
    plein, process tué) — un partiel serait ensuite piégé par la détection
    « déjà sur disque » au re-run. Sur erreur, le temporaire est nettoyé et
    l'``OSError`` propagée (gérée par fichier dans la boucle d'import)."""
    cible.parent.mkdir(parents=True, exist_ok=True)
    tmp = cible.with_name(cible.name + ".colstmp")
    try:
        tmp.write_bytes(data)
        tmp.replace(cible)  # atomique intra-volume
    except OSError:
        tmp.unlink(missing_ok=True)
        raise


def importer_depuis_sharedocs(
    db: Any,
    client: ClientShareDocs,
    chemins_distants: Sequence[str],
    item: Item,
    *,
    racine_cible: str,
    racines: Mapping[str, Path],
    dry_run: bool = True,
    importe_par: str | None = None,
    on_progress: ProgressImport | None = None,
    should_cancel: SondeAnnulation | None = None,
) -> RapportImportShareDocs:
    """Importe les ``chemins_distants`` (ShareDocs) en ``Fichier`` de ``item``.

    Chaque fichier est téléchargé puis écrit sous
    ``<racine_cible>/<cote_item>/<nom_fichier>`` — chemin relatif namespacé
    par item (anti-collision **inter-items** ; deux fichiers distants de même
    basename dans un lot sont signalés ``collision_nom``, pas écrasés). Un
    ``Fichier`` est créé ; un binaire déjà présent sur disque est adopté
    (cf. docstring du module). Voir ``RapportImportShareDocs`` pour le détail
    par fichier (``retenu`` / ``raison``).

    Raises:
        RacineCibleInconnue: ``racine_cible`` absente de ``racines``.
    """
    if racine_cible not in racines:
        raise RacineCibleInconnue(
            f"Racine cible {racine_cible!r} inconnue. "
            f"Racines configurées : {', '.join(sorted(racines)) or '(aucune)'}."
        )

    rapport = RapportImportShareDocs(
        cote_item=item.cote,
        racine_cible=racine_cible,
        dry_run=dry_run,
    )
    # Index des fichiers déjà rattachés (idempotence) + ordre courant max.
    deja_en_base = {(f.racine, f.chemin_relatif) for f in item.fichiers}
    ordre_courant = max((f.ordre for f in item.fichiers), default=0)
    cote_nfc = normaliser_nfc(item.cote)
    # Chemins relatifs déjà traités DANS ce lot — distingue une collision
    # intra-lot (deux fichiers distants de même basename → même cible) d'un
    # vrai « déjà en base ». Sans ça, le 2e serait silencieusement perdu.
    vus_ce_lot: set[str] = set()

    def _noter(nom, rel, retenu, raison=None, taille=None) -> None:
        rapport.fichiers.append(
            FichierImporte(
                chemin, nom, rel, retenu=retenu, raison=raison, taille=taille
            )
        )

    a_persister = False
    total = len(chemins_distants)
    for index, chemin in enumerate(chemins_distants, start=1):
        # Annulation coopérative : vérifiée AVANT de toucher au fichier
        # suivant. Les fichiers déjà traités restent (commit plus bas).
        if should_cancel is not None and should_cancel():
            break
        # Hook de progression (tâche de fond) : signalé AVANT le
        # téléchargement du fichier courant — la barre montre « fichier N
        # en cours », ce qui est le moment le plus long (download réseau).
        if on_progress is not None:
            on_progress(index, total, chemin.rsplit("/", 1)[-1])
        nom = normaliser_nfc(chemin.rsplit("/", 1)[-1])
        if not nom:  # chemin distant finissant par "/" → basename vide
            _noter(nom, "", retenu=False, raison="nom_invalide")
            continue
        chemin_relatif = f"{cote_nfc}/{nom}"
        # Cible absolue traversal-safe. `..` dans le nom / racine inconnue →
        # consigné, le lot continue (jamais de traversal effectif).
        try:
            cible = resoudre_chemin(racines, racine_cible, chemin_relatif)
        except (KeyError, ValueError):
            _noter(nom, chemin_relatif, retenu=False, raison="chemin_invalide")
            continue

        # `vus_ce_lot` AVANT `deja_en_base` : une collision intra-lot prime
        # (sinon, après import du 1er, le 2e de même basename tomberait en
        # `deja_en_base` au réel mais `collision_nom` en dry-run → divergence).
        if chemin_relatif in vus_ce_lot:
            _noter(nom, chemin_relatif, retenu=False, raison="collision_nom")
            continue
        if (racine_cible, chemin_relatif) in deja_en_base:
            _noter(nom, chemin_relatif, retenu=False, raison="deja_en_base")
            continue
        vus_ce_lot.add(chemin_relatif)

        sur_disque = cible.exists()
        if dry_run:
            # Aperçu honnête : un binaire déjà présent serait *rattaché*
            # (adopté), pas re-téléchargé.
            _noter(
                nom,
                chemin_relatif,
                retenu=True,
                raison="rattache_disque" if sur_disque else None,
            )
            continue

        # Réel. Échec réseau OU disque → consigné par fichier, le lot
        # continue (succès partiel pour TOUS les modes d'échec).
        try:
            if sur_disque:
                # Reprise auto-réparante : un binaire présent sans pendant en
                # base (import précédent interrompu, ou fichier pré-placé) est
                # *adopté* tel quel — pas de re-téléchargement, pas d'écrasement.
                taille = cible.stat().st_size
                raison = "rattache_disque"
            else:
                data = client.telecharger(chemin)
                _ecrire_atomique(cible, data)
                taille = len(data)
                raison = None
            hsha = hash_sha256(cible)
        except ErreurShareDocs as exc:
            logger.warning(
                "ShareDocs import : échec téléchargement %s : %s", chemin, exc
            )
            _noter(nom, chemin_relatif, retenu=False, raison="echec_telechargement")
            continue
        except OSError as exc:
            logger.warning("ShareDocs import : échec écriture %s : %s", chemin, exc)
            _noter(nom, chemin_relatif, retenu=False, raison="echec_ecriture")
            continue

        ordre_courant += 1
        db.add(
            Fichier(
                item_id=item.id,
                racine=racine_cible,
                chemin_relatif=chemin_relatif,
                nom_fichier=nom,
                hash_sha256=hsha,
                taille_octets=taille,
                ordre=ordre_courant,
                ajoute_par=importe_par,
            )
        )
        deja_en_base.add((racine_cible, chemin_relatif))
        a_persister = True
        _noter(nom, chemin_relatif, retenu=True, raison=raison, taille=taille)

    if a_persister:
        db.commit()
        logger.info(
            "ShareDocs import COMMIT cote=%s racine=%s retenus=%d sautes=%d",
            item.cote,
            racine_cible,
            rapport.nb_retenus,
            rapport.nb_sautes,
        )
    return rapport
