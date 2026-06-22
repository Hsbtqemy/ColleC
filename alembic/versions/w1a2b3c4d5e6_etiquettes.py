"""Étiquettes colorées de chantier (Lot 4 UI⁺) : table `etiquette` + junction.

Marquage workflow ad-hoc, global, multi-tag par item, **jamais exporté**
(distinct des vocabulaires contrôlés). Cf. `models/etiquette.py`.

Idempotente (skip si les tables existent — base recréée via
`Base.metadata.create_all` en parallèle des migrations). downgrade
fonctionnel (post-refonte V0.9.0, cf. règle `contribuer.md`) : drop des
deux tables dans l'ordre enfant→parent.

Revision ID: w1a2b3c4d5e6
Revises: v0z1a2b3c4d5
Create Date: 2026-06-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "w1a2b3c4d5e6"
down_revision: str | None = "v0z1a2b3c4d5"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())
    if "etiquette" not in tables:
        op.create_table(
            "etiquette",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("libelle", sa.String(length=80), nullable=False),
            sa.Column("couleur", sa.String(length=20), nullable=False),
            sa.Column(
                "cree_le",
                sa.DateTime(),
                server_default=sa.text("(CURRENT_TIMESTAMP)"),
                nullable=False,
            ),
            sa.Column("cree_par", sa.String(length=255), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("libelle", name="uq_etiquette_libelle"),
        )
    if "item_etiquette" not in tables:
        op.create_table(
            "item_etiquette",
            sa.Column("item_id", sa.Integer(), nullable=False),
            sa.Column("etiquette_id", sa.Integer(), nullable=False),
            sa.Column(
                "ajoute_le",
                sa.DateTime(),
                server_default=sa.text("(CURRENT_TIMESTAMP)"),
                nullable=False,
            ),
            sa.Column("ajoute_par", sa.String(length=255), nullable=True),
            sa.ForeignKeyConstraint(["item_id"], ["item.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["etiquette_id"], ["etiquette.id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("item_id", "etiquette_id"),
        )
        op.create_index(
            "ix_item_etiquette_etiquette", "item_etiquette", ["etiquette_id"]
        )


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(inspect(bind).get_table_names())
    if "item_etiquette" in tables:
        op.drop_table("item_etiquette")  # enfant d'abord (FK → etiquette)
    if "etiquette" in tables:
        op.drop_table("etiquette")
