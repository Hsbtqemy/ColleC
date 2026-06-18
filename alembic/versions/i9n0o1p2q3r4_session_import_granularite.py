"""Ajoute session_import.granularite (assistant d'import).

L'assistant web doit savoir si une ligne du tableur représente un
item ou un fichier (lignes regroupées par cote). Nouvelle colonne
`granularite` avec CHECK ('item', 'fichier'), défaut 'item'.

Revision ID: i9n0o1p2q3r4
Revises: h8m9n0o1p2q3
Create Date: 2026-05-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "i9n0o1p2q3r4"
down_revision: str | None = "h8m9n0o1p2q3"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    with op.batch_alter_table("session_import") as batch:
        batch.add_column(
            sa.Column(
                "granularite",
                sa.String(length=20),
                nullable=False,
                server_default="item",
            )
        )
        batch.create_check_constraint(
            "ck_session_import_granularite",
            "granularite IN ('item', 'fichier')",
        )


def downgrade() -> None:
    with op.batch_alter_table("session_import") as batch:
        batch.drop_constraint("ck_session_import_granularite", type_="check")
        batch.drop_column("granularite")
