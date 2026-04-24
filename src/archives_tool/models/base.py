"""Classe Base SQLAlchemy et mixins partagés."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Integer, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Classe de base pour tous les modèles."""

    type_annotation_map = {
        dict[str, Any]: JSON,
        list[Any]: JSON,
    }


class TracabiliteMixin:
    """Champs de traçabilité : création, modification, version.

    L'identité des auteurs est un simple texte libre issu de la config
    locale (`utilisateur: "Marie"`). Pas de FK, pas de table utilisateur :
    l'information est purement informative et ne sert pas de clé métier.
    """

    cree_le: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    cree_par: Mapped[str | None] = mapped_column(Text, nullable=True)
    modifie_le: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    modifie_par: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
