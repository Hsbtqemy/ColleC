"""Journal des push fichiers Nakala (operation_push_nakala).

V0.10+ : comble le principe directeur n°4 sur les opérations
destructives **côté distant** (PUT files=[...] qui retire des
fichiers Nakala absents de la liste cible). Audit + snapshot
forensique des sha1 retirés ; pas de FK (les sha1 distants retirés
n'ont pas forcément un Fichier ColleC correspondant à conserver).

Voir CLAUDE.md « Questions ouvertes » → dette journal des push
fichiers (signalée passe 5, attaquée passe 24).

Revision ID: t8x9y0z1a2b3
Revises: s7w8x9y0z1a2
Create Date: 2026-06-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "t8x9y0z1a2b3"
down_revision: str | None = "s7w8x9y0z1a2"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    # Idempotent : si la table a déjà été créée via Base.metadata.create_all
    # (base recréée en parallèle de la migration, cas tests/startup), on passe.
    if "operation_push_nakala" in inspect(op.get_bind()).get_table_names():
        return

    op.create_table(
        "operation_push_nakala",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("batch_id", sa.String(length=36), nullable=False),
        sa.Column("type_operation", sa.String(length=30), nullable=False),
        sa.Column("cote_item", sa.Text(), nullable=False),
        sa.Column("fonds_cote", sa.Text(), nullable=True),
        sa.Column("doi", sa.Text(), nullable=False),
        sa.Column("snapshot_avant", sa.Text(), nullable=True),
        sa.Column("snapshot_apres", sa.Text(), nullable=True),
        sa.Column("sha1s_uploades", sa.Text(), nullable=True),
        sa.Column("sha1s_retires", sa.Text(), nullable=True),
        sa.Column(
            "execute_le",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("execute_par", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_op_push_nakala_batch", "operation_push_nakala", ["batch_id"],
    )
    op.create_index(
        "ix_op_push_nakala_doi", "operation_push_nakala", ["doi"],
    )
    op.create_index(
        "ix_op_push_nakala_date", "operation_push_nakala", ["execute_le"],
    )


def downgrade() -> None:
    op.drop_index("ix_op_push_nakala_date", table_name="operation_push_nakala")
    op.drop_index("ix_op_push_nakala_doi", table_name="operation_push_nakala")
    op.drop_index("ix_op_push_nakala_batch", table_name="operation_push_nakala")
    op.drop_table("operation_push_nakala")
