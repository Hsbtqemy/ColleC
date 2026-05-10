"""Contrôles de cohérence d'une base archives-tool (lecture seule).

Quatre familles de contrôles :
- `invariants` : INV1, INV2, INV4, INV6 sur le modèle Fonds/Collection/Item.
- `fichiers` : présence disque, hash, items sans fichier.
- `metadonnees` : cote, titre, date EDTF, année plausible.
- `cross` : cohérence cross-entités (cotes uniques, fonds non vides).

Les contrôles n'écrivent jamais en base ni sur disque.
"""

from __future__ import annotations

from ._commun import (
    Exemple,
    PerimetreControle,
    RapportQa,
    ResultatControle,
    Severite,
)
from .cross import (
    controler_cross_cote_dupliquee_fonds,
    controler_cross_fonds_vide,
)
from .fichiers import (
    controler_file_hash_duplique,
    controler_file_hash_manquant,
    controler_file_item_vide,
    controler_file_missing,
)
from .formatteurs import formatter_rapport_json, formatter_rapport_text
from .invariants import (
    controler_inv1_miroir_unique,
    controler_inv2_miroir_avec_fonds,
    controler_inv4_item_avec_fonds,
    controler_inv6_item_dans_miroir,
)
from .metadonnees import (
    controler_meta_annee_implausible,
    controler_meta_cote_invalide,
    controler_meta_date_invalide,
    controler_meta_titre_vide,
)
from .orchestrateur import (
    CONTROLES_DISPONIBLES,
    VERSION_QA,
    composer_perimetre,
    executer_controles,
)

__all__ = [
    # commun
    "Severite",
    "Exemple",
    "ResultatControle",
    "PerimetreControle",
    "RapportQa",
    # orchestrateur
    "VERSION_QA",
    "CONTROLES_DISPONIBLES",
    "composer_perimetre",
    "executer_controles",
    # invariants
    "controler_inv1_miroir_unique",
    "controler_inv2_miroir_avec_fonds",
    "controler_inv4_item_avec_fonds",
    "controler_inv6_item_dans_miroir",
    # fichiers
    "controler_file_missing",
    "controler_file_item_vide",
    "controler_file_hash_duplique",
    "controler_file_hash_manquant",
    # metadonnees
    "controler_meta_cote_invalide",
    "controler_meta_titre_vide",
    "controler_meta_date_invalide",
    "controler_meta_annee_implausible",
    # cross
    "controler_cross_cote_dupliquee_fonds",
    "controler_cross_fonds_vide",
    # formatteurs
    "formatter_rapport_json",
    "formatter_rapport_text",
]
