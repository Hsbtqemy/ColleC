"""Contrôles de cohérence base/disque (lecture seule).

Quatre contrôles V1 :
- fichiers référencés en base mais absents du disque ;
- fichiers présents sur disque mais non référencés en base ;
- items sans aucun fichier rattaché ;
- groupes de fichiers partageant un même `hash_sha256`.

Les contrôles n'écrivent jamais en base ni sur disque.
"""

from __future__ import annotations

from .controles import (
    CODES_CONTROLES,
    controler_doublons_par_hash,
    controler_fichiers_manquants_disque,
    controler_items_sans_fichier,
    controler_orphelins_disque,
    controler_tout,
)
from .rapport import (
    AnomalieFichierManquant,
    AnomalieItemVide,
    AnomalieOrphelinDisque,
    GroupeDoublons,
    RapportControle,
    RapportQa,
)

__all__ = [
    "CODES_CONTROLES",
    "controler_doublons_par_hash",
    "controler_fichiers_manquants_disque",
    "controler_items_sans_fichier",
    "controler_orphelins_disque",
    "controler_tout",
    "AnomalieFichierManquant",
    "AnomalieItemVide",
    "AnomalieOrphelinDisque",
    "GroupeDoublons",
    "RapportControle",
    "RapportQa",
]
