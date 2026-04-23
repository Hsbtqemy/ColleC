"""Sources externes (Nakala, HAL...) — V2+."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .item import Item


class SourceExterne(Base):
    __tablename__ = "source_externe"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    libelle: Mapped[str] = mapped_column(String(200), nullable=False)
    type_api: Mapped[str] = mapped_column(String(20), nullable=False)
    url_base: Mapped[str] = mapped_column(Text, nullable=False)
    ttl_cache_heures: Mapped[int] = mapped_column(Integer, nullable=False, default=24)
    actif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    ressources: Mapped[list[RessourceExterne]] = relationship(
        back_populates="source", cascade="all, delete-orphan"
    )


class RessourceExterne(Base):
    __tablename__ = "ressource_externe"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("source_externe.id"), nullable=False
    )
    identifiant_externe: Mapped[str] = mapped_column(String(300), nullable=False)
    type: Mapped[str | None] = mapped_column(String(30))
    titre: Mapped[str | None] = mapped_column(Text)
    auteurs: Mapped[list[Any] | None] = mapped_column(JSON)
    date: Mapped[str | None] = mapped_column(String(50))
    metadonnees_brutes: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    manifeste_iiif: Mapped[str | None] = mapped_column(Text)
    recupere_le: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    statut: Mapped[str] = mapped_column(String(20), nullable=False, default="actif")

    source: Mapped[SourceExterne] = relationship(back_populates="ressources")
    liens: Mapped[list[LienExterneItem]] = relationship(
        back_populates="ressource", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint(
            "source_id", "identifiant_externe", name="uq_ressource_source_ident"
        ),
    )


class LienExterneItem(Base):
    __tablename__ = "lien_externe_item"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("item.id"), nullable=False)
    ressource_externe_id: Mapped[int] = mapped_column(
        ForeignKey("ressource_externe.id"), nullable=False
    )
    type_relation: Mapped[str] = mapped_column(String(30), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    cree_le: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    cree_par_id: Mapped[int | None] = mapped_column(ForeignKey("utilisateur.id"))

    item: Mapped[Item] = relationship(back_populates="liens_externes")
    ressource: Mapped[RessourceExterne] = relationship(back_populates="liens")

    __table_args__ = (
        UniqueConstraint(
            "item_id",
            "ressource_externe_id",
            "type_relation",
            name="uq_lien_item_ressource_type",
        ),
    )
