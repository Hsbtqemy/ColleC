"""suppression table utilisateur

Revision ID: 1b5220a50dee
Revises: 6c56abe736b4
Create Date: 2026-04-24 10:04:33.833220

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "1b5220a50dee"
down_revision: Union[str, None] = "6c56abe736b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Note : les FK vers utilisateur.id étaient anonymes (aucune `name=`
# passée à ForeignKey). En batch SQLite la table est recréée sans ces
# FK dès qu'on drop les colonnes porteuses — pas besoin d'un
# drop_constraint(None, ...) explicite (qui ferait échouer la migration
# puisque batch_op exige un nom pour retrouver la contrainte).


def upgrade() -> None:
    with op.batch_alter_table("collection", schema=None) as batch_op:
        batch_op.add_column(sa.Column("cree_par", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("modifie_par", sa.Text(), nullable=True))
        batch_op.drop_column("modifie_par_id")
        batch_op.drop_column("cree_par_id")

    with op.batch_alter_table("fichier", schema=None) as batch_op:
        batch_op.add_column(sa.Column("ajoute_par", sa.Text(), nullable=True))
        batch_op.drop_column("ajoute_par_id")

    with op.batch_alter_table("item", schema=None) as batch_op:
        batch_op.add_column(sa.Column("cree_par", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("modifie_par", sa.Text(), nullable=True))
        batch_op.drop_column("modifie_par_id")
        batch_op.drop_column("cree_par_id")

    with op.batch_alter_table("lien_externe_item", schema=None) as batch_op:
        batch_op.add_column(sa.Column("cree_par", sa.Text(), nullable=True))
        batch_op.drop_column("cree_par_id")

    with op.batch_alter_table("modification_item", schema=None) as batch_op:
        batch_op.add_column(sa.Column("modifie_par", sa.Text(), nullable=True))
        batch_op.drop_column("modifie_par_id")

    with op.batch_alter_table("operation_fichier", schema=None) as batch_op:
        batch_op.add_column(sa.Column("execute_par", sa.Text(), nullable=True))
        batch_op.drop_column("execute_par_id")

    # Les deux tables d'identité disparaissent en dernier, une fois
    # toutes les FK retirées ci-dessus (implicitement en batch).
    op.drop_table("session_edition")
    op.drop_table("utilisateur")


def downgrade() -> None:
    op.create_table(
        "utilisateur",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("nom", sa.String(length=120), nullable=False),
        sa.Column("actif", sa.Boolean(), nullable=False),
        sa.Column(
            "cree_le",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("nom"),
    )
    op.create_table(
        "session_edition",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("utilisateur_id", sa.Integer(), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=True),
        sa.Column(
            "ouverte_le",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "dernier_heartbeat",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("fermee_le", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["item_id"], ["item.id"]),
        sa.ForeignKeyConstraint(["utilisateur_id"], ["utilisateur.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    with op.batch_alter_table("collection", schema=None) as batch_op:
        batch_op.add_column(sa.Column("cree_par_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("modifie_par_id", sa.Integer(), nullable=True))
        batch_op.drop_column("modifie_par")
        batch_op.drop_column("cree_par")

    with op.batch_alter_table("fichier", schema=None) as batch_op:
        batch_op.add_column(sa.Column("ajoute_par_id", sa.Integer(), nullable=True))
        batch_op.drop_column("ajoute_par")

    with op.batch_alter_table("item", schema=None) as batch_op:
        batch_op.add_column(sa.Column("cree_par_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("modifie_par_id", sa.Integer(), nullable=True))
        batch_op.drop_column("modifie_par")
        batch_op.drop_column("cree_par")

    with op.batch_alter_table("lien_externe_item", schema=None) as batch_op:
        batch_op.add_column(sa.Column("cree_par_id", sa.Integer(), nullable=True))
        batch_op.drop_column("cree_par")

    with op.batch_alter_table("modification_item", schema=None) as batch_op:
        batch_op.add_column(sa.Column("modifie_par_id", sa.Integer(), nullable=True))
        batch_op.drop_column("modifie_par")

    with op.batch_alter_table("operation_fichier", schema=None) as batch_op:
        batch_op.add_column(sa.Column("execute_par_id", sa.Integer(), nullable=True))
        batch_op.drop_column("execute_par")
