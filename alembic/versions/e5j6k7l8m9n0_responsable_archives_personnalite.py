"""Renomme `auteur_principal` en `responsable_archives` et ajoute
`personnalite_associee` sur Collection.

Revision ID: e5j6k7l8m9n0
Revises: d4i5j6k7l8m9
Create Date: 2026-05-09
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "e5j6k7l8m9n0"
down_revision: str | None = "d4i5j6k7l8m9"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    with op.batch_alter_table("collection") as batch_op:
        batch_op.add_column(
            sa.Column("personnalite_associee", sa.Text(), nullable=True)
        )
        batch_op.alter_column(
            "auteur_principal", new_column_name="responsable_archives"
        )


def downgrade() -> None:
    with op.batch_alter_table("collection") as batch_op:
        batch_op.alter_column(
            "responsable_archives", new_column_name="auteur_principal"
        )
        batch_op.drop_column("personnalite_associee")
