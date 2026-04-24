"""Journaux : opérations fichiers, modifications items."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func
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
    execute_par: Mapped[str | None] = mapped_column(Text)
    annule_par_batch_id: Mapped[str | None] = mapped_column(String(36))

    fichier: Mapped[Fichier | None] = relationship(back_populates="operations")

    __table_args__ = (
        Index("ix_op_batch", "batch_id"),
        Index("ix_op_fichier", "fichier_id"),
        Index("ix_op_date", "execute_le"),
    )


class OperationImport(Base):
    """Journal des imports depuis profil YAML.

    Une entrée par exécution réelle (pas en dry-run). Le rapport
    complet est sérialisé dans `rapport_json` pour navigation future.
    Le `batch_id` fait le lien avec d'éventuelles `OperationFichier`
    générées pendant l'import.
    """

    __tablename__ = "operation_import"

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[str] = mapped_column(String(36), nullable=False)
    profil_chemin: Mapped[str] = mapped_column(Text, nullable=False)
    collection_id: Mapped[int | None] = mapped_column(ForeignKey("collection.id"))
    items_crees: Mapped[int] = mapped_column(default=0)
    items_mis_a_jour: Mapped[int] = mapped_column(default=0)
    items_inchanges: Mapped[int] = mapped_column(default=0)
    fichiers_ajoutes: Mapped[int] = mapped_column(default=0)
    execute_le: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    execute_par: Mapped[str | None] = mapped_column(Text)
    rapport_json: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("batch_id", name="uq_op_import_batch_id"),
        Index("ix_op_import_batch", "batch_id"),
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
    modifie_par: Mapped[str | None] = mapped_column(Text)

    item: Mapped[Item] = relationship(back_populates="modifications")

    __table_args__ = (
        Index("ix_mod_item", "item_id"),
        Index("ix_mod_date", "modifie_le"),
    )
