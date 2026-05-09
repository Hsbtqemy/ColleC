"""Collaborateur d'un Fonds.

Personnes ayant contribué à la constitution du fonds (numérisation,
transcription, indexation, catalogage). Analogue de
`CollaborateurCollection` mais rattaché au fonds — c'est l'usage
courant ; les collaborateurs propres à une collection particulière
restent gérés par `CollaborateurCollection`.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .fonds import Fonds


class CollaborateurFonds(Base):
    __tablename__ = "collaborateur_fonds"

    id: Mapped[int] = mapped_column(primary_key=True)
    fonds_id: Mapped[int] = mapped_column(
        ForeignKey("fonds.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    nom: Mapped[str] = mapped_column(String(255), nullable=False)
    roles: Mapped[list[Any]] = mapped_column(JSON, nullable=False)
    periode: Mapped[str | None] = mapped_column(String(64))
    notes: Mapped[str | None] = mapped_column(Text)

    cree_le: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    modifie_le: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    fonds: Mapped[Fonds] = relationship(back_populates="collaborateurs")
