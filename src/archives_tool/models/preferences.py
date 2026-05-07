"""Préférences d'affichage par utilisateur et par collection.

Persiste l'ordre des colonnes choisi dans une vue tabulaire (items,
fichiers, sous-collections). Pas d'utilisation effective en v0.5 ;
structure créée pour ne pas avoir à reprendre la migration en v0.6
quand l'UI tabulaire arrivera.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class PreferencesAffichage(Base):
    __tablename__ = "preferences_affichage"

    id: Mapped[int] = mapped_column(primary_key=True)
    utilisateur: Mapped[str] = mapped_column(Text, nullable=False)
    collection_id: Mapped[int | None] = mapped_column(
        ForeignKey("collection.id", ondelete="CASCADE")
    )
    vue: Mapped[str] = mapped_column(String(40), nullable=False)
    colonnes_ordonnees: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    cree_le: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    modifie_le: Mapped[datetime | None] = mapped_column(DateTime)

    __table_args__ = (
        UniqueConstraint(
            "utilisateur",
            "collection_id",
            "vue",
            name="uq_preferences_affichage",
        ),
        Index("ix_preferences_utilisateur", "utilisateur"),
        Index("ix_preferences_collection", "collection_id"),
    )
