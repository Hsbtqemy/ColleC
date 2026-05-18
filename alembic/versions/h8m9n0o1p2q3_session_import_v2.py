"""Refonte session_import vers le modèle v2 (fonds).

L'assistant d'import web (V0.7) crée désormais un *fonds* via un
profil v2, plus une collection. La table `session_import`, jamais
peuplée (feature placeholder jusqu'ici), est recréée avec la nouvelle
forme : `etape`, `colonnes_detectees`, `fonds_data`,
`collection_miroir_data`, `fonds_cree_id` remplacent les colonnes
`collection_cible_id` / `nouvelle_collection` héritées de l'ancien
modèle pré-V0.9.0.

Drop + recreate plutôt que batch-alter : la table est vide partout
(aucune base de production ne l'utilise), donc aucune perte de données.

Revision ID: h8m9n0o1p2q3
Revises: g7l8m9n0o1p2
Create Date: 2026-05-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "h8m9n0o1p2q3"
down_revision: str | None = "g7l8m9n0o1p2"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def _creer_table_v2() -> None:
    op.create_table(
        "session_import",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("utilisateur", sa.Text(), nullable=False),
        sa.Column(
            "etape",
            sa.String(length=20),
            nullable=False,
            server_default="tableur",
        ),
        sa.Column("chemin_tableur", sa.Text(), nullable=True),
        sa.Column("nom_tableur_original", sa.String(length=500), nullable=True),
        sa.Column("feuille", sa.String(length=200), nullable=True),
        sa.Column("colonnes_detectees", sa.JSON(), nullable=True),
        sa.Column("fonds_data", sa.JSON(), nullable=True),
        sa.Column("collection_miroir_data", sa.JSON(), nullable=True),
        sa.Column("mappings", sa.JSON(), nullable=True),
        sa.Column("configuration_fichiers", sa.JSON(), nullable=True),
        sa.Column(
            "fonds_cree_id",
            sa.Integer(),
            sa.ForeignKey("fonds.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "statut",
            sa.String(length=20),
            nullable=False,
            server_default="en_cours",
        ),
        sa.Column(
            "cree_le",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("modifie_le", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "statut IN ('en_cours', 'validee', 'abandonnee')",
            name="ck_session_import_statut",
        ),
    )
    op.create_index(
        "ix_session_import_utilisateur", "session_import", ["utilisateur"]
    )
    op.create_index("ix_session_import_statut", "session_import", ["statut"])


def _creer_table_v1() -> None:
    """Forme historique, pour le downgrade."""
    op.create_table(
        "session_import",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("utilisateur", sa.Text(), nullable=False),
        sa.Column("chemin_tableur", sa.Text(), nullable=True),
        sa.Column("nom_tableur_original", sa.String(length=500), nullable=True),
        sa.Column("feuille", sa.String(length=200), nullable=True),
        sa.Column(
            "collection_cible_id",
            sa.Integer(),
            sa.ForeignKey("collection.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("nouvelle_collection", sa.JSON(), nullable=True),
        sa.Column("mappings", sa.JSON(), nullable=True),
        sa.Column("configuration_fichiers", sa.JSON(), nullable=True),
        sa.Column(
            "statut",
            sa.String(length=20),
            nullable=False,
            server_default="en_cours",
        ),
        sa.Column(
            "cree_le",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("modifie_le", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "statut IN ('en_cours', 'validee', 'abandonnee')",
            name="ck_session_import_statut",
        ),
    )
    op.create_index(
        "ix_session_import_utilisateur", "session_import", ["utilisateur"]
    )
    op.create_index("ix_session_import_statut", "session_import", ["statut"])


def upgrade() -> None:
    op.drop_table("session_import")
    _creer_table_v2()


def downgrade() -> None:
    op.drop_table("session_import")
    _creer_table_v1()
