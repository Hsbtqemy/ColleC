"""Ajoute champ_personnalise.actif pour permettre la dépréciation.

V0.9.4 : un champ déprécié reste en base (les valeurs item.metadonnees
sont préservées et retombent en clé libre via le fallback Bug C
V0.9.2-import) mais n'apparaît plus dans la section « Champs
personnalisés » formels du cartouche item.

Revision ID: n2r3s4t5u6v7
Revises: m1q2r3s4t5u6
Create Date: 2026-05-25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "n2r3s4t5u6v7"
down_revision: str | None = "m1q2r3s4t5u6"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    # Idempotent : skip si la colonne existe déjà (cas d'une base
    # recréée via create_all en parallèle).
    cols = {c["name"] for c in inspect(op.get_bind()).get_columns("champ_personnalise")}
    if "actif" in cols:
        return
    with op.batch_alter_table("champ_personnalise") as batch:
        batch.add_column(
            sa.Column(
                "actif",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            )
        )


def downgrade() -> None:
    cols = {c["name"] for c in inspect(op.get_bind()).get_columns("champ_personnalise")}
    if "actif" not in cols:
        return
    with op.batch_alter_table("champ_personnalise") as batch:
        batch.drop_column("actif")
