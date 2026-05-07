"""Génération de dérivés (vignettes, aperçus) pour les fichiers.

Pillow est utilisé pour les formats raster ; PyMuPDF (fitz) pour
extraire la première page d'un PDF. Sortie : JPEG qualité 85 par défaut.

Le module est idempotent : un fichier dont `derive_genere = True`
est ignoré sauf si `--force` est demandé.
"""

from __future__ import annotations

from .chemins import chemin_derive
from .generateur import (
    TAILLES_PAR_DEFAUT,
    generer_derives,
    generer_derives_pour_fichier,
    nettoyer_derives,
)
from .rapport import RapportDerivation, ResultatDerive, StatutDerive

__all__ = [
    "chemin_derive",
    "TAILLES_PAR_DEFAUT",
    "generer_derives",
    "generer_derives_pour_fichier",
    "nettoyer_derives",
    "RapportDerivation",
    "ResultatDerive",
    "StatutDerive",
]
