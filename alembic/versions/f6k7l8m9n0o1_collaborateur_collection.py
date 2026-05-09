"""Table collaborateur_collection (V0.8.0).

Revision ID: f6k7l8m9n0o1
Revises: e5j6k7l8m9n0
Create Date: 2026-05-09
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "f6k7l8m9n0o1"
down_revision: str | None = "e5j6k7l8m9n0"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        "collaborateur_collection",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "collection_id",
            sa.Integer(),
            sa.ForeignKey("collection.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("nom", sa.String(length=255), nullable=False),
        sa.Column("roles", sa.JSON(), nullable=False),
        sa.Column("periode", sa.String(length=64), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "cree_le",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "modifie_le",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_collaborateur_collection_collection_id",
        "collaborateur_collection",
        ["collection_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_collaborateur_collection_collection_id",
        table_name="collaborateur_collection",
    )
    op.drop_table("collaborateur_collection")
