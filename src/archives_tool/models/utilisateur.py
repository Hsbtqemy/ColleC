"""Modèle Utilisateur (identité simple, pas d'auth forte)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Utilisateur(Base):
    __tablename__ = "utilisateur"

    id: Mapped[int] = mapped_column(primary_key=True)
    nom: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    actif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    cree_le: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
