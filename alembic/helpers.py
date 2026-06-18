"""Helpers réutilisables pour les migrations Alembic.

Centralise la gestion des triggers FTS5 sur `item`, `fonds`,
`collection`. Sans ces helpers, une migration qui ALTER une de ces
tables via `batch_alter_table(...)` recompilerait la table SQLite
(copie → drop → rename) et perdrait silencieusement les triggers
FTS — l'index ne serait plus synchronisé jusqu'à un rebuild manuel.

Convention : toute migration qui touche aux colonnes de `item`/`fonds`/
`collection` doit appeler `drop_fts_triggers()` en début de upgrade
et `create_fts_triggers()` en fin de upgrade (et symétriquement en
downgrade).

Le SQL des triggers vit dans `archives_tool.db._SQL_TRIGGERS_FTS`
— c'est la source de vérité unique, réutilisée par
`assurer_tables_fts()` (startup + tests) et par les migrations.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

# Source de vérité du SQL des triggers FTS5 — vit dans le module
# applicatif et non dans `alembic/` car le nom de dossier `alembic/`
# entre en conflit avec la lib `alembic` installée (résolu vers la
# lib lors d'un `from alembic.helpers import ...` depuis le module
# applicatif).
from archives_tool.db import _SQL_TRIGGERS_FTS


_NOMS_TRIGGERS_FTS: list[str] = [
    "item_fts_insert",
    "item_fts_delete",
    "item_fts_update",
    "fonds_fts_insert",
    "fonds_fts_delete",
    "fonds_fts_update",
    "collection_fts_insert",
    "collection_fts_delete",
    "collection_fts_update",
]


def drop_fts_triggers(connection: Any) -> None:
    """Drop tous les triggers FTS. À appeler en début de migration
    qui ALTER `item`/`fonds`/`collection` via `batch_alter_table`.

    `IF EXISTS` : idempotent — si les triggers n'existent pas encore
    (cas migration FTS pas encore appliquée, ou base test partant
    de zéro), pas d'erreur.
    """
    for trigger in _NOMS_TRIGGERS_FTS:
        connection.execute(text(f"DROP TRIGGER IF EXISTS {trigger}"))


def create_fts_triggers(connection: Any) -> None:
    """Recrée tous les triggers FTS. À appeler en fin de migration
    qui ALTER `item`/`fonds`/`collection` (après `drop_fts_triggers`).

    No-op si les tables FTS n'existent pas encore (cas pré-migration
    FTS5 initiale — celle-ci créera les tables ET les triggers
    elle-même).
    """
    # Garde : si item_fts n'existe pas (migration FTS pas encore
    # appliquée), on skip.
    result = connection.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name='item_fts'")
    ).fetchone()
    if result is None:
        return
    for sql in _SQL_TRIGGERS_FTS:
        connection.execute(text(sql))
