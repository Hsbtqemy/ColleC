"""Collaborateurs d'une collection (V0.8.0).

Personnes qui ont contribué techniquement à la constitution de la
collection (numérisation, transcription, indexation, catalogage).
Texte libre pour le nom — pas d'auth, pas de FK utilisateur.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .collection import Collection


class CollaborateurCollection(Base):
    """Une personne qui a contribué à une collection, avec un ou
    plusieurs rôles dans le vocabulaire fermé `RoleCollaborateur`.

    `roles` est stocké en JSON (liste de chaînes) ; la validation du
    vocabulaire est applicative, pas SQL — voir `services/collaborateurs.py`.
    """

    __tablename__ = "collaborateur_collection"

    id: Mapped[int] = mapped_column(primary_key=True)
    collection_id: Mapped[int] = mapped_column(
        ForeignKey("collection.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    nom: Mapped[str] = mapped_column(String(255), nullable=False)
    roles: Mapped[list[Any]] = mapped_column(JSON, nullable=False)
    periode: Mapped[str | None] = mapped_column(String(64), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    cree_le: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    modifie_le: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    collection: Mapped[Collection] = relationship(back_populates="collaborateurs")
