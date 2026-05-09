"""Modèle Collection — un classement publiable.

Distinct du Fonds : la Collection est ce qui sera publié sur Nakala
(une sélection d'items pour une présentation, un thème, un export).

Deux types :
- MIROIR : créée automatiquement avec un Fonds, regroupe par défaut
  tous les items du fonds. Toujours rattachée à un fonds.
- LIBRE : créée manuellement. Peut être rattachée à un fonds ou
  rester transversale (`fonds_id IS NULL`).

Une Collection peut contenir des items provenant de plusieurs fonds
si elle est libre — la liaison N-N passe par `item_collection`.

Invariants (la couche service les garantit) :
- Une cote est unique au sein d'un fonds donné, mais peut se répéter
  entre fonds (deux fonds peuvent avoir une collection « OEUVRES »).
- La cote du fonds et celle de sa miroir sont volontairement
  identiques (fonds HK ↔ collection miroir HK).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TracabiliteMixin
from .enums import PhaseChantier, TypeCollection

if TYPE_CHECKING:
    from .collaborateur import CollaborateurCollection
    from .fonds import Fonds
    from .item import Item
    from .profil import ChampPersonnalise, ProfilImport


class Collection(Base, TracabiliteMixin):
    __tablename__ = "collection"

    id: Mapped[int] = mapped_column(primary_key=True)
    cote: Mapped[str] = mapped_column(String(64), nullable=False)
    titre: Mapped[str] = mapped_column(String(500), nullable=False)
    titre_secondaire: Mapped[str | None] = mapped_column(Text)

    description: Mapped[str | None] = mapped_column(Text)
    description_publique: Mapped[str | None] = mapped_column(Text)
    description_interne: Mapped[str | None] = mapped_column(Text)

    type_collection: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=TypeCollection.LIBRE.value,
    )

    # ON DELETE SET NULL : les collections libres rattachées au fonds
    # supprimé deviennent transversales. La miroir, qui ne peut pas
    # avoir fonds_id NULL (CHECK), doit être supprimée explicitement
    # par le service avant le fonds.
    fonds_id: Mapped[int | None] = mapped_column(
        ForeignKey("fonds.id", ondelete="SET NULL"),
        nullable=True,
    )

    phase: Mapped[str] = mapped_column(
        String(20), nullable=False, default=PhaseChantier.CATALOGAGE.value
    )

    # Champs périodique (collection-revue).
    editeur: Mapped[str | None] = mapped_column(String(300))
    lieu_edition: Mapped[str | None] = mapped_column(String(200))
    periodicite: Mapped[str | None] = mapped_column(String(100))
    issn: Mapped[str | None] = mapped_column(String(20))
    date_debut: Mapped[str | None] = mapped_column(String(50))
    date_fin: Mapped[str | None] = mapped_column(String(50))

    doi_nakala: Mapped[str | None] = mapped_column(Text)
    doi_collection_nakala_parent: Mapped[str | None] = mapped_column(String(128))

    personnalite_associee: Mapped[str | None] = mapped_column(String(255))
    responsable_archives: Mapped[str | None] = mapped_column(String(255))

    metadonnees: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    notes_internes: Mapped[str | None] = mapped_column(Text)

    profil_import_id: Mapped[int | None] = mapped_column(ForeignKey("profil_import.id"))

    fonds: Mapped[Fonds | None] = relationship(back_populates="collections")
    items: Mapped[list[Item]] = relationship(
        secondary="item_collection",
        back_populates="collections",
    )
    profil_import: Mapped[ProfilImport | None] = relationship()
    champs_personnalises: Mapped[list[ChampPersonnalise]] = relationship(
        back_populates="collection", cascade="all, delete-orphan"
    )
    collaborateurs: Mapped[list[CollaborateurCollection]] = relationship(
        back_populates="collection",
        cascade="all, delete-orphan",
        order_by="CollaborateurCollection.cree_le",
    )

    __table_args__ = (
        # Cote unique par fonds (les collections transversales partagent
        # un slot `fonds_id IS NULL` — SQLite traite NULL comme distinct,
        # donc l'unicité ne se déclenche pas pour les transversales).
        Index("ix_collection_fonds_cote", "fonds_id", "cote", unique=True),
        Index("ix_collection_cote", "cote"),
        Index("ix_collection_titre", "titre"),
        Index("ix_collection_fonds_id", "fonds_id"),
        UniqueConstraint("doi_nakala", name="uq_collection_doi_nakala"),
        Index("ix_collection_doi_nakala", "doi_nakala"),
        # Une miroir doit toujours pointer vers son fonds.
        CheckConstraint(
            "(type_collection = 'libre') OR (fonds_id IS NOT NULL)",
            name="ck_collection_miroir_a_fonds",
        ),
    )
