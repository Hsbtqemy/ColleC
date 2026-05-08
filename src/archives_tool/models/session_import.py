"""Session d'import en cours depuis l'assistant web.

Persiste l'état d'un import en plusieurs étapes (upload, mappings,
fichiers, aperçu, exécution). Survit à un rechargement de page :
l'utilisateur peut reprendre une session en cours.

V0.7 — onglet Import depuis le tableau de bord. Les sessions
abandonnées (statut "en_cours" depuis plus de 7 jours) seront
nettoyées par un job dédié — non implémenté en V0.7, prévu V0.8.
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


class SessionImport(Base):
    __tablename__ = "session_import"

    id: Mapped[int] = mapped_column(primary_key=True)
    utilisateur: Mapped[str] = mapped_column(Text, nullable=False)

    # État de la session — sérialisable en JSON pour reprise.
    chemin_tableur: Mapped[str | None] = mapped_column(Text)
    nom_tableur_original: Mapped[str | None] = mapped_column(String(500))
    feuille: Mapped[str | None] = mapped_column(String(200))

    # Cible : soit collection existante, soit nouvelle (dict avec champs
    # de création). Mutuellement exclusifs côté logique applicative ;
    # pas de CHECK car les deux peuvent être null pendant la phase upload.
    collection_cible_id: Mapped[int | None] = mapped_column(
        ForeignKey("collection.id", ondelete="SET NULL")
    )
    nouvelle_collection: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    mappings: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    configuration_fichiers: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    # États possibles : 'en_cours', 'validee', 'abandonnee'.
    statut: Mapped[str] = mapped_column(String(20), nullable=False, default="en_cours")

    cree_le: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    modifie_le: Mapped[datetime | None] = mapped_column(DateTime)

    __table_args__ = (
        CheckConstraint(
            "statut IN ('en_cours', 'validee', 'abandonnee')",
            name="ck_session_import_statut",
        ),
        Index("ix_session_import_utilisateur", "utilisateur"),
        Index("ix_session_import_statut", "statut"),
    )
