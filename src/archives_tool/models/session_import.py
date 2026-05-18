"""Session d'import en cours depuis l'assistant web (modèle v2 / fonds).

Persiste l'état d'un import multi-étapes : tableur, fonds, mapping,
résolution fichiers, aperçu. Survit à un rechargement de page —
l'utilisateur peut reprendre une session via `/import/{id}`.

Le format cible est le profil d'import **v2** (`profils/schema.py`) :
un import crée un *fonds* (et sa miroir auto), pas une collection.
Ce modèle a été refondu en conséquence — l'ancienne version
(`collection_cible_id` / `nouvelle_collection`) datait d'avant la
refonte V0.9.0.

Les sessions abandonnées (statut `abandonnee`, ou `en_cours` depuis
longtemps) seront nettoyées par un job dédié — non implémenté.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base

# Étapes du wizard, dans l'ordre. `etape` stocke laquelle est courante
# pour qu'une reprise rouvre la bonne page.
ETAPES_IMPORT: tuple[str, ...] = (
    "tableur",
    "fonds",
    "mapping",
    "fichiers",
    "apercu",
)


class SessionImport(Base):
    __tablename__ = "session_import"

    id: Mapped[int] = mapped_column(primary_key=True)
    utilisateur: Mapped[str] = mapped_column(Text, nullable=False)

    # Étape courante du wizard (cf. ETAPES_IMPORT).
    etape: Mapped[str] = mapped_column(
        String(20), nullable=False, default="tableur"
    )

    # --- Étape tableur : fichier uploadé + colonnes détectées --------
    chemin_tableur: Mapped[str | None] = mapped_column(Text)
    nom_tableur_original: Mapped[str | None] = mapped_column(String(500))
    feuille: Mapped[str | None] = mapped_column(String(200))
    colonnes_detectees: Mapped[list[Any] | None] = mapped_column(JSON)

    # --- Étape fonds : section `fonds:` + `collection_miroir:` -------
    fonds_data: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    collection_miroir_data: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    # --- Étape mapping : colonne tableur → champ item ----------------
    mappings: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    # Granularité du tableur : "item" (une ligne = un item) ou
    # "fichier" (une ligne = un scan ; les lignes sont regroupées
    # par cote à l'import).
    granularite: Mapped[str] = mapped_column(
        String(20), nullable=False, default="item"
    )

    # --- Étape fichiers : racine + motif de résolution ---------------
    configuration_fichiers: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    # Fonds créé une fois l'import exécuté (null tant que `en_cours`).
    fonds_cree_id: Mapped[int | None] = mapped_column(
        ForeignKey("fonds.id", ondelete="SET NULL")
    )

    # États possibles : 'en_cours', 'validee', 'abandonnee'.
    statut: Mapped[str] = mapped_column(
        String(20), nullable=False, default="en_cours"
    )

    cree_le: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    modifie_le: Mapped[datetime | None] = mapped_column(DateTime)

    __table_args__ = (
        CheckConstraint(
            "statut IN ('en_cours', 'validee', 'abandonnee')",
            name="ck_session_import_statut",
        ),
        CheckConstraint(
            "etape IN ("
            + ", ".join(f"'{e}'" for e in ETAPES_IMPORT)
            + ")",
            name="ck_session_import_etape",
        ),
        CheckConstraint(
            "granularite IN ('item', 'fichier')",
            name="ck_session_import_granularite",
        ),
        Index("ix_session_import_utilisateur", "utilisateur"),
        Index("ix_session_import_statut", "statut"),
    )
