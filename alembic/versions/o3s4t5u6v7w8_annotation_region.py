"""Table annotation_region pour les annotations d'image W3C / IIIF.

V0.9.7 : conforme à W3C Web Annotation Data Model + IIIF Presentation
API 3. Cible : indexation à la granularité région d'image (chantier
Por Favor — identifier dessinateurs, sujets, etc.).

Voir `docs/developpeurs/annotations-image-future.md`.

Revision ID: o3s4t5u6v7w8
Revises: n2r3s4t5u6v7
Create Date: 2026-05-26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "o3s4t5u6v7w8"
down_revision: str | None = "n2r3s4t5u6v7"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    # Idempotent : si la table a déjà été créée via Base.metadata.create_all
    # (cas d'une base recréée en parallèle de la migration), on passe.
    if "annotation_region" in inspect(op.get_bind()).get_table_names():
        return

    op.create_table(
        "annotation_region",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "fichier_id",
            sa.Integer(),
            sa.ForeignKey("fichier.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("selecteur", sa.Text(), nullable=False),
        sa.Column(
            "selecteur_type",
            sa.String(16),
            nullable=False,
            server_default="fragment",
        ),
        sa.Column("corps", sa.JSON(), nullable=False),
        sa.Column(
            "motivation",
            sa.String(32),
            nullable=False,
            server_default="tagging",
        ),
        # TracabiliteMixin
        sa.Column(
            "cree_le",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("cree_par", sa.Text(), nullable=True),
        sa.Column("modifie_le", sa.DateTime(), nullable=True),
        sa.Column("modifie_par", sa.Text(), nullable=True),
        sa.Column(
            "version",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )
    op.create_index(
        "ix_annotation_region_fichier_cree",
        "annotation_region",
        ["fichier_id", "cree_le"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_annotation_region_fichier_cree",
        table_name="annotation_region",
    )
    op.drop_table("annotation_region")
