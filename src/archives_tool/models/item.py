"""Modèle Item (unité de catalogage)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TracabiliteMixin
from .enums import EtatCatalogage

if TYPE_CHECKING:
    from .collection import Collection
    from .externe import LienExterneItem
    from .fichier import Fichier
    from .journal import ModificationItem


class Item(Base, TracabiliteMixin):
    __tablename__ = "item"

    id: Mapped[int] = mapped_column(primary_key=True)
    collection_id: Mapped[int] = mapped_column(
        ForeignKey("collection.id"), nullable=False
    )

    cote: Mapped[str] = mapped_column(String(100), nullable=False)
    numero: Mapped[str | None] = mapped_column(String(50))
    numero_tri: Mapped[int | None] = mapped_column(Integer)

    titre: Mapped[str | None] = mapped_column(Text)
    date: Mapped[str | None] = mapped_column(String(50))
    annee: Mapped[int | None] = mapped_column(Integer)

    type_coar: Mapped[str | None] = mapped_column(String(200))
    langue: Mapped[str | None] = mapped_column(String(10))

    # DOI Nakala : unique pour l'item lui-même ; non-unique pour le
    # rattachement à une collection Nakala partagée par plusieurs items.
    doi_nakala: Mapped[str | None] = mapped_column(Text)
    doi_collection_nakala: Mapped[str | None] = mapped_column(Text)

    description: Mapped[str | None] = mapped_column(Text)
    metadonnees: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    etat_catalogage: Mapped[str] = mapped_column(
        String(30), nullable=False, default=EtatCatalogage.BROUILLON.value
    )
    notes_internes: Mapped[str | None] = mapped_column(Text)

    collection: Mapped[Collection] = relationship(back_populates="items")
    fichiers: Mapped[list[Fichier]] = relationship(
        back_populates="item", cascade="all, delete-orphan"
    )
    modifications: Mapped[list[ModificationItem]] = relationship(
        back_populates="item", cascade="all, delete-orphan"
    )
    liens_externes: Mapped[list[LienExterneItem]] = relationship(
        back_populates="item", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("collection_id", "cote", name="uq_item_collection_cote"),
        UniqueConstraint("doi_nakala", name="uq_item_doi_nakala"),
        CheckConstraint(
            "etat_catalogage IN "
            "('brouillon', 'a_verifier', 'verifie', 'valide', 'a_corriger')",
            name="ck_item_etat_catalogage",
        ),
        Index("ix_item_collection_id", "collection_id"),
        Index("ix_item_annee", "annee"),
        Index("ix_item_etat", "etat_catalogage"),
        Index("ix_item_doi_nakala", "doi_nakala"),
        Index("ix_item_doi_collection_nakala", "doi_collection_nakala"),
    )
