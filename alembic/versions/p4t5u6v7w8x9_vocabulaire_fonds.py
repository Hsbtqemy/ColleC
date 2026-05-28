"""Junction vocabulaire_fonds pour le scoping vocabulaire ↔ fonds.

V0.9.x : permet de restreindre l'autocomplete d'annotations selon
le fonds courant. Un vocabulaire sans aucun rattachement reste
visible globalement (défaut).

Voir `docs/developpeurs/vocabulaire-scoping-future.md` T1.

Revision ID: p4t5u6v7w8x9
Revises: o3s4t5u6v7w8
Create Date: 2026-05-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "p4t5u6v7w8x9"
down_revision: str | None = "o3s4t5u6v7w8"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    # Idempotent : si la table a déjà été créée via Base.metadata.create_all
    # (cas d'une base recréée en parallèle de la migration), on passe.
    if "vocabulaire_fonds" in inspect(op.get_bind()).get_table_names():
        return

    op.create_table(
        "vocabulaire_fonds",
        sa.Column(
            "vocabulaire_id",
            sa.Integer(),
            sa.ForeignKey("vocabulaire.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "fonds_id",
            sa.Integer(),
            sa.ForeignKey("fonds.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )


def downgrade() -> None:
    op.drop_table("vocabulaire_fonds")
