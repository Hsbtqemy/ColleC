"""Étiquettes colorées de chantier (Lot 4 UI⁺).

Marquage workflow **ad-hoc**, délibérément DISTINCT de `etat_catalogage`
et des vocabulaires contrôlés :

- étiquettes éphémères (« litigieux », « à revoir avec le conservateur »,
  « relu par Hugo »), **globales** à l'instance, **multi-tag** par item ;
- **jamais exportées** — contrairement aux valeurs de vocabulaire qui
  partent en `metadonnees` → Dublin Core / Nakala. Une étiquette est du
  chantier interne, pas de la métadonnée catalographique. C'est la raison
  d'être d'un modèle dédié plutôt que d'un `Vocabulaire`.

Cibles : `Item` uniquement (junction `item_etiquette`). Extensible plus
tard si le besoin remonte pour collections/fonds.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .item import Item


class Etiquette(Base):
    __tablename__ = "etiquette"

    id: Mapped[int] = mapped_column(primary_key=True)
    #: Libellé unique (global). Sert d'identité métier visible.
    libelle: Mapped[str] = mapped_column(String(80), nullable=False)
    #: Couleur (hex `#RRGGBB`) issue d'une palette fermée — validée par le
    #: service `FormulaireEtiquette`, pas par une contrainte SQL (palette
    #: susceptible d'évoluer sans migration).
    couleur: Mapped[str] = mapped_column(String(20), nullable=False)
    cree_le: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    cree_par: Mapped[str | None] = mapped_column(String(255))

    items: Mapped[list[Item]] = relationship(
        secondary="item_etiquette", back_populates="etiquettes"
    )

    __table_args__ = (UniqueConstraint("libelle", name="uq_etiquette_libelle"),)


class ItemEtiquette(Base):
    """Liaison N-N Item ↔ Étiquette. `item_id` en `ON DELETE CASCADE` :
    supprimer un item retire ses étiquetages (les étiquettes survivent)."""

    __tablename__ = "item_etiquette"

    item_id: Mapped[int] = mapped_column(
        ForeignKey("item.id", ondelete="CASCADE"),
        primary_key=True,
    )
    etiquette_id: Mapped[int] = mapped_column(
        ForeignKey("etiquette.id", ondelete="CASCADE"),
        primary_key=True,
    )
    ajoute_le: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    ajoute_par: Mapped[str | None] = mapped_column(String(255))

    __table_args__ = (Index("ix_item_etiquette_etiquette", "etiquette_id"),)
