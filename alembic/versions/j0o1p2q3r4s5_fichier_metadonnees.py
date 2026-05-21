"""Ajoute fichier.metadonnees JSON.

Pendant de `Item.metadonnees` au niveau fichier. Permet de stocker des
champs propres à un scan (URLs Nakala data/embed/preview/thumb, hash
dupliqués, infos techniques import) qui ne rentrent pas dans les
colonnes dédiées. Sans cette colonne, l'import en granularité fichier
forçait toutes les colonnes par-fichier sur `Item.metadonnees`, ce qui
provoquait des warnings de divergence à la fusion par cote.

Revision ID: j0o1p2q3r4s5
Revises: i9n0o1p2q3r4
Create Date: 2026-05-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "j0o1p2q3r4s5"
down_revision: str | None = "i9n0o1p2q3r4"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    # Idempotent : la refonte V0.9.0-alpha (`g7l8m9n0o1p2`) recrée
    # `fichier` via `Base.metadata.create_all`, ce qui peut déjà avoir
    # créé la colonne si le modèle la déclare. Skip si présente.
    cols = {c["name"] for c in inspect(op.get_bind()).get_columns("fichier")}
    if "metadonnees" in cols:
        return
    with op.batch_alter_table("fichier") as batch:
        batch.add_column(sa.Column("metadonnees", sa.JSON(), nullable=True))


def downgrade() -> None:
    cols = {c["name"] for c in inspect(op.get_bind()).get_columns("fichier")}
    if "metadonnees" not in cols:
        return
    with op.batch_alter_table("fichier") as batch:
        batch.drop_column("metadonnees")
