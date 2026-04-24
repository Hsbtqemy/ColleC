"""Profils d'import, champs personnalisés, vocabulaires contrôlés."""

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
    from .collection import Collection


class ProfilImport(Base):
    __tablename__ = "profil_import"

    id: Mapped[int] = mapped_column(primary_key=True)
    nom: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    chemin_yaml: Mapped[str] = mapped_column(Text, nullable=False)
    contenu: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    cree_le: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    modifie_le: Mapped[datetime | None] = mapped_column(DateTime)


class Vocabulaire(Base):
    __tablename__ = "vocabulaire"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    libelle: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    description_interne: Mapped[str | None] = mapped_column(Text)
    uri_base: Mapped[str | None] = mapped_column(Text)

    valeurs: Mapped[list[ValeurControlee]] = relationship(
        back_populates="vocabulaire", cascade="all, delete-orphan"
    )


class ValeurControlee(Base):
    __tablename__ = "valeur_controlee"

    id: Mapped[int] = mapped_column(primary_key=True)
    vocabulaire_id: Mapped[int] = mapped_column(
        ForeignKey("vocabulaire.id"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(120), nullable=False)
    libelle: Mapped[str] = mapped_column(String(300), nullable=False)
    uri: Mapped[str | None] = mapped_column(Text)
    description_interne: Mapped[str | None] = mapped_column(Text)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("valeur_controlee.id"))
    ordre: Mapped[int | None] = mapped_column(Integer)
    actif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    vocabulaire: Mapped[Vocabulaire] = relationship(back_populates="valeurs")

    __table_args__ = (
        UniqueConstraint("vocabulaire_id", "code", name="uq_valeur_vocab_code"),
    )


class ChampPersonnalise(Base):
    __tablename__ = "champ_personnalise"

    id: Mapped[int] = mapped_column(primary_key=True)
    collection_id: Mapped[int | None] = mapped_column(ForeignKey("collection.id"))
    cle: Mapped[str] = mapped_column(String(80), nullable=False)
    libelle: Mapped[str] = mapped_column(String(200), nullable=False)
    type: Mapped[str] = mapped_column(String(30), nullable=False)
    obligatoire: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    valeurs_controlees_id: Mapped[int | None] = mapped_column(
        ForeignKey("vocabulaire.id")
    )
    ordre: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    aide: Mapped[str | None] = mapped_column(Text)
    description_interne: Mapped[str | None] = mapped_column(Text)

    collection: Mapped[Collection | None] = relationship(
        back_populates="champs_personnalises"
    )
    vocabulaire: Mapped[Vocabulaire | None] = relationship()

    __table_args__ = (
        UniqueConstraint("collection_id", "cle", name="uq_champ_collection_cle"),
    )
