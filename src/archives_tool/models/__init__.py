"""Modèles SQLAlchemy de l'application.

Découpage par domaine ; les imports ci-dessous enregistrent toutes les
classes sur `Base.metadata` pour Alembic et `create_all`.
"""

from __future__ import annotations

from .base import Base, TracabiliteMixin
from .collection import Collection
from .enums import (
    EtatCatalogage,
    EtatFichier,
    StatutOperation,
    TypeChamp,
    TypeOperationFichier,
    TypePage,
    TypeRelationExterne,
)
from .externe import LienExterneItem, RessourceExterne, SourceExterne
from .fichier import Fichier
from .item import Item
from .journal import ModificationItem, OperationFichier, SessionEdition
from .profil import ChampPersonnalise, ProfilImport, ValeurControlee, Vocabulaire
from .utilisateur import Utilisateur

__all__ = [
    "Base",
    "TracabiliteMixin",
    "Collection",
    "Item",
    "Fichier",
    "Utilisateur",
    "ProfilImport",
    "ChampPersonnalise",
    "Vocabulaire",
    "ValeurControlee",
    "OperationFichier",
    "ModificationItem",
    "SessionEdition",
    "SourceExterne",
    "RessourceExterne",
    "LienExterneItem",
    "EtatCatalogage",
    "EtatFichier",
    "TypePage",
    "TypeOperationFichier",
    "StatutOperation",
    "TypeChamp",
    "TypeRelationExterne",
]
