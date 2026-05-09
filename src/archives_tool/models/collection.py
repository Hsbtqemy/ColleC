"""Modèle Collection avec hiérarchie auto-référentielle.

Les collections peuvent être imbriquées via `parent_id` (fonds > série
> sous-série). L'anti-cycle est validé au niveau applicatif via un
listener `before_flush` — SQLite ne supporte pas proprement les CHECK
récursifs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, ForeignKey, Index, String, Text, UniqueConstraint, event
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from .base import Base, TracabiliteMixin
from .enums import PhaseChantier

if TYPE_CHECKING:
    from .collaborateur import CollaborateurCollection
    from .item import Item
    from .profil import ChampPersonnalise, ProfilImport


class Collection(Base, TracabiliteMixin):
    __tablename__ = "collection"

    id: Mapped[int] = mapped_column(primary_key=True)
    cote_collection: Mapped[str] = mapped_column(
        String(50), nullable=False, unique=True
    )
    titre: Mapped[str] = mapped_column(String(500), nullable=False)
    titre_secondaire: Mapped[str | None] = mapped_column(Text)
    editeur: Mapped[str | None] = mapped_column(String(300))
    lieu_edition: Mapped[str | None] = mapped_column(String(200))
    periodicite: Mapped[str | None] = mapped_column(String(100))
    date_debut: Mapped[str | None] = mapped_column(String(50))
    date_fin: Mapped[str | None] = mapped_column(String(50))
    issn: Mapped[str | None] = mapped_column(String(20))
    doi_nakala: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    description_interne: Mapped[str | None] = mapped_column(Text)
    personnalite_associee: Mapped[str | None] = mapped_column(Text)
    responsable_archives: Mapped[str | None] = mapped_column(Text)
    metadonnees: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    notes_internes: Mapped[str | None] = mapped_column(Text)

    phase: Mapped[str] = mapped_column(
        String(20), nullable=False, default=PhaseChantier.CATALOGAGE.value
    )

    profil_import_id: Mapped[int | None] = mapped_column(ForeignKey("profil_import.id"))

    # Hiérarchie auto-référentielle.
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("collection.id", name="fk_collection_parent_id")
    )
    parent: Mapped[Collection | None] = relationship(
        remote_side="Collection.id",
        back_populates="enfants",
        foreign_keys=[parent_id],
    )
    enfants: Mapped[list[Collection]] = relationship(
        back_populates="parent",
        cascade="all, delete-orphan",
        foreign_keys=[parent_id],
    )

    items: Mapped[list[Item]] = relationship(
        back_populates="collection", cascade="all, delete-orphan"
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
        UniqueConstraint("doi_nakala", name="uq_collection_doi_nakala"),
        Index("ix_collection_titre", "titre"),
        Index("ix_collection_doi_nakala", "doi_nakala"),
        Index("ix_collection_parent_id", "parent_id"),
    )

    def ids_descendants(self) -> list[int]:
        """IDs de cette collection et de toute sa descendance (BFS).

        Source de vérité unique pour les requêtes scopées à un sous-arbre
        (importer, qa, renamer, derivatives, exporters).
        """
        ids = [self.id]
        a_visiter = list(self.enfants)
        while a_visiter:
            n = a_visiter.pop(0)
            ids.append(n.id)
            a_visiter.extend(n.enfants)
        return ids


def valider_hierarchie(collection: Collection) -> None:
    """Lève ValueError si la chaîne de parents contient un cycle.

    Gère deux cas :
    - Auto-référence sur objet transient (id `None` des deux côtés) :
      détection par identité Python.
    - Cycle profond sur objets persistés : détection par comparaison
      d'`id` au long de la chaîne.
    """
    if collection.parent is None and collection.parent_id is None:
        return
    if collection.parent is collection:
        raise ValueError(
            f"Collection {collection.cote_collection!r} : une collection ne "
            "peut pas être son propre parent."
        )
    vus: set[int] = set()
    courant = collection.parent
    while courant is not None:
        if courant is collection:
            raise ValueError(
                f"Collection {collection.cote_collection!r} : cycle détecté "
                "dans la hiérarchie de collections."
            )
        if courant.id is not None and collection.id is not None:
            if courant.id == collection.id:
                raise ValueError(
                    f"Collection {collection.cote_collection!r} : cycle "
                    "détecté dans la hiérarchie de collections."
                )
            if courant.id in vus:
                break
            vus.add(courant.id)
        courant = courant.parent


@event.listens_for(Session, "before_flush")
def _valider_hierarchie_avant_flush(session, flush_context, instances):  # noqa: ANN001
    for obj in list(session.new) + list(session.dirty):
        if isinstance(obj, Collection):
            valider_hierarchie(obj)
