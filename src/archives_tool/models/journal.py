"""Journaux : opérations fichiers, modifications items."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .fichier import Fichier
    from .item import Item


class OperationFichier(Base):
    __tablename__ = "operation_fichier"

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[str] = mapped_column(String(36), nullable=False)

    fichier_id: Mapped[int | None] = mapped_column(ForeignKey("fichier.id"))
    type_operation: Mapped[str] = mapped_column(String(20), nullable=False)

    racine_avant: Mapped[str | None] = mapped_column(String(100))
    chemin_avant: Mapped[str | None] = mapped_column(Text)
    racine_apres: Mapped[str | None] = mapped_column(String(100))
    chemin_apres: Mapped[str | None] = mapped_column(Text)
    hash_avant: Mapped[str | None] = mapped_column(String(64))
    hash_apres: Mapped[str | None] = mapped_column(String(64))

    statut: Mapped[str] = mapped_column(String(20), nullable=False)
    message: Mapped[str | None] = mapped_column(Text)

    execute_le: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    execute_par: Mapped[str | None] = mapped_column(Text)
    annule_par_batch_id: Mapped[str | None] = mapped_column(String(36))

    fichier: Mapped[Fichier | None] = relationship(back_populates="operations")

    __table_args__ = (
        Index("ix_op_batch", "batch_id"),
        Index("ix_op_fichier", "fichier_id"),
        Index("ix_op_date", "execute_le"),
    )


class OperationImport(Base):
    """Journal des imports depuis profil YAML.

    Une entrée par exécution réelle (pas en dry-run). Le rapport
    complet est sérialisé dans `rapport_json` pour navigation future.
    Le `batch_id` fait le lien avec d'éventuelles `OperationFichier`
    générées pendant l'import.
    """

    __tablename__ = "operation_import"

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[str] = mapped_column(String(36), nullable=False)
    profil_chemin: Mapped[str] = mapped_column(Text, nullable=False)
    collection_id: Mapped[int | None] = mapped_column(ForeignKey("collection.id"))
    items_crees: Mapped[int] = mapped_column(default=0)
    items_mis_a_jour: Mapped[int] = mapped_column(default=0)
    items_inchanges: Mapped[int] = mapped_column(default=0)
    fichiers_ajoutes: Mapped[int] = mapped_column(default=0)
    execute_le: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    execute_par: Mapped[str | None] = mapped_column(Text)
    rapport_json: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("batch_id", name="uq_op_import_batch_id"),
        Index("ix_op_import_batch", "batch_id"),
    )


class OperationEntite(Base):
    """Journal des suppressions d'entités (fonds / collection / item).

    Comble le trou du principe directeur n°4 (« journaliser toutes les
    opérations destructives ») : `OperationFichier` ne couvre que les
    fichiers, `ModificationItem` que les métadonnées d'item — les
    suppressions d'entités n'étaient tracées nulle part.

    Pas de FK : l'entité référencée n'existe plus après la suppression.
    On conserve donc `entite_id` (l'ancien id, purement informatif),
    `cote` et `fonds_cote` (contexte de désambiguïsation) en clair.

    `snapshot_json` : colonnes propres de l'entité supprimée, sérialisées
    au moment de la suppression. `cascade_resume` : compteurs JSON de ce
    que la cascade a détruit (items, fichiers, collaborateurs, collections
    détachées, annotations, junctions) + listes d'ids/cotes des enfants
    directement affectés. Ces listes sont bornées (ids, pas de dump de
    rows complètes — tient même pour un fonds à 7000+ fichiers) et rendent
    un undo futur possible sans perte d'information (réversibilité
    asymétrique : la donnée est préservée, l'exécution du restore est
    reportée à un chantier dédié).
    """

    __tablename__ = "operation_entite"

    id: Mapped[int] = mapped_column(primary_key=True)
    type_entite: Mapped[str] = mapped_column(String(20), nullable=False)
    entite_id: Mapped[int | None] = mapped_column()
    cote: Mapped[str | None] = mapped_column(Text)
    fonds_cote: Mapped[str | None] = mapped_column(Text)
    titre: Mapped[str | None] = mapped_column(Text)

    snapshot_json: Mapped[str | None] = mapped_column(Text)
    cascade_resume: Mapped[str | None] = mapped_column(Text)

    execute_le: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    execute_par: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index("ix_op_entite_type", "type_entite"),
        Index("ix_op_entite_date", "execute_le"),
    )


class OperationPushNakala(Base):
    """Journal des push vers Nakala (fichiers, V0.10+).

    Comble le trou du principe directeur n°4 sur les opérations
    destructives **côté distant** : un ``PUT /datas/{id}`` avec
    ``files[]`` réduit RETIRE silencieusement les fichiers absents
    (H1 — sémantique « remplace intégralement »). ``OperationFichier``
    ne couvre que les opérations sur disque local. Sans journal
    dédié, un push qui retire des fichiers (orphelins, non-ACTIF,
    doublons) ne laisse aucune trace consultable.

    Pas de FK vers le Fichier (les sha1 distants retirés n'ont pas
    forcément un Fichier ColleC correspondant à conserver). On
    stocke à plat :

    - ``cote_item`` + ``fonds_cote`` : désambiguïsation contextuelle.
    - ``doi`` : DOI Nakala impacté.
    - ``type_operation`` : `push_fichiers` (extensible : `push_metas`
      en V2+ si besoin).
    - ``snapshot_avant`` : liste JSON des fichiers distants AVANT
      le PUT (sha1, name, taille, mime). Source : ``lire_depot``.
    - ``snapshot_apres`` : liste JSON des fichiers distants ATTENDUS
      après le PUT (sha1, name). Source : ``files[]`` envoyé.
    - ``sha1s_uploades`` / ``sha1s_retires`` : extraits du
      ``RapportPushFichiers`` pour audit rapide.
    - ``batch_id`` : UUID pour grouper si un push collection
      enchaîne plusieurs push items (alignement avec
      `OperationFichier` / `OperationImport`).

    L'écriture est journalisée **dans la même transaction** que la
    mise à jour `Fichier.sha1_nakala` du service push — atomique avec
    la mutation locale (les deux ou rien).
    """

    __tablename__ = "operation_push_nakala"

    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[str] = mapped_column(String(36), nullable=False)
    type_operation: Mapped[str] = mapped_column(String(30), nullable=False)
    cote_item: Mapped[str] = mapped_column(Text, nullable=False)
    fonds_cote: Mapped[str | None] = mapped_column(Text)
    doi: Mapped[str] = mapped_column(Text, nullable=False)

    snapshot_avant: Mapped[str | None] = mapped_column(Text)
    snapshot_apres: Mapped[str | None] = mapped_column(Text)
    sha1s_uploades: Mapped[str | None] = mapped_column(Text)
    sha1s_retires: Mapped[str | None] = mapped_column(Text)

    execute_le: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    execute_par: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index("ix_op_push_nakala_batch", "batch_id"),
        Index("ix_op_push_nakala_doi", "doi"),
        Index("ix_op_push_nakala_date", "execute_le"),
    )


class ModificationItem(Base):
    __tablename__ = "modification_item"

    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("item.id"), nullable=False)
    champ: Mapped[str] = mapped_column(String(120), nullable=False)
    valeur_avant: Mapped[str | None] = mapped_column(Text)
    valeur_apres: Mapped[str | None] = mapped_column(Text)
    modifie_le: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    modifie_par: Mapped[str | None] = mapped_column(Text)

    item: Mapped[Item] = relationship(back_populates="modifications")

    __table_args__ = (
        Index("ix_mod_item", "item_id"),
        Index("ix_mod_date", "modifie_le"),
    )
