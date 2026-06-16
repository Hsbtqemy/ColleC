"""Ajoute Fichier.description_externe (transcription publique par fichier, S7).

Champ texte libre destiné à accompagner un scan côté Nakala (le `description`
par fichier — round-trip validé live : sondes H11 + périmètre 2026-06-15, cf.
`docs/developpeurs/nakala-savoir-api.md` §4) et à l'indexation textuelle
future. Nakala n'accepte aucune métadonnée structurée par fichier au-delà de
`description` (texte) + `embargoed` — d'où une simple colonne TEXT.

**Distinct** de `Fichier.notes_techniques` (interne, jamais exporté) et de
`Item.description` (niveau donnée). Pas d'index : champ de contenu, pas de clé
de recherche/jointure (une éventuelle indexation FTS5 viendra séparément).

Aucun backfill : colonne neuve, la transcription n'était stockée nulle part
avant. Idempotente (skip si la colonne existe déjà — base recréée via
`Base.metadata.create_all` en parallèle des migrations). downgrade fonctionnel
(post-refonte V0.9.0, cf. règle `contribuer.md`).

Revision ID: u9y0z1a2b3c4
Revises: t8x9y0z1a2b3
Create Date: 2026-06-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "u9y0z1a2b3c4"
down_revision: str | None = "t8x9y0z1a2b3"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in inspect(bind).get_columns("fichier")}
    if "description_externe" not in cols:
        with op.batch_alter_table("fichier") as batch:
            batch.add_column(
                sa.Column("description_externe", sa.Text(), nullable=True),
            )


def downgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in inspect(bind).get_columns("fichier")}
    if "description_externe" not in cols:
        return
    with op.batch_alter_table("fichier") as batch:
        batch.drop_column("description_externe")
