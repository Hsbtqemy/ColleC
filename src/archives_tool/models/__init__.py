"""Modèles SQLAlchemy de l'application.

Découpage par domaine ; les imports ci-dessous enregistrent toutes les
classes sur `Base.metadata` pour Alembic et `create_all`.
"""

from __future__ import annotations

from .base import Base, TracabiliteMixin
from .collaborateur import CollaborateurCollection
from .collaborateur_fonds import CollaborateurFonds
from .collection import Collection
from .enums import (
    LIBELLES_PHASE,
    LIBELLES_ROLE,
    EtatCatalogage,
    EtatFichier,
    PhaseChantier,
    RoleCollaborateur,
    StatutOperation,
    TypeChamp,
    TypeCollection,
    TypeOperationFichier,
    TypePage,
    TypeRelationExterne,
)
from .externe import LienExterneItem, RessourceExterne, SourceExterne
from .fichier import Fichier
from .fonds import Fonds
from .item import Item
from .item_collection import ItemCollection
from .journal import ModificationItem, OperationFichier, OperationImport
from .preferences import PreferencesAffichage
from .profil import ChampPersonnalise, ProfilImport, ValeurControlee, Vocabulaire
from .session_import import SessionImport

__all__ = [
    "Base",
    "TracabiliteMixin",
    "Fonds",
    "Collection",
    "CollaborateurCollection",
    "CollaborateurFonds",
    "Item",
    "ItemCollection",
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
    "TypeCollection",
    "LIBELLES_PHASE",
    "LIBELLES_ROLE",
    "TypePage",
    "TypeOperationFichier",
    "StatutOperation",
    "TypeChamp",
    "TypeRelationExterne",
]
