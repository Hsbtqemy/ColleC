"""Modèle Fonds — corpus de matériel brut.

Le Fonds est interne à l'outil : Nakala n'a pas cette notion. Chaque
fonds porte une **collection miroir** (créée automatiquement à la
création du fonds), qui regroupe par défaut tous les items du fonds.
Des **collections libres** peuvent être rattachées au fonds ou rester
transversales.

Invariants :
- Un fonds a exactement une collection de type MIROIR (créé au service).
- La cascade `ON DELETE` du fonds supprime ses items et sa miroir ;
  les collections libres rattachées sont rendues transversales (logique
  service, pas SQL).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TracabiliteMixin
from .enums import TypeCollection

if TYPE_CHECKING:
    from .collaborateur_fonds import CollaborateurFonds
    from .collection import Collection
    from .item import Item


class Fonds(Base, TracabiliteMixin):
    __tablename__ = "fonds"

    id: Mapped[int] = mapped_column(primary_key=True)
    cote: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    titre: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    description_publique: Mapped[str | None] = mapped_column(Text)
    description_interne: Mapped[str | None] = mapped_column(Text)

    personnalite_associee: Mapped[str | None] = mapped_column(String(255))
    responsable_archives: Mapped[str | None] = mapped_column(String(255))

    # Champs périodique (fonds-revue).
    editeur: Mapped[str | None] = mapped_column(String(255))
    lieu_edition: Mapped[str | None] = mapped_column(String(255))
    periodicite: Mapped[str | None] = mapped_column(String(64))
    issn: Mapped[str | None] = mapped_column(String(32))

    date_debut: Mapped[str | None] = mapped_column(String(64))
    date_fin: Mapped[str | None] = mapped_column(String(64))

    items: Mapped[list[Item]] = relationship(
        back_populates="fonds",
        cascade="all, delete-orphan",
        order_by="Item.cote",
    )
    # `passive_deletes=True` : déléguer au FK `ON DELETE SET NULL` sur
    # les collections libres. Le service `supprimer_fonds` supprime la
    # miroir explicitement (sans quoi le CHECK miroir↔fonds_id serait
    # violé par l'auto-NULL d'SQLAlchemy).
    collections: Mapped[list[Collection]] = relationship(
        back_populates="fonds",
        order_by="Collection.titre",
        passive_deletes=True,
    )
    collaborateurs: Mapped[list[CollaborateurFonds]] = relationship(
        back_populates="fonds",
        cascade="all, delete-orphan",
        order_by="CollaborateurFonds.cree_le",
    )

    __table_args__ = (
        Index("ix_fonds_cote", "cote"),
        Index("ix_fonds_titre", "titre"),
    )

    @property
    def collection_miroir(self) -> Collection | None:
        """La collection miroir de ce fonds (créée automatiquement).

        Retourne `None` si aucune n'a encore été créée — état transitoire
        que le service `creer_fonds` ne laisse jamais persister. Pour
        un listing à grande échelle, préférer une requête SQL ciblée
        plutôt que cette propriété (cf. `services.fonds.lister_fonds`).
        """
        for c in self.collections:
            if c.type_collection == TypeCollection.MIROIR.value:
                return c
        return None
