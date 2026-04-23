"""Classe Base SQLAlchemy et mixins partagés."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Classe de base pour tous les modèles."""

    type_annotation_map = {
        dict[str, Any]: JSON,
        list[Any]: JSON,
    }


class TracabiliteMixin:
    """Champs de traçabilité : création, modification, version."""

    cree_le: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    cree_par_id: Mapped[int | None] = mapped_column(
        ForeignKey("utilisateur.id"), nullable=True
    )
    modifie_le: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    modifie_par_id: Mapped[int | None] = mapped_column(
        ForeignKey("utilisateur.id"), nullable=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
