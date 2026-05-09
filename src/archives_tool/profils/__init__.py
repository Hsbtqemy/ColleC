"""Profils d'import : schéma Pydantic et loader YAML."""

from .generateur import analyser_tableur, generer_squelette
from .loader import ProfilInvalide, ProfilObsoleteV1, charger_profil
from .schema import (
    CollectionMiroirProfil,
    DecompositionCote,
    DecompositionType,
    FondsProfil,
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
    "FondsProfil",
    "CollectionMiroirProfil",
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
    "ProfilObsoleteV1",
    "generer_squelette",
    "analyser_tableur",
]
