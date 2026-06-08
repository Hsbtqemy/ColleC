"""Journal des suppressions d'entités (operation_entite).

V0.9.9 : comble le principe directeur n°4 (« journaliser toutes les
opérations destructives ») pour les suppressions de fonds / collection /
item, jusque-là non tracées. Audit + snapshot forensique ; pas de FK
(l'entité référencée n'existe plus après suppression).

Voir CLAUDE.md « Questions ouvertes » → dette journal des suppressions.

Revision ID: q5u6v7w8x9y0
Revises: p4t5u6v7w8x9
Create Date: 2026-06-08
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "q5u6v7w8x9y0"
down_revision: str | None = "p4t5u6v7w8x9"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    # Idempotent : si la table a déjà été créée via Base.metadata.create_all
    # (base recréée en parallèle de la migration, cas tests/startup), on passe.
    if "operation_entite" in inspect(op.get_bind()).get_table_names():
        return

    op.create_table(
        "operation_entite",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("type_entite", sa.String(length=20), nullable=False),
        sa.Column("entite_id", sa.Integer(), nullable=True),
        sa.Column("cote", sa.Text(), nullable=True),
        sa.Column("fonds_cote", sa.Text(), nullable=True),
        sa.Column("titre", sa.Text(), nullable=True),
        sa.Column("snapshot_json", sa.Text(), nullable=True),
        sa.Column("cascade_resume", sa.Text(), nullable=True),
        sa.Column(
            "execute_le",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("execute_par", sa.Text(), nullable=True),
    )
    op.create_index("ix_op_entite_type", "operation_entite", ["type_entite"])
    op.create_index("ix_op_entite_date", "operation_entite", ["execute_le"])


def downgrade() -> None:
    op.drop_index("ix_op_entite_date", table_name="operation_entite")
    op.drop_index("ix_op_entite_type", table_name="operation_entite")
    op.drop_table("operation_entite")
