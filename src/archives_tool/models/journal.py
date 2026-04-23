"""Journaux : opérations fichiers, modifications items, sessions d'édition."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .fichier import Fichier
    from .item import Item


class OperationFichier(Base):
    __tablename__ = "operation_fichier"

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[str] = mapped_column(String(36), nullable=False)

    fichier_id: Mapped[int | None] = mapped_column(ForeignKey("fichier.id"))
    type_operation: Mapped[str] = mapped_column(String(20), nullable=False)

    racine_avant: Mapped[str | None] = mapped_column(String(100))
    chemin_avant: Mapped[str | None] = mapped_column(Text)
    racine_apres: Mapped[str | None] = mapped_column(String(100))
    chemin_apres: Mapped[str | None] = mapped_column(Text)
    hash_avant: Mapped[str | None] = mapped_column(String(64))
    hash_apres: Mapped[str | None] = mapped_column(String(64))

    statut: Mapped[str] = mapped_column(String(20), nullable=False)
    message: Mapped[str | None] = mapped_column(Text)

    execute_le: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    execute_par_id: Mapped[int | None] = mapped_column(ForeignKey("utilisateur.id"))
    annule_par_batch_id: Mapped[str | None] = mapped_column(String(36))

    fichier: Mapped[Fichier | None] = relationship(back_populates="operations")

    __table_args__ = (
        Index("ix_op_batch", "batch_id"),
        Index("ix_op_fichier", "fichier_id"),
        Index("ix_op_date", "execute_le"),
    )


class ModificationItem(Base):
    __tablename__ = "modification_item"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("item.id"), nullable=False)
    champ: Mapped[str] = mapped_column(String(120), nullable=False)
    valeur_avant: Mapped[str | None] = mapped_column(Text)
    valeur_apres: Mapped[str | None] = mapped_column(Text)
    modifie_le: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    modifie_par_id: Mapped[int | None] = mapped_column(ForeignKey("utilisateur.id"))

    item: Mapped[Item] = relationship(back_populates="modifications")

    __table_args__ = (
        Index("ix_mod_item", "item_id"),
        Index("ix_mod_date", "modifie_le"),
    )


class SessionEdition(Base):
    __tablename__ = "session_edition"

    id: Mapped[int] = mapped_column(primary_key=True)
    utilisateur_id: Mapped[int] = mapped_column(
        ForeignKey("utilisateur.id"), nullable=False
    )
    item_id: Mapped[int | None] = mapped_column(ForeignKey("item.id"))
    ouverte_le: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    dernier_heartbeat: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    fermee_le: Mapped[datetime | None] = mapped_column(DateTime)
