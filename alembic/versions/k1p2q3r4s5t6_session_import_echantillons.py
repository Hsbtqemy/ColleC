"""Ajoute session_import.colonnes_echantillon (V0.9.2-import #2).

Statistiques d'échantillonnage par colonne, calculées à l'upload du
tableur et consommées par l'étape mapping : `{nom_colonne: {exemples,
valeur_frequente, uniques, remplies, total}}`. Élimine le besoin de
rouvrir le tableur pour se rappeler ce qu'une colonne contient.

Revision ID: k1p2q3r4s5t6
Revises: j0o1p2q3r4s5
Create Date: 2026-05-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "k1p2q3r4s5t6"
down_revision: str | None = "j0o1p2q3r4s5"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    # Idempotent : `session_import` peut être recréée par `create_all`
    # dans les tests qui partent d'une base vide (le modèle déclare
    # déjà la colonne). Skip si présente.
    cols = {
        c["name"] for c in inspect(op.get_bind()).get_columns("session_import")
    }
    if "colonnes_echantillon" in cols:
        return
    with op.batch_alter_table("session_import") as batch:
        batch.add_column(
            sa.Column("colonnes_echantillon", sa.JSON(), nullable=True)
        )


def downgrade() -> None:
    cols = {
        c["name"] for c in inspect(op.get_bind()).get_columns("session_import")
    }
    if "colonnes_echantillon" not in cols:
        return
    with op.batch_alter_table("session_import") as batch:
        batch.drop_column("colonnes_echantillon")
