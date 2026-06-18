"""Index full-text search FTS5 sur item, fonds, collection (V0.9.x recherche).

Crée 3 tables virtuelles FTS5 (external content) qui indexent les
champs textuels des entités principales :
- `item_fts` : cote, titre, description, notes_internes, metadonnees (flatten JSON)
- `fonds_fts` : cote, titre, description, description_publique, description_interne
- `collection_fts` : cote, titre, description, description_publique

Triggers de synchronisation (insert/delete/update) maintiennent l'index
automatiquement. Tokeniseur `unicode61 remove_diacritics 2` pour
correspondre `café` / `cafe`, indispensable en archives multilingues.

`Fichier` n'est PAS indexé (volume × peu de valeur côté metadonnées —
on attend l'arrivée de l'OCR pour ajouter `fichier_fts` dédié).

Revision ID: m1q2r3s4t5u6
Revises: k1p2q3r4s5t6
Create Date: 2026-05-24
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import inspect, text

from archives_tool.db import _SQL_PEUPLEMENT_FTS, _SQL_TRIGGERS_FTS

revision: str = "m1q2r3s4t5u6"
down_revision: str | None = "k1p2q3r4s5t6"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = inspect(bind)
    tables = set(insp.get_table_names())

    # Mode FTS5 « standard » (pas de content=, pas d'external content) :
    # FTS5 stocke l'index ET le texte. Permet snippet() qui surligne
    # les matchs. Indispensable parce qu'on indexe une colonne dérivée
    # (`metadonnees_text` = flatten JSON) qui n'existe pas dans la
    # source — l'external content planterait avec « no such column ».
    cree_quelque_chose = False
    if "item_fts" not in tables:
        bind.execute(
            text(
                """
                CREATE VIRTUAL TABLE item_fts USING fts5(
                    cote, titre, description, notes_internes, metadonnees_text,
                    tokenize='unicode61 remove_diacritics 2'
                )
                """
            )
        )
        cree_quelque_chose = True
    if "fonds_fts" not in tables:
        bind.execute(
            text(
                """
                CREATE VIRTUAL TABLE fonds_fts USING fts5(
                    cote, titre, description, description_publique, description_interne,
                    tokenize='unicode61 remove_diacritics 2'
                )
                """
            )
        )
        cree_quelque_chose = True
    if "collection_fts" not in tables:
        bind.execute(
            text(
                """
                CREATE VIRTUAL TABLE collection_fts USING fts5(
                    cote, titre, description, description_publique,
                    tokenize='unicode61 remove_diacritics 2'
                )
                """
            )
        )
        cree_quelque_chose = True

    if cree_quelque_chose:
        # Peuplement initial des items/fonds/collections existants.
        # SQL centralisé dans `archives_tool.db._SQL_PEUPLEMENT_FTS`.
        for sql in _SQL_PEUPLEMENT_FTS:
            bind.execute(text(sql))

    # Triggers de synchronisation. SQL centralisé dans
    # `archives_tool.db._SQL_TRIGGERS_FTS` (réutilisable par les
    # migrations futures qui ALTER les tables indexées). Idempotent :
    # on droppe d'abord les triggers existants — `assurer_tables_fts`
    # peut les avoir créés au startup de l'app avant que cette
    # migration ne soit appliquée sur une base pré-FTS.
    for trigger in (
        "item_fts_insert",
        "item_fts_delete",
        "item_fts_update",
        "fonds_fts_insert",
        "fonds_fts_delete",
        "fonds_fts_update",
        "collection_fts_insert",
        "collection_fts_delete",
        "collection_fts_update",
    ):
        bind.execute(text(f"DROP TRIGGER IF EXISTS {trigger}"))
    for sql in _SQL_TRIGGERS_FTS:
        bind.execute(text(sql))


def downgrade() -> None:
    bind = op.get_bind()
    # DROP TRIGGER avant DROP TABLE pour éviter des références orphelines
    # à des tables qui ne seraient plus là.
    for trigger in [
        "item_fts_insert",
        "item_fts_delete",
        "item_fts_update",
        "fonds_fts_insert",
        "fonds_fts_delete",
        "fonds_fts_update",
        "collection_fts_insert",
        "collection_fts_delete",
        "collection_fts_update",
    ]:
        bind.execute(text(f"DROP TRIGGER IF EXISTS {trigger}"))
    for table in ("item_fts", "fonds_fts", "collection_fts"):
        bind.execute(text(f"DROP TABLE IF EXISTS {table}"))
