"""Modèle Collection."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TracabiliteMixin

if TYPE_CHECKING:
    from .item import Item
    from .profil import ChampPersonnalise, ProfilImport


class Collection(Base, TracabiliteMixin):
    __tablename__ = "collection"

    id: Mapped[int] = mapped_column(primary_key=True)
    cote_collection: Mapped[str] = mapped_column(
        String(50), nullable=False, unique=True
    )
    titre: Mapped[str] = mapped_column(String(500), nullable=False)
    titre_secondaire: Mapped[str | None] = mapped_column(Text)
    editeur: Mapped[str | None] = mapped_column(String(300))
    lieu_edition: Mapped[str | None] = mapped_column(String(200))
    periodicite: Mapped[str | None] = mapped_column(String(100))
    date_debut: Mapped[str | None] = mapped_column(String(50))
    date_fin: Mapped[str | None] = mapped_column(String(50))
    issn: Mapped[str | None] = mapped_column(String(20))
    description: Mapped[str | None] = mapped_column(Text)
    metadonnees: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    notes_internes: Mapped[str | None] = mapped_column(Text)

    profil_import_id: Mapped[int | None] = mapped_column(
        ForeignKey("profil_import.id")
    )

    items: Mapped[list[Item]] = relationship(
        back_populates="collection", cascade="all, delete-orphan"
    )
    profil_import: Mapped[ProfilImport | None] = relationship()
    champs_personnalises: Mapped[list[ChampPersonnalise]] = relationship(
        back_populates="collection", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_collection_titre", "titre"),)
