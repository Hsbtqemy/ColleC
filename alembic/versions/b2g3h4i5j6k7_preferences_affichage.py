"""Table preferences_affichage.

Revision ID: b2g3h4i5j6k7
Revises: a1f2c3d4e5f6
Create Date: 2026-05-07
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "b2g3h4i5j6k7"
down_revision: str | None = "a1f2c3d4e5f6"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        "preferences_affichage",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("utilisateur", sa.Text(), nullable=False),
        sa.Column(
            "collection_id",
            sa.Integer(),
            sa.ForeignKey("collection.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("vue", sa.String(length=40), nullable=False),
        sa.Column("colonnes_ordonnees", sa.JSON(), nullable=False),
        sa.Column(
            "cree_le", sa.DateTime(), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("modifie_le", sa.DateTime(), nullable=True),
        sa.UniqueConstraint(
            "utilisateur",
            "collection_id",
            "vue",
            name="uq_preferences_affichage",
        ),
    )
    op.create_index(
        "ix_preferences_utilisateur",
        "preferences_affichage",
        ["utilisateur"],
    )
    op.create_index(
        "ix_preferences_collection",
        "preferences_affichage",
        ["collection_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_preferences_collection", table_name="preferences_affichage")
    op.drop_index("ix_preferences_utilisateur", table_name="preferences_affichage")
    op.drop_table("preferences_affichage")
