"""Liaison N-N entre Item et Collection.

Un item peut figurer dans 0..N collections : la miroir de son fonds
plus, optionnellement, des collections libres (rattachées au même
fonds ou transversales).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class ItemCollection(Base):
    __tablename__ = "item_collection"

    item_id: Mapped[int] = mapped_column(
        ForeignKey("item.id", ondelete="CASCADE"),
        primary_key=True,
    )
    collection_id: Mapped[int] = mapped_column(
        ForeignKey("collection.id", ondelete="CASCADE"),
        primary_key=True,
    )
    ajoute_le: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    ajoute_par: Mapped[str | None] = mapped_column(String(255))
