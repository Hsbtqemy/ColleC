"""Compte utilisateur (Phase 1 couche identité) : table `utilisateur`.

Référentiel des identités nommées du mode serveur (V1.0). Cf.
`models/utilisateur.py`. Périmètre minimal V1.0 : nom (unique), actif,
peut_editer. La matrice scope/invité viendra par migration au besoin.

Idempotente (skip si la table existe — base recréée via
`Base.metadata.create_all` en parallèle des migrations). downgrade
fonctionnel (post-refonte V0.9.0, cf. règle `contribuer.md`).

Revision ID: x2b3c4d5e6f7
Revises: w1a2b3c4d5e6
Create Date: 2026-06-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "x2b3c4d5e6f7"
down_revision: str | None = "w1a2b3c4d5e6"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())
    if "utilisateur" not in tables:
        op.create_table(
            "utilisateur",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("nom", sa.String(length=255), nullable=False),
            sa.Column("actif", sa.Boolean(), nullable=False),
            sa.Column("peut_editer", sa.Boolean(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("nom", name="uq_utilisateur_nom"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())
    if "utilisateur" in tables:
        op.drop_table("utilisateur")
