"""Profils d'import : schéma Pydantic et loader YAML."""

from .generateur import analyser_tableur, generer_squelette
from .loader import ProfilInvalide, charger_profil
from .schema import (
    CollectionProfil,
    DecompositionCote,
    DecompositionType,
    MappingAgrege,
    MappingChamp,
    MappingSimple,
    MappingTransforme,
    Profil,
    ResolutionFichiers,
    TableurSource,
)

__all__ = [
    "Profil",
    "CollectionProfil",
    "TableurSource",
    "MappingChamp",
    "MappingSimple",
    "MappingTransforme",
    "MappingAgrege",
    "ResolutionFichiers",
    "DecompositionCote",
    "DecompositionType",
    "charger_profil",
    "ProfilInvalide",
    "generer_squelette",
    "analyser_tableur",
]
