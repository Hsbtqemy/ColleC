"""Modèle Fichier (scan rattaché à un item)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base
from .enums import EtatFichier, TypePage

if TYPE_CHECKING:
    from .item import Item
    from .journal import OperationFichier


class Fichier(Base):
    __tablename__ = "fichier"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("item.id"), nullable=False)

    racine: Mapped[str] = mapped_column(String(100), nullable=False)
    chemin_relatif: Mapped[str] = mapped_column(Text, nullable=False)
    nom_fichier: Mapped[str] = mapped_column(String(500), nullable=False)

    hash_sha256: Mapped[str | None] = mapped_column(String(64))
    taille_octets: Mapped[int | None] = mapped_column(Integer)
    format: Mapped[str | None] = mapped_column(String(20))
    largeur_px: Mapped[int | None] = mapped_column(Integer)
    hauteur_px: Mapped[int | None] = mapped_column(Integer)

    ordre: Mapped[int] = mapped_column(Integer, nullable=False)
    type_page: Mapped[str] = mapped_column(
        String(30), nullable=False, default=TypePage.PAGE.value
    )
    folio: Mapped[str | None] = mapped_column(String(20))

    etat: Mapped[str] = mapped_column(
        String(20), nullable=False, default=EtatFichier.ACTIF.value
    )
    derive_genere: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notes_techniques: Mapped[str | None] = mapped_column(Text)

    ajoute_le: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    ajoute_par_id: Mapped[int | None] = mapped_column(ForeignKey("utilisateur.id"))
    modifie_le: Mapped[datetime | None] = mapped_column(DateTime)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    item: Mapped[Item] = relationship(back_populates="fichiers")
    operations: Mapped[list[OperationFichier]] = relationship(back_populates="fichier")

    __table_args__ = (
        UniqueConstraint("racine", "chemin_relatif", name="uq_fichier_chemin"),
        UniqueConstraint("item_id", "ordre", name="uq_fichier_item_ordre"),
        Index("ix_fichier_item", "item_id"),
        Index("ix_fichier_hash", "hash_sha256"),
        Index("ix_fichier_nom", "nom_fichier"),
        Index("ix_fichier_etat", "etat"),
    )
