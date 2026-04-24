"""Profils d'import : schéma Pydantic et loader YAML."""

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
]
