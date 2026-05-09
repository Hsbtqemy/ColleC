"""Modèles SQLAlchemy de l'application.

Découpage par domaine ; les imports ci-dessous enregistrent toutes les
classes sur `Base.metadata` pour Alembic et `create_all`.
"""

from __future__ import annotations

from .base import Base, TracabiliteMixin
from .collaborateur import CollaborateurCollection
from .collection import Collection, valider_hierarchie
from .enums import (
    LIBELLES_ROLE,
    EtatCatalogage,
    EtatFichier,
    PhaseChantier,
    RoleCollaborateur,
    StatutOperation,
    TypeChamp,
    TypeOperationFichier,
    TypePage,
    TypeRelationExterne,
)
from .externe import LienExterneItem, RessourceExterne, SourceExterne
from .fichier import Fichier
from .item import Item
from .journal import ModificationItem, OperationFichier, OperationImport
from .preferences import PreferencesAffichage
from .profil import ChampPersonnalise, ProfilImport, ValeurControlee, Vocabulaire
from .session_import import SessionImport

__all__ = [
    "Base",
    "TracabiliteMixin",
    "Collection",
    "CollaborateurCollection",
    "valider_hierarchie",
    "Item",
    "Fichier",
    "ProfilImport",
    "ChampPersonnalise",
    "Vocabulaire",
    "ValeurControlee",
    "OperationFichier",
    "ModificationItem",
    "OperationImport",
    "PreferencesAffichage",
    "SessionImport",
    "SourceExterne",
    "RessourceExterne",
    "LienExterneItem",
    "EtatCatalogage",
    "EtatFichier",
    "PhaseChantier",
    "RoleCollaborateur",
    "LIBELLES_ROLE",
    "TypePage",
    "TypeOperationFichier",
    "StatutOperation",
    "TypeChamp",
    "TypeRelationExterne",
]
