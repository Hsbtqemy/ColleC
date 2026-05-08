"""Sources d'image multiples sur Fichier.

Ajoute les colonnes :
- apercu_chemin, vignette_chemin : alimentées par derivatives à
  partir de cette version (avant, c'était implicite via la convention
  de chemins_derive).
- dzi_chemin : réservé pour les tuiles locales (V2+).
- iiif_url_nakala : URL info.json IIIF d'un fichier déposé sur Nakala
  (V0.7+ pour le dépôt, exploité par la visionneuse dès V0.6).

Rend `racine` et `chemin_relatif` nullables pour permettre les
fichiers exclusivement référencés via Nakala. Une CHECK garantit
qu'au moins une source (locale ou IIIF) est renseignée.

Revision ID: c3h4i5j6k7l8
Revises: b2g3h4i5j6k7
Create Date: 2026-05-07
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "c3h4i5j6k7l8"
down_revision: str | None = "b2g3h4i5j6k7"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    with op.batch_alter_table("fichier") as batch_op:
        batch_op.add_column(sa.Column("apercu_chemin", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("vignette_chemin", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("dzi_chemin", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("iiif_url_nakala", sa.Text(), nullable=True))
        batch_op.alter_column("racine", existing_type=sa.String(100), nullable=True)
        batch_op.alter_column("chemin_relatif", existing_type=sa.Text(), nullable=True)
        batch_op.create_check_constraint(
            "ck_fichier_source_au_moins_une",
            "chemin_relatif IS NOT NULL OR iiif_url_nakala IS NOT NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("fichier") as batch_op:
        batch_op.drop_constraint("ck_fichier_source_au_moins_une", type_="check")
        batch_op.alter_column("chemin_relatif", existing_type=sa.Text(), nullable=False)
        batch_op.alter_column("racine", existing_type=sa.String(100), nullable=False)
        batch_op.drop_column("iiif_url_nakala")
        batch_op.drop_column("dzi_chemin")
        batch_op.drop_column("vignette_chemin")
        batch_op.drop_column("apercu_chemin")
