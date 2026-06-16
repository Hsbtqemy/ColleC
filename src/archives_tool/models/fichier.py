"""Modèle Fichier (scan rattaché à un item)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base
from .enums import EtatFichier, TypePage

if TYPE_CHECKING:
    from .annotation import AnnotationRegion
    from .item import Item
    from .journal import OperationFichier


class Fichier(Base):
    __tablename__ = "fichier"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("item.id"), nullable=False)

    # Le fichier original peut être local (racine + chemin_relatif),
    # exclusivement sur Nakala (iiif_url_nakala) ou les deux. Au moins
    # une source doit être renseignée — voir CHECK ci-dessous.
    racine: Mapped[str | None] = mapped_column(String(100))
    chemin_relatif: Mapped[str | None] = mapped_column(Text)
    nom_fichier: Mapped[str] = mapped_column(String(500), nullable=False)

    # Sources d'images résolues à l'affichage. Aperçu/vignette
    # remplis par derivatives ; dzi_chemin réservé pour les tuiles
    # locales (V2+) ; iiif_url_nakala renseigné lors d'un dépôt ou
    # d'un import depuis Nakala (V0.7+).
    apercu_chemin: Mapped[str | None] = mapped_column(Text)
    vignette_chemin: Mapped[str | None] = mapped_column(Text)
    dzi_chemin: Mapped[str | None] = mapped_column(Text)
    iiif_url_nakala: Mapped[str | None] = mapped_column(Text)

    hash_sha256: Mapped[str | None] = mapped_column(String(64))
    #: SHA-1 calculé par Nakala à l'upload (`POST /datas/uploads`) ou
    #: lu sur un fichier matérialisé via `rapatrier`. C'est l'identité
    #: du fichier côté Nakala — sert au versioning fichiers (P3+ du
    #: backlog `nakala-depot-future.md` difficulté #4) : on réconcilie
    #: `Fichier` ColleC ↔ entrée `files[i]` Nakala par cette colonne.
    #:
    #: **Distinct de `hash_sha256`** : algorithmes différents (SHA-1 vs
    #: SHA-256), sémantiques distinctes — ne pas comparer l'un à l'autre.
    #: `hash_sha256` reste la source de vérité ColleC pour l'intégrité
    #: disque ; `sha1_nakala` est purement l'identifiant Nakala.
    #:
    #: `None` pour les fichiers jamais déposés ni pullés depuis Nakala
    #: (cas normal d'un fichier purement local).
    sha1_nakala: Mapped[str | None] = mapped_column(String(40))
    taille_octets: Mapped[int | None] = mapped_column(Integer)
    format: Mapped[str | None] = mapped_column(String(20))
    largeur_px: Mapped[int | None] = mapped_column(Integer)
    hauteur_px: Mapped[int | None] = mapped_column(Integer)

    ordre: Mapped[int] = mapped_column(Integer, nullable=False)
    type_page: Mapped[str] = mapped_column(
        String(30), nullable=False, default=TypePage.PAGE.value
    )
    folio: Mapped[str | None] = mapped_column(String(20))

    etat: Mapped[str] = mapped_column(
        String(20), nullable=False, default=EtatFichier.ACTIF.value
    )
    derive_genere: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notes_techniques: Mapped[str | None] = mapped_column(Text)
    #: Transcription / description **publique** du fichier (S7), destinée à
    #: accompagner le scan côté Nakala (champ `description` par fichier —
    #: round-trip validé : sondes H11 + périmètre 2026-06-15) et à
    #: l'indexation textuelle future. Texte libre : Nakala n'accepte AUCUNE
    #: métadonnée structurée par fichier au-delà de `description` +
    #: `embargoed` (cf. nakala-savoir-api §4). **Distinct** de
    #: `notes_techniques` (interne, jamais exporté) et de `Item.description`
    #: (niveau donnée). `None` = pas de transcription.
    description_externe: Mapped[str | None] = mapped_column(Text)
    # Métadonnées libres par-fichier — pendant de `Item.metadonnees`.
    # Sert aux champs propres à un scan (URLs Nakala data/embed/preview/thumb,
    # hash dupliqués, infos techniques import) qui ne rentrent pas dans
    # les colonnes dédiées. En granularité fichier, chaque ligne du
    # tableur peut porter ses propres valeurs sans déclencher de
    # warning de divergence à la fusion (cf. `_grouper_par_cote`).
    metadonnees: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    ajoute_le: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    ajoute_par: Mapped[str | None] = mapped_column(Text)
    modifie_le: Mapped[datetime | None] = mapped_column(DateTime)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    item: Mapped[Item] = relationship(back_populates="fichiers")
    operations: Mapped[list[OperationFichier]] = relationship(back_populates="fichier")
    annotations: Mapped[list["AnnotationRegion"]] = relationship(
        back_populates="fichier",
        cascade="all, delete-orphan",
        order_by="AnnotationRegion.cree_le",
    )

    __table_args__ = (
        UniqueConstraint("racine", "chemin_relatif", name="uq_fichier_chemin"),
        UniqueConstraint("item_id", "ordre", name="uq_fichier_item_ordre"),
        # Au moins une source originale doit exister. apercu_chemin
        # et dzi_chemin sont des dérivés régénérables, ils ne comptent
        # pas comme source primaire.
        CheckConstraint(
            "chemin_relatif IS NOT NULL OR iiif_url_nakala IS NOT NULL",
            name="ck_fichier_source_au_moins_une",
        ),
        Index("ix_fichier_item", "item_id"),
        Index("ix_fichier_hash", "hash_sha256"),
        Index("ix_fichier_sha1_nakala", "sha1_nakala"),
        Index("ix_fichier_nom", "nom_fichier"),
        Index("ix_fichier_etat", "etat"),
    )
