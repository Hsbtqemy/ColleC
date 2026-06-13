"""Ajoute Fichier.sha1_nakala (identite distante pour versioning).

Posée pour le palier P3+a du versioning fichiers Nakala (cf.
`docs/developpeurs/nakala-depot-future.md` difficulté #4 *Identité
fichiers*). Le SHA-1 calculé par Nakala à l'upload (`POST /datas/uploads`)
ou lu sur un fichier matérialisé via `rapatrier` devient l'identifiant
canonique pour réconcilier `Fichier` ColleC ↔ entrée `files[i]` Nakala.

Distinct de `Fichier.hash_sha256` (SHA-256, intégrité disque ColleC).
Algorithmes et sémantiques différents — on ne fusionne pas.

**Backfill** : pour les `Fichier` matérialisés via `rapatrier` avant
cette migration, le sha1 est rangé en `metadonnees["sha1"]` (cf.
`services/nakala.py::materialiser_fichiers_nakala`). On le promeut en
colonne dédiée — idempotent (rejouer ne change rien : la condition WHERE
filtre les lignes déjà migrées).

Idempotence : la colonne est créée avec un guard (`add_column` standard
échoue si déjà présente — pas de protection nécessaire, Alembic ne rejoue
pas une migration deja appliquee). Le backfill UPDATE ne touche que les
fichiers dont la colonne est NULL et `metadonnees->>'sha1'` non vide.

Revision ID: s7w8x9y0z1a2
Revises: r6v7w8x9y0z1
Create Date: 2026-06-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "s7w8x9y0z1a2"
down_revision: str | None = "r6v7w8x9y0z1"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


_SQL_BACKFILL = """
UPDATE fichier
SET sha1_nakala = json_extract(metadonnees, '$.sha1')
WHERE sha1_nakala IS NULL
  AND metadonnees IS NOT NULL
  AND json_extract(metadonnees, '$.sha1') IS NOT NULL
  AND json_extract(metadonnees, '$.sha1') != ''
"""


def appliquer_backfill(conn) -> None:
    """Promeut `metadonnees["sha1"]` en colonne `sha1_nakala` pour les
    Fichier déjà matérialisés via `rapatrier` avant cette migration.

    Extrait pour être testable avec une connexion SQLAlchemy hors
    contexte Alembic — pattern aligné sur `r6v7w8x9y0z1::appliquer_remap`.

    Pré-condition : la colonne `sha1_nakala` doit déjà exister.
    """
    conn.exec_driver_sql(_SQL_BACKFILL)


def upgrade() -> None:
    # Colonne nullable — pas de défaut serveur (chaque écriture pose la
    # valeur depuis Nakala). String(40) pour 40 hex chars d'un SHA-1.
    op.add_column(
        "fichier",
        sa.Column("sha1_nakala", sa.String(length=40), nullable=True),
    )
    op.create_index(
        "ix_fichier_sha1_nakala", "fichier", ["sha1_nakala"], unique=False,
    )
    appliquer_backfill(op.get_bind())


def downgrade() -> None:
    # La colonne dropped ne touche pas `metadonnees` — le backfill
    # initial reste lisible via `metadonnees->>'sha1'`.
    op.drop_index("ix_fichier_sha1_nakala", table_name="fichier")
    op.drop_column("fichier", "sha1_nakala")
