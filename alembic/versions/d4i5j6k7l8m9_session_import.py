"""Table session_import (assistant d'import V0.7).

Persiste l'état d'un import multi-étapes depuis l'UI web. La session
référence éventuellement une collection cible (FK + ON DELETE SET
NULL) ; les autres états (chemin du tableur, mappings, configuration
fichiers) sont sérialisés en JSON pour reprise après rechargement.

Revision ID: d4i5j6k7l8m9
Revises: c3h4i5j6k7l8
Create Date: 2026-05-08
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "d4i5j6k7l8m9"
down_revision: str | None = "c3h4i5j6k7l8"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
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
        "ix_session_import_utilisateur",
        "session_import",
        ["utilisateur"],
    )
    op.create_index("ix_session_import_statut", "session_import", ["statut"])


def downgrade() -> None:
    op.drop_index("ix_session_import_statut", table_name="session_import")
    op.drop_index("ix_session_import_utilisateur", table_name="session_import")
    op.drop_table("session_import")
