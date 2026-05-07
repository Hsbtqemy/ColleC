"""Ajout colonne phase sur collection.

Revision ID: a1f2c3d4e5f6
Revises: 8c193feadcd0
Create Date: 2026-05-07
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "a1f2c3d4e5f6"
down_revision: str | None = "8c193feadcd0"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    with op.batch_alter_table("collection") as batch_op:
        batch_op.add_column(
            sa.Column(
                "phase",
                sa.String(length=20),
                nullable=False,
                server_default="catalogage",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("collection") as batch_op:
        batch_op.drop_column("phase")
