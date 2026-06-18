"""Ingestion remote-first depuis ShareDocs (Chantier 1, tranche 2).

Télécharge des fichiers d'un partage WebDAV ShareDocs (via
``ClientShareDocs``) et les matérialise en ``Fichier`` ColleC rattachés à un
``Item``, sous une **racine locale configurée**. Le binaire devient un
intrant local normal (décision « download → racine » de la roadmap, cf.
`docs/developpeurs/roadmap.md` § Chantier 1) : la recherche/indexation reste
possible hors-source.

Garde-fous alignés sur le projet :

- **Dry-run par défaut** (principe directeur n°3) : aperçu du plan sans aucun
  téléchargement ni écriture (disque + DB).
- **Idempotent** : un fichier déjà rattaché (même racine + chemin) ou déjà
  présent sur disque est **sauté** (jamais d'écrasement silencieux).
- **Chemin sûr** : la cible passe par ``resoudre_chemin`` (rejette `..`,
  normalise NFC) ; le nom de fichier est normalisé NFC.
- **Succès partiel** : un échec de téléchargement sur un fichier est
  consigné et n'interrompt pas le lot.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from archives_tool.external.sharedocs import ClientShareDocs, ErreurShareDocs
from archives_tool.files.paths import hash_sha256, normaliser_nfc, resoudre_chemin
from archives_tool.models import Fichier, Item

logger = logging.getLogger(__name__)


class RacineCibleInconnue(Exception):
    """La racine logique cible n'est pas déclarée dans la config locale."""


@dataclass
class FichierImporte:
    """Sort d'un fichier dans le rapport d'ingestion.

    ``retenu`` : True s'il a été importé (ou le serait en dry-run) ; False
    s'il a été sauté. ``raison`` précise le saut / l'échec
    (``deja_en_base`` | ``deja_sur_disque`` | ``echec_telechargement``)."""

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
) -> RapportImportShareDocs:
    """Importe les ``chemins_distants`` (ShareDocs) en ``Fichier`` de ``item``.

    Chaque fichier est téléchargé puis écrit sous
    ``<racine_cible>/<cote_item>/<nom_fichier>`` (chemin relatif
    namespacé par item, anti-collision), et un ``Fichier`` est créé.

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

    a_persister = False
    for chemin in chemins_distants:
        nom = normaliser_nfc(chemin.rsplit("/", 1)[-1])
        chemin_relatif = f"{cote_nfc}/{nom}"
        # Cible absolue traversal-safe (lève ValueError/KeyError sur `..` ou
        # racine inconnue — racine déjà validée plus haut).
        cible = resoudre_chemin(racines, racine_cible, chemin_relatif)

        if (racine_cible, chemin_relatif) in deja_en_base:
            rapport.fichiers.append(
                FichierImporte(
                    chemin,
                    nom,
                    chemin_relatif,
                    retenu=False,
                    raison="deja_en_base",
                )
            )
            continue
        if cible.exists():
            rapport.fichiers.append(
                FichierImporte(
                    chemin,
                    nom,
                    chemin_relatif,
                    retenu=False,
                    raison="deja_sur_disque",
                )
            )
            continue
        if dry_run:
            rapport.fichiers.append(
                FichierImporte(
                    chemin,
                    nom,
                    chemin_relatif,
                    retenu=True,
                )
            )
            continue

        # Réel : télécharger → écrire → hash → Fichier. Un échec réseau sur
        # un fichier est consigné, le lot continue (succès partiel).
        try:
            data = client.telecharger(chemin)
        except ErreurShareDocs as exc:
            logger.warning(
                "ShareDocs import : échec téléchargement %s : %s",
                chemin,
                exc,
            )
            rapport.fichiers.append(
                FichierImporte(
                    chemin,
                    nom,
                    chemin_relatif,
                    retenu=False,
                    raison="echec_telechargement",
                )
            )
            continue

        cible.parent.mkdir(parents=True, exist_ok=True)
        cible.write_bytes(data)
        ordre_courant += 1
        db.add(
            Fichier(
                item_id=item.id,
                racine=racine_cible,
                chemin_relatif=chemin_relatif,
                nom_fichier=nom,
                hash_sha256=hash_sha256(cible),
                taille_octets=len(data),
                ordre=ordre_courant,
                ajoute_par=importe_par,
                modifie_le=datetime.now(),
            )
        )
        deja_en_base.add((racine_cible, chemin_relatif))
        a_persister = True
        rapport.fichiers.append(
            FichierImporte(
                chemin,
                nom,
                chemin_relatif,
                retenu=True,
                taille=len(data),
            )
        )

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
